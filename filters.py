"""
filters.py
==========
Förbättrade filter och regler för att minska falska signaler och förbättra timing.

Innehåller:
1. Trendfilter        – köp aldrig aktier under MA200
2. Konfidensfilter    – kräv att flera faktorer är överens
3. Entry-regler       – RSI sweet spot, pullback-detektering
4. Exit-regler        – trailing stop, MA-brott, score-försämring
5. Kvalitetsfilter    – eliminera röda flaggor innan scoring
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime

STRIKE_FILE = Path("data/strike_list.json")
BLACKLIST_FILE = Path("data/blacklist.json")

# ═══════════════════════════════════════════════════════════════
# 1. TRENDFILTER
# ═══════════════════════════════════════════════════════════════

def apply_trend_filter(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sätter max-rekommendation till BEVAKA om aktien handlas under MA200.
    En aktie med starka fundamenta men i nedtrend är en "value trap".

    Kräver kolumnerna: price_vs_ma200, price_vs_ma50
    """
    df = df.copy()
    df["trend_signal"] = "UPPTREND"
    df["trend_capped"]  = False

    # Under MA200 = nedtrend, cappa rekommendation
    if "price_vs_ma200" in df.columns:
        under_ma200 = df["price_vs_ma200"].fillna(0) < 0
        df.loc[under_ma200, "trend_signal"] = "NEDTREND"
        df.loc[under_ma200, "trend_capped"]  = True

    # Under MA50 men över MA200 = varning
    if "price_vs_ma50" in df.columns and "price_vs_ma200" in df.columns:
        death_cross = (df["price_vs_ma50"].fillna(0) < 0) & (df["price_vs_ma200"].fillna(0) >= 0)
        df.loc[death_cross, "trend_signal"] = "VARNING"

    return df


# ═══════════════════════════════════════════════════════════════
# 2. KONFIDENSFILTER
# ═══════════════════════════════════════════════════════════════

def calc_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Beräknar hur många faktorer som är "positiva" (score >= 60).
    Hög konfidensbredd = stark signal (flera faktorer överens).
    Låg konfidensbredd = svag signal (blandat).

    Returns df med nya kolonner:
    - factors_positive: antal faktorer >= 60
    - confidence_pct: % av faktorer som är positiva
    - confidence_label: HÖG / MEDEL / LÅG
    """
    df = df.copy()

    score_cols = [
        "score_value", "score_quality", "score_momentum",
        "score_growth", "score_risk", "score_sentiment",
        "score_dividend"
    ]
    available = [c for c in score_cols if c in df.columns]

    if not available:
        df["factors_positive"]  = 0
        df["confidence_pct"]    = 0.5
        df["confidence_label"]  = "OKÄND"
        return df

    # Räkna faktorer >= 60
    positive_matrix = df[available].ge(60)
    df["factors_positive"] = positive_matrix.sum(axis=1)
    df["confidence_pct"]   = df["factors_positive"] / len(available)

    # Label
    def label(pct):
        if pct >= 0.70:  return "HÖG"
        elif pct >= 0.45: return "MEDEL"
        else:             return "LÅG"

    df["confidence_label"] = df["confidence_pct"].apply(label)
    return df


# ═══════════════════════════════════════════════════════════════
# 3. ENTRY-REGLER
# ═══════════════════════════════════════════════════════════════

def calc_entry_signal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Kombinerar trendfilter + RSI sweet spot + pullback-detektering
    för att ge konkreta entry-signaler.

    Entry-regler:
    ① Trend: pris > MA200  (obligatoriskt)
    ② RSI 35-68           (inte överköpt/översålt)
    ③ Score >= 65         (stark fundamental grund)
    ④ Pullback 3-20% från 52v-high = extra bra timing

    Returnerar kolumn "entry_signal": STARK / OK / VÄNTA / EJ AKTUELL
    """
    df = df.copy()

    def get_entry(row):
        score      = row.get("score_total", 0)   or 0
        rsi        = row.get("rsi_14")
        vs_ma200   = row.get("price_vs_ma200")
        vs_high    = row.get("pct_from_52w_high")
        trend_cap  = row.get("trend_capped", False)

        # Obligatoriskt: över MA200
        if trend_cap or (vs_ma200 is not None and vs_ma200 < 0):
            return "EJ AKTUELL"

        # Svag fundamental grund
        if score < 55:
            return "EJ AKTUELL"

        # RSI-koll
        rsi_ok       = rsi is None or (35 <= rsi <= 68)
        rsi_overköpt = rsi is not None and rsi > 75
        rsi_överSålt = rsi is not None and rsi < 30

        if rsi_overköpt:
            return "VÄNTA"  # Vänta på rekyl

        if rsi_överSålt:
            return "VÄNTA"  # Vänta på stabilisering

        # Pullback-detektion: 5-18% från 52v-high = sweet spot
        pullback_ok = False
        if vs_high is not None and -0.18 <= vs_high <= -0.05:
            pullback_ok = True

        # Stark entry: score >= 72 + RSI ok + pullback
        if score >= 72 and rsi_ok and pullback_ok:
            return "STARK"

        # OK entry: score >= 65 + RSI ok
        if score >= 65 and rsi_ok:
            return "OK"

        return "VÄNTA"

    df["entry_signal"] = df.apply(get_entry, axis=1)
    return df


