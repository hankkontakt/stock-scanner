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

Region neutralization (added 2026-05):
- Fundamental metrics (P/E, P/B, ROE, margins) are region-adjusted before
  percentile ranking. A Swedish industrial stock's P/E 15 is no longer ranked
  against Nasdaq tech P/E 35 — instead it's ranked relative to its regional
  peers. This corrects the most significant cross-market bias in the original
  global-percentile approach.
- Momentum is intentionally kept global (cross-market relative strength is
  a valid factor and is not distorted by valuation-regime differences).
- Liquidity flag: stocks with estimated daily turnover < USD 50k (or equivalent)
  are tagged low_liquidity=True so users can filter them out.
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

# ── Likviditetsgräns ─────────────────────────────────────────────────────────
# Uppskattad daglig omsättning i USD under denna gräns → low_liquidity = True.
# avg_volume (aktier/dag) × current_price (lokal valuta) omräknas till USD via
# en förenklad tabell. Allt under $50k/dag är i praktiken handelsmässigt svårt
# att kliva in/ur utan onödig spread och slippage.
MIN_DAILY_TURNOVER_USD = 50_000

# Ungefärliga konverteringsfaktorer lokal valuta → USD (uppdateras sällan).
# Används ENBART för likviditetsestimering, inte för kursjämförelser.
_CCY_TO_USD = {
    "SEK": 0.095,   # 1 SEK ≈ 0.095 USD (1 USD ≈ 10.5 SEK)
    "NOK": 0.093,
    "DKK": 0.143,
    "EUR": 1.08,
    "GBP": 1.27,
    "JPY": 0.0065,
    "HKD": 0.128,
    "KRW": 0.00073,
    "TWD": 0.031,
    "AUD": 0.65,
    "CAD": 0.73,
    "INR": 0.012,
    "BRL": 0.18,
    "MXN": 0.052,
    "CHF": 1.12,
    "SGD": 0.74,
    "CNY": 0.138,
    "USD": 1.0,
}

HOLDING_INDUSTRIES = {
    "asset management", "diversified investments", "investment trusts",
    "closed-end fund", "exchange traded fund", "capital markets",
}
COMMODITY_INDUSTRIES = {
    "gold", "silver", "copper", "other precious metals & mining",
    "steel", "aluminum", "uranium", "oil & gas e&p",
}

# ── Börsgrupper för region-neutralisering ────────────────────────────────────
# Fundamentala värderingsmultiplar (P/E, P/B, ROE, marginaler) skiljer sig
# systematiskt mellan marknader p.g.a. redovisningsregler, ränteklimat och
# historiska prissättningsregimer. Vi subtraherar gruppens median innan
# percentilrankning så att en svenska aktie rankas mot svenska aktier,
# inte mot Nasdaq-tech.
#
# Ticker-suffix → exchange_group
_SUFFIX_TO_GROUP = {
    # Norden
    ".ST": "Nordic", ".HE": "Nordic", ".CO": "Nordic", ".OL": "Nordic",
    # UK
    ".L": "UK",
    # Kontinentaleuropa
    ".DE": "Europe", ".PA": "Europe", ".AS": "Europe", ".MI": "Europe",
    ".MC": "Europe", ".VI": "Europe", ".WA": "Europe", ".LS": "Europe",
    ".SW": "Europe",
    # Nordamerika
    ".TO": "Canada", ".AX": "Australia",
    # Asien
    ".T": "Japan",
    ".HK": "Asia", ".TW": "Asia", ".KS": "Asia",
    ".NS": "India", ".BO": "India",
    # Latinamerika
    ".SA": "LatAm", ".MX": "LatAm",
    # Singapore
    ".SI": "Singapore",
}

# Fundamentala kolumner som ska region-neutraliseras.
# Momentum-kolumner (return_*) är medvetet EXKLUDERADE — global relativ styrka
# är ett legitimt cross-market-signal.
_REGION_NEUTRALIZE_COLS = [
    ("pe_trailing",       False),   # Lägre är bättre
    ("pe_forward",        False),
    ("price_to_book",     False),
    ("ev_to_ebitda",      False),
    ("roe",               True),    # Högre är bättre
    ("roa",               True),
    ("profit_margin",     True),
    ("operating_margin",  True),
    ("gross_margin",      True),
    ("debt_to_equity",    False),
    ("current_ratio",     True),
    ("free_cash_flow",    True),    # Relativt EV — region-median påverkar FCF-yield-rankning
]

