"""
app.py
======
Portfolio Manager – öppnas i webbläsaren på http://localhost:5001

Starta med:  python app.py
Stäng med:   Ctrl+C i terminalen

Funktioner:
- Sök aktier med live autocomplete (yfinance Search)
- Lägg till/ta bort/redigera innehav
- Se live-priser och P&L för hela portföljen
- Sparar automatiskt till holdings.csv
"""

import base64
import csv
import io
import os
import threading
import webbrowser
from pathlib import Path

import requests
from nacl import encoding, public

import yfinance as yf
from flask import Flask, jsonify, render_template, request

import config
import watchlist as wl

app = Flask(__name__)
HOLDINGS_FILE = config.HOLDINGS_FILE


# ── Helpers ────────────────────────────────────────────────────────────────

def load_holdings() -> list:
    """Läs holdings.csv och returnera som lista av dicts."""
    path = Path(HOLDINGS_FILE)
    if not path.exists():
        return []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({
                    "ticker":     row.get("ticker", "").strip().upper(),
                    "shares":     float(row.get("shares", 0)),
                    "cost_basis": float(row.get("cost_basis", 0)) if row.get("cost_basis") else None,
                })
            return rows
    except Exception as e:
        print(f"Fel vid läsning av holdings: {e}")
        return []


def save_holdings(holdings: list):
    """Spara lista av holdings tillbaka till CSV."""
    path = Path(HOLDINGS_FILE)
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker", "shares", "cost_basis"])
            writer.writeheader()
            for h in holdings:
                writer.writerow({
                    "ticker":     h["ticker"],
                    "shares":     h["shares"],
                    "cost_basis": h.get("cost_basis", ""),
                })
    except Exception as e:
        print(f"Fel vid sparning av holdings: {e}")


def _encrypt_secret(public_key_b64: str, value: str) -> str:
    """Encrypt a secret value with the repo's public key (GitHub requirement)."""
    key = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder)
    box = public.SealedBox(key)
    return base64.b64encode(box.encrypt(value.encode())).decode()


def sync_watchlist_to_github():
    """Push watchlist.json content to GitHub Actions secret WATCHLIST_JSON."""
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("GITHUB_OWNER")
    repo  = os.getenv("GITHUB_REPO")
    if not all([token, owner, repo]):
        return False, "GITHUB_TOKEN/OWNER/REPO saknas i .env"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"https://api.github.com/repos/{owner}/{repo}"

    r = requests.get(f"{base}/actions/secrets/public-key", headers=headers, timeout=10)
    if r.status_code != 200:
        return False, f"Kunde inte hämta publik nyckel: {r.status_code}"
    pk_data = r.json()

    from pathlib import Path as _P
    wl_path = _P(config.WATCHLIST_FILE)
    if not wl_path.exists():
        return True, "Tom bevakningslista – inget att synka"
    json_content = wl_path.read_text(encoding="utf-8")
    encrypted    = _encrypt_secret(pk_data["key"], json_content)

    r = requests.put(
        f"{base}/actions/secrets/WATCHLIST_JSON",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": pk_data["key_id"]},
        timeout=10,
    )
    if r.status_code in (201, 204):
        return True, "OK"
    return False, f"GitHub API svarade {r.status_code}: {r.text}"


def sync_holdings_to_github():
    """Push holdings.csv content to GitHub Actions secret HOLDINGS_CSV."""
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("GITHUB_OWNER")
    repo  = os.getenv("GITHUB_REPO")
    if not all([token, owner, repo]):
        return False, "GITHUB_TOKEN/OWNER/REPO saknas i .env"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"https://api.github.com/repos/{owner}/{repo}"

    # 1. Hämta repots publika nyckel
    r = requests.get(f"{base}/actions/secrets/public-key", headers=headers, timeout=10)
    if r.status_code != 200:
        return False, f"Kunde inte hämta publik nyckel: {r.status_code}"
    pk_data = r.json()

    # 2. Läs och kryptera holdings.csv
    csv_content = Path(HOLDINGS_FILE).read_text(encoding="utf-8")
    encrypted   = _encrypt_secret(pk_data["key"], csv_content)

    # 3. Uppdatera secreten
    r = requests.put(
        f"{base}/actions/secrets/HOLDINGS_CSV",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": pk_data["key_id"]},
        timeout=10,
    )
    if r.status_code in (201, 204):
        return True, "OK"
    return False, f"GitHub API svarade {r.status_code}: {r.text}"


def parse_avanza_csv(content: str) -> list:
    """Parse Avanza portfolio export (semicolon-separated, Swedish decimals)."""
    content = content.lstrip('﻿').strip()
    reader = csv.DictReader(io.StringIO(content), delimiter=';')

    def sv_float(s):
        if not s: return None
        s = str(s).strip().replace('\xa0', '').replace(' ', '').replace('%', '')
        s = s.replace('.', '').replace(',', '.')
        try: return float(s)
        except: return None

    rows = []
    for row in reader:
        name = (row.get('Beteckning') or row.get('Namn') or row.get('Värdepapper') or '').strip()
        if not name:
            continue
        typ = (row.get('Typ') or row.get('Typ av värdepapper') or '').strip().lower()
        if typ and typ not in ('aktie', 'etf', 'fond', ''):
            continue
        antal = sv_float(row.get('Antal') or row.get('Antal aktier') or '')
        if not antal or antal <= 0:
            continue
        avg = sv_float(row.get('Genomsnittligt anskaffningsvärde') or '')
        tot = sv_float(row.get('Anskaffningsvärde') or '')
        if avg and avg > 0:
            cost = round(avg, 2)
        elif tot and tot > 0:
            cost = round(tot / antal, 2)
        else:
            cost = None
        rows.append({'name': name, 'shares': antal, 'cost_basis': cost})
    return rows


