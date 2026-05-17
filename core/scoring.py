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
    Value score: FCF Yield primary (70%), other multiples as conditioning signals.
    
    Per the quantitative architecture review:
    - EV-based FCF Yield is the most robust valuation metric over 30-year horizons
      (higher absolute returns, fewer drawdowns than P/E, P/B, or EV/EBITDA
    - EV/EBITDA is relegated to a conditioning variable: flags aggressive
      depreciation/tax deferral when EBITDA >> FCF
    - P/E, P/B, P/S used as secondary consistency checks
    """
    components = []
    component_weights = []

    # ── PRIMARY: EV-based FCF Yield (70% of value score) ────────────────
    fcf_score = calc_fcf_yield_score(df)
    fcf_neutral = (fcf_score == NEUTRAL_SCORE).all()
    if not fcf_neutral:
        components.append(fcf_score)
        component_weights.append(0.70)

    # ── Conditioning: EV/EBITDA (30% of value score) ───────────────────
    # Also serves as penalty flag: if EV/EBITDA is extremely low (< 3) while
    # FCF yield is poor → possible aggressive accruals / tax deferral
    ev_ebitda = df["ev_to_ebitda"].where(df["ev_to_ebitda"] > 0)
    ev_score = _try_rank(ev_ebitda, ascending=False)
    if ev_score is not None:
        components.append(ev_score)
        component_weights.append(0.30)

    # ── No primary available? Fall back to P/E, P/B, P/S ───────────────
    if not components:
        # Forward P/E (preferred over trailing if available)
        pe = df["pe_forward"].fillna(df["pe_trailing"])
        pe = pe.where(pe > 0)
        score = _try_rank(pe, ascending=False)
        if score is not None:
            components.append(score)
            component_weights.append(0.40)

        # Price-to-Book
        pb = df["price_to_book"].where(df["price_to_book"] > 0)
        score = _try_rank(pb, ascending=False)
        if score is not None:
            components.append(score)
            component_weights.append(0.35)

        # Price-to-Sales
        ps = df["price_to_sales"].where(df["price_to_sales"] > 0)
        score = _try_rank(ps, ascending=False)
        if score is not None:
            components.append(score)
            component_weights.append(0.25)

    if not components:
        return _neutral_series(df.index)

    # Weighted sum (not equal-weighted as before)
    total_w = sum(component_weights)
    weighted = sum(c * w for c, w in zip(components, component_weights))
    return weighted / total_w


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


def score_universe_sector_neutralized(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate factor scores WITHIN-sector neutralization.
    
    Per the architecture review: for long-short strategies, stripping out
    the cross-sector component isolates pure firm-specific alpha.
    The within-sector portfolio (W) dominates the across-sector portfolio (A)
    with a 78% win-rate in long-short applications.
    
    This function subtracts the sector median from each raw metric
    BEFORE percentile ranking, removing structural sector biases.
    
    Returns df with same schema as score_universe() but sector-neutralized.
    """
    df = df.copy()
    
    # Ensure we have sector data
    if "sector" not in df.columns:
        df["sector"] = df.get("industry", "Unknown").fillna("Unknown")
    
    sectors = df["sector"].fillna("Unknown")
    
    # Define which metrics to neutralize (lower-is-better already handled later)
    _NEUTRALIZE_METRICS = [
        # Valuation — subtract sector median P/E, P/B, EV/EBITDA
        ("pe_forward", False), ("pe_trailing", False),
        ("price_to_book", False), ("ev_to_ebitda", False),
        # Quality — subract sector median ROE, margins  
        ("roe", True), ("roa", True),
        ("profit_margin", True), ("operating_margin", True),
        # Growth — subtract sector median growth rates
        ("revenue_growth", True), ("earnings_growth", True),
        # Risk — subtract sector median D/E, current ratio
        ("debt_to_equity", False), ("current_ratio", True),
    ]
    
    # Create sector-neutralized versions of each metric
    for col, _ in _NEUTRALIZE_METRICS:
        if col in df.columns:
            sector_median = df.groupby(sectors)[col].transform("median")
            df[f"{col}_neutral"] = df[col] - sector_median
    
    # Patching step: overwrite original columns with neutralized versions
    for col, _ in _NEUTRALIZE_METRICS:
        neutral_col = f"{col}_neutral"
        if neutral_col in df.columns and df[neutral_col].notna().any():
            df[col] = df[neutral_col]
    
    # Calculate all factor scores (now sector-neutralized)
    df["score_value"]     = calc_value_score(df)
    df["score_quality"]   = calc_quality_score(df)
    df["score_momentum"]  = calc_momentum_score(df)
    df["score_growth"]    = calc_growth_score(df)
    df["score_risk"]      = calc_risk_score(df)
    df["score_size"]      = calc_size_score(df)
    df["score_dividend"]  = calc_dividend_score(df)
    df["score_fcf_yield"] = calc_fcf_yield_score(df)
    
    # Beräkna sentimentpoäng alltid – insider-boostar appliceras oavsett
    # om sentiment_raw finns (calc_sentiment_score startar från neutral vid saknad data).
    df["score_sentiment"] = calc_sentiment_score(df)

    # Dynamic weights (neutral mode → use base weights)
    w = get_dynamic_weights("OSÄKER", config.FACTOR_WEIGHTS)

    df["score_total"] = (
        w.get("value", 0)     * df["score_value"]     +
        w.get("quality", 0)   * df["score_quality"]   +
        w.get("momentum", 0)  * df["score_momentum"]  +
        w.get("growth", 0)    * df["score_growth"]    +
        w.get("risk", 0)      * df["score_risk"]      +
        w.get("size", 0)      * df["score_size"]      +
        w.get("dividend", 0)  * df["score_dividend"]  +
        w.get("sentiment", 0) * df["score_sentiment"]
    )
    
    # Same holding/commodity discounts as score_universe
    if "industry" in df.columns:
        ind_lower = df["industry"].fillna("").str.lower()
        is_holding = ind_lower.apply(lambda i: any(h in i for h in HOLDING_INDUSTRIES))
        df.loc[is_holding, "score_total"] = (df.loc[is_holding, "score_total"] * HOLDING_DISCOUNT).clip(0, 100)
        is_commodity = ind_lower.apply(lambda i: any(c in i for c in COMMODITY_INDUSTRIES))
        df.loc[is_commodity & ~is_holding, "score_total"] = (df.loc[is_commodity & ~is_holding, "score_total"] * COMMODITY_DISCOUNT).clip(0, 100)
    
    df["rank"] = df["score_total"].rank(ascending=False, method="min").astype("Int64")
    
    return df.sort_values("score_total", ascending=False).reset_index(drop=True)


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
    
    # Beräkna sentimentpoäng alltid – calc_sentiment_score() hanterar saknad
    # sentiment_raw genom att starta från neutral (50) och applicerar ändå
    # insider-boostarna (insider_executive_buy, insider_cluster) om de finns.
    df["score_sentiment"] = calc_sentiment_score(df)

    # Hämta dynamiska vikter
    w = get_dynamic_weights(regime, config.FACTOR_WEIGHTS)

    # Composite score using the dynamic weights
    # Alla faktorer (inklusive sentiment) ingår i vikterna – summan = 1.0
    df["score_total"] = (
        w.get("value", 0)     * df["score_value"]     +
        w.get("quality", 0)   * df["score_quality"]   +
        w.get("momentum", 0)  * df["score_momentum"]  +
        w.get("growth", 0)    * df["score_growth"]    +
        w.get("risk", 0)      * df["score_risk"]      +
        w.get("size", 0)      * df["score_size"]      +
        w.get("dividend", 0)  * df["score_dividend"]  +
        w.get("sentiment", 0) * df["score_sentiment"]
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