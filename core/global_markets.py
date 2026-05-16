"""
global_markets.py – Hämta globala börsindex via yfinance
=======================================================
Ger aktuell data för 15+ världsindex som används i morgon-
och kvällsrapporterna för att ge en global marknadsöverblick.

All data är gratis via yfinance. Inget API-nyckel behövs.
"""

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Globala index med ticker, namn, emoji ────────────────────────────────────
GLOBAL_INDEXES = [
    # Asien/Stillahavet (stänger innan svensk morgon)
    ("^N225",  "🇯🇵 Japan Nikkei 225"),
    ("^TOPX",  "🇯🇵 Japan Topix"),
    ("^HSI",   "🇭🇰 Hong Kong HSI"),
    ("000001.SS", "🇨🇳 Kina Shanghai Comp"),
    ("^KS11",  "🇰🇷 Korea KOSPI"),
    ("^AXJO",  "🇦🇺 Australien ASX 200"),
    ("^BSESN", "🇮🇳 India Sensex"),
    ("^STI",   "🇸🇬 Singapore STI"),

    # Europa (öppnar 08:00-09:00 CET)
    ("^GDAXI", "🇩🇪 Tyskland DAX"),
    ("^FTSE",  "🇬🇧 UK FTSE 100"),
    ("^FCHI",  "🇫🇷 Frankrike CAC 40"),
    ("^STOXX50E", "🇪🇺 Euro Stoxx 50"),
    ("^OMX",   "🇸🇪 Sverige OMXS30"),

    # USA (stänger 22:00 CET)
    ("^GSPC",  "🇺🇸 USA S&P 500"),
    ("^IXIC",  "🇺🇸 USA Nasdaq"),
    ("^DJI",   "🇺🇸 USA Dow Jones"),
    ("^VIX",   "📊 VIX (rädsleindex)"),
]

# Map ticker → display name
INDEX_NAMES = {t: n for t, n in GLOBAL_INDEXES}

# Lista med tickers
INDEX_TICKERS = list(INDEX_NAMES.keys())


def fetch_global_indices(timeout: int = 15) -> dict:
    """
    Hämta aktuella kurser för alla globala index via yfinance.

    Args:
        timeout: Maxväntetid per API-anrop (sekunder)

    Returns:
        dict: {ticker: {"name": str, "change_pct": float, "close": float, "open": float}}
              None-värden om indexet inte kunde hämtas.
    """
    import yfinance as yf

    results = {}
    errors = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(_fetch_single_index, ticker, timeout): ticker
            for ticker in INDEX_TICKERS
        }

        for future in as_completed(future_map):
            ticker = future_map[future]
            try:
                data = future.result()
                if data is not None:
                    results[ticker] = data
                else:
                    errors.append(ticker)
            except Exception as e:
                errors.append(ticker)

    # Logga errors (utan att störa flödet)
    if errors:
        import logging
        logging.getLogger(__name__).warning(
            f"Kunde inte hämta {len(errors)} index: {', '.join(errors[:5])}"
        )

    return results


