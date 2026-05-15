"""
extra_data.py
=============
Hämtar tre extra datakällor som ger starkare signaler:

1. Insider-transaktioner  – faktiska köp/sälj från VD/styrelse
2. Earnings surprise      – slår bolaget estimat konsekvent?
3. Analytiker-revisioner  – förbättras eller försämras konsensus?

Alla tre returnerar ett signal-värde 0.0–1.0:
  0.0–0.3 = negativt / bearish
  0.4–0.6 = neutralt
  0.7–1.0 = positivt / bullish

Cachelagrade separat (48-72h) för att inte överbelasta API:er.
"""

import time
import pickle
import hashlib
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

CACHE_DIR        = "data/cache"
INSIDER_CACHE_H  = 48
EARNINGS_CACHE_H = 72
ANALYST_CACHE_H  = 24

Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


# ── Cache helpers ──────────────────────────────────────────────

def _cp(key: str) -> Path:
    h = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"extra_{h}.pkl"

def _rc(key: str, max_h: float):
    p = _cp(key)
    if not p.exists(): return None
    if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > timedelta(hours=max_h):
        return None
    try:
        with open(p, "rb") as f: return pickle.load(f)
    except: return None

def _wc(key: str, data):
    try:
        with open(_cp(key), "wb") as f: pickle.dump(data, f)
    except: pass


# ══════════════════════════════════════════════════════════════
# 1. INSIDER-TRANSAKTIONER
# ══════════════════════════════════════════════════════════════

def fetch_insider_signal(ticker: str) -> float:
    """
    Hämtar faktiska insider-transaktioner och beräknar netto-köpsignal.

    Logik:
    - Tittar på köp/sälj senaste 90 dagarna
    - Netto-köpare (VD/styrelse köper mer än de säljer) = bullish signal
    - Automatiska försäljningar (planerade) räknas ned
    - Returnerar 0.5 om ingen data finns

    OBS: Fungerar bäst för US-aktier (SEC-data).
         Svenska aktier har begränsad data i yfinance.
    """
    import yfinance as yf

    cached = _rc(f"insider:{ticker}", INSIDER_CACHE_H)
    if cached is not None:
        return cached

    try:
        from core.data_fetcher import _with_timeout
        time.sleep(0.4)
        stock  = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=8)
        trades = _with_timeout(lambda: stock.insider_transactions, timeout_sec=15)

        if trades is None or (hasattr(trades, 'empty') and trades.empty):
            _wc(f"insider:{ticker}", 0.5)
            return 0.5

        df = trades.copy()

        # Normalisera kolumnnamn (yfinance ändrar ibland)
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # Hitta datumkolumn
        date_col = next((c for c in df.columns if "date" in c), None)
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            cutoff       = pd.Timestamp.now() - pd.Timedelta(days=90)
            df           = df[df[date_col] >= cutoff]

        if df.empty:
            _wc(f"insider:{ticker}", 0.5)
            return 0.5

        # Hitta transaktionstyp-kolumn
        trans_col = next((c for c in df.columns if "transaction" in c or "text" in c), None)

        # Hitta shares-kolumn
        shares_col = next((c for c in df.columns if "shares" in c), None)

        if not trans_col or not shares_col:
            _wc(f"insider:{ticker}", 0.5)
            return 0.5

        df[shares_col] = pd.to_numeric(df[shares_col], errors="coerce").fillna(0).abs()
        trans_lower    = df[trans_col].astype(str).str.lower()

        # Köp
        buy_mask  = trans_lower.str.contains("buy|purchase|acquired", na=False)
        # Sälj (exkludera automatiska/planerade = "sale (automatic)", "10b5-1")
        sell_mask = (
            trans_lower.str.contains("sale|sell|sold|disposed", na=False) &
            ~trans_lower.str.contains("automatic|plan|10b5", na=False)
        )

        buys  = df.loc[buy_mask,  shares_col].sum()
        sells = df.loc[sell_mask, shares_col].sum()
        total = buys + sells

        if total == 0:
            signal = 0.5
        else:
            ratio  = (buys - sells) / total  # -1 till +1
            signal = 0.5 + ratio * 0.35       # 0.15 till 0.85
            signal = round(max(0.1, min(0.9, signal)), 3)

        _wc(f"insider:{ticker}", signal)
        return signal

    except Exception:
        return 0.5


