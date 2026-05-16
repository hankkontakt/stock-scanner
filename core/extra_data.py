"""
extra_data.py
=============
Hämtar extra datakällor som ger starkare signaler:

1. Insider-transaktioner  – faktiska köp/sälj från VD/styrelse
2. Earnings surprise      – slår bolaget estimat konsekvent?
3. Analytiker-revisioner  – förbättras eller försämras konsensus?
4. Short Interest         – blankningsgrad (låg blankning = positivt)
5. Seasonality            – säsongsmönster (stark månad = positivt)
6. Options Flow           – puts/calls ratio (lågt P/C = bullish)

Alla returnerar ett signal-värde 0.0–1.0:
  0.0–0.3 = negativt / bearish
  0.4–0.6 = neutralt
  0.7–1.0 = positivt / bullish

Cachelagrade separat (24-72h) för att inte överbelasta API:er.
"""

import time
import pickle
import hashlib
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

CACHE_DIR        = "data/cache"
INSIDER_CACHE_H  = 48
EARNINGS_CACHE_H = 72
ANALYST_CACHE_H  = 24
SHORT_CACHE_H    = 24
SEASONALITY_CACHE_H = 720  # 30 dagar – säsongsmönster ändras långsamt
OPTIONS_CACHE_H  = 24

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
# 4. SHORT INTEREST (blankningsgrad)
# ══════════════════════════════════════════════════════════════

def fetch_short_interest_signal(ticker: str, finnhub_key: str = None) -> float:
    """
    Beräknar signal baserat på blankningsgrad (Short Interest).
    
    Logik:
    - Låg blankning (SI < 3% av float) = positiv signal (0.7-0.9)
    - Hög blankning (SI > 15% av float) = negativ signal (0.1-0.3)
    - Ingen data = neutral (0.5)
    
    Källa: Finnhub /api/v1/stock/short-interest eller yfinance fallback
    """
    cached = _rc(f"short:{ticker}", SHORT_CACHE_H)
    if cached is not None:
        return cached

    # Försök Finnhub
    if finnhub_key:
        try:
            time.sleep(0.3)
            clean = ticker.split(".")[0]
            resp = requests.get(
                "https://finnhub.io/api/v1/stock/short-interest",
                params={"symbol": clean, "token": finnhub_key},
                timeout=8
            )
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data and len(data) > 0:
                    latest = data[0]
                    si_pct = latest.get("shortInterestPercent")
                    if si_pct is not None:
                        si_pct = float(si_pct)
                        if si_pct < 3.0:
                            signal = round(0.5 + (3.0 - si_pct) / 3.0 * 0.4, 3)  # 0.5-0.9
                        elif si_pct > 15.0:
                            signal = round(max(0.1, 0.5 - (si_pct - 15.0) / 15.0 * 0.4), 3)  # 0.1-0.5
                        else:
                            signal = round(0.5 - (si_pct - 3.0) / 12.0 * 0.2, 3)  # 0.3-0.7
                        signal = max(0.1, min(0.9, signal))
                        _wc(f"short:{ticker}", signal)
                        return signal
        except Exception:
            pass

    # yfinance fallback – försök via info
    try:
        import yfinance as yf
        from core.data_fetcher import _with_timeout
        time.sleep(0.3)
        stock = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=8)
        info = _with_timeout(lambda: stock.info, timeout_sec=15)
        if info:
            si_pct = info.get("shortPercentOfFloat")
            if si_pct is not None:
                si_pct = float(si_pct) * 100  # Konvertera från decimal till procent
                if si_pct < 3.0:
                    signal = round(0.5 + (3.0 - si_pct) / 3.0 * 0.4, 3)
                elif si_pct > 15.0:
                    signal = round(max(0.1, 0.5 - (si_pct - 15.0) / 15.0 * 0.4), 3)
                else:
                    signal = round(0.5 - (si_pct - 3.0) / 12.0 * 0.2, 3)
                signal = max(0.1, min(0.9, signal))
                _wc(f"short:{ticker}", signal)
                return signal

            # Alternative: shortRatio
            si_ratio = info.get("shortRatio")
            if si_ratio is not None:
                si_ratio = float(si_ratio)
                if si_ratio < 1.0:
                    signal = round(0.5 + (1.0 - si_ratio) / 1.0 * 0.3, 3)
                elif si_ratio > 5.0:
                    signal = round(max(0.1, 0.5 - (si_ratio - 5.0) / 5.0 * 0.3), 3)
                else:
                    signal = round(0.5, 3)
                signal = max(0.1, min(0.9, signal))
                _wc(f"short:{ticker}", signal)
                return signal
    except Exception:
        pass

    _wc(f"short:{ticker}", 0.5)
    return 0.5


