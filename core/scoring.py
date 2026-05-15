"""
scoring.py
==========
Factor scoring engine. Converts raw metrics into 0-100 scores using
percentile rankings within the universe, then combines into a composite score.

Scoring philosophy:
- Each factor is calculated as a percentile rank (0-100) within the universe
- This makes the scores comparable across stocks regardless of sector
- Lower-is-better metrics (P/E, debt) are inverted before ranking
- Final composite is a weighted average of all factor scores
"""

import pandas as pd
import numpy as np

from core import config

def get_dynamic_weights(regime: str, base_weights: dict) -> dict:
    """
    Justerar faktorvikter dynamiskt baserat på marknadsregim.
    Returnerar normaliserade vikter så att summan alltid blir 1.0 (100%).
    """
    w = base_weights.copy()

    if regime == "TJUR":
        # 🟢 OFFENSIV: Marknaden är stark. Vi vill rida på trender och tillväxt.
        w["momentum"] += 0.05
        w["growth"]   += 0.05
        w["risk"]     -= 0.05
        w["value"]    -= 0.05

    elif regime == "BJÖRN":
        # 🔴 DEFENSIV: Marknaden skakar. Vi vill ha stabila, billiga kvalitetsbolag.
        w["quality"]  += 0.15
        w["risk"]     += 0.10
        w["value"]    += 0.10
        w["momentum"] -= 0.20  # Momentum fungerar uselt när trender bryts
        w["growth"]   -= 0.15

    # Om OSÄKER behåller vi base_weights intakta.

    # Normalisera vikterna så att de alltid summerar till exakt 1.0
    total = sum(w.values())
    return {k: v / total for k, v in w.items()}

def percentile_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """
    Convert a series to percentile ranks (0-100).

    ascending=True: higher values = higher rank (good for ROE, growth, etc.)
    ascending=False: lower values = higher rank (good for P/E, debt, etc.)
    """
    # rank() with pct=True gives 0-1, multiply by 100
    # ascending=False inverts so low values rank high
    return series.rank(pct=True, ascending=ascending) * 100


def winsorize(series: pd.Series, lower: float = 0.02, upper: float = 0.98) -> pd.Series:
    """
    Cap extreme values at the 2nd and 98th percentile to reduce outlier influence.
    Important because yfinance sometimes returns weird P/E ratios like 99999.
    """
    if series.isna().all():
        return series
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lower=lo, upper=hi)


def calc_value_score(df: pd.DataFrame) -> pd.Series:
    """
    Value score: lower valuation ratios = higher score.
    Combines P/E, P/B, P/S, EV/EBITDA equally.
    """
    components = []

    # Forward P/E (preferred over trailing if available)
    pe = df["pe_forward"].fillna(df["pe_trailing"])
    pe = pe.where(pe > 0)  # Negative P/E = unprofitable, exclude from value calc
    pe = winsorize(pe)
    if pe.notna().sum() > 5:
        components.append(percentile_rank(pe, ascending=False))

    # Price-to-Book
    pb = winsorize(df["price_to_book"].where(df["price_to_book"] > 0))
    if pb.notna().sum() > 5:
        components.append(percentile_rank(pb, ascending=False))

    # Price-to-Sales
    ps = winsorize(df["price_to_sales"].where(df["price_to_sales"] > 0))
    if ps.notna().sum() > 5:
        components.append(percentile_rank(ps, ascending=False))

    # EV/EBITDA
    ev_ebitda = winsorize(df["ev_to_ebitda"].where(df["ev_to_ebitda"] > 0))
    if ev_ebitda.notna().sum() > 5:
        components.append(percentile_rank(ev_ebitda, ascending=False))

    if not components:
        return pd.Series(50.0, index=df.index)  # Neutral if no data

    return pd.concat(components, axis=1).mean(axis=1)


