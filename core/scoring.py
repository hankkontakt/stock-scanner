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


# ── Konstanter ──────────────────────────────────────────────────────────────
MIN_VALID_OBSERVATIONS = 5  # Min antal observationer för att beräkna en faktor
NEUTRAL_SCORE          = 50.0  # Neutralpoäng när data saknas
MAX_DIVIDEND_YIELD     = 0.15  # Max dividend yield innan det är en fälla
UNSUSTAINABLE_PAYOUT   = 1.0   # Payout ratio över detta = ohållbart
HOLDING_DISCOUNT       = 0.85  # Multiplikator för holdingbolag
COMMODITY_DISCOUNT     = 0.90  # Multiplikator för råvarubolag

HOLDING_INDUSTRIES = {
    "asset management", "diversified investments", "investment trusts",
    "closed-end fund", "exchange traded fund", "capital markets",
}
COMMODITY_INDUSTRIES = {
    "gold", "silver", "copper", "other precious metals & mining",
    "steel", "aluminum", "uranium", "oil & gas e&p",
}

# ── Hjälpfunktioner ────────────────────────────────────────────────────────

def _neutral_series(index) -> pd.Series:
    """Returnerar en serie med neutrala poäng (50) för alla index-entries."""
    return pd.Series(NEUTRAL_SCORE, index=index)


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


def _try_rank(series: pd.Series, ascending: bool, min_valid: int = MIN_VALID_OBSERVATIONS) -> pd.Series | None:
    """
    Winsorize, kolla att tillräckligt många observationer finns, och ranka.
    Returnerar None om för få observationer.
    """
    wins = winsorize(series)
    if wins.notna().sum() < min_valid:
        return None
    return percentile_rank(wins, ascending=ascending)


