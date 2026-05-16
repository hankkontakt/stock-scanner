"""
interest_rate.py
================
Interest Rate Sensitivity Module – analyserar hur portföljen påverkas av
förändringar i styrräntor (Fed, ECB, Riksbanken).

Beräknar en 'räntekänslighetspoäng' baserat på sektorer och duration,
samt ger en riskbedömning vid räntehöjningar/sänkningar.

Användning:
    python -c "from core.interest_rate import build_rates_section; print(build_rates_section())"
"""

from __future__ import annotations

import datetime
from typing import Optional

import yfinance as yf

# ── Styrränte-tickers ─────────────────────────────────────────────────────────
# Använder statsobligationsräntor som proxy för räntenivåer
RATE_TICKERS: dict[str, str] = {
    "Fed (USD)":      "^TNX",   # US 10Y Treasury Yield (proxar Fed)
    "ECB (EUR)":      "DE10Y.DE", # Tysk 10Y Bund (proxar ECB)
    "Riksbanken (SEK)": "SE10Y.ST",  # Svensk 10Y (proxar Riksbanken)
    "BOE (GBP)":      "UK10Y.UK",   # Brittisk 10Y Gilt (proxar BOE)
    "Norges Bank (NOK)": "NO10Y.OL", # Norsk 10Y Statsobligation
    "Riksbank (DKK)":   "DK10Y.CO", # Dansk 10Y
}

RATE_CACHE: dict[str, dict] = {}
RATE_CACHE_EXPIRY: dict[str, datetime.datetime] = {}
RATE_CACHE_TTL = datetime.timedelta(hours=6)

# ── Sektorns räntekänslighet (1-10, 10 = mest känslig) ──────────────────────
# Baserat på hög skuldsättning, lång duration, eller räntekänslig efterfrågan
SECTOR_RATE_SENSITIVITY: dict[str, int] = {
    "Real Estate":       9,
    "Utilities":         8,
    "Financial Services": 7,
    "Banks":             7,
    "Insurance":         6,
    "Consumer Cyclical":  6,
    "Homebuilding":      8,
    "REITs":             9,
    "Energy":            5,
    "Basic Materials":   5,
    "Industrials":       4,
    "Technology":        3,
    "Healthcare":        3,
    "Consumer Defensive": 2,
    "Communication":     3,
    "Unknown":           5,
}

# ── Duration-klass per sektor (år) ──────────────────────────────────────────
SECTOR_DURATION: dict[str, float] = {
    "Real Estate":        8.0,
    "Utilities":          7.0,
    "Financial Services": 5.0,
    "Banks":              4.5,
    "Insurance":          5.0,
    "Consumer Cyclical":  3.0,
    "Homebuilding":       6.0,
    "REITs":              8.5,
    "Energy":             3.5,
    "Basic Materials":    3.0,
    "Industrials":        3.5,
    "Technology":         2.0,
    "Healthcare":         2.5,
    "Consumer Defensive": 2.5,
    "Communication":      3.0,
    "Unknown":            4.0,
}


def fetch_current_rates() -> dict[str, Optional[float]]:
    """Hämta aktuella räntenivåer från yfinance.

    Returnerar dict med name -> yield i procent (t.ex. 4.32).
    """
    results: dict[str, Optional[float]] = {}
    now = datetime.datetime.now()

    for name, ticker in RATE_TICKERS.items():
        # Kolla cache
        if name in RATE_CACHE and name in RATE_CACHE_EXPIRY:
            if now < RATE_CACHE_EXPIRY[name]:
                results[name] = RATE_CACHE[name].get("rate")
                continue

        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = info.last_price
            if price is not None:
                rate = round(float(price), 2)
                RATE_CACHE[name] = {"rate": rate, "timestamp": now.isoformat()}
                RATE_CACHE_EXPIRY[name] = now + RATE_CACHE_TTL
                results[name] = rate
            else:
                results[name] = None
        except Exception:
            results[name] = None

    return results