# ── Hjälpfunktioner ────────────────────────────────────────────────────────

def _neutral_series(index) -> pd.Series:
    """Returnerar en serie med neutrala poäng (50) för alla index-entries."""
    return pd.Series(NEUTRAL_SCORE, index=index)


def _assign_exchange_group(ticker: str) -> str:
    """Returnerar börsgrupp baserat på ticker-suffix.

    Exempel:
        'VOLV-B.ST' → 'Nordic'
        'AAPL'      → 'US'
        'SAP.DE'    → 'Europe'
        '7203.T'    → 'Japan'
    """
    t = str(ticker).upper()
    for suffix, group in _SUFFIX_TO_GROUP.items():
        if t.endswith(suffix.upper()):
            return group
    return "US"  # Ingen suffix = amerikanskt papper


def _add_exchange_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Lägger till kolumnen 'exchange_group' om den saknas."""
    if "exchange_group" not in df.columns:
        if "ticker" in df.columns:
            df = df.copy()
            df["exchange_group"] = df["ticker"].apply(_assign_exchange_group)
        else:
            df = df.copy()
            df["exchange_group"] = df.index.map(
                lambda t: _assign_exchange_group(str(t))
            )
    return df


def _region_neutralize_fundamentals(df: pd.DataFrame) -> pd.DataFrame:
    """Subtraherar regionmedianen från fundamentala värderingsmultiplar
    INNAN percentilrankning. Detta gör att en svensk aktie rankas mot
    svenska/nordiska peers, inte mot global median.

    Kolumner som neutraliseras definieras i _REGION_NEUTRALIZE_COLS.
    Momentum (return_*) neutraliseras INTE — global relativ styrka är valid.

    Returnerar en kopia av df med justerade kolumnvärden.
    Originaldatan skrivs inte tillbaka; df-schemat bibehålls.
    """
    df = _add_exchange_groups(df)
    groups = df["exchange_group"]

    for col, _ in _REGION_NEUTRALIZE_COLS:
        if col not in df.columns:
            continue
        # Tvinga numerisk typ — yfinance kan returnera strängen "Infinity"
        # (eller "-Infinity") som JSON-token för P/E när vinst ≈ 0.
        # pd.to_numeric(..., errors="coerce") konverterar sådana strängar till NaN.
        series = pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
        df[col] = series
        if series.isna().all():
            continue
        # Beräkna regionmedian för varje rad
        region_median = series.groupby(groups).transform("median")
        # Subtrahera medianen: värdet blir nu "relativt regionen"
        # NaN-rader i originalet förblir NaN (transform hanterar det korrekt)
        df[col] = series - region_median

    return df


def _estimate_daily_turnover_usd(df: pd.DataFrame) -> pd.Series:
    """Uppskattar daglig omsättning i USD per aktie.

    Formel: avg_volume_10d (aktier/dag) × current_price (lokal valuta) × FX → USD

    Fallback-kedja:
        1. avg_volume_10d × current_price × FX
        2. avg_volume × current_price × FX
        3. NaN (otillräcklig data)

    Notera: FX-faktorerna i _CCY_TO_USD är statiska approximationer som
    enbart används för likviditetsflaggning — inte för kursjämförelser.
    """
    # Välj bästa volymkolumn
    if "avg_volume_10d" in df.columns and df["avg_volume_10d"].notna().any():
        vol = df["avg_volume_10d"]
    elif "avg_volume" in df.columns and df["avg_volume"].notna().any():
        vol = df["avg_volume"]
    else:
        return pd.Series(np.nan, index=df.index)

    # Pris i lokal valuta
    price_col = next(
        (c for c in ("current_price", "close", "last_price") if c in df.columns),
        None,
    )
    if price_col is None:
        return pd.Series(np.nan, index=df.index)
    price = df[price_col]

    # FX-konvertering
    if "currency" in df.columns:
        fx = df["currency"].map(_CCY_TO_USD).fillna(1.0)
    else:
        # Ingen valutakolumn: anta USD för US, SEK för .ST, annars 1.0
        if "ticker" in df.columns:
            def _guess_fx(t: str) -> float:
                t = str(t).upper()
                for sfx, grp in _SUFFIX_TO_GROUP.items():
                    if t.endswith(sfx.upper()):
                        # Approximera: Nordic→SEK, UK→GBP, Europe→EUR, Japan→JPY
                        _grp_ccy = {
                            "Nordic": "SEK", "UK": "GBP", "Europe": "EUR",
                            "Japan": "JPY", "Asia": "HKD", "Canada": "CAD",
                            "Australia": "AUD", "India": "INR",
                            "LatAm": "BRL", "Singapore": "SGD",
                        }
                        ccy = _grp_ccy.get(grp, "USD")
                        return _CCY_TO_USD.get(ccy, 1.0)
                return 1.0  # US
            fx = df["ticker"].apply(_guess_fx)
        else:
            fx = pd.Series(1.0, index=df.index)

    turnover_usd = vol * price * fx
    return turnover_usd.where(turnover_usd > 0)


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


def _insider_decay_weight(df: pd.DataFrame) -> pd.Series:
    """
    Beräkna time-based decay weight för insider-signaler.
    Nyinsider-signaler får full vikt, men avtar linjärt mot 0 efter 180 dagar.
    Detta eftersom forskning visar att insider alpha decayar inom 3-6 månader.
    
    Returnerar pd.Series med decay weights (0.0–1.0).
    Om datum saknas → weight = 1.0 (full boost, bakåtkompatibelt).
    """
    if "insider_recent_date" not in df.columns:
        return pd.Series(1.0, index=df.index)
    
    now = pd.Timestamp.now()
    dates = pd.to_datetime(df["insider_recent_date"], errors="coerce")
    
    days_since = (now - dates).dt.days.clip(lower=0)
    decay = 1.0 - (days_since / 180.0)  # Linjär decay: 1.0 dag 0 → 0.0 dag 180
    decay = decay.clip(lower=0.0, upper=1.0)
    # NaT = datum saknas (t.ex. gammal cachad data utan datumsupport).
    # Bakåtkompatibelt beteende: behåll full boost (1.0) så att befintliga
    # insider-signaler utan datum inte tystnar plötsligt vid uppgradering.
    # Ny data har alltid insider_recent_date satt av _get_insider_signal().
    return decay.fillna(1.0)


def calc_sentiment_score(df: pd.DataFrame) -> pd.Series:
    """
    Sentiment score från Finnhub-nyhetsdata + insiderhandelssignaler.
    'sentiment_raw' = -1 till +1 från Finnhub.
    Insider-boost: VD/CFO-köp → +20 poäng, cluster-köp → +30 poäng.
    Insider-boosten är tidsdämpad (decay över 180 dagar) enligt forskning
    som visar att insider alpha förfaller inom 3-6 månader.
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

    # ── Insider-boost med tidsdämpning ──────────────────────────────────────
    # VD/CFO köper: starkt bullish signal (+20 base, capped 95)
    # Cluster (≥3 insiders inom 30d): ännu starkare (+30 base, capped 98)
    # Båda dämpas linjärt över 180 dagar via _insider_decay_weight()
    if "insider_executive_buy" in df.columns:
        exec_mask    = df["insider_executive_buy"].fillna(False).astype(bool)
        cluster_mask = df.get("insider_cluster", pd.Series(False, index=df.index)).fillna(False).astype(bool)
        decay_w      = _insider_decay_weight(df)
        
        score = score.copy()
        score[exec_mask]    = (score[exec_mask]    + 20 * decay_w[exec_mask]).clip(upper=95)
        score[cluster_mask] = (score[cluster_mask] + 30 * decay_w[cluster_mask]).clip(upper=98)

    return score


