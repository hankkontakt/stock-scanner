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


def compare_snapshots(
    date_a: str,
    date_b: str,
    top_n: int = 20,
    min_score_change: float = 5.0,
) -> dict:
    """
    Jamfor scores mellan tva snapshot-datum.

    Identifierar:
    - Storsta score-okningar (top_n)
    - Storsta score-minskningar (top_n)
    - Nya i topp-N (i date_b men inte i date_a)
    - Fallna ur topp-N (i date_a men inte i date_b)
    - Aggregerad statistik

    Args:
        date_a: Tidigare snapshot (YYYY-MM-DD)
        date_b: Senare snapshot (YYYY-MM-DD)
        top_n: Antal topp-movers att returnera
        min_score_change: Minsta absoluta forandring for att inkluderas

    Returns:
        dict med movers_up, movers_down, new_entries, fallen, stats
    """
    snap_a = load_snapshot(date_a)
    snap_b = load_snapshot(date_b)

    if snap_a.empty or snap_b.empty:
        return {"error": "En eller bada snapshots saknas"}

    # Slå ihop på ticker
    score_cols = [c for c in [
        "score_total", "score_value", "score_quality", "score_momentum",
        "score_growth", "score_risk", "score_dividend", "score_sentiment",
        "score_short_interest",
    ] if c in snap_a.columns and c in snap_b.columns]

    merged = snap_a[["ticker"] + score_cols].merge(
        snap_b[["ticker"] + score_cols],
        on="ticker", how="outer", suffixes=("_a", "_b"),
        indicator=True,
    )

    # Beräkna score_total-delta for alla gemensamma
    common = merged[merged["_merge"] == "both"].copy()
    if common.empty:
        return {"error": "Inga gemensamma tickers mellan snapshoterna"}

    common["score_delta"] = common["score_total_b"] - common["score_total_a"]

    # Movers
    filtered = common[common["score_delta"].abs() >= min_score_change].copy()
    movers_up = filtered.nlargest(top_n, "score_delta")[[
        "ticker", "score_total_a", "score_total_b", "score_delta"
    ]].to_dict("records")
    movers_down = filtered.nsmallest(top_n, "score_delta")[[
        "ticker", "score_total_a", "score_total_b", "score_delta"
    ]].to_dict("records")

    # Nytt i topp-N
    top_a = set(snap_a.nlargest(top_n, "score_total")["ticker"])
    top_b = set(snap_b.nlargest(top_n, "score_total")["ticker"])
    new_entries = []
    for t in (top_b - top_a):
        row = snap_b[snap_b["ticker"] == t]
        if not row.empty:
            new_entries.append({"ticker": t, "score": float(row["score_total"].iloc[0])})
    fallen = []
    for t in (top_a - top_b):
        row = snap_a[snap_a["ticker"] == t]
        if not row.empty:
            fallen.append({"ticker": t, "score": float(row["score_total"].iloc[0])})

    # Aggregerad statistik
    stats = {
        "n_common": len(common),
        "mean_abs_change": float(common["score_delta"].abs().mean()),
        "median_abs_change": float(common["score_delta"].abs().median()),
        "max_increase": float(common["score_delta"].max()),
        "max_decrease": float(common["score_delta"].min()),
    }

    return {
        "movers_up": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()} for m in movers_up],
        "movers_down": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()} for m in movers_down],
        "new_entries": new_entries,
        "fallen": fallen,
        "stats": stats,
    }


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


# ══════════════════════════════════════════════════════════════════════════════
# 4. A/B-TEST AV FAKTORVIKTER
# ══════════════════════════════════════════════════════════════════════════════

# Faktorscore-kolumner → viktnyckel (matchar config.FACTOR_WEIGHTS)
_FACTOR_SCORE_COLS = {
    "score_value":          "value",
    "score_quality":        "quality",
    "score_momentum":       "momentum",
    "score_growth":         "growth",
    "score_risk":           "risk",
    "score_dividend":       "dividend",
    "score_sentiment":      "sentiment",
    "score_short_interest": "short_interest",
}