def get_live_price(ticker: str) -> dict:
    """Hämta nuvarande kurs och namn från yfinance (snabb variant)."""
    try:
        t = yf.Ticker(ticker)
        info = t.fast_info
        return {
            "price":    round(float(info.last_price), 2) if info.last_price else None,
            "currency": info.currency or "USD",
            "name":     t.info.get("shortName") or ticker,
        }
    except Exception:
        return {"price": None, "currency": "?", "name": ticker}


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def search():
    """Sök aktier via yfinance Search."""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    try:
        results = yf.Search(q, max_results=8).quotes
        filtered = []
        for r in results:
            if r.get("quoteType") in ("EQUITY", "ETF"):
                filtered.append({
                    "ticker":   r.get("symbol", ""),
                    "name":     r.get("shortname") or r.get("longname") or "",
                    "exchange": r.get("exchange") or r.get("fullExchangeName") or "",
                    "type":     r.get("quoteType", ""),
                })
        return jsonify(filtered[:7])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/holdings", methods=["GET"])
def get_holdings():
    """Hämta alla innehav med live-priser och P&L."""
    holdings = load_holdings()
    enriched = []
    total_value = 0
    total_cost  = 0

    for h in holdings:
        live = get_live_price(h["ticker"])
        price  = live["price"]
        shares = h["shares"]
        cost   = h.get("cost_basis")

        market_value = round(shares * price, 2)  if price else None
        cost_total   = round(shares * cost,  2)  if cost  else None
        pnl          = round(market_value - cost_total, 2) if (market_value and cost_total) else None
        pnl_pct      = round(pnl / cost_total * 100, 2)   if (pnl is not None and cost_total) else None

        if market_value:
            total_value += market_value
        if cost_total:
            total_cost += cost_total

        enriched.append({
            "ticker":       h["ticker"],
            "name":         live["name"],
            "shares":       shares,
            "cost_basis":   cost,
            "currency":     live["currency"],
            "current_price":price,
            "market_value": market_value,
            "pnl":          pnl,
            "pnl_pct":      pnl_pct,
        })

    total_pnl     = round(total_value - total_cost, 2) if (total_value and total_cost) else None
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if (total_pnl is not None and total_cost) else None

    return jsonify({
        "holdings":     enriched,
        "total_value":  round(total_value, 2),
        "total_cost":   round(total_cost, 2),
        "total_pnl":    total_pnl,
        "total_pnl_pct":total_pnl_pct,
    })


@app.route("/api/holdings", methods=["POST"])
def add_holding():
    """Lägg till ett nytt innehav."""
    data = request.get_json()
    ticker     = data.get("ticker", "").strip().upper()
    shares     = float(data.get("shares", 0))
    cost_basis = float(data.get("cost_basis")) if data.get("cost_basis") else None

    if not ticker or shares <= 0:
        return jsonify({"error": "Ogiltigt ticker eller antal"}), 400

    holdings = load_holdings()

    # Kolla om tickern redan finns – uppdatera då istället
    for h in holdings:
        if h["ticker"] == ticker:
            h["shares"]     = shares
            h["cost_basis"] = cost_basis
            save_holdings(holdings)
            sync_holdings_to_github()
            return jsonify({"status": "updated", "ticker": ticker})

    holdings.append({"ticker": ticker, "shares": shares, "cost_basis": cost_basis})
    save_holdings(holdings)
    sync_holdings_to_github()
    return jsonify({"status": "added", "ticker": ticker})


@app.route("/api/holdings/<ticker>", methods=["DELETE"])
def remove_holding(ticker: str):
    """Ta bort ett innehav."""
    ticker   = ticker.upper()
    holdings = load_holdings()
    before   = len(holdings)
    holdings = [h for h in holdings if h["ticker"] != ticker]

    if len(holdings) == before:
        return jsonify({"error": "Ticker ej hittad"}), 404

    save_holdings(holdings)
    sync_holdings_to_github()
    return jsonify({"status": "removed", "ticker": ticker})


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    """Hämta alla aktier i bevakningslistan med live-priser."""
    items = wl.load_watchlist()
    enriched = []
    for item in items:
        live = get_live_price(item["ticker"])
        enriched.append({
            "ticker":   item["ticker"],
            "name":     live["name"] or item.get("name", item["ticker"]),
            "currency": live["currency"],
            "price":    live["price"],
            "added":    item.get("added", ""),
        })
    return jsonify(enriched)


