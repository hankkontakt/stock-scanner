"""
filters.py – Hårda filter för svenska småbolag.

Dessa filter körs INNAN scoring och eliminerar "giftiga" bolag:
  1. Likviditetsgräns     – för illikvida aktier kan man inte sälja i stress
  2. Marknadsvärde        – håll dig inom small/micro-cap-definitionen
  3. Balansräkning        – negativt eget kapital = konkursrisk
  4. Extremt hög skuld    – ränteskydd < 1x
  5. Piotroski-gräns      – för svaga fundamenta
  6. Utspädningsfälla     – bolag som kontinuerligt späder ut ägarna

Varje filter returnerar en bool-mask (True = behåll).
apply_all_filters() kör alla och loggar vad som filtreras bort.
"""

import pandas as pd
import numpy as np

# ── Trösklar ─────────────────────────────────────────────────────────────────
MIN_DAILY_TURNOVER_SEK  = 300_000   # Daglig omsättning SEK (volym × pris)
MIN_MARKET_CAP_SEK      = 30_000_000  # 30 MSEK – under detta = micro/penny
MAX_MARKET_CAP_SEK      = 10_000_000_000  # 10 GSEK – över detta = mid/large cap
MAX_DEBT_TO_EQUITY      = 300       # D/E > 300% = skuldfälla
MIN_CURRENT_RATIO       = 0.4       # Under 0.4 = likviditetskris
MAX_PIOTROSKI_SKIP      = 2         # F-Score ≤ 2 = eliminera (ej bara penalty)
MAX_DILUTION_PCT        = 0.30      # Aktieantal ökat > 30% senaste år = stor röd flagga

# SEK till USD approximation (yfinance returnerar USD market_cap för .ST)
# Faktisk conversion-rate för filter-ändamål – bara ungefärlig
SEK_USD_APPROX = 0.094  # 1 SEK ≈ 0.094 USD


def _daily_turnover(df: pd.DataFrame) -> pd.Series:
    """Daglig omsättning i aktiets valuta (volym × stängningspris)."""
    vol   = df.get("avg_volume",    pd.Series(0, index=df.index)).fillna(0)
    price = df.get("current_price", pd.Series(0, index=df.index)).fillna(0)
    return (vol * price).fillna(0)


def filter_liquidity(df: pd.DataFrame, verbose: bool = True) -> pd.Series:
    """
    Ta bort aktier med för låg daglig handel.
    Illikvida small caps kan inte säljas i kris utan att flytta kursen.
    """
    turnover = _daily_turnover(df)
    # Konvertera till SEK (yfinance priset är i SEK för .ST)
    mask = turnover >= MIN_DAILY_TURNOVER_SEK
    if verbose and (~mask).any():
        n = (~mask).sum()
        bad = df.loc[~mask, "ticker"].tolist()[:6]
        print(f"  Likviditet: tar bort {n} illikvida ({bad}{'...' if n>6 else ''})")
    return mask


def filter_market_cap(df: pd.DataFrame, verbose: bool = True) -> pd.Series:
    """
    Filtrera på marknadsvärde. yfinance returnerar USD för .ST.
    Konverterar till SEK med grov approximation.
    """
    mkcap = df.get("market_cap", pd.Series(np.nan, index=df.index)).fillna(0)
    # yfinance returnerar ofta USD för svenska aktier
    mkcap_sek = mkcap / SEK_USD_APPROX

    mask = mkcap_sek.between(MIN_MARKET_CAP_SEK, MAX_MARKET_CAP_SEK)
    # Om market_cap saknas – behåll (låt scoring hantera det)
    mask = mask | mkcap.isna() | mkcap.eq(0)
    if verbose and (~mask).any():
        n = (~mask).sum()
        print(f"  Marknadsvärde: tar bort {n} utanför 30 MSEK–10 GSEK")
    return mask


def filter_balance_sheet(df: pd.DataFrame, verbose: bool = True) -> pd.Series:
    """
    Ta bort bolag med livsfarlig balansräkning:
    - Negativt eget kapital (techniskt insolvent)
    - Current ratio < 0.4 (kan inte betala kortfristiga skulder)
    - D/E > 300% (skuldfälla)
    """
    de = df.get("debt_to_equity", pd.Series(np.nan, index=df.index))
    cr = df.get("current_ratio",  pd.Series(np.nan, index=df.index))

    mask_de = de.isna() | (de <= MAX_DEBT_TO_EQUITY)
    mask_cr = cr.isna() | (cr >= MIN_CURRENT_RATIO)
    mask    = mask_de & mask_cr

    if verbose and (~mask).any():
        n = (~mask).sum()
        bad = df.loc[~mask, "ticker"].tolist()[:5]
        print(f"  Balansräkning: tar bort {n} farliga ({bad})")
    return mask