def calc_value_score(df: pd.DataFrame) -> pd.Series:
    """
    Value score: lower valuation ratios = higher score.
    Combines P/E, P/B, P/S, EV/EBITDA equally.
    """
    components = []

    # Forward P/E (preferred over trailing if available)
    pe = df["pe_forward"].fillna(df["pe_trailing"])
    pe = pe.where(pe > 0)  # Negative P/E = unprofitable, exclude from value calc
    score = _try_rank(pe, ascending=False)
    if score is not None:
        components.append(score)

    # Price-to-Book
    pb = df["price_to_book"].where(df["price_to_book"] > 0)
    score = _try_rank(pb, ascending=False)
    if score is not None:
        components.append(score)

    # Price-to-Sales
    ps = df["price_to_sales"].where(df["price_to_sales"] > 0)
    score = _try_rank(ps, ascending=False)
    if score is not None:
        components.append(score)

    # EV/EBITDA och FCF Yield – 50/50 blend för ett sammansatt värderingsvärde
    ev_ebitda = df["ev_to_ebitda"].where(df["ev_to_ebitda"] > 0)
    ev_score = _try_rank(ev_ebitda, ascending=False)
    fcf_score = calc_fcf_yield_score(df)
    fcf_neutral = (fcf_score == NEUTRAL_SCORE).all()
    if ev_score is not None and not fcf_neutral:
        components.append((ev_score + fcf_score) / 2)
    elif ev_score is not None:
        components.append(ev_score)
    elif not fcf_neutral:
        components.append(fcf_score)

    if not components:
        return _neutral_series(df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_fcf_yield_score(df: pd.DataFrame) -> pd.Series:
    """
    FCF Yield score: free_cash_flow / enterprise_value.
    Högre FCF yield = bättre värdering = högre poäng.
    Används som komplement till EV/EBITDA i calc_value_score().
    Fallback: approximerar EV med market_cap + total_debt - total_cash.
    """
    if "free_cash_flow" not in df.columns:
        return _neutral_series(df.index)

    if "enterprise_value" in df.columns and df["enterprise_value"].notna().any():
        ev = df["enterprise_value"].where(df["enterprise_value"] > 0)
    else:
        # Enkel approximation om enterpriseValue saknas
        mc   = df.get("market_cap",  pd.Series(0.0, index=df.index)).fillna(0)
        debt = df.get("total_debt",  pd.Series(0.0, index=df.index)).fillna(0)
        cash = df.get("total_cash",  pd.Series(0.0, index=df.index)).fillna(0)
        ev_raw = mc + debt - cash
        ev = ev_raw.where(ev_raw > 0)

    fcf = df["free_cash_flow"]
    with np.errstate(divide="ignore", invalid="ignore"):
        fcf_yield = fcf / ev
    # Klipp extrema negativa värden (t.ex. -500 % ger brus)
    fcf_yield = fcf_yield.where(fcf_yield > -0.50)

    score = _try_rank(fcf_yield, ascending=True)
    return score if score is not None else _neutral_series(df.index)


def calc_quality_score(df: pd.DataFrame) -> pd.Series:
    """
    Quality score: profitability and efficiency metrics.
    Higher ROE, ROA, margins = higher score.
    """
    components = []

    for col in ["roe", "roa", "profit_margin", "operating_margin", "gross_margin"]:
        if col in df.columns:
            score = _try_rank(df[col], ascending=True)
            if score is not None:
                components.append(score)

    if not components:
        return _neutral_series(df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_momentum_score(df: pd.DataFrame) -> pd.Series:
    """
    Momentum score: combination of recent returns.
    Classic academic approach: 12-month return is the main signal.
    Higher returns = higher score (winsorized to handle outliers).
    """
    components = []

    for col in ["return_12m", "return_6m", "return_3m"]:
        if col in df.columns:
            score = _try_rank(df[col], ascending=True)
            if score is not None:
                components.append(score)

    # Distance from 52-week high (closer = better)
    if "pct_from_52w_high" in df.columns:
        score = _try_rank(df["pct_from_52w_high"], ascending=True)
        if score is not None:
            components.append(score)

    if not components:
        return _neutral_series(df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_growth_score(df: pd.DataFrame) -> pd.Series:
    """
    Growth score: revenue and earnings growth.
    Higher growth = higher score.
    """
    components = []

    for col in ["revenue_growth", "earnings_growth", "earnings_quarterly_growth"]:
        if col in df.columns:
            score = _try_rank(df[col], ascending=True)
            if score is not None:
                components.append(score)

    if not components:
        return _neutral_series(df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_risk_score(df: pd.DataFrame) -> pd.Series:
    """
    Risk score: lower debt, lower volatility = higher score.
    NOTE: 'higher score = lower risk', so we INVERT.
    """
    components = []

    # Debt to equity (lower = better)
    if "debt_to_equity" in df.columns:
        de = df["debt_to_equity"].where(df["debt_to_equity"] >= 0)
        score = _try_rank(de, ascending=False)
        if score is not None:
            components.append(score)

    # Current ratio (higher = better, but cap at 5+ since extreme is suspicious)
    if "current_ratio" in df.columns:
        cr = df["current_ratio"].clip(upper=5)
        score = _try_rank(cr, ascending=True)
        if score is not None:
            components.append(score)

    # Volatility (lower = better)
    if "volatility" in df.columns:
        score = _try_rank(df["volatility"], ascending=False)
        if score is not None:
            components.append(score)

    # Beta (closer to 1.0 = market-like; we prefer low beta for risk score)
    if "beta" in df.columns:
        score = _try_rank(df["beta"], ascending=False)
        if score is not None:
            components.append(score)

    if not components:
        return _neutral_series(df.index)

    return pd.concat(components, axis=1).mean(axis=1)


def calc_size_score(df: pd.DataFrame) -> pd.Series:
    """
    Size score: small-cap premium (smaller = higher score, but capped).
    Based on Fama-French SMB factor.
    """
    if "market_cap" not in df.columns:
        return _neutral_series(df.index)
    
    mc = df["market_cap"].where(df["market_cap"] > 0)
    if mc.isna().all():
        return _neutral_series(df.index)

    # Use log of market cap to compress extreme range
    # Ersätt -inf (log(0)) och behåll NaN för saknade värden
    log_cap = np.log(mc)
    log_cap = log_cap.replace([np.inf, -np.inf], np.nan)
    
    if log_cap.notna().sum() < MIN_VALID_OBSERVATIONS:
        return _neutral_series(df.index)

    return percentile_rank(log_cap, ascending=False)  # smaller = higher score


def calc_dividend_score(df: pd.DataFrame) -> pd.Series:
    """
    Dividend score: yield with payout ratio sanity check.
    """
    if "dividend_yield" not in df.columns:
        return _neutral_series(df.index)

    yield_ = df["dividend_yield"].fillna(0)

    # Cap at 15% (anything higher is often a dividend trap)
    yield_capped = yield_.clip(upper=MAX_DIVIDEND_YIELD)

    # Penalize unsustainable payout ratios (>100%)
    if "payout_ratio" in df.columns:
        payout = df["payout_ratio"]
        # If payout > 1, halve the effective yield
        unsustainable = (payout > UNSUSTAINABLE_PAYOUT).fillna(False)
        yield_capped = yield_capped.where(~unsustainable, yield_capped * 0.5)

    if yield_capped.notna().sum() < MIN_VALID_OBSERVATIONS:
        return _neutral_series(df.index)

    return percentile_rank(yield_capped, ascending=True)


def calc_sentiment_score(df: pd.DataFrame) -> pd.Series:
    """
    Sentiment score från Finnhub-nyhetsdata + insiderhandelssignaler.
    'sentiment_raw' = -1 till +1 från Finnhub.
    Insider-boost: VD/CFO-köp → +20 poäng, cluster-köp → +30 poäng.
    """
    if "sentiment_raw" not in df.columns or df["sentiment_raw"].isna().all():
        score = _neutral_series(df.index)
    else:
        raw = df["sentiment_raw"].fillna(0)
        linear = (raw + 1) * 50
        if raw.notna().sum() > MIN_VALID_OBSERVATIONS:
            pct = percentile_rank(raw, ascending=True)
            score = (linear * 0.5 + pct * 0.5)
        else:
            score = linear

    # ── Insider-boost ────────────────────────────────────────────────────────
    # VD/CFO köper: starkt bullish signal (+20, capped 95)
    # Cluster (≥3 insiders inom 30d): ännu starkare (+30, capped 98)
    if "insider_executive_buy" in df.columns:
        exec_mask    = df["insider_executive_buy"].fillna(False).astype(bool)
        cluster_mask = df.get("insider_cluster", pd.Series(False, index=df.index)).fillna(False).astype(bool)
        score = score.copy()
        score[exec_mask]    = (score[exec_mask]    + 20).clip(upper=95)
        score[cluster_mask] = (score[cluster_mask] + 30).clip(upper=98)

    return score


def score_universe(df: pd.DataFrame, regime: str = "OSÄKER") -> pd.DataFrame:
    """
    Calculate all factor scores and composite score.
    Returns df with new columns added.
    """
    df = df.copy()

    # Calculate each factor score
    df["score_value"]     = calc_value_score(df)
    df["score_quality"]   = calc_quality_score(df)
    df["score_momentum"]  = calc_momentum_score(df)
    df["score_growth"]    = calc_growth_score(df)
    df["score_risk"]      = calc_risk_score(df)
    df["score_size"]      = calc_size_score(df)
    df["score_dividend"]  = calc_dividend_score(df)
    df["score_fcf_yield"] = calc_fcf_yield_score(df)  # Exponerat för AI Djup-analys
    
    # Beräkna sentimentpoäng om sentiment_raw finns i datan
    if "sentiment_raw" in df.columns and df["sentiment_raw"].notna().any():
        df["score_sentiment"] = calc_sentiment_score(df)

    # Hämta dynamiska vikter
    w = get_dynamic_weights(regime, config.FACTOR_WEIGHTS)

    # Composite score using the dynamic weights
    # Alla faktorer (inklusive sentiment) ingår i vikterna – summan = 1.0
    df["score_total"] = (
        w.get("value", 0)    * df["score_value"]    +
        w.get("quality", 0)  * df["score_quality"]  +
        w.get("momentum", 0) * df["score_momentum"] +
        w.get("growth", 0)   * df["score_growth"]   +
        w.get("risk", 0)     * df["score_risk"]     +
        w.get("size", 0)     * df["score_size"]     +
        w.get("dividend", 0) * df["score_dividend"] +
        w.get("sentiment", 0) * df.get("score_sentiment", pd.Series(50, index=df.index))
    )

    # ── Holdingbolag & råvarubolag: score-rabatt ────────────────────────
    # Dessa bolag ser "fantastiska" ut i en faktormodell men av fel skäl:
    #   Holdingbolag  → vinster = orealiserade portföljuppgångar, ej operativ lönsamhet
    #   Guld/Silver   → marginaler driven av råvarupris, ej uthållig quality
    # Rabatten hindrar dem från att dominera topp-10 utan att utesluta dem helt.

    if "industry" in df.columns:
        ind_lower = df["industry"].fillna("").str.lower()

        # Holdingbolag: 15% rabatt
        is_holding = ind_lower.apply(
            lambda i: any(h in i for h in HOLDING_INDUSTRIES)
        )
        df.loc[is_holding, "score_total"] = (
            df.loc[is_holding, "score_total"] * HOLDING_DISCOUNT
        ).clip(0, 100)
        df.loc[is_holding, "company_type"] = "holding"

        # Råvarubolag: 10% rabatt (cykliska, commoditypris-beroende)
        is_commodity = ind_lower.apply(
            lambda i: any(c in i for c in COMMODITY_INDUSTRIES)
        )
        df.loc[is_commodity & ~is_holding, "score_total"] = (
            df.loc[is_commodity & ~is_holding, "score_total"] * COMMODITY_DISCOUNT
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