# ═══════════════════════════════════════════════════════════════
# 4. EXIT-REGLER (för portföljanalys)
# ═══════════════════════════════════════════════════════════════

def calc_exit_signal(holding_row: pd.Series, universe_size: int) -> tuple:
    """
    Analyserar ett specifikt innehav och avgör om det är dags att sälja.

    Exit-triggers (i prioritetsordning):
    ① Score < 35           → SÄLJ (kraftigt försämrade fundamenta)
    ② Under MA200          → SÄLJ/MINSKA (trendbrott)
    ③ RSI < 28 + nedtrend  → BEVAKA NOGA (panik-sälj-risk)
    ④ Upp >100% sen köp    → TA HEM HALVA (riskhantering)
    ⑤ Bättre alternativ    → ROTERA (score 15p högre finns)
    ⑥ Score 35-50          → MINSKA
    ⑦ Annars               → BEHÅLL / KÖP MER

    Returns: (signal, skäl, prioritet)
    """
    score    = holding_row.get("score_total")
    rank     = holding_row.get("rank", universe_size)
    vs_ma200 = holding_row.get("price_vs_ma200")
    rsi      = holding_row.get("rsi_14")
    pnl_pct  = holding_row.get("unrealized_pnl_pct")  # som decimal, t.ex. 1.05 = +105%
    r3m      = holding_row.get("return_3m")

    if score is None:
        return "OKÄND", "Ingen data tillgänglig", 99

    percentile = 100 * (1 - (rank - 1) / max(universe_size, 1))
    top_pct    = 100 - percentile

    # ① Kraftigt försämrade fundamenta
    if score < 35:
        return "SÄLJ", f"Score {score:.0f} – kraftigt försämrade fundamenta", 1

    # ② Trendbrott under MA200
    if vs_ma200 is not None and vs_ma200 < -0.05:
        drop_pct = abs(vs_ma200) * 100
        return "SÄLJ/MINSKA", f"Pris {drop_pct:.0f}% under MA200 – trendbrott", 2

    # ③ Panik-sälj-risk
    if rsi is not None and rsi < 28 and r3m is not None and r3m < -0.12:
        return "BEVAKA NOGA", f"RSI={rsi:.0f} + ned {abs(r3m)*100:.0f}% senaste 3m", 3

    # ④ Ta hem vinst på stora uppgångar
    if pnl_pct is not None and pnl_pct > 1.0:  # +100%
        return "TA HEM HALVA", f"Upp {pnl_pct*100:.0f}% – överväg att ta hem halva positionen", 4

    # ⑤ Score under medel
    if score < 45:
        return "MINSKA", f"Score {score:.0f} (svag) – i topp {top_pct:.0f}%", 5

    # ⑥ Håll
    if percentile >= 80:
        return "KÖP MER", f"Topp {top_pct:.0f}% av universumet", 6

    if percentile >= 50:
        return "BEHÅLL", f"Topp {top_pct:.0f}% av universumet", 7

    return "MINSKA", f"Under medel (topp {top_pct:.0f}%) – bevaka", 8


# ═══════════════════════════════════════════════════════════════
# 5. KVALITETSFILTER – eliminera röda flaggor
# ═══════════════════════════════════════════════════════════════

def apply_quality_filter(df: pd.DataFrame) -> tuple:
    """
    Eliminerar aktier med tydliga röda flaggor innan scoring.
    Sparar tid och förhindrar att skräpaktier hamnar i topp-listan.

    Returnerar: (filtrerad_df, eliminerade_df)
    """
    df       = df.copy()
    mask_bad = pd.Series(False, index=df.index)
    reasons  = pd.Series("", index=df.index)

    # 1. Negativt eget kapital (tekniskt konkurs)
    if "price_to_book" in df.columns:
        neg_book = df["price_to_book"].notna() & (df["price_to_book"] < 0)
        mask_bad |= neg_book
        reasons = reasons.where(~neg_book, reasons + "Negativt eget kapital; ")

    # 2. Extrem skuldsättning + negativt kassaflöde
    if "debt_to_equity" in df.columns and "free_cash_flow" in df.columns:
        extreme_debt = (
            df["debt_to_equity"].fillna(0) > 400
        ) & (
            df["free_cash_flow"].fillna(0) < 0
        )
        mask_bad |= extreme_debt
        reasons = reasons.where(~extreme_debt, reasons + "Extrem skuld + neg kassaflöde; ")

    # 3. Strong Sell konsensus
    if "recommendation_mean" in df.columns:
        strong_sell = df["recommendation_mean"].fillna(3) > 4.2
        mask_bad |= strong_sell
        reasons = reasons.where(~strong_sell, reasons + "Analytiker: Strong Sell; ")

    # 4. Fallande kniv (ned >55% senaste 12m) UTAN fundamental förbättring
    if "return_12m" in df.columns:
        knife = df["return_12m"].fillna(0) < -0.55
        mask_bad |= knife
        reasons = reasons.where(~knife, reasons + "Ned >55% senaste 12m; ")

    eliminated        = df[mask_bad].copy()
    eliminated["filter_reason"] = reasons[mask_bad]
    clean             = df[~mask_bad].copy()

    return clean, eliminated


