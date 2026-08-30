"""
mews.py — Multi-Bagger Early Warning Score.
Evidensbaserad (Yartseva 2025): hittar småbolag med 10x-potential tidigt.
Returnerar 0-100 + komponenter + boolean-flagga POTENTIAL_MANGDUBBLARE (>=70).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from smallcap.scoring import _percentile_score

# Vikter (summa = 1.0). Härledda ur studiens prediktorstyrka.
MEWS_WEIGHTS = {
    "fcf_yield":          0.25,  # starkaste prediktorn
    "small_size":         0.15,  # litet bolag = mer utrymme att växa
    "low_ps":             0.15,  # låg price/sales vid ingång
    "operating_leverage": 0.20,  # rörelsevinst växer snabbare än intäkter
    "revenue_accel":      0.15,  # intäktsacceleration
    "clean_accruals":     0.10,  # låg Sloan = ärliga vinster
}
MEWS_THRESHOLD = 70.0  # >= → POTENTIAL_MANGDUBBLARE

# Lägsta market cap i USD för att inte vara ren skräp (oinvesterbar mikrobolag)
MIN_MARKET_CAP_USD = 10_000_000  # 10 MSEK ungefär
# Lägsta daily turnover i USD för likviditetsfilter
MIN_DAILY_TURNOVER_USD = 1_000_000  # 1 MSEK


def _f_fcf_yield(df: pd.DataFrame) -> pd.Series:
    """FCF-yield: free_cash_flow / market_cap. Negativ FCF → 0."""
    mc = df["market_cap"].replace(0, np.nan)
    fcf = df["free_cash_flow"].clip(lower=0)  # Negativ FCF → 0
    ratio = fcf / mc
    # Percentil-rank (högre = bättre). NaN (saknad data) flödar in i
    # _percentile_score som median-fyller → neutral ~50 (aldrig 0 = "ren"/"billig").
    return _percentile_score(ratio, ascending=True)


def _f_small_size(df: pd.DataFrame) -> pd.Series:
    """Small size: invers av market_cap (mindre = högre).
    Nollställ mikrobolag under likviditetsgräns. NaN/<=0 market_cap → NaN (saknad)."""
    mc = df["market_cap"].replace(0, np.nan)
    size_score = _percentile_score(mc, ascending=False)
    # NaN/<=0 market_cap → NaN (saknad data, aldrig belönad som "litet")
    size_score = size_score.where(mc.notna(), np.nan)
    # Nollställ oinvesterbara mikrobolag
    below_min = mc < MIN_MARKET_CAP_USD
    size_score = size_score.where(~below_min, np.nan)
    # NaN → neutral (50)
    return size_score.fillna(50.0)


def _f_low_ps(df: pd.DataFrame) -> pd.Series:
    """Low P/S: lägre price_to_sales = högre poäng.
    NaN/<= 0 → NaN (aldrig 0). Försäkringsbolag maskeras ut:
    premieintäkter ≠ försäljning → strukturellt låg P/S skulle annars belönas."""
    ps = df.get("price_to_sales", pd.Series(np.nan, index=df.index))
    # NaN/<= 0 → NaN (aldrig 0)
    ps = ps.where(ps > 0)
    # Maskera ut Financial Services / Insurance (premieintäkter ≠ försäljning)
    if "sector" in df.columns:
        fin = df["sector"].isin(["Financial Services", "Insurance"])
        ps = ps.where(~fin)
    # NaN flödar in i _percentile_score → median-fill → neutral ~50
    return _percentile_score(ps, ascending=False)


def _f_operating_leverage(df: pd.DataFrame) -> pd.Series:
    """Operating leverage: op_income_growth / revenue_growth.
    > 1 = expanderande marginal. Kräver rev_growth > 0 OCH positivt TTM-operating result."""
    rev_ttm = df.get("revenue_ttm", pd.Series(np.nan, index=df.index))
    rev_prev = df.get("revenue_prev", pd.Series(np.nan, index=df.index))
    opinc_ttm = df.get("operating_income_ttm", pd.Series(np.nan, index=df.index))
    opinc_prev = df.get("operating_income_prev", pd.Series(np.nan, index=df.index))

    rev_growth = rev_ttm / rev_prev - 1.0
    opinc_growth = opinc_ttm / opinc_prev - 1.0

    # Bara meningsfullt när rev_growth > 0 och TTM-operating result är positivt
    # (negativt TTM-operating result ska aldrig belönas)
    valid = (rev_growth > 0) & (rev_prev > 0) & (opinc_prev > 0) & (opinc_ttm > 0)
    ratio = pd.Series(np.nan, index=df.index)
    ratio[valid] = opinc_growth[valid] / rev_growth[valid]

    ratio = ratio.clip(lower=0, upper=10)  # Hantera orimliga värden
    # NaN flödar in i _percentile_score → median-fill → neutral ~50
    return _percentile_score(ratio, ascending=True)


def _f_revenue_accel(df: pd.DataFrame) -> pd.Series:
    """Revenue acceleration: senaste tillväxt minus föregående periods tillväxt.
    Om kvartalsdata saknas: 1-årig CAGR minus 2-årig CAGR."""
    # Försök med kvartalsdata först
    rev_growth_q = df.get("revenue_growth_q", pd.Series(np.nan, index=df.index))
    rev_growth_q_prev = df.get("revenue_growth_q_prev", pd.Series(np.nan, index=df.index))

    # Fallback till årsdata
    rev_ttm = df.get("revenue_ttm", pd.Series(np.nan, index=df.index))
    rev_prev = df.get("revenue_prev", pd.Series(np.nan, index=df.index))
    rev_2y_ago = df.get("revenue_2y_ago", pd.Series(np.nan, index=df.index))

    accel = pd.Series(np.nan, index=df.index)

    # Använd kvartalsdata där den finns
    q_mask = rev_growth_q.notna() & rev_growth_q_prev.notna()
    accel[q_mask] = rev_growth_q[q_mask] - rev_growth_q_prev[q_mask]

    # Fallback: 1y CAGR minus 2y CAGR
    y_mask = (~q_mask) & rev_prev.notna() & rev_2y_ago.notna() & (rev_prev > 0) & (rev_2y_ago > 0)
    cagr_1y = rev_ttm / rev_prev - 1.0
    cagr_2y = (rev_ttm / rev_2y_ago) ** 0.5 - 1.0
    accel[y_mask] = cagr_1y[y_mask] - cagr_2y[y_mask]

    # NaN flödar in i _percentile_score → median-fill → neutral ~50
    return _percentile_score(accel, ascending=True)


def _f_clean_accruals(df: pd.DataFrame) -> pd.Series:
    """Clean accruals (Sloan): lägre = bättre.
    sloan = (net_income - operating_cashflow) / ((total_assets + total_assets_prev)/2)"""
    ni = df.get("net_income_ttm", pd.Series(np.nan, index=df.index))
    ocf = df.get("operating_cashflow_ttm", pd.Series(np.nan, index=df.index))
    ta = df.get("total_assets", pd.Series(np.nan, index=df.index))
    ta_prev = df.get("total_assets_prev", pd.Series(np.nan, index=df.index))

    avg_assets = (ta + ta_prev) / 2
    sloan = pd.Series(np.nan, index=df.index)
    valid = ni.notna() & ocf.notna() & (avg_assets > 0)
    sloan[valid] = (ni[valid] - ocf[valid]) / avg_assets[valid]

    # Lägre Sloan = bättre (ascending=False). NaN flödar in i _percentile_score
    # (median-fill → neutral ~50); slut-fillna(50.0) täcker alla-NaN-kolumnen.
    return _percentile_score(sloan, ascending=False).fillna(50.0)


def score_mews(df: pd.DataFrame) -> pd.DataFrame:
    """Returnerar df med kolumner:
       mews_fcf_yield, mews_small_size, mews_low_ps, mews_operating_leverage,
       mews_revenue_accel, mews_clean_accruals,
       mews_score (0-100), mews_flag (bool)."""
    if df.empty:
        return df.copy()
    out = df.copy()
    out["mews_fcf_yield"]          = _f_fcf_yield(df)
    out["mews_small_size"]         = _f_small_size(df)
    out["mews_low_ps"]             = _f_low_ps(df)
    out["mews_operating_leverage"] = _f_operating_leverage(df)
    out["mews_revenue_accel"]      = _f_revenue_accel(df)
    out["mews_clean_accruals"]     = _f_clean_accruals(df)
    out["mews_score"] = (
        out["mews_fcf_yield"]          * MEWS_WEIGHTS["fcf_yield"] +
        out["mews_small_size"]         * MEWS_WEIGHTS["small_size"] +
        out["mews_low_ps"]             * MEWS_WEIGHTS["low_ps"] +
        out["mews_operating_leverage"] * MEWS_WEIGHTS["operating_leverage"] +
        out["mews_revenue_accel"]      * MEWS_WEIGHTS["revenue_accel"] +
        out["mews_clean_accruals"]     * MEWS_WEIGHTS["clean_accruals"]
    ).clip(0, 100).round(1)

    # ── Coverage: antal sub-signaler med ÄKTA rådata (0-6).
    #    Beräknas på df-input-nivå (rådata), INTE på sub-score-nivå — median-fillade
    #    sub-scores är icke-NaN och skulle annars räknas som "täckta".
    coverage = pd.Series(0, index=df.index)
    # fcf_yield-valid: free_cash_flow + market_cap finns
    coverage += df["free_cash_flow"].notna() & df["market_cap"].notna()
    # small_size-valid: market_cap finns och > 10M (över likviditetsgräns)
    coverage += df["market_cap"].notna() & (df["market_cap"] > MIN_MARKET_CAP_USD)
    # low_ps-valid: price_to_sales finns, > 0, och inte Financial Services/Insurance
    ps = df.get("price_to_sales", pd.Series(np.nan, index=df.index))
    ps_ok = ps.notna() & (ps > 0)
    if "sector" in df.columns:
        ps_ok = ps_ok & ~df["sector"].isin(["Financial Services", "Insurance"])
    coverage += ps_ok
    # op_leverage-valid: rev_prev, opinc_prev, opinc_ttm alla > 0 (samma mask som _f_operating_leverage)
    rev_prev = df.get("revenue_prev", pd.Series(np.nan, index=df.index))
    opinc_prev = df.get("operating_income_prev", pd.Series(np.nan, index=df.index))
    opinc_ttm = df.get("operating_income_ttm", pd.Series(np.nan, index=df.index))
    coverage += (rev_prev > 0) & (opinc_prev > 0) & (opinc_ttm > 0)
    # revenue_accel-valid: kvartalsdata ELLER 1y/2y-rev-data finns
    rev_growth_q = df.get("revenue_growth_q", pd.Series(np.nan, index=df.index))
    rev_growth_q_prev = df.get("revenue_growth_q_prev", pd.Series(np.nan, index=df.index))
    rev_ttm = df.get("revenue_ttm", pd.Series(np.nan, index=df.index))
    rev_2y_ago = df.get("revenue_2y_ago", pd.Series(np.nan, index=df.index))
    accel_ok = (rev_growth_q.notna() & rev_growth_q_prev.notna()) | (
        rev_prev.notna() & rev_2y_ago.notna() & (rev_prev > 0) & (rev_2y_ago > 0)
    )
    coverage += accel_ok
    # clean_accruals-valid: net_income_ttm, operating_cashflow_ttm, avg_assets > 0
    ni = df.get("net_income_ttm", pd.Series(np.nan, index=df.index))
    ocf = df.get("operating_cashflow_ttm", pd.Series(np.nan, index=df.index))
    ta = df.get("total_assets", pd.Series(np.nan, index=df.index))
    ta_prev = df.get("total_assets_prev", pd.Series(np.nan, index=df.index))
    avg_assets = (ta + ta_prev) / 2
    coverage += ni.notna() & ocf.notna() & (avg_assets > 0)

    # ── Kvalitetsgate: Piotroski F >= 5 OCH positiv ROA, samt coverage >= 3.
    #    ROND 7 (2026-08-30): coverage-kravet sänkt 4 -> 3 (var för strängt och
    #    resulterade i 0 flaggor för hela universumet → MEWS oanvändbar).
    #    Fallback om kolumn saknas → hoppa över den delen av gaten (gate ofullständig).
    gate_ok = pd.Series(True, index=df.index)
    if "piotroski_f" in df.columns:
        gate_ok &= df["piotroski_f"] >= 5
    # roa saknas → fallback till roe > 0
    if "roa" in df.columns:
        gate_ok &= df["roa"] > 0
    elif "roe" in df.columns:
        gate_ok &= df["roe"] > 0
    gate_ok &= coverage >= 3
    # fcf_yield är den starkaste prediktorn (vikt 0.25) — flagga kräver äkta FCF-data
    gate_ok &= df["free_cash_flow"].notna() & df["market_cap"].notna()
    out["mews_flag"] = (out["mews_score"] >= MEWS_THRESHOLD) & gate_ok
    # ROND 7: "kandidat" (70% av tröskeln) — sämre än flagga men värde-att bevaka.
    # Mångdubblar-potential kan vara tidig; kandidat-fältet ger UI möjlighet
    # att visa "värd att följa" utan att lova en flagg.
    out["mews_candidate"] = (out["mews_score"] >= 0.85 * MEWS_THRESHOLD) & gate_ok
    return out
