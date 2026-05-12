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

import csv
import io
import os
import threading
import webbrowser
from pathlib import Path

import yfinance as yf
from flask import Flask, jsonify, render_template, request

import config

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
            return jsonify({"status": "updated", "ticker": ticker})

    holdings.append({"ticker": ticker, "shares": shares, "cost_basis": cost_basis})
    save_holdings(holdings)
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
    return jsonify({"status": "ok", "added": n_added, "updated": n_updated})


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