@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    """Lägg till en aktie i bevakningslistan."""
    data   = request.get_json()
    ticker = data.get("ticker", "").strip().upper()
    name   = data.get("name", "").strip()

    if not ticker:
        return jsonify({"error": "Ogiltigt ticker"}), 400

    is_new = wl.add_ticker(ticker, name)
    sync_watchlist_to_github()
    status = "added" if is_new else "already_exists"
    return jsonify({"status": status, "ticker": ticker})


@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
def remove_from_watchlist(ticker: str):
    """Ta bort en aktie från bevakningslistan."""
    ticker = ticker.upper()
    removed = wl.remove_ticker(ticker)
    if not removed:
        return jsonify({"error": "Ticker ej hittad i bevakningslistan"}), 404
    sync_watchlist_to_github()
    return jsonify({"status": "removed", "ticker": ticker})


@app.route("/api/smallcap/universe", methods=["GET"])
def get_smallcap_universe():
    """Returnerar custom-tickers + basuniversumstatistik."""
    from smallcap.universe import load_custom, SMALLCAP_UNIVERSE, is_builtin
    custom = load_custom()
    return jsonify({
        "custom":      custom,
        "base_count":  len(SMALLCAP_UNIVERSE),
        "total_count": len(SMALLCAP_UNIVERSE) + sum(
            1 for c in custom if not is_builtin(c["ticker"])
        ),
    })


@app.route("/api/smallcap/universe", methods=["POST"])
def add_to_smallcap():
    """Lägger till en ticker i custom-listan."""
    data    = request.get_json()
    ticker  = data.get("ticker", "").strip().upper()
    name    = data.get("name", "").strip()
    segment = data.get("segment", "first_north")
    if not ticker:
        return jsonify({"error": "Ogiltigt ticker"}), 400
    from smallcap.universe import add_custom, is_builtin
    is_new  = add_custom(ticker, name, segment)
    builtin = is_builtin(ticker)
    return jsonify({
        "status":  "added" if is_new else "already_exists",
        "ticker":  ticker,
        "builtin": builtin,
    })


@app.route("/api/smallcap/universe/<ticker>", methods=["DELETE"])
def remove_from_smallcap(ticker: str):
    """Tar bort en ticker ur custom-listan."""
    ticker = ticker.upper()
    from smallcap.universe import remove_custom
    if not remove_custom(ticker):
        return jsonify({"error": "Ticker ej hittad i custom-listan"}), 404
    return jsonify({"status": "removed", "ticker": ticker})


@app.route("/api/import/avanza", methods=["POST"])
def import_avanza_preview():
    """Parse Avanza CSV and return rows with suggested ticker matches."""
    if 'file' not in request.files:
        return jsonify({"error": "Ingen fil"}), 400
    content = request.files['file'].read().decode('utf-8-sig')
    rows = parse_avanza_csv(content)
    if not rows:
        return jsonify({"error": "Kunde inte läsa filen – kontrollera att det är en Avanza-export"}), 400

    results = []
    for row in rows:
        ticker = ''
        suggestions = []
        try:
            hits = yf.Search(row['name'], max_results=5).quotes
            for r in hits:
                if r.get('quoteType') in ('EQUITY', 'ETF', 'MUTUALFUND'):
                    suggestions.append({
                        'ticker': r.get('symbol', ''),
                        'name':   r.get('shortname') or r.get('longname') or '',
                    })
            if suggestions:
                ticker = suggestions[0]['ticker']
        except Exception:
            pass
        results.append({
            'avanza_name': row['name'],
            'shares':      row['shares'],
            'cost_basis':  row['cost_basis'],
            'ticker':      ticker,
            'suggestions': suggestions[:3],
        })
    return jsonify(results)


@app.route("/api/import/avanza/confirm", methods=["POST"])
def import_avanza_confirm():
    """Save confirmed import rows to holdings.csv."""
    rows = request.get_json() or []
    if not rows:
        return jsonify({"error": "Inga rader"}), 400

    holdings = load_holdings()
    n_added = n_updated = 0
    for row in rows:
        ticker = row.get('ticker', '').strip().upper()
        shares = float(row.get('shares', 0))
        cost   = row.get('cost_basis')
        if not ticker or shares <= 0:
            continue
        found = False
        for h in holdings:
            if h['ticker'] == ticker:
                h['shares'] = shares
                h['cost_basis'] = cost
                n_updated += 1
                found = True
                break
        if not found:
            holdings.append({'ticker': ticker, 'shares': shares, 'cost_basis': cost})
            n_added += 1

    save_holdings(holdings)

    ok, msg = sync_holdings_to_github()
    return jsonify({"status": "ok", "added": n_added, "updated": n_updated, "github_sync": ok, "github_msg": msg})


# ── Start ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5001
    url  = f"http://localhost:{port}"
    print(f"\n🚀 Portfolio Manager startar...")
    print(f"   Öppna: {url}")
    print(f"   Stoppa: Ctrl+C\n")

    # Öppna webbläsaren automatiskt efter 1.5s
    def open_browser():
        import time; time.sleep(1.5)
        webbrowser.open(url)
    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="0.0.0.0", port=port, debug=False)
