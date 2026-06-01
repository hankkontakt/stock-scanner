"""
fi_insider_fetcher.py
=====================
Finansinspektionens Insynsregister -- Swedish insider transactions (free, public data).

All Swedish listed companies must report insider trades to FI within 3 business days
under EU Market Abuse Regulation (MAR). This is the same data that Börsdata resells.

Data source: https://marknadssok.fi.se (FI's public search register)

Usage:
    from core.fi_insider_fetcher import get_insider_signal_fi
    result = get_insider_signal_fi("VOLV-B.ST")
    # -> {"insider_cluster": False, "insider_executive_buy": True}
"""

import re
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

logger = logging.getLogger(__name__)

# ── FI API endpoints ─────────────────────────────────────────────────────────
# FI has no official JSON API. The search page uses a server-rendered HTML form
# but the XHR requests return JSON when called with the right headers.
FI_SEARCH_URL = "https://marknadssok.fi.se/publiceringsklient/sv/Search"

# Session-level headers that mimic a browser (required -- bare requests get 403)
_SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://marknadssok.fi.se/publiceringsklient/sv/Search?SearchFunctionType=Insyn",
}

# ── Cache ─────────────────────────────────────────────────────────────────────
try:
    from core import config
    _CACHE_DIR = Path(config.CACHE_DIR) / "fi_insider"
except Exception:
    _CACHE_DIR = Path(__file__).parent.parent / ".cache" / "fi_insider"

_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_TTL_HOURS = 24  # Insider-data uppdateras löpande, cachas 24h

# Historisk mönsterdatabas - lagrar varje insiders beteende över tid
# för att klassificera "routine" vs "opportunistic" trades.
_HISTORY_DIR = Path(__file__).parent.parent / "data" / "insider_history"
_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
_HISTORY_TTL_DAYS = 730  # Behåll 2 år historik för mönsterigenkänning


def _history_path(ticker: str) -> Path:
    h = hashlib.md5(ticker.encode()).hexdigest()[:16]
    return _HISTORY_DIR / f"{h}.json"


