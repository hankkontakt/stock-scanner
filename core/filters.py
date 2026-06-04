"""
filters.py
==========
Förbättrade filter och regler för att minska falska signaler och förbättra timing.

Innehåller:
1. Trendfilter        - köp aldrig aktier under MA200
2. Konfidensfilter    - kräv att flera faktorer är överens
3. Entry-regler       - RSI sweet spot, pullback-detektering
4. Exit-regler        - trailing stop, MA-brott, score-försämring
5. Kvalitetsfilter    - eliminera röda flaggor innan scoring
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime

# Absoluta sökvägar förankrade i repo-roten (tidigare relativa -> bröts vid annan CWD)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STRIKE_FILE = _DATA_DIR / "strike_list.json"
BLACKLIST_FILE = _DATA_DIR / "blacklist.json"

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

        # RSI-koll — saknad RSI (ny notering / kort historik) → VÄNTA, ge ej STARK/OK utan bekräftelse
        if rsi is None:
            return "VÄNTA"
        rsi_ok       = 35 <= rsi <= 68
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

# ═══════════════════════════════════════════════════════════════
# 5. KVALITETSFILTER - eliminera röda flaggor
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

    # 1. Negativt eget kapital (tekniskt konkurs) -- men inte for finans/REIT
    # Finansiella bolag, banker, REITs har ofta negativt eget kapital som en
    # normal konsekvens av skuldstruktur och aktieaterekop -- det ar inte konkurs.
    if "price_to_book" in df.columns and "sector" in df.columns:
        is_financial = df["sector"].str.contains(
            "Financial|Real Estate|Insurance|Bank|REIT", case=False, na=False
        )
        neg_book = (~is_financial) & df["price_to_book"].notna() & (df["price_to_book"] < 0)
        mask_bad |= neg_book
        reasons = reasons.where(~neg_book, reasons + "Negativt eget kapital; ")
    elif "price_to_book" in df.columns:
        # Fallback om sector-kolumn saknas -- ta bort alla med negativt PB
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

    # 4. Fallande kniv (ned >55% senaste 12m) -- bara for icke-finansiella bolag
    if "return_12m" in df.columns:
        is_financial = df.get("sector", pd.Series("")).str.contains(
            "Financial|Real Estate|Insurance|Bank|REIT", case=False, na=False
        )
        knife = (~is_financial) & (df["return_12m"].fillna(0) < -0.55)
        mask_bad |= knife
        reasons = reasons.where(~knife, reasons + "Ned >55% senaste 12m; ")

    eliminated        = df[mask_bad].copy()
    eliminated["filter_reason"] = reasons[mask_bad]
    clean             = df[~mask_bad].copy()

    return clean, eliminated



# ═══════════════════════════════════════════════════════════════
# 7. KOMBINERAD PIPELINE
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
            print(f"     {row['ticker']:12s} -> {row.get('filter_reason','')[:60]}")

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


# Tickers som ALDRIG ska blacklistas oavsett datakvalitet.
# Välkända storbolag där problemet alltid är tillfälliga Yahoo-fel.
NEVER_BLACKLIST = {
    # US mega cap - alltid tillgängliga men kan sakna enstaka fält
    "AAPL","MSFT","GOOGL","GOOG","AMZN","META","NVDA","TSLA","AVGO","ORCL",
    "CRM","ADBE","AMD","INTC","CSCO","QCOM","TXN","IBM","NOW","INTU",
    "PANW","PLTR","SNOW","MU","AMAT","LRCX","KLAC","ADI","MRVL","FTNT",
    "DDOG","CRWD","WDAY","TEAM","MDB","NET","ZS","OKTA","SHOP","UBER",
    # Finansbolag
    "JPM","BAC","WFC","GS","MS","C","BLK","AXP","V","MA","BRK-B","SCHW",
    # Övriga välkända
    "JNJ","UNH","LLY","PFE","ABBV","MRK","TMO","ABT","WMT","PG","KO","PEP",
    "COST","MCD","NKE","SBUX","HD","DIS","NFLX","XOM","CVX","CAT","BA",
    # Svenska large cap
    "VOLV-B.ST","ERIC-B.ST","INVE-A.ST","INVE-B.ST","INDU-C.ST","INDU-A.ST",
    "ATCO-A.ST","ATCO-B.ST","ASSA-B.ST","SEB-A.ST","SHB-A.ST","SWED-A.ST",
    "HM-B.ST","ABB.ST","SAND.ST","ALFA.ST","AZN.ST","EVO.ST","EQT.ST",
    # Europeiska large cap
    "ASML.AS","SAP.DE","NOVO-B.CO","NESN.SW","NOVN.SW","ROG.SW","SHEL.L",
    "AZN.L","HSBA.L","BP.L","MC.PA","LVMH.PA",
}


def update_ticker_health(
    attempted_tickers:  list,
    survived_tickers:   list,
    df_raw:             pd.DataFrame,
    fetch_failed:       list = None,   # Tickers som HELT misslyckades med hämtning
) -> tuple:
    """
    Hanterar strike-systemet korrekt:

    VIKTIGT: Strikes triggas BARA vid verkliga hämtningsfel (fetch_failed),
    INTE när en ticker filtreras bort av data_quality-tröskeln.
    Att ha 75% datakvalitet (6/8 fält) är inte ett fel - det är vanligt
    för investmentbolag, råvarubolag och tillväxtbolag utan earnings.

    3 verkliga hämtningsfel = permanent blacklist.
    Tickers i NEVER_BLACKLIST skyddas alltid.

    Returnerar (warnings, removed_details)
    """
    strikes       = _load_json(STRIKE_FILE)
    blacklist     = _load_json(BLACKLIST_FILE)
    fetch_failed  = fetch_failed or []
    today_str     = str(datetime.now().date())

    warnings        = []
    removed_details = []

    for ticker in fetch_failed:
        # Aldrig blacklista kända storbolag
        if ticker in NEVER_BLACKLIST:
            continue
        if ticker in blacklist:
            continue

        # Hämta rådata för diagnostik
        ticker_data = (
            df_raw[df_raw["ticker"] == ticker]
            if not df_raw.empty else pd.DataFrame()
        )
        diagnosis = diagnose_failure(ticker, ticker_data)

        # Idempotens: räkna upp max en gång per dag så CI-retries inte dubblerar strikes.
        prev = strikes.get(ticker)
        if isinstance(prev, dict):
            prev_count = int(prev.get("count", 0))
            prev_date  = prev.get("date", "")
        else:
            prev_count = int(prev or 0)
            prev_date  = ""

        if prev_date == today_str:
            new_count = prev_count  # redan räknat idag, hoppa över
        else:
            new_count = prev_count + 1

        strikes[ticker] = {"count": new_count, "date": today_str}

        if new_count == 2:
            warnings.append(f"{ticker} ({diagnosis})")
        elif new_count >= 3:
            removed_details.append({"ticker": ticker, "reason": diagnosis})
            blacklist[ticker] = {
                "reason": diagnosis,
                "date":   today_str,
            }
            del strikes[ticker]

            # Notifiera rotation-motorn genom att logga en rotation entry
            try:
                from core.rotation_engine import _log_rotation
                _log_rotation(
                    removed=ticker,
                    added=None,
                    reason=f"3 strikes (auto-blacklist): {diagnosis}",
                )
            except Exception:
                pass

    # Rensa strikes för tickers som nu klarar sig
    for ticker in survived_tickers:
        if ticker in strikes:
            del strikes[ticker]

    _save_json(STRIKE_FILE, strikes)
    _save_json(BLACKLIST_FILE, blacklist)
    return warnings, removed_details


def diagnose_failure(ticker: str, row: pd.DataFrame) -> str:
    """
    Bestämmer sannolik orsak till att en ticker HELT misslyckades att hämta data.
    Skiljer mellan: Yahoo-fel, felaktigt suffix, genuint saknad data.
    """
    # Ingen data alls = Yahoo kan inte hitta tickern
    if row is None or (hasattr(row, "empty") and row.empty):
        suffix = ticker.rsplit(".", 1)[-1] if "." in ticker else ""
        known_suffixes = {
            "ST","L","DE","PA","AS","SW","CO","OL","HE","MC","MI",
            "TO","AX","T","KS","HK","TW","NS","SA","SI","VI","PL","MX","LS"
        }
        if suffix and suffix not in known_suffixes:
            return f"Okänt börssuffix '.{suffix}' - kontrollera ticker"
        return "Yahoo Finance hittar ingen data för denna ticker"

    # Data finns men kanske ofullständig
    missing = []
    for field in ["pe_trailing", "market_cap", "revenue_growth", "current_price"]:
        val = row.get(field)
        if val is None or (hasattr(val, "all") and pd.isna(val).all()):
            missing.append(field)

    if "current_price" in missing:
        return "Kan inte hämta aktuellt pris - troligt delistning eller namnbyte"

    if len(missing) >= 3:
        return "Fundamentaldata saknas hos Yahoo (vanligt för nystartade/delisted bolag)"

    return "Intermittent hämtningsfel - försöker igen nästa körning"


def clear_blacklist(tickers: list = None):
    """
    Rensar blacklist manuellt.
    Om tickers=None rensas hela blacklisten (nollstart).
    Om tickers=["INTC","SNOW"] rensas bara de angivna.
    """
    blacklist = _load_json(BLACKLIST_FILE)
    strikes   = _load_json(STRIKE_FILE)

    if tickers is None:
        removed = list(blacklist.keys())
        blacklist = {}
        strikes   = {}
        print(f"✓ Hela blacklisten rensad ({len(removed)} tickers)")
    else:
        removed = []
        for t in tickers:
            t = t.upper()
            if t in blacklist:
                del blacklist[t]; removed.append(t)
            if t in strikes:
                del strikes[t]
        print(f"✓ Rensade {len(removed)} tickers: {removed}")

    _save_json(BLACKLIST_FILE, blacklist)
    _save_json(STRIKE_FILE, strikes)
    return removed


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(p: Path, d: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=4, ensure_ascii=False), encoding="utf-8")