def _fetch_single_index(ticker: str, timeout: int = 15) -> dict | None:
    """
    Hämta data för ett enskilt index.

    Hämtar 5 dagar för att kunna beräkna dagsförändring,
    samt dagens open/close för öppningsgap.
    """
    try:
        import yfinance as yf
        ticker_obj = yf.Ticker(ticker)
        hist = ticker_obj.history(period="5d", auto_adjust=True)

        if hist.empty or len(hist) < 2:
            return None

        latest = hist.iloc[-1]
        prev_close = hist["Close"].iloc[-2]
        close = latest["Close"]
        open_ = latest["Open"]

        change_pct = ((close / prev_close) - 1) * 100 if prev_close > 0 else 0
        gap_pct = ((open_ / prev_close) - 1) * 100 if prev_close > 0 else 0

        return {
            "name": INDEX_NAMES.get(ticker, ticker),
            "change_pct": round(change_pct, 2),
            "close": round(close, 2),
            "open": round(open_, 2),
            "prev_close": round(prev_close, 2),
            "gap_pct": round(gap_pct, 2),
            "high": round(latest["High"], 2),
            "low": round(latest["Low"], 2),
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(
            f"Misslyckades hämta {ticker}: {e}"
        )
        return None


def format_index_summary(indices: dict, max_items: int = 15) -> str:
    """
    Formatera globala index till en text för AI-prompt eller mail.

    Args:
        indices: Output från fetch_global_indices()
        max_items: Max antal index att visa

    Returns:
        Formaterad text som "🇺🇸 USA S&P 500 +1.8%, 🇯🇵 Japan Nikkei -0.4%..."
    """
    if not indices:
        return "Ingen indexdata tillgänglig."

    # Sortera: Asien först (stängde nyss), Europa, USA
    asia_tickers = {"^N225", "^TOPX", "^HSI", "000001.SS", "^KS11", "^AXJO", "^BSESN", "^STI"}
    euro_tickers = {"^GDAXI", "^FTSE", "^FCHI", "^STOXX50E", "^OMX"}
    us_tickers = {"^GSPC", "^IXIC", "^DJI", "^VIX"}

    def sort_key(item):
        t = item[0]
        if t in asia_tickers:
            return 0
        if t in euro_tickers:
            return 1
        if t in us_tickers:
            return 2
        return 3

    sorted_items = sorted(indices.items(), key=sort_key)

    parts = []
    for ticker, data in sorted_items[:max_items]:
        name = data.get("name", ticker)
        change = data.get("change_pct")
        close = data.get("close")

        if change is not None and close is not None:
            arrow = "🟢" if change >= 0 else "🔴"
            parts.append(f"{name} {arrow} {change:+.1f}% ({close:,.0f})")
        elif close is not None:
            parts.append(f"{name} {close:,.0f}")

    return " · ".join(parts)


def format_index_summary_short(indices: dict) -> str:
    """
    Kortare version: bara region-förändring.
    Används i AI-prompten för att spara tokens.

    Exempel:
    "🇺🇸 USA +1.8% | 🇪🇺 Europa +0.5% | 🇯🇵 Asien -0.4%"
    """
    region_tickers = {
        "🇺🇸 USA": ["^GSPC", "^IXIC", "^DJI"],
        "🇪🇺 Europa": ["^GDAXI", "^FTSE", "^FCHI", "^STOXX50E", "^OMX"],
        "🇯🇵 Asien": ["^N225", "^TOPX", "^HSI", "000001.SS", "^KS11", "^AXJO", "^BSESN"],
    }

    parts = []
    for region, tickers in region_tickers.items():
        changes = []
        for t in tickers:
            if t in indices and indices[t].get("change_pct") is not None:
                changes.append(indices[t]["change_pct"])
        if changes:
            avg = sum(changes) / len(changes)
            arrow = "🟢" if avg >= 0 else "🔴"
            parts.append(f"{region} {arrow} {avg:+.1f}%")

    return " | ".join(parts) if parts else "Ingen indexdata"


def get_global_market_narrative(indices: dict) -> str:
    """
    Skapa en kort narrativ sammanfattning av globala marknader.
    Används som kontext i AI-prompten.

    Exempel: "Blandat på världsmarknaderna. USA upp, Asien ned."
    """
    if not indices:
        return ""

    us = indices.get("^GSPC")
    jp = indices.get("^N225")
    hk = indices.get("^HSI")
    eu = indices.get("^GDAXI")
    se = indices.get("^OMX")
    vix = indices.get("^VIX")

    parts = []

    if us:
        arrow = "positiv" if us["change_pct"] >= 0 else "negativ"
        parts.append(f"USA {arrow} ({us['change_pct']:+.1f}%)")

    if jp:
        arrow = "positiv" if jp["change_pct"] >= 0 else "negativ"
        parts.append(f"Japan {arrow} ({jp['change_pct']:+.1f}%)")

    if hk:
        arrow = "positiv" if hk["change_pct"] >= 0 else "negativ"
        parts.append(f"Hongkong {arrow} ({hk['change_pct']:+.1f}%)")

    if eu:
        arrow = "positiv" if eu["change_pct"] >= 0 else "negativ"
        parts.append(f"Tyskland/ Europa {arrow} ({eu['change_pct']:+.1f}%)")

    if se:
        arrow = "positiv" if se["change_pct"] >= 0 else "negativ"
        parts.append(f"Sverige {arrow} ({se['change_pct']:+.1f}%)")

    if vix:
        vix_val = vix.get("close", 0)
        if vix_val < 15:
            parts.append("VIX låg – marknaden är lugn 😌")
        elif vix_val < 25:
            parts.append("VIX måttlig – normal marknadsoro 😐")
        else:
            parts.append(f"VIX förhöjd ({vix_val}) – marknadsoro! 😰")

    narrative = "Blandat på världsmarknaderna. " if not parts else ""
    return narrative + ". ".join(parts) + "."