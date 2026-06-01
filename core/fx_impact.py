"""
fx_impact.py
============
FX Impact Module - analyserar valutarisken för icke-USD-innehav.

Beräknar hur mycket portföljen påverkas av en 1%, 5% respektive 10%
förändring i USD-växelkursen mot respektive lokalvaluta.

Användning:
    python -c "from core.fx_impact import build_fx_section; print(build_fx_section())"
"""

from __future__ import annotations

import datetime
from typing import Optional

import yfinance as yf

# ── Currency pair mapping ─────────────────────────────────────────────────────
# Map local currency -> USD FX ticker (hur mycket USD kostar 1 enhet lokalvaluta)
CURRENCY_TO_FX_TICKER: dict[str, str] = {
    "SEK": "SEKUSD=X",  # 1 SEK i USD
    "NOK": "NOKUSD=X",  # 1 NOK i USD
    "DKK": "DKKUSD=X",  # 1 DKK i USD
    "EUR": "EURUSD=X",  # 1 EUR i USD
    "GBP": "GBPUSD=X",  # 1 GBP i USD
    "CAD": "CADUSD=X",  # 1 CAD i USD
    "AUD": "AUDUSD=X",  # 1 AUD i USD
    "NZD": "NZDUSD=X",  # 1 NZD i USD
    "JPY": "JPYUSD=X",  # 1 JPY i USD
    "INR": "INRUSD=X",  # 1 INR i USD
    "HKD": "HKDUSD=X",  # 1 HKD i USD
    "SGD": "SGDUSD=X",  # 1 SGD i USD
    "TWD": "TWDUSD=X",  # 1 TWD i USD (via TWD=X)
    "KRW": "KRWUSD=X",  # 1 KRW i USD (via KRW=X)
    "BRL": "BRLUSD=X",  # 1 BRL i USD
    "CNY": "CNYUSD=X",  # 1 CNY i USD (offshore)
    "PLN": "PLNUSD=X",  # 1 PLN i USD
    "CHF": "CHFUSD=X",  # 1 CHF i USD
}

FX_CACHE: dict[str, dict] = {}
FX_CACHE_EXPIRY: dict[str, datetime.datetime] = {}
FX_CACHE_TTL = datetime.timedelta(hours=4)


def _fetch_fx_rate(currency: str) -> Optional[float]:
    """Hämta aktuell FX-kurs för en valuta (1 enhet lokalvaluta i USD).

    Returnerar None om valutan inte stöds eller data inte kan hämtas.
    """
    if currency.upper() == "USD":
        return 1.0  # USD mot USD = 1.0

    ticker = CURRENCY_TO_FX_TICKER.get(currency.upper())
    if not ticker:
        return None

    now = datetime.datetime.now()
    if currency in FX_CACHE and currency in FX_CACHE_EXPIRY:
        if now < FX_CACHE_EXPIRY[currency]:
            return FX_CACHE[currency].get("rate")

    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.last_price
        if price is not None and price > 0:
            FX_CACHE[currency] = {"rate": float(price), "timestamp": now.isoformat()}
            FX_CACHE_EXPIRY[currency] = now + FX_CACHE_TTL
            return float(price)
    except Exception:
        pass

    return None


def get_fx_rates(currencies: list[str]) -> dict[str, Optional[float]]:
    """Hämta FX-kurser för en lista av valutor.

    Returnerar dict med currency -> kurs (eller None om ej tillgänglig).
    """
    return {c: _fetch_fx_rate(c) for c in currencies}


def calculate_fx_impact(
    market_values: dict[str, float],
    fx_rates: dict[str, Optional[float]],
) -> list[dict]:
    """Beräkna FX-impact för varje valuta i portföljen.

    Args:
        market_values: dict med currency -> totalt marknadsvärde i USD
        fx_rates: dict med currency -> aktuell FX-kurs (1 lokalvaluta i USD)

    Returns:
        Lista med dicts innehållande valuta, exponering, och impact vid
        1%, 5% och 10% försvagning av USD.
    """
    results = []
    for currency, value_usd in market_values.items():
        if currency == "USD" or not value_usd:
            continue
        rate = fx_rates.get(currency)
        if rate is None or rate <= 0:
            continue

        results.append({
            "currency":         currency,
            "exposure_usd":     round(value_usd, 2),
            "fx_rate":          round(rate, 6),
            "impact_1pct":      round(value_usd * 0.01, 2),
            "impact_5pct":      round(value_usd * 0.05, 2),
            "impact_10pct":     round(value_usd * 0.10, 2),
        })

    return sorted(results, key=lambda r: r["exposure_usd"], reverse=True)


def build_fx_section(holdings: Optional[list[dict]] = None) -> str:
    """Bygg en FX-rapportsektion för portföljen.

    Args:
        holdings: Lista med dicts med keys 'currency', 'market_value'.
                  Om None, används mock-data för demo.

    Returns:
        Markdown-sträng med FX-riskanalys.
    """
    if holdings is None:
        holdings = _get_mock_holdings()

    # Aggregera marknadsvärden per valuta
    market_values: dict[str, float] = {}
    for h in holdings:
        curr = h.get("currency", "USD").upper()
        mv   = h.get("market_value", 0) or 0
        market_values[curr] = market_values.get(curr, 0) + mv

    currencies = [c for c in market_values if c != "USD"]
    fx_rates = get_fx_rates(currencies)

    impacts = calculate_fx_impact(market_values, fx_rates)

    if not impacts:
        return "### 💱 FX-exponering\n\nIngen valutariskt exponerad portfölj - endast USD-innehav.\n"

    total_exposure = sum(r["exposure_usd"] for r in impacts)
    total_risk_1pct = sum(r["impact_1pct"] for r in impacts)
    total_risk_5pct = sum(r["impact_5pct"] for r in impacts)
    total_risk_10pct = sum(r["impact_10pct"] for r in impacts)

    lines = [
        "### 💱 FX-exponering & Valutakursrisk",
        "",
        "| Valuta | Exponering (USD) | FX-kurs | −1% USD | −5% USD | −10% USD |",
        "|--------|-----------------|---------|---------|---------|----------|",
    ]

    for r in impacts:
        lines.append(
            f"| {r['currency']} "
            f"| ${r['exposure_usd']:,.0f} "
            f"| {r['fx_rate']:.4f} "
            f"| ${r['impact_1pct']:,.0f} "
            f"| ${r['impact_5pct']:,.0f} "
            f"| ${r['impact_10pct']:,.0f} |"
        )

    lines.extend([
        "",
        f"**Total exponering:** ${total_exposure:,.0f}",
        f"**Risk vid −1% USD:** ${total_risk_1pct:,.0f}",
        f"**Risk vid −5% USD:** ${total_risk_5pct:,.0f}",
        f"**Risk vid −10% USD:** ${total_risk_10pct:,.0f}",
        "",
        "_Ovanstående visar portföljens känslighet för en försvagning av USD "
        "mot respektive lokalvaluta._",
    ])

    return "\n".join(lines)


def _get_mock_holdings() -> list[dict]:
    """Returnera mock-portfölj för test/demo."""
    return [
        {"ticker": "VOLV-B.ST", "currency": "SEK", "market_value": 15000},
        {"ticker": "NOVO-B.CO", "currency": "DKK", "market_value": 22000},
        {"ticker": "SAP.DE",    "currency": "EUR", "market_value": 18000},
        {"ticker": "HSBA.L",    "currency": "GBP", "market_value": 12000},
        {"ticker": "AAPL",      "currency": "USD", "market_value": 45000},
        {"ticker": "BARC.L",    "currency": "GBP", "market_value": 8000},
    ]