def _recompute_score(snap: pd.DataFrame, weights: dict) -> pd.Series:
    """Räknar om score_total från lagrade faktorpoäng med en given viktuppsättning.

    Bara faktorer som finns BÅDE i snapshoten och i weights används; vikterna
    omnormaliseras till de tillgängliga faktorerna så summan blir 1.0.
    """
    avail = {col: weights.get(key, 0.0)
             for col, key in _FACTOR_SCORE_COLS.items()
             if col in snap.columns and weights.get(key, 0.0) > 0}
    total_w = sum(avail.values())
    if total_w <= 0:
        # Fallback: använd lagrad score_total om inga faktorvikter matchar
        return snap.get("score_total", pd.Series(50.0, index=snap.index))
    score = pd.Series(0.0, index=snap.index)
    for col, w in avail.items():
        score += (w / total_w) * pd.to_numeric(snap[col], errors="coerce").fillna(50.0)
    return score


def _backtest_with_weights(weights: dict, top_n: int, holding_days: int,
                           price_cache: dict) -> dict:
    """Kör snapshot-backtest men rangordnar på OMVIKTAD score istället för lagrad."""
    snapshots = list_snapshots()
    rets_per_period = []
    for snap_date in snapshots[:-1]:
        snap = load_snapshot(snap_date)
        if snap.empty or "ticker" not in snap.columns:
            continue
        snap = snap.copy()
        snap["_score_ab"] = _recompute_score(snap, weights)
        top = snap.nlargest(top_n, "_score_ab")

        buy_dt  = snap_date
        sell_dt = (pd.Timestamp(buy_dt) + timedelta(days=holding_days)).strftime("%Y-%m-%d")
        rets = []
        for _, row in top.iterrows():
            buy_p  = _fetch_price_at(str(row["ticker"]), buy_dt,  price_cache)
            sell_p = _fetch_price_at(str(row["ticker"]), sell_dt, price_cache)
            if buy_p and sell_p and buy_p > 0:
                rets.append((sell_p / buy_p) - 1.0)
            time.sleep(0.02)
        if rets:
            rets_per_period.append(float(np.mean(rets)))

    if not rets_per_period:
        return {"n_periods": 0}

    arr = np.array(rets_per_period)
    equity = float(100_000 * np.prod(1 + arr))
    sharpe = float(arr.mean() / arr.std() * np.sqrt(12)) if arr.std() > 0 else 0.0
    return {
        "n_periods":      len(arr),
        "cum_return_pct": round((equity / 100_000 - 1) * 100, 2),
        "avg_period_pct": round(float(arr.mean()) * 100, 2),
        "sharpe":         round(sharpe, 2),
        "win_rate":       round(float((arr > 0).mean() * 100), 1),
    }


def ab_test_weights(
    weights_a: dict,
    weights_b: dict,
    top_n: int = 10,
    holding_days: int = 30,
    label_a: str = "A",
    label_b: str = "B",
) -> dict:
    """
    A/B-testar två faktorviktuppsättningar mot historiska snapshots.

    Insikt: snapshots lagrar redan per-faktor-poäng → vi kan omvikta dem med
    olika viktuppsättningar och mäta vilken topp-N-portfölj som presterat bäst,
    UTAN att hämta om någon scoring-data. Endast priser hämtas (delad cache).

    Args:
        weights_a/b: dicts {faktornyckel: vikt} (samma format som config.FACTOR_WEIGHTS).
        top_n, holding_days: backtest-parametrar (samma för båda för rättvis jämförelse).
        label_a/b: etiketter för resultatet.

    Returns:
        dict med resultat per viktset + vinnare, eller {"error": ...} om för få snapshots.
    """
    snapshots = list_snapshots()
    if len(snapshots) < 3:
        return {"error": f"Bara {len(snapshots)} snapshots — behöver ≥3 för A/B-test.",
                "n_snapshots": len(snapshots)}

    price_cache: dict = {}  # Delad cache → priserna hämtas bara en gång för båda
    res_a = _backtest_with_weights(weights_a, top_n, holding_days, price_cache)
    res_b = _backtest_with_weights(weights_b, top_n, holding_days, price_cache)

    winner = None
    if res_a.get("n_periods") and res_b.get("n_periods"):
        winner = label_a if res_a["cum_return_pct"] >= res_b["cum_return_pct"] else label_b

    return {
        "n_snapshots": len(snapshots),
        "top_n":       top_n,
        "holding_days": holding_days,
        label_a:       res_a,
        label_b:       res_b,
        "winner":      winner,
    }