# ══════════════════════════════════════════════════════════════
# 2. EARNINGS SURPRISE-HISTORIA
# ══════════════════════════════════════════════════════════════

def fetch_earnings_surprise_signal(ticker: str) -> float:
    """
    Beräknar hur konsekvent bolaget slår analytikernas EPS-estimat.

    Logik:
    - Tittar på senaste 8 kvartal
    - Beat rate (andel kvartal med positivt surprise) = primär signal
    - Genomsnittlig surprise-storlek = sekundär signal
    - Bolag som konsekvent slår estimat tenderar fortsätta

    Akademisk grund: Post-earnings announcement drift (PEAD) – ett av
    de mest robusta anomalierna i finansforskning.
    """
    import yfinance as yf

    cached = _rc(f"earnings:{ticker}", EARNINGS_CACHE_H)
    if cached is not None:
        return cached

    try:
        from core.data_fetcher import _with_timeout
        time.sleep(0.4)
        stock = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=8)
        hist  = _with_timeout(lambda: stock.earnings_history, timeout_sec=15)

        if hist is None or (hasattr(hist, 'empty') and hist.empty):
            _wc(f"earnings:{ticker}", 0.5)
            return 0.5

        df = hist.copy()
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # Hämta senaste 8 kvartal
        df = df.tail(8)

        # Letar efter surprise-kolumn
        surp_col = next(
            (c for c in df.columns if "surprise" in c and "percent" in c), None
        ) or next(
            (c for c in df.columns if "surprise" in c), None
        )

        if surp_col:
            vals  = pd.to_numeric(df[surp_col], errors="coerce").dropna()
            if len(vals) == 0:
                signal = 0.5
            else:
                beat_rate    = (vals > 0).mean()                    # 0-1
                avg_surp_pct = vals.mean() / 100 if vals.abs().max() > 1 else vals.mean()
                # Kombinera: 65% beat rate + 35% surprise-storlek
                size_score = min(1.0, max(0.0, 0.5 + avg_surp_pct * 4))
                signal     = beat_rate * 0.65 + size_score * 0.35

        else:
            # Försök via epsActual vs epsEstimate
            actual_col   = next((c for c in df.columns if "actual" in c), None)
            estimate_col = next((c for c in df.columns if "estimate" in c), None)

            if actual_col and estimate_col:
                valid = df[[actual_col, estimate_col]].apply(
                    pd.to_numeric, errors="coerce"
                ).dropna()
                if not valid.empty:
                    beats  = (valid[actual_col] > valid[estimate_col]).mean()
                    signal = beats
                else:
                    signal = 0.5
            else:
                signal = 0.5

        signal = round(max(0.0, min(1.0, float(signal))), 3)
        _wc(f"earnings:{ticker}", signal)
        return signal

    except Exception:
        return 0.5


# ══════════════════════════════════════════════════════════════
# 3. ANALYTIKER-REVISIONER
# ══════════════════════════════════════════════════════════════

