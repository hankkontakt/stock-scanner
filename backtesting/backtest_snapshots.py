"""
backtest_snapshots.py — Point-in-time-korrekt backtest
======================================================
Backtestas mot faktiska scored_universe-snapshots som committas av CI-pipelinen.
Till skillnad från backtest.py (som rekonstruerar scoring på historisk prisdata)
använder denna modul de *riktiga* score-rekommendationerna vid varje tidpunkt —
inget look-ahead bias, inga rekonstruerade fundamental-poäng.

Begränsning: kräver att snapshots finns (byggs upp löpande av CI).
Ju fler snapshots som ackumulerats, desto meningsfullare backtest.

Användning:
    from backtesting.backtest_snapshots import run_snapshot_backtest, save_snapshot
    results = run_snapshot_backtest(top_n=10, benchmark="^OMXS30")
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import yfinance as yf

_ROOT        = Path(__file__).resolve().parent.parent
REPORTS_DIR  = _ROOT / "reports"
SNAPSHOT_DIR = _ROOT / "data" / "bt_snapshots"

SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. SNAPSHOT-INSAMLING (körs av CI-pipelinen efter varje veckoscan)
# ══════════════════════════════════════════════════════════════════════════════

def save_snapshot(scored_df: pd.DataFrame, date_str: str | None = None) -> bool:
    """
    Sparar en tunn snapshot av dagens scoring för framtida backtest.

    Sparar bara de kolumner som krävs för backtesting — håller filstorleken liten.
    Anropas av daily_pipeline.py efter score_universe() vid weekly-körning.

    Returns True om snapshoten sparades, False om den redan existerade.
    """
    if scored_df is None or scored_df.empty:
        return False

    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    path = SNAPSHOT_DIR / f"snapshot_{date_str}.parquet"
    if path.exists():
        return False  # Redan sparad för detta datum

    keep_cols = [
        "ticker", "score_total", "score_value", "score_quality",
        "score_momentum", "score_growth", "score_risk", "score_dividend",
        "score_sentiment", "score_short_interest",
        "entry_signal", "current_price", "sector", "name",
        "return_12m", "return_6m", "return_3m",
    ]
    cols = [c for c in keep_cols if c in scored_df.columns]
    snap = scored_df[cols].copy()
    snap["snapshot_date"] = date_str

    try:
        snap.to_parquet(path, index=False, compression="zstd")
    except Exception:
        # Fallback till JSON om pyarrow saknas
        path = path.with_suffix(".json")
        snap.to_json(path, orient="records", force_ascii=False)

    return True


def list_snapshots() -> list[str]:
    """Returnerar alla tillgängliga snapshot-datum sorterade."""
    dates = []
    for f in SNAPSHOT_DIR.glob("snapshot_*.parquet"):
        dates.append(f.stem.replace("snapshot_", ""))
    for f in SNAPSHOT_DIR.glob("snapshot_*.json"):
        d = f.stem.replace("snapshot_", "")
        if d not in dates:
            dates.append(d)
    return sorted(dates)


def load_snapshot(date_str: str) -> pd.DataFrame:
    """Laddar en snapshot för ett givet datum."""
    for ext in (".parquet", ".json"):
        path = SNAPSHOT_DIR / f"snapshot_{date_str}{ext}"
        if path.exists():
            return pd.read_parquet(path) if ext == ".parquet" else pd.read_json(path, orient="records")
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# 2. PRIS-HÄMTNING (enkel, med caching)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_price_at(ticker: str, date_str: str, price_cache: dict) -> float | None:
    """Hämtar stängningskurs för en ticker på eller nära ett datum."""
    if ticker in price_cache:
        series = price_cache[ticker]
    else:
        try:
            target = pd.Timestamp(date_str)
            start  = (target - timedelta(days=60)).strftime("%Y-%m-%d")
            end    = (target + timedelta(days=60)).strftime("%Y-%m-%d")
            data   = yf.download(ticker, start=start, end=end,
                                 auto_adjust=True, progress=False)
            if data.empty:
                price_cache[ticker] = None
                return None
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            price_cache[ticker] = close
            series = close
        except Exception:
            price_cache[ticker] = None
            return None

    if series is None or series.empty:
        return None

    target_ts = pd.Timestamp(date_str)
    # Hitta närmaste handelsdatum
    valid = series.index[series.index <= target_ts]
    if len(valid) == 0:
        valid = series.index[series.index > target_ts]
    if len(valid) == 0:
        return None
    return float(series.loc[valid[-1]])


# ══════════════════════════════════════════════════════════════════════════════
# 3. BACKTEST-MOTOR
# ══════════════════════════════════════════════════════════════════════════════

def run_snapshot_backtest(
    top_n: int = 10,
    holding_days: int = 30,
    benchmark: str = "^OMXS30",
    min_entry_signal: str | None = None,
    verbose: bool = True,
) -> dict:
    """
    Kör point-in-time-korrekt backtest mot faktiska score-snapshots.

    För varje snapshot:
    1. Väljer topp-N aktier (efter score_total, ev. filtrerat på entry_signal)
    2. Hämtar priset på snapshot-datumet (köp-pris)
    3. Hämtar priset holding_days senare (sälj-pris)
    4. Beräknar avkastning vs benchmark

    Returns dict med periods, equity_curve, sharpe, max_drawdown, hit_rate.
    """
    snapshots = list_snapshots()
    if len(snapshots) < 2:
        return {
            "error": (
                f"Bara {len(snapshots)} snapshot(s) tillgängliga. "
                f"Backtesten byggs upp löpande — kör vecko­scanen regelbundet."
            ),
            "n_snapshots": len(snapshots),
        }

    if verbose:
        print(f"  Backtestas mot {len(snapshots)} snapshots ({snapshots[0]} → {snapshots[-1]})")
        print(f"  Topp-{top_n}, håll {holding_days} dagar, benchmark={benchmark}")

    price_cache: dict = {}
    periods = []

    for i, snap_date in enumerate(snapshots[:-1]):
        snap = load_snapshot(snap_date)
        if snap.empty or "ticker" not in snap.columns:
            continue

        # Välj topp-N
        if min_entry_signal and "entry_signal" in snap.columns:
            signal_prio = {"STARK": 0, "OK": 1, "VÄNTA": 2, "EJ AKTUELL": 3}
            snap["_sig_prio"] = snap["entry_signal"].map(signal_prio).fillna(3)
            snap = snap.sort_values(["_sig_prio", "score_total"], ascending=[True, False])
        else:
            snap = snap.sort_values("score_total", ascending=False)

        top = snap.head(top_n)

        # Sälj-datum
        buy_dt  = snap_date
        sell_dt = (pd.Timestamp(buy_dt) + timedelta(days=holding_days)).strftime("%Y-%m-%d")

        # Beräkna avkastning för portföljen (likaviktad)
        returns = []
        for _, row in top.iterrows():
            ticker = str(row["ticker"])
            buy_p  = _fetch_price_at(ticker, buy_dt,  price_cache)
            sell_p = _fetch_price_at(ticker, sell_dt, price_cache)
            if buy_p and sell_p and buy_p > 0:
                ret = (sell_p / buy_p) - 1.0
                returns.append(ret)
            time.sleep(0.05)  # Rate-limiting

        if not returns:
            continue

        port_ret = float(np.mean(returns))

        # Benchmark
        bench_buy  = _fetch_price_at(benchmark, buy_dt,  price_cache)
        bench_sell = _fetch_price_at(benchmark, sell_dt, price_cache)
        bench_ret  = (bench_sell / bench_buy - 1.0) if bench_buy and bench_sell and bench_buy > 0 else None

        periods.append({
            "date":      buy_dt,
            "sell_date": sell_dt,
            "n_picks":   len(returns),
            "return":    round(port_ret * 100, 2),
            "benchmark": round(bench_ret * 100, 2) if bench_ret is not None else None,
            "alpha":     round((port_ret - bench_ret) * 100, 2) if bench_ret is not None else None,
            "hit":       port_ret > (bench_ret or 0),
        })

        if verbose:
            bench_str = f"bench {bench_ret*100:+.1f}%" if bench_ret is not None else ""
            print(f"  {buy_dt}: port {port_ret*100:+.1f}% {bench_str}")

    if not periods:
        return {"error": "Inga perioder med tillräcklig prisdata.", "n_snapshots": len(snapshots)}

    df_p = pd.DataFrame(periods)

    # Equity curve (kumulativ, börjar på 100k)
    equity = 100_000.0
    equity_curve = []
    for _, row in df_p.iterrows():
        equity *= (1 + row["return"] / 100)
        equity_curve.append({"date": row["date"], "equity": round(equity, 2)})

    # Statistik
    rets   = df_p["return"].values / 100
    bench  = df_p["benchmark"].dropna().values / 100
    n      = len(rets)
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(12)) if np.std(rets) > 0 else 0.0
    cum_ret = (equity / 100_000 - 1) * 100
    hit_rate = float(df_p["hit"].sum() / n * 100) if n > 0 else 0.0

    # Max drawdown
    eq_vals = np.array([e["equity"] for e in equity_curve])
    peak = np.maximum.accumulate(eq_vals)
    dd   = (eq_vals - peak) / peak
    max_dd = float(dd.min() * 100)

    return {
        "n_snapshots":    len(snapshots),
        "n_periods":      n,
        "top_n":          top_n,
        "holding_days":   holding_days,
        "benchmark":      benchmark,
        "periods":        periods,
        "equity_curve":   equity_curve,
        "cum_return_pct": round(cum_ret, 2),
        "sharpe":         round(sharpe, 2),
        "max_drawdown":   round(max_dd, 2),
        "hit_rate":       round(hit_rate, 1),
        "avg_alpha":      round(float(df_p["alpha"].dropna().mean()), 2) if "alpha" in df_p else None,
    }