# ══════════════════════════════════════════════════════════════
# 5. SEASONALITY (säsongsmönster)
# ══════════════════════════════════════════════════════════════

def fetch_seasonality_signal(ticker: str) -> float:
    """
    Beräknar säsongssignal baserat på historiskt månadsmönster.
    
    Logik:
    - Hämtar 5-10 års prishistorik
    - Beräknar genomsnittlig avkastning för innevarande månad
    - Jämför med aktiens övergripande medelavkastning
    - Stark månad (över snittet) = positiv signal
    
    Använder yfinance historik.
    """
    import yfinance as yf

    cached = _rc(f"seasonality:{ticker}", SEASONALITY_CACHE_H)
    if cached is not None:
        return cached

    try:
        from core.data_fetcher import _with_timeout
        time.sleep(0.3)
        stock = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=8)
        hist = _with_timeout(
            lambda: stock.history(period="10y", auto_adjust=True),
            timeout_sec=20
        )

        if hist.empty or len(hist) < 252:  # Behöver minst ~1 år
            _wc(f"seasonality:{ticker}", 0.5)
            return 0.5

        close = hist["Close"]
        
        # Beräkna månatlig avkastning
        monthly_returns = close.resample("ME").ffill().pct_change().dropna()
        
        if len(monthly_returns) < 12:
            _wc(f"seasonality:{ticker}", 0.5)
            return 0.5

        # Genomsnittlig avkastning per månad
        current_month = datetime.now().month
        month_returns = monthly_returns[monthly_returns.index.month == current_month]
        avg_month_ret = month_returns.mean()
        overall_avg   = monthly_returns.mean()
        median_month  = monthly_returns.groupby(monthly_returns.index.month).mean().median()

        if pd.isna(avg_month_ret) or pd.isna(overall_avg):
            _wc(f"seasonality:{ticker}", 0.5)
            return 0.5

        # Jämför månadsgenomsnitt med övergripande genomsnitt
        # Positiv = månaden är bättre än snittet
        diff = avg_month_ret - overall_avg
        
        # Konvertera till signal på 0-1 skala
        # Normalisera: diff på ±2% = signal ±0.3
        signal = 0.5 + (diff / 0.02) * 0.3
        signal = round(max(0.1, min(0.9, signal)), 3)

        # Styrka: om månaden har varit konsekvent (högt antal observationer)
        if len(month_returns) >= 5:
            win_rate = (month_returns > 0).mean()
            if win_rate > 0.65:
                signal = min(0.9, signal + 0.05)
            elif win_rate < 0.35:
                signal = max(0.1, signal - 0.05)

        _wc(f"seasonality:{ticker}", signal)
        return signal

    except Exception:
        return 0.5


# ══════════════════════════════════════════════════════════════
# 6. OPTIONS FLOW (put/call ratio)
# ══════════════════════════════════════════════════════════════