def fetch_analyst_revision_signal(ticker: str, finnhub_key: str = None) -> float:
    """
    Detekterar om analytiker uppgraderar eller nedgraderar aktien.

    Logik (Finnhub):
    - Hämtar månatlig buy/sell/hold-fördelning senaste 3 månader
    - Beräknar nuvarande bullish-% och om det förbättras

    Logik (yfinance fallback):
    - Använder recommendation_mean (1=Strong Buy, 5=Strong Sell)
    - Tittar på trend i recommendations DataFrame

    Signal: uppgraderande trend = 0.7-0.9, nedgraderande = 0.1-0.3
    """
    import yfinance as yf

    cached = _rc(f"analyst_rev:{ticker}", ANALYST_CACHE_H)
    if cached is not None:
        return cached

    # Försök Finnhub först
    if finnhub_key:
        try:
            time.sleep(0.3)
            clean = ticker.split(".")[0]
            resp  = requests.get(
                "https://finnhub.io/api/v1/stock/recommendation",
                params={"symbol": clean, "token": finnhub_key},
                timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) >= 2:

                    def bull_pct(d):
                        total = sum(d.get(k, 0) for k in
                                    ["strongBuy","buy","hold","sell","strongSell"])
                        if total == 0: return 0.5
                        return (d.get("strongBuy", 0) + d.get("buy", 0)) / total

                    pcts = [bull_pct(d) for d in data[:3]]

                    # Nuvarande + trendbonus
                    current = pcts[0]
                    trend   = pcts[0] - pcts[-1]   # Positiv = förbättring
                    signal  = current + trend * 0.25
                    signal  = round(max(0.0, min(1.0, signal)), 3)

                    _wc(f"analyst_rev:{ticker}", signal)
                    return signal
        except Exception:
            pass

    # yfinance fallback
    try:
        from core.data_fetcher import _with_timeout
        time.sleep(0.3)
        stock    = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=8)
        info     = _with_timeout(lambda: stock.info, timeout_sec=15)
        rec_mean = info.get("recommendationMean") if info else None

        if rec_mean is not None:
            # 1=Strong Buy→1.0, 3=Hold→0.5, 5=Strong Sell→0.0
            signal = round(1.0 - (float(rec_mean) - 1.0) / 4.0, 3)
            signal = max(0.0, min(1.0, signal))

            # Försök hitta trend via recommendations DataFrame
            try:
                recs = _with_timeout(lambda: stock.recommendations, timeout_sec=10)
                if recs is not None and not recs.empty and len(recs) >= 4:
                    recs = recs.tail(8).copy()
                    # Räkna buy/strong buy vs sell/strong sell
                    grade_col = next(
                        (c for c in recs.columns if "grade" in c.lower() or
                         "action" in c.lower() or "to_grade" in c.lower()), None
                    )
                    if grade_col:
                        grades    = recs[grade_col].astype(str).str.lower()
                        upgrades  = grades.str.contains("buy|outperform|overweight", na=False).sum()
                        downgrades= grades.str.contains("sell|underperform|underweight", na=False).sum()
                        if upgrades + downgrades > 0:
                            trend_adj = (upgrades - downgrades) / (upgrades + downgrades)
                            signal    = max(0.0, min(1.0, signal + trend_adj * 0.15))
            except Exception:
                pass

            _wc(f"analyst_rev:{ticker}", signal)
            return signal

    except Exception:
        pass

    return 0.5


# ══════════════════════════════════════════════════════════════
# BATCH-FUNKTION (kör alla tre för hela universumet)
# ══════════════════════════════════════════════════════════════

def fetch_extra_data_batch(
    tickers:      list,
    finnhub_key:  str  = None,
    verbose:      bool = True,
) -> pd.DataFrame:
    """
    Hämtar insider, earnings surprise och analytiker-revision för alla tickers.
    Returnerar DataFrame med kolumner:
        ticker, insider_signal, earnings_signal, analyst_signal, extra_composite
    """
    rows = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        if verbose and i % 20 == 0:
            print(f"  Extra data: {i}/{total}...")

        insider  = fetch_insider_signal(ticker)
        earnings = fetch_earnings_surprise_signal(ticker)
        analyst  = fetch_analyst_revision_signal(ticker, finnhub_key)

        # Kombinerad extra-signal (viktat snitt)
        composite = insider * 0.30 + earnings * 0.40 + analyst * 0.30

        rows.append({
            "ticker":          ticker,
            "insider_signal":  insider,
            "earnings_signal": earnings,
            "analyst_signal":  analyst,
            "extra_composite": round(composite, 3),
        })

    df = pd.DataFrame(rows)
    if verbose:
        high = (df["extra_composite"] > 0.65).sum()
        low  = (df["extra_composite"] < 0.35).sum()
        print(f"  ✓ Extra data klar: {high} bullish, {low} bearish, {total-high-low} neutrala")

    return df