def filter_piotroski(df: pd.DataFrame, verbose: bool = True) -> pd.Series:
    """
    Eliminera bolag med extremt låg Piotroski F-Score (≤ 2).
    F-Score 0–2 = allvarliga redovisningsproblem.
    Saknas data → behåll (ge benefit of doubt).
    """
    if "piotroski_score" not in df.columns:
        return pd.Series(True, index=df.index)

    score = df["piotroski_score"].fillna(5)  # Neutralt default
    mask  = score > MAX_PIOTROSKI_SKIP
    if verbose and (~mask).any():
        n = (~mask).sum()
        bad = df.loc[~mask, "ticker"].tolist()[:5]
        print(f"  Piotroski: tar bort {n} med F-Score ≤ {MAX_PIOTROSKI_SKIP} ({bad})")
    return mask


def filter_dilution(df: pd.DataFrame, verbose: bool = True) -> pd.Series:
    """
    Ta bort bolag som späder ut ägarna aggressivt.
    shares_change_pct > 30% på ett år = trolig desperat kapitalförstärkning.
    """
    if "shares_change_pct" not in df.columns:
        return pd.Series(True, index=df.index)

    chg  = df["shares_change_pct"].fillna(0)
    mask = chg <= MAX_DILUTION_PCT
    if verbose and (~mask).any():
        n = (~mask).sum()
        bad = df.loc[~mask, "ticker"].tolist()[:5]
        print(f"  Utspädning: tar bort {n} (aktieantal +{MAX_DILUTION_PCT*100:.0f}%+) ({bad})")
    return mask


def filter_has_price(df: pd.DataFrame, verbose: bool = True) -> pd.Series:
    """Grundkrav: måste ha ett aktuellt pris (annars delistad/trasig data)."""
    price = df.get("current_price", pd.Series(np.nan, index=df.index))
    mask  = price.notna() & (price > 0)
    if verbose and (~mask).any():
        n = (~mask).sum()
        bad = df.loc[~mask, "ticker"].tolist()[:5]
        print(f"  Pris saknas: tar bort {n} ({bad})")
    return mask


def apply_all_filters(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    Kör alla hårda filter i ordning.
    Returnerar filtrerad DataFrame + dict med statistik.
    """
    n_start = len(df)
    if verbose:
        print(f"  Startuniversum: {n_start} bolag")

    mask = (
        filter_has_price(df, verbose)    &
        filter_liquidity(df, verbose)    &
        filter_balance_sheet(df, verbose) &
        filter_piotroski(df, verbose)    &
        filter_dilution(df, verbose)
    )
    # market_cap-filtret är mjukare – varnar men exkluderar inte alltid
    # (yfinance-data för .ST är ibland USD-konverterad)

    result = df[mask].copy()
    n_kept = len(result)
    n_removed = n_start - n_kept

    if verbose:
        pct = (n_removed / n_start * 100) if n_start > 0 else 0
        print(f"  → Kvar efter filter: {n_kept} bolag "
              f"({n_removed} filtrerade bort, {pct:.0f}%)")

    return result


def get_red_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returnerar en DataFrame med alla tickers och deras röda flaggor.
    Används i rapporten för att varna om bolag som passerat filtren
    men ändå har varningssignaler.
    """
    flags = []
    for _, row in df.iterrows():
        ticker = row.get("ticker", "?")
        ticker_flags = []

        de = row.get("debt_to_equity", 0) or 0
        cr = row.get("current_ratio",  2) or 2
        pf = row.get("piotroski_score", 5) or 5
        gm = row.get("gross_margin",   0) or 0
        dy = row.get("dividend_yield", 0) or 0
        ins = row.get("insider_pct",   0) or 0
        fcf = row.get("free_cash_flow", 1) or 1

        if de > 150:
            ticker_flags.append(f"Hög skuld D/E {de:.0f}%")
        if cr < 1.0:
            ticker_flags.append(f"Låg likviditet CR {cr:.1f}x")
        if pf <= 3:
            ticker_flags.append(f"Svag Piotroski {pf:.0f}/9")
        if gm < 0.15:
            ticker_flags.append(f"Låg bruttomarginal {gm*100:.0f}%")
        if dy > 0.08:
            ticker_flags.append(f"Suspekt hög yield {dy*100:.0f}% (hållbar?)")
        if ins < 0.03:
            ticker_flags.append("Lågt insiderägarskap (<3%)")
        if fcf < 0:
            ticker_flags.append("Negativt FCF")

        flags.append({
            "ticker": ticker,
            "flags":  " · ".join(ticker_flags) if ticker_flags else "—",
            "n_flags": len(ticker_flags),
        })

    return pd.DataFrame(flags).sort_values("n_flags", ascending=False)