def fetch_options_flow_signal(ticker: str) -> float:
    """
    Beräknar signal baserat på optionsflöde (put/call ratio).
    
    Logik:
    - Hämtar optionskedjan för närmaste utgångsdatum
    - Beräknar total open interest för puts vs calls
    - Lågt P/C-ratio = bullish sentiment (0.6-0.9)
    - Högt P/C-ratio = bearish sentiment (0.1-0.4)
    
    Använder yfinance options chain.
    """
    import yfinance as yf

    cached = _rc(f"options:{ticker}", OPTIONS_CACHE_H)
    if cached is not None:
        return cached

    try:
        from core.data_fetcher import _with_timeout
        time.sleep(0.3)
        stock = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=8)

        # Hämta tillgängliga utgångsdatum
        try:
            expirations = _with_timeout(lambda: stock.options, timeout_sec=10)
        except Exception:
            _wc(f"options:{ticker}", 0.5)
            return 0.5

        if not expirations or len(expirations) == 0:
            _wc(f"options:{ticker}", 0.5)
            return 0.5

        # Använd närmaste utgångsdatum med minst 7 dagar kvar
        today = datetime.now().date()
        nearest_exp = None
        for exp in sorted(expirations):
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            days_until = (exp_date - today).days
            if 7 <= days_until <= 60:
                nearest_exp = exp
                break
        if not nearest_exp:
            nearest_exp = expirations[0]

        # Hämta optionskedja
        opt_chain = _with_timeout(
            lambda: stock.option_chain(nearest_exp), timeout_sec=15
        )

        calls = opt_chain.calls
        puts  = opt_chain.puts

        call_oi = calls["openInterest"].sum() if "openInterest" in calls else 0
        put_oi  = puts["openInterest"].sum()  if "openInterest" in puts  else 0

        total_oi = call_oi + put_oi
        if total_oi == 0 or call_oi == 0 or put_oi == 0:
            _wc(f"options:{ticker}", 0.5)
            return 0.5

        pc_ratio = put_oi / call_oi

        # Konvertera P/C-ratio till signal
        # P/C < 0.5 = starkt bullish → signal 0.7-0.9
        # P/C 0.5-0.8 = måttligt bullish → signal 0.6-0.7
        # P/C 0.8-1.2 = neutral → signal 0.45-0.55
        # P/C 1.2-2.0 = måttligt bearish → signal 0.3-0.45
        # P/C > 2.0 = starkt bearish → signal 0.1-0.3

        if pc_ratio < 0.5:
            signal = round(0.7 + (0.5 - pc_ratio) / 0.5 * 0.2, 3)
        elif pc_ratio < 0.8:
            signal = round(0.55 + (0.8 - pc_ratio) / 0.3 * 0.15, 3)
        elif pc_ratio < 1.2:
            signal = round(0.5 - (pc_ratio - 0.8) / 0.4 * 0.05, 3)
        elif pc_ratio < 2.0:
            signal = round(0.45 - (pc_ratio - 1.2) / 0.8 * 0.15, 3)
        else:
            signal = round(max(0.1, 0.3 - (pc_ratio - 2.0) / 3.0 * 0.2), 3)

        signal = max(0.1, min(0.9, signal))
        _wc(f"options:{ticker}", signal)
        return signal

    except Exception:
        return 0.5


# ══════════════════════════════════════════════════════════════
# BATCH-FUNKTION (kör alla 6 för hela universumet)
# ══════════════════════════════════════════════════════════════

def fetch_extra_data_batch(
    tickers:      list,
    finnhub_key:  str  = None,
    verbose:      bool = True,
) -> pd.DataFrame:
    """
    Hämtar alla extra signaler för alla tickers.
    Returnerar DataFrame med kolumner:
        ticker, insider_signal, earnings_signal, analyst_signal,
        short_interest_signal, seasonality_signal, options_flow_signal,
        extra_composite
    """
    rows = []
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        if verbose and i % 20 == 0:
            print(f"  Extra data: {i}/{total}...")

        insider  = fetch_insider_signal(ticker)
        earnings = fetch_earnings_surprise_signal(ticker)
        analyst  = fetch_analyst_revision_signal(ticker, finnhub_key)
        short    = fetch_short_interest_signal(ticker, finnhub_key)
        season   = fetch_seasonality_signal(ticker)
        options  = fetch_options_flow_signal(ticker)

        # Kombinerad extra-signal (viktat snitt)
        # Grundsignaler: 0.75, Nya signaler: 0.25 (lägre initial vikt tills bevisade)
        composite_base = insider * 0.30 + earnings * 0.40 + analyst * 0.30
        composite_new  = short * 0.40 + season * 0.35 + options * 0.25
        composite      = composite_base * 0.75 + composite_new * 0.25

        rows.append({
            "ticker":                ticker,
            "insider_signal":        insider,
            "earnings_signal":       earnings,
            "analyst_signal":        analyst,
            "short_interest_signal": short,
            "seasonality_signal":    season,
            "options_flow_signal":   options,
            "extra_composite":       round(composite, 3),
        })

    df = pd.DataFrame(rows)
    if verbose:
        high = (df["extra_composite"] > 0.65).sum()
        low  = (df["extra_composite"] < 0.35).sum()
        print(f"  ✓ Extra data klar: {high} bullish, {low} bearish, {total-high-low} neutrala")

    return df