def _load_history(ticker: str) -> list[dict]:
    """Laddar historisk insiderhandelsdata för en ticker."""
    p = _history_path(ticker)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_history(ticker: str, trades: list[dict]):
    """Sparar (ersätter) historik för en ticker."""
    p = _history_path(ticker)
    try:
        p.write_text(json.dumps(trades, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _append_trades(ticker: str, new_trades: list[dict]):
    """Lägger till nya trades i historikdatabasen."""
    existing = _load_history(ticker)
    # Dedup: slå ihop på (name, date, shares) unik nyckel
    seen = {(t.get("name", ""), t.get("date", ""), t.get("shares", 0))
            for t in existing}
    for t in new_trades:
        key = (t.get("name", ""), t.get("date", ""), t.get("shares", 0))
        if key not in seen:
            existing.append(t)
            seen.add(key)
    _save_history(ticker, existing)


def _is_routine_trader(ticker: str, insider_name: str, trade: dict) -> bool:
    """
    Klassificerar en insider som 'routine' eller 'opportunistic'.

    Routine = samma person köper i samma månad varje år,
    eller handlar alltid samma belopp (±20%).

    Opportunistic = bryter etablerat mönster (t.ex. VD som
    normalt köper för 100K i januari men nu köper för 2M i oktober).

    Returns:
        True = routine trade (viktas ned), False = opportunistic (boostas)
    """
    history = _load_history(ticker)
    if not history:
        return False  # Ingen historik -> kan inte vara routine

    # Filtrera på samma insider
    insider_trades = [
        t for t in history
        if t.get("name", "").lower().strip() == insider_name.lower().strip()
    ]
    if len(insider_trades) < 3:
        return False  # För få datapunkter för mönsterdetektion

    # 1. Månadsmönster: handlar alltid samma månad?
    current_month = trade.get("date", "")[:7]  # "2026-05"
    prev_months = [t.get("date", "")[:7] for t in insider_trades[:-3]]
    if prev_months:
        unique_months = set(prev_months[-4:])  # Senaste 4 månader
        if len(unique_months) == 1 and list(unique_months)[0] == current_month:
            return True  # Samma månad varje år -> routine

    # 2. Beloppsmönster: handlar alltid samma belopp?
    current_val = float(trade.get("shares", 0)) * float(trade.get("price", 0) or 1)
    if current_val <= 0:
        return False

    prev_vals = [
        float(t.get("shares", 0)) * float(t.get("price", 0) or 1)
        for t in insider_trades[:-3]
        if t.get("shares") and t.get("price")
    ]
    if prev_vals:
        avg_val = sum(prev_vals) / len(prev_vals)
        if avg_val > 0:
            ratio = current_val / avg_val
            if 0.8 <= ratio <= 1.2:
                return True  # Samma belopp ±20% -> routine

    return False


def _cache_path(key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    return _CACHE_DIR / f"{h}.json"


def _read_cache(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        age_h = (time.time() - data.get("_ts", 0)) / 3600
        if age_h < _CACHE_TTL_HOURS:
            return data.get("payload")
    except Exception:
        pass
    return None


def _write_cache(key: str, payload: dict) -> None:
    p = _cache_path(key)
    try:
        p.write_text(
            json.dumps({"_ts": time.time(), "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── Ticker -> company name lookup ──────────────────────────────────────────────
# FI search requires the company name, not the ticker symbol.
# We derive it from yfinance .info or strip the suffix.

def _ticker_to_company_name(ticker: str) -> str:
    """
    Best-effort: fetch longName from yfinance, fall back to cleaned ticker.
    Example: 'VOLV-B.ST' -> 'Volvo AB' or 'VOLV-B'
    """
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        name = info.get("longName") or info.get("shortName") or ""
        if name:
            # Strip common legal suffixes to improve FI match rate
            name = re.sub(
                r"\s+(AB|ASA|AS|A/S|Oyj|SE|NV|PLC|Ltd|Inc|Corp|GmbH)\b.*$",
                "", name, flags=re.IGNORECASE,
            ).strip()
            return name
    except Exception:
        pass
    # Fallback: "VOLV-B.ST" -> "VOLV-B"
    return ticker.split(".")[0]


# ── FI data fetching ──────────────────────────────────────────────────────────

def fetch_insider_trades_fi(
    company_name: str,
    days_back: int = 90,
    page_size: int = 50,
) -> list[dict]:
    """
    Fetch insider transactions from FI's public register for a Swedish company.

    Args:
        company_name: Company name to search (e.g., "Volvo", "NCC", "Hemfosa").
                      Partial names work -- FI does a contains-search.
        days_back:    How many days back to search (default 90).
        page_size:    Results per page (FI max is ~100).

    Returns:
        List of normalized transaction dicts:
        {name, role, transaction_type, shares, price, currency, isin, date}
    """
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date   = datetime.now().strftime("%Y-%m-%d")

    params = {
        "SearchFunctionType": "Insyn",
        "Utgivare":           company_name,
        "FrånDatum":          from_date,
        "TillDatum":          to_date,
        "Page":               1,
        "PageSize":           page_size,
    }

    session = requests.Session()
    session.headers.update(_SESSION_HEADERS)

    try:
        r = session.get(FI_SEARCH_URL, params=params, timeout=15)

        if r.status_code != 200:
            logger.debug(f"FI search returned {r.status_code} for '{company_name}'")
            return []

        # Try JSON parse first (XHR mode)
        content_type = r.headers.get("Content-Type", "")
        if "json" in content_type or r.text.strip().startswith("{"):
            try:
                raw = r.json()
                return _parse_fi_json(raw)
            except Exception:
                pass

        # Fall back to HTML parsing
        return _parse_fi_html(r.text)

    except requests.RequestException as e:
        logger.debug(f"FI request failed for '{company_name}': {e}")
        return []


def _parse_fi_json(data: dict) -> list[dict]:
    """Parse FI JSON response (if the XHR endpoint returns JSON)."""
    trades = []
    results = data.get("results") or data.get("Records") or data.get("items") or []
    for item in results:
        # FI field names (Swedish):
        # Publiceringsdatum, Emittent, PersonILedandeStallning,
        # Befattning, Karaktär, Volym, Pris, Valuta, ISIN, Transaktionsdatum
        trade = {
            "name":             item.get("PersonILedandeStallning") or item.get("Anmälningsskyldig") or "",
            "role":             item.get("Befattning") or "",
            "transaction_type": item.get("Karaktär") or item.get("Karaktar") or "",
            "shares":           _to_float(item.get("Volym") or item.get("Volume")),
            "price":            _to_float(item.get("Pris") or item.get("Kurs")),
            "currency":         item.get("Valuta") or "SEK",
            "isin":             item.get("ISIN") or "",
            "date":             item.get("Transaktionsdatum") or item.get("Publiceringsdatum") or "",
        }
        trades.append(trade)
    return trades


def _parse_fi_html(html: str) -> list[dict]:
    """
    Parse FI HTML table as fallback when JSON endpoint is unavailable.
    The result table has these columns (in order):
    Publiceringsdatum | Emittent | Person | Befattning | Närstående |
    Karaktär | Instrumentnamn | Instrumenttyp | ISIN | Transaktionsdatum |
    Volym | Volymsenhet | Pris | Valuta | Status
    """
    trades = []
    try:
        # Quick pandas HTML parse
        tables = pd.read_html(html, flavor="lxml")
        if not tables:
            return []
        df = tables[0]
        df.columns = [str(c).strip() for c in df.columns]

        # Map Swedish column names (may vary slightly)
        col_map = {
            "person": "name",
            "befattning": "role",
            "karaktär": "transaction_type",
            "karaktar": "transaction_type",
            "volym": "shares",
            "pris": "price",
            "valuta": "currency",
            "isin": "isin",
            "transaktionsdatum": "date",
            "publiceringsdatum": "pub_date",
        }
        df.columns = [col_map.get(c.lower(), c.lower()) for c in df.columns]

        for _, row in df.iterrows():
            trade = {
                "name":             str(row.get("name") or row.get("person i ledande ställning", "")),
                "role":             str(row.get("role", "")),
                "transaction_type": str(row.get("transaction_type", "")),
                "shares":           _to_float(row.get("shares", 0)),
                "price":            _to_float(row.get("price", 0)),
                "currency":         str(row.get("currency", "SEK")),
                "isin":             str(row.get("isin", "")),
                "date":             str(row.get("date") or row.get("pub_date", "")),
            }
            trades.append(trade)
    except Exception as e:
        logger.debug(f"FI HTML parse failed: {e}")

    return trades


def _to_float(val) -> float:
    """Convert FI numeric strings (e.g., '46 297' or '193,1497') to float."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        s = str(val).replace("\xa0", "").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return 0.0


# ── Signal analysis ───────────────────────────────────────────────────────────

# Executive titles (Swedish + English) that count as "strong" insider signals
_EXEC_TITLES = frozenset({
    "vd", "verkst", "verkställande direktör", "ceo",
    "cfo", "finansdirektör", "chief financial",
    "chief executive", "managing director",
    "styrelseordförande", "chairman",
    "coo", "operativ",
})

# Transaction types that mean "buy" in FI data
_BUY_KEYWORDS = frozenset({
    "förvärv", "köp", "purchase", "acquisition",
    "tilldelning",  # allocation (e.g., via options/LTI program)
})


def get_insider_signal_fi(ticker: str) -> dict:
    """
    Analyse Finansinspektionen insider data for a Swedish stock.

    Returns same dict format as _get_insider_signal() in data_fetcher.py:
        insider_cluster (bool): >=3 distinct insiders buying within 30 days
        insider_executive_buy (bool): CEO/CFO buying within 90 days

    Args:
        ticker: Yahoo Finance ticker, e.g. "VOLV-B.ST", "NCC-B.ST"
    """
    cache_key = f"fi_signal:{ticker}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    result = {"insider_cluster": False, "insider_executive_buy": False}

    company_name = _ticker_to_company_name(ticker)
    trades = fetch_insider_trades_fi(company_name, days_back=90)

    if not trades:
        _write_cache(cache_key, result)
        return result

    now = datetime.now()
    cutoff_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    cutoff_30 = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    buys_90 = [
        t for t in trades
        if t.get("date", "") >= cutoff_90
        and any(kw in t.get("transaction_type", "").lower() for kw in _BUY_KEYWORDS)
    ]

    # ── Spara trades i historikdatabasen (för routine/opportunistic-detektion) ──
    _append_trades(ticker, trades)

    # ── Uppgraderad signalanalys med CFO-weight och routine-filter ─────────
    exec_buy = False
    cluster_buyers = set()
    routine_traders = set()

    for t in buys_90:
        name = t.get("name", "")
        role = t.get("role", "").lower()
        is_exec = any(exec_kw in role for exec_kw in _EXEC_TITLES)

        # Flagga routine-traders (samma person, samma månad, samma belopp)
        if name and _is_routine_trader(ticker, name, t):
            routine_traders.add(name)
            continue  # Hoppa över routine-trades i signalberäkningen

        # Executive buy: VD/CFO/Styrelseordförande
        if is_exec:
            exec_buy = True

        # Cluster-detektion: bara opportunistiska köp räknas
        if t.get("date", "") >= cutoff_30:
            cluster_buyers.add(name)

    result["insider_executive_buy"] = exec_buy
    result["insider_cluster"] = len(cluster_buyers) >= 3

    # Extra metadata för diagnostik
    if routine_traders:
        logger.debug(f"{ticker}: filtrerade bort {len(routine_traders)} routine-traders")

    _write_cache(cache_key, result)
    return result


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    ticker = sys.argv[1] if len(sys.argv) > 1 else "NCC-B.ST"
    print(f"\nTesting FI insider fetch for {ticker}")

    name = _ticker_to_company_name(ticker)
    print(f"Company name: {name}")

    trades = fetch_insider_trades_fi(name, days_back=90)
    print(f"Found {len(trades)} trades in last 90 days")
    for t in trades[:5]:
        print(f"  {t['date']}  {t['name']!r:30s}  {t['role']!r:30s}  {t['transaction_type']!r}  {t['shares']} @ {t['price']}")

    signal = get_insider_signal_fi(ticker)
    print(f"\nSignal: {signal}")