def score_universe_sector_neutralized(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate factor scores with BOTH region- and sector-neutralization.

    Tillämpningsordning:
        1. Region-neutralisering (subtrahera regionmedian) — tar bort systematiska
           skillnader i värderingsregim mellan marknader (US tech vs Nordic industrial).
        2. Sektor-neutralisering (subtrahera sektormedianen) — isolerar
           bolagsspecifik alpha från sektorexponering.

    Per the architecture review: the within-sector portfolio (W) dominates the
    across-sector portfolio (A) with a 78% win-rate in long-short applications.
    Combining with region-neutralization removes the cross-market valuation bias
    that distorts single-region percentile rankings.

    Returns df with same schema as score_universe() + low_liquidity flag.
    """
    df = df.copy()

    # ── Steg 1: Region-neutralisering ────────────────────────────────────────
    df = _region_neutralize_fundamentals(df)

    # ── Steg 2: Sektor-neutralisering (ovanpå region-justerade värden) ───────
    if "sector" not in df.columns:
        df["sector"] = df.get("industry", "Unknown").fillna("Unknown")

    sectors = df["sector"].fillna("Unknown")

    _SECTOR_NEUTRALIZE = [
        "pe_forward", "pe_trailing", "price_to_book", "ev_to_ebitda",
        "roe", "roa", "profit_margin", "operating_margin",
        "revenue_growth", "earnings_growth",
        "debt_to_equity", "current_ratio",
    ]
    for col in _SECTOR_NEUTRALIZE:
        if col in df.columns and df[col].notna().any():
            sector_median = df.groupby(sectors)[col].transform("median")
            df[col] = df[col] - sector_median

    # ── Steg 3: Faktorscore ───────────────────────────────────────────────────
    df["score_value"]     = calc_value_score(df)
    df["score_quality"]   = calc_quality_score(df)
    df["score_momentum"]  = calc_momentum_score(df)
    df["score_growth"]    = calc_growth_score(df)
    df["score_risk"]      = calc_risk_score(df)
    df["score_size"]      = calc_size_score(df)
    df["score_dividend"]  = calc_dividend_score(df)
    df["score_fcf_yield"] = calc_fcf_yield_score(df)
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
        df.loc[is_holding, "score_total"] = (
            df.loc[is_holding, "score_total"] * HOLDING_DISCOUNT
        ).clip(0, 100)
        is_commodity = ind_lower.apply(lambda i: any(c in i for c in COMMODITY_INDUSTRIES))
        df.loc[is_commodity & ~is_holding, "score_total"] = (
            df.loc[is_commodity & ~is_holding, "score_total"] * COMMODITY_DISCOUNT
        ).clip(0, 100)

    df["rank"] = df["score_total"].rank(ascending=False, method="min").astype("Int64")

    # ── Steg 4: Likviditetsflagg (identisk med score_universe) ───────────────
    turnover = _estimate_daily_turnover_usd(df)
    df["est_daily_turnover_usd"] = turnover.round(0).astype("Int64", errors="ignore")
    df["low_liquidity"] = (
        turnover.fillna(0) < MIN_DAILY_TURNOVER_USD
    ) | turnover.isna()

    return df.sort_values("score_total", ascending=False).reset_index(drop=True)


def score_universe(df: pd.DataFrame, regime: str = "OSÄKER") -> pd.DataFrame:
    """
    Calculate all factor scores and composite score.
    Returns df with new columns added.

    Pipeline:
        1. Region-neutralisera fundamentala metrics (subtrahera regionmedian)
           så att P/E 15 för ett nordiskt bolag inte jämförs mot Nasdaq-tech P/E 35.
        2. Beräkna faktorscore på de region-justerade värdena.
        3. Momentum hålls globalt (intentionellt — cross-market relativ styrka är valid).
        4. Likviditetsflagg: low_liquidity=True om dagsomsättning < MIN_DAILY_TURNOVER_USD.
    """
    df = df.copy()

    # ── Steg 1: Region-neutralisera fundamentala metrics ─────────────────────
    # Subtraherar regionmedianen för P/E, P/B, ROE, marginaler m.fl. INNAN
    # percentilrankning. Nordiska aktier rankas mot nordiska peers.
    # Momentum-kolumner (return_*) är undantagna — de rankas globalt.
    df = _region_neutralize_fundamentals(df)

    # ── Steg 2: Beräkna faktorscore ──────────────────────────────────────────
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
    if available_cols:
        df["data_quality"] = df[available_cols].notna().sum(axis=1) / len(available_cols)
    else:
        # Inga metric-kolumner alls (t.ex. korrupt cache) → undvik division med noll
        df["data_quality"] = 0.0

    # ── Steg 4: Likviditetsflagg ──────────────────────────────────────────────
    # Beräkna uppskattad daglig omsättning i USD. Aktier under tröskeln
    # (MIN_DAILY_TURNOVER_USD) flaggas low_liquidity=True. Dessa visas
    # fortfarande i UI:t men kan filtreras bort av användaren.
    # Flaggan påverkar INTE score_total (vi bestraffar inte för låg likviditet
    # eftersom småbolagspremien är en del av poängsättningen — storlekspoängen
    # hanterar det redan via calc_size_score).
    turnover = _estimate_daily_turnover_usd(df)
    df["est_daily_turnover_usd"] = turnover.round(0).astype("Int64", errors="ignore")
    df["low_liquidity"] = (
        turnover.fillna(0) < MIN_DAILY_TURNOVER_USD
    ) | turnover.isna()

    return df.sort_values("score_total", ascending=False).reset_index(drop=True)