# ═══════════════════════════════════════════════════════════════
# 6. KOMBINERAD PIPELINE
# ═══════════════════════════════════════════════════════════════

def apply_all_filters(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    Kör alla filter i rätt ordning och lägger till alla signalkolumner.
    Returnerar berikad DataFrame redo för rapport-generering.
    """
    original_count = len(df)

    # Steg 1: Eliminera röda flaggor
    df, eliminated = apply_quality_filter(df)
    if verbose and len(eliminated) > 0:
        print(f"  🚫 Kvalitetsfilter: eliminerade {len(eliminated)} aktier")
        for _, row in eliminated.head(5).iterrows():
            print(f"     {row['ticker']:12s} → {row.get('filter_reason','')[:60]}")

    # Steg 2: Trendfilter
    df = apply_trend_filter(df)
    under_trend = df["trend_capped"].sum()
    if verbose:
        print(f"  📉 Trendfilter: {under_trend} aktier under MA200 (cappade till BEVAKA)")

    # Steg 3: Konfidensfilter
    df = calc_confidence(df)
    high_conf = (df["confidence_label"] == "HÖG").sum()
    if verbose:
        print(f"  ✅ Konfidensfilter: {high_conf} aktier med HÖG konfidens")

    # Steg 4: Entry-signaler
    df = calc_entry_signal(df)
    stark = (df["entry_signal"] == "STARK").sum()
    ok    = (df["entry_signal"] == "OK").sum()
    if verbose:
        print(f"  🎯 Entry-signaler: {stark} STARK, {ok} OK")

    return df


def update_ticker_health(attempted_tickers: list, survived_tickers: list, df_raw: pd.DataFrame) -> tuple:
    """
    Hanterar Strikes. 3 missar = Blacklist.
    Returnerar (warnings, removed_details)
    """
    strikes = _load_json(STRIKE_FILE)
    blacklist = _load_json(BLACKLIST_FILE)
    
    warnings = []
    removed_details = [] # Innehåller ticker + AI-diagnos
    
    for ticker in attempted_tickers:
        if ticker in blacklist: continue
            
        if ticker not in survived_tickers:
            strikes[ticker] = strikes.get(ticker, 0) + 1
            
            # Hämta rådata för att se vad som saknas för diagnostik
            ticker_data = df_raw[df_raw['ticker'] == ticker] if not df_raw.empty else pd.DataFrame()
            diagnosis = diagnose_failure(ticker, ticker_data)
            
            if strikes[ticker] == 2:
                warnings.append(f"{ticker} ({diagnosis})")
            elif strikes[ticker] >= 3:
                removed_details.append({"ticker": ticker, "reason": diagnosis})
                blacklist[ticker] = {"reason": diagnosis, "date": str(datetime.now().date())}
                if ticker in strikes: del strikes[ticker]
        else:
            if ticker in strikes: del strikes[ticker]
                
    _save_json(STRIKE_FILE, strikes)
    _save_json(BLACKLIST_FILE, blacklist)
    return warnings, removed_details

def diagnose_failure(ticker: str, row: pd.DataFrame) -> str:
    """AI-diagnostik: Listar ut om felet ligger i Yahoo, koden eller aktien."""
    if row.empty:
        return "Yahoo Finance hittar ingen data (kontrollera ticker-suffix)"
    
    missing = []
    if pd.isna(row.get('pe_trailing')).all(): missing.append("P/E")
    if pd.isna(row.get('market_cap')).all(): missing.append("MarketCap")
    if pd.isna(row.get('revenue_growth')).all(): missing.append("Growth")
    
    if len(missing) > 2:
        return "Fundamentaldata saknas hos Yahoo (vanligt för små/europeiska bolag)"
    if not ticker.endswith(".ST") and len(ticker) > 5:
        return "Möjligt kodfel: Saknar .ST suffix för svensk aktie?"
    
    return "Okänd brist i datakvalitet"

def _load_json(p): return json.loads(p.read_text()) if p.exists() else {}
def _save_json(p, d): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d, indent=4))
def _save_json(p, d): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d, indent=4))