def calculate_portfolio_rate_sensitivity(
    holdings: list[dict],
    rates: dict[str, Optional[float]],
) -> dict:
    """Beräkna portföljens räntekänslighet.

    Args:
        holdings: Lista med dicts med keys 'ticker', 'sector', 'market_value'
        rates: Dict med räntor från fetch_current_rates()

    Returns:
        Dict med sammanställd analys.
    """
    total_value = sum(h.get("market_value", 0) or 0 for h in holdings)

    if total_value == 0:
        return {
            "score": 0,
            "level": "neutral",
            "details": [],
            "summary": "Ingen portföljdata.",
        }

    weighted_sensitivity = 0.0
    weighted_duration = 0.0
    details = []

    for h in holdings:
        sector = h.get("sector", "Unknown")
        mv = h.get("market_value", 0) or 0
        weight = mv / total_value

        sens = SECTOR_RATE_SENSITIVITY.get(sector, 5)
        dur = SECTOR_DURATION.get(sector, 4.0)

        weighted_sensitivity += sens * weight
        weighted_duration += dur * weight

        details.append({
            "ticker":     h.get("ticker", "?"),
            "sector":     sector,
            "sensitivity": sens,
            "duration":   round(dur, 1),
            "weight_pct": round(weight * 100, 1),
        })

    avg_sensitivity = round(weighted_sensitivity, 1)
    avg_duration = round(weighted_duration, 1)

    # Räntenivå
    rate_info = {}
    fed_rate = rates.get("Fed (USD)")
    if fed_rate is not None:
        rate_info["fed"] = fed_rate
    ecb_rate = rates.get("ECB (EUR)")
    if ecb_rate is not None:
        rate_info["ecb"] = ecb_rate
    riksbank = rates.get("Riksbanken (SEK)")
    if riksbank is not None:
        rate_info["riksbank"] = riksbank

    # Risknivå
    if avg_sensitivity >= 7:
        level = "🔴 Hög räntekänslighet"
    elif avg_sensitivity >= 5:
        level = "🟡 Medel räntekänslighet"
    else:
        level = "🟢 Låg räntekänslighet"

    # Uppskattad påverkan vid ±1% ränteförändring (ca -duration * Δr)
    impact_per_1pct = round(-avg_duration * 0.01 * 100, 1)

    return {
        "score":             avg_sensitivity,
        "duration":          avg_duration,
        "level":             level,
        "impact_per_1pct":   impact_per_1pct,
        "rates":             rate_info,
        "details":           sorted(details, key=lambda d: d["weight_pct"], reverse=True),
        "summary": (
            f"Portföljens räntekänslighet: **{avg_sensitivity}/10** "
            f"(genomsnittlig duration ~{avg_duration} år). "
            f"Vid en räntehöjning på 1% påverkas portföljen med "
            f"ca **{impact_per_1pct}%** (durationseffekt)."
        ),
    }


def build_rates_section(holdings: Optional[list[dict]] = None) -> str:
    """Bygg en ränterapportsektion i Markdown.

    Args:
        holdings: Lista med dicts med keys 'ticker', 'sector', 'market_value'.
                  Om None, används mock-data.

    Returns:
        Markdown-sträng med ränteanalys.
    """
    rates = fetch_current_rates()

    if holdings is None:
        holdings = _get_mock_holdings()

    result = calculate_portfolio_rate_sensitivity(holdings, rates)

    lines = [
        "### 🏦 Räntekänslighetsanalys",
        "",
        "**Aktuella räntenivåer:**",
        "",
    ]

    # Räntetabell
    for name, rate in rates.items():
        if rate is not None:
            lines.append(f"- **{name}:** {rate:.2f}%")
        else:
            lines.append(f"- **{name}:** ⏳ hämtas...")

    lines.extend([
        "",
        f"**{result['level']}**",
        "",
        result["summary"],
        "",
        "| Ticker | Sektor | Känslighet | Duration | Vikt |",
        "|--------|--------|-----------|---------|------|",
    ])

    for d in result["details"][:10]:  # Top 10
        lines.append(
            f"| {d['ticker']} "
            f"| {d['sector']} "
            f"| {d['sensitivity']}/10 "
            f"| {d['duration']} år "
            f"| {d['weight_pct']}% |"
        )

    if result["rates"]:
        lines.extend([
            "",
            "**Rekommendation:**",
        ])
        if result["score"] >= 7:
            lines.append(
                "> ⚠ Hög räntekänslighet – överväg att minska exponeringen mot "
                "räntekänsliga sektorer (Fastigheter, Utility) i en "
                "stigande räntemiljö."
            )
        elif result["score"] >= 5:
            lines.append(
                "> 📊 Måttlig räntekänslighet – bevaka ränteutvecklingen, "
                "särskilt för sektorer med hög belåning."
            )
        else:
            lines.append(
                "> ✅ Låg räntekänslighet – portföljen är relativt okänslig "
                "för ränteförändringar."
            )

    return "\n".join(lines)


def _get_mock_holdings() -> list[dict]:
    """Returnera mock-portfölj för test/demo."""
    return [
        {"ticker": "AAPL",      "sector": "Technology",         "market_value": 45000},
        {"ticker": "VOLV-B.ST", "sector": "Industrials",        "market_value": 15000},
        {"ticker": "PLD",       "sector": "Real Estate",        "market_value": 12000},
        {"ticker": "NOVO-B.CO", "sector": "Healthcare",         "market_value": 22000},
        {"ticker": "JPM",       "sector": "Banks",              "market_value": 18000},
        {"ticker": "SAP.DE",    "sector": "Technology",         "market_value": 18000},
    ]