def calc_quality_score(df: pd.DataFrame) -> pd.Series:
    """
    Quality score: profitability and efficiency metrics.
    Higher ROE, ROA, margins = higher score.
    """
    components = []

    for col in ["roe", "roa", "profit_margin", "operating_margin", "gross_margin"]:
        if col in df.columns:
            values = winsorize(df[col])
            if values.notna().sum() > 5:
                components.append(percentile_rank(values, ascending=True))

    if not components:
        return pd.Series(50.0, index=df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_momentum_score(df: pd.DataFrame) -> pd.Series:
    """
    Momentum score: combination of recent returns.
    Classic academic approach: 12-month return is the main signal.
    Higher returns = higher score (winsorized to handle outliers).
    """
    components = []

    for col in ["return_12m", "return_6m", "return_3m"]:
        if col in df.columns and df[col].notna().sum() > 5:
            values = winsorize(df[col])
            components.append(percentile_rank(values, ascending=True))

    # Distance from 52-week high (closer = better)
    if "pct_from_52w_high" in df.columns and df["pct_from_52w_high"].notna().sum() > 5:
        components.append(percentile_rank(df["pct_from_52w_high"], ascending=True))

    if not components:
        return pd.Series(50.0, index=df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_growth_score(df: pd.DataFrame) -> pd.Series:
    """
    Growth score: revenue and earnings growth.
    Higher growth = higher score.
    """
    components = []

    for col in ["revenue_growth", "earnings_growth", "earnings_quarterly_growth"]:
        if col in df.columns and df[col].notna().sum() > 5:
            values = winsorize(df[col])
            components.append(percentile_rank(values, ascending=True))

    if not components:
        return pd.Series(50.0, index=df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_risk_score(df: pd.DataFrame) -> pd.Series:
    """
    Risk score: lower debt, lower volatility = higher score.
    NOTE: 'higher score = lower risk', so we INVERT.
    """
    components = []

    # Debt to equity (lower = better)
    if "debt_to_equity" in df.columns and df["debt_to_equity"].notna().sum() > 5:
        de = winsorize(df["debt_to_equity"].where(df["debt_to_equity"] >= 0))
        components.append(percentile_rank(de, ascending=False))

    # Current ratio (higher = better, but cap at 5+ since extreme is suspicious)
    if "current_ratio" in df.columns and df["current_ratio"].notna().sum() > 5:
        cr = df["current_ratio"].clip(upper=5)
        components.append(percentile_rank(cr, ascending=True))

    # Volatility (lower = better)
    if "volatility" in df.columns and df["volatility"].notna().sum() > 5:
        vol = winsorize(df["volatility"])
        components.append(percentile_rank(vol, ascending=False))

    # Beta (closer to 1.0 = market-like; we prefer low beta for risk score)
    if "beta" in df.columns and df["beta"].notna().sum() > 5:
        beta = winsorize(df["beta"])
        components.append(percentile_rank(beta, ascending=False))

    if not components:
        return pd.Series(50.0, index=df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_size_score(df: pd.DataFrame) -> pd.Series:
    """
    Size score: small-cap premium (smaller = higher score, but capped).
    Based on Fama-French SMB factor.
    """
    if "market_cap" not in df.columns or df["market_cap"].notna().sum() < 5:
        return pd.Series(50.0, index=df.index)

    # Use log of market cap to compress extreme range
    log_cap = np.log(df["market_cap"].where(df["market_cap"] > 0))
    return percentile_rank(log_cap, ascending=False)  # smaller = higher score


def calc_dividend_score(df: pd.DataFrame) -> pd.Series:
    """
    Dividend score: yield with payout ratio sanity check.
    """
    if "dividend_yield" not in df.columns:
        return pd.Series(50.0, index=df.index)

    yield_ = df["dividend_yield"].fillna(0)

    # Cap at 15% (anything higher is often a dividend trap)
    yield_capped = yield_.clip(upper=0.15)

    # Penalize unsustainable payout ratios (>100%)
    if "payout_ratio" in df.columns:
        payout = df["payout_ratio"]
        # If payout > 1, halve the effective yield
        unsustainable = (payout > 1.0).fillna(False)
        yield_capped = yield_capped.where(~unsustainable, yield_capped * 0.5)

    if yield_capped.notna().sum() < 5:
        return pd.Series(50.0, index=df.index)

    return percentile_rank(yield_capped, ascending=True)


def score_universe(df: pd.DataFrame, regime: str = "OSÄKER") -> pd.DataFrame:
    """
    Calculate all factor scores and composite score.
    Returns df with new columns added.
    """
    df = df.copy()

    # --- (Ev. logik för sentiment_raw om du har det här uppe) ---

    # Calculate each factor score
    df["score_value"]     = calc_value_score(df)
    df["score_quality"]   = calc_quality_score(df)
    df["score_momentum"]  = calc_momentum_score(df)
    df["score_growth"]    = calc_growth_score(df)
    df["score_risk"]      = calc_risk_score(df)
    df["score_size"]      = calc_size_score(df)
    df["score_dividend"]  = calc_dividend_score(df)
    
    # Beräkna sentimentpoäng om sentiment_raw finns i datan
    if "sentiment_raw" in df.columns and df["sentiment_raw"].notna().any():
        df["score_sentiment"] = calc_sentiment_score(df)

    # ---------------------------------------------------------
    # 🌟 HÄR ÄR DEN NYA ÄNDRINGEN FÖR REGIME-SWITCHING
    # ---------------------------------------------------------
    # Hämta dynamiska vikter istället för att ta dem direkt från config
    w = get_dynamic_weights(regime, config.FACTOR_WEIGHTS)

    # Composite score using the dynamic weights
    df["score_total"] = (
        w.get("value", 0)    * df["score_value"]    +
        w.get("quality", 0)  * df["score_quality"]  +
        w.get("momentum", 0) * df["score_momentum"] +
        w.get("growth", 0)   * df["score_growth"]   +
        w.get("risk", 0)     * df["score_risk"]     +
        w.get("size", 0)     * df["score_size"]     +
        w.get("dividend", 0) * df["score_dividend"] 
    )
    
    # Lägg till sentiment om det finns i vikterna
    if "sentiment" in w and "score_sentiment" in df.columns:
        df["score_total"] += w["sentiment"] * df["score_sentiment"]
    elif "score_sentiment" in df.columns:
        # Fallback om config har sentiment men inte get_dynamic_weights
        df["score_total"] += config.FACTOR_WEIGHTS.get("sentiment", 0.10) * df["score_sentiment"]

    # ── Holdingbolag & råvarubolag: score-rabatt ────────────────────────
    # Dessa bolag ser "fantastiska" ut i en faktormodell men av fel skäl:
    #   Holdingbolag  → vinster = orealiserade portföljuppgångar, ej operativ lönsamhet
    #   Guld/Silver   → marginaler driven av råvarupris, ej uthållig quality
    # Rabatten hindrar dem från att dominera topp-10 utan att utesluta dem helt.

    HOLDING_INDUSTRIES = {
        "asset management", "diversified investments", "investment trusts",
        "closed-end fund", "exchange traded fund", "capital markets",
    }
    COMMODITY_INDUSTRIES = {
        "gold", "silver", "copper", "other precious metals & mining",
        "steel", "aluminum", "uranium", "oil & gas e&p",
    }

    if "industry" in df.columns:
        ind_lower = df["industry"].fillna("").str.lower()

        # Holdingbolag: 15% rabatt (de är köpvärda men ska inte dominera)
        is_holding = ind_lower.apply(
            lambda i: any(h in i for h in HOLDING_INDUSTRIES)
        )
        df.loc[is_holding, "score_total"] = (
            df.loc[is_holding, "score_total"] * 0.85
        ).clip(0, 100)
        df.loc[is_holding, "company_type"] = "holding"

        # Råvarubolag: 10% rabatt (cykliska, commoditypris-beroende)
        is_commodity = ind_lower.apply(
            lambda i: any(c in i for c in COMMODITY_INDUSTRIES)
        )
        df.loc[is_commodity & ~is_holding, "score_total"] = (
            df.loc[is_commodity & ~is_holding, "score_total"] * 0.90
        ).clip(0, 100)
        df.loc[is_commodity & ~is_holding, "company_type"] = "commodity"

    # Sätt standard för alla som saknar company_type
    if "company_type" not in df.columns:
        df["company_type"] = "standard"
    df["company_type"] = df["company_type"].fillna("standard")

    # Add rank column
    df["rank"] = df["score_total"].rank(ascending=False, method="min").astype("Int64")

    # Add data quality indicator (% of fields populated)
    metric_cols = [
        "pe_trailing", "price_to_book", "roe", "profit_margin",
        "revenue_growth", "debt_to_equity", "return_12m", "beta"
    ]
    available_cols = [c for c in metric_cols if c in df.columns]
    df["data_quality"] = df[available_cols].notna().sum(axis=1) / len(available_cols)

    return df.sort_values("score_total", ascending=False).reset_index(drop=True)


def get_recommendation(score: float) -> str:
    """Map a score to a buy/hold/sell recommendation."""
    if score >= config.BUY_MORE_PERCENTILE:
        return "KÖP MER"
    elif score >= config.HOLD_PERCENTILE:
        return "BEHÅLL"
    else:
        return "SÄLJ/MINSKA"


def calc_sentiment_score(df: pd.DataFrame) -> pd.Series:
    """
    Sentiment score from Finnhub news data.
    'sentiment_raw' column contains -1 to +1 values from Finnhub.
    If no Finnhub data, defaults to neutral (50).
    """
    if "sentiment_raw" not in df.columns or df["sentiment_raw"].isna().all():
        return pd.Series(50.0, index=df.index)

    # sentiment_raw is -1 to +1 → convert to 0-100 percentile
    # We do a simple linear mapping: -1 → 0, 0 → 50, +1 → 100
    # Then also do percentile rank for relative comparison
    raw = df["sentiment_raw"].fillna(0)  # Missing = neutral

    # Linear map -1..+1 to 0..100
    linear = (raw + 1) * 50

    # Blend with percentile rank for stability
    if raw.notna().sum() > 5:
        pct = percentile_rank(raw, ascending=True)
        return (linear * 0.5 + pct * 0.5)

    return linear

