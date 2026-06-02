"""
ml_backtest.py -- ML-backtesting-motor for stock-scanner.

Simulerar tradingstrategier baserade pa ML-prediktioner:
  - simulate_strategy:  top-N equal-weight med manadsvis rebalansering
  - rolling_backtest:   rullande backtest over tid

Resultat sparas som JSON i data/ml_backtest_results/.
Benchmark-jamforelse mot SPY / OMXS30.
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
BACKTEST_DIR = ROOT / "data" / "ml_backtest_results"
BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

# Default benchmark-tickers per marknad
BENCHMARK_TICKERS = {
    "universe": "SPY",
    "smallcap": "OMXS30",  # Representativ index for svenska smabolag
}
_BENCHMARK_ALIASES = {
    "SPY": "SPY",
    "OMXS30": "XACTOMXS3.ST",
}


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BacktestResult:
    """Resultat fran en backtest-korning."""
    total_return: float
    cagr: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    n_trades: int
    equity_curve: list  # [{date, portfolio_value, benchmark_value}]
    benchmark_return: float
    benchmark_cagr: float
    benchmark_sharpe: float
    benchmark_max_dd: float
    params: dict
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class RollingWindowResult:
    """Resultat for en enskild fold i en rullande backtest."""
    window_label: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    ic: float
    hit_rate: float
    top_n_return: float
    max_drawdown: float
    n_tickers_in_universe: int


# ══════════════════════════════════════════════════════════════════════════════
# HJALPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Saker konvertering till float."""
    try:
        v = float(value)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except (ValueError, TypeError):
        return default


def _compute_cagr(start_value: float, end_value: float, years: float) -> float:
    """Beraknar CAGR (Compound Annual Growth Rate)."""
    if start_value <= 0 or years <= 0:
        return 0.0
    ratio = end_value / start_value
    if ratio <= 0:
        return 0.0
    return float(ratio ** (1.0 / years) - 1.0)


def _compute_sharpe(returns_series: pd.Series, risk_free_rate: float = 0.02) -> float:
    """
    Beraknar annualiserad Sharpe-kvot.

    Args:
        returns_series: Series med dagliga avkastningar.
        risk_free_rate: Annualiserad riskfri ranta (standard 2 %).

    Returns:
        Sharpe-kvot (annualiserad).
    """
    if len(returns_series) < 5:
        return 0.0
    excess = returns_series - risk_free_rate / 252.0
    std = float(excess.std())
    if std == 0 or np.isnan(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(252.0))


def _compute_max_drawdown(equity: pd.Series) -> float:
    """Beraknar maximal drawdown fran en equity curve (positivt tal, t.ex. 0.25 = 25 %)."""
    if len(equity) < 2:
        return 0.0
    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    return float(abs(dd.min()))


def _compute_profit_factor(gross_profit: float, gross_loss: float) -> float:
    """Profit factor = bruttoförtjänst / bruttöförlust."""
    if abs(gross_loss) < 1e-10:
        return 999.0 if gross_profit > 0 else 1.0
    return float(gross_profit / abs(gross_loss))


def _compute_win_rate(trades: list[float]) -> tuple[float, float, float, float]:
    """Beraknar win rate, avg win, avg loss fran en lista av trade-avkastningar."""
    if not trades:
        return 0.0, 0.0, 0.0, 0.0

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]

    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    return win_rate, avg_win, avg_loss


def _fetch_benchmark_data(ticker: str, start_date: str, end_date: str) -> pd.Series | None:
    """
    Hamtar benchmark-data (SPY eller OMXS30) for given period.

    Args:
        ticker: Benchmark-ticker (SPY eller XACTOMXS3.ST).
        start_date: Startdatum (YYYY-MM-DD).
        end_date: Slutdatum (YYYY-MM-DD).

    Returns:
        Series med stängningskurser och datum-index, eller None vid fel.
    """
    try:
        import yfinance as yf
        bm = yf.download(ticker, start=start_date, end=end_date,
                         auto_adjust=True, progress=False, threads=False)
        if bm is None or bm.empty:
            logger.warning(f"Ingen benchmark-data for {ticker}")
            return None
        close = bm["Close"] if "Close" in bm.columns else bm.iloc[:, 0]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close
    except Exception as e:
        logger.warning(f"Kunde inte hamta benchmark {ticker}: {e}")
        return None


def _download_benchmark_if_missing(
    benchmark_ticker: str, start_date: str, end_date: str
) -> pd.Series | None:
    """
    Laddar ner benchmark-data om den inte redan finns cachad.
    """
    # Forenkad: anropar alltid yfinance (cachen i yfinance skoter sig sjalv)
    return _fetch_benchmark_data(benchmark_ticker, start_date, end_date)


# ══════════════════════════════════════════════════════════════════════════════
# SIMULERA STRATEGI
# ══════════════════════════════════════════════════════════════════════════════

def simulate_strategy(
    scored_df: pd.DataFrame,
    model: Any = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 10,
    rebalance_freq: str = "ME",  # 'ME' = manadsvis, 'W' = veckovis
    max_position_size: float = 1.0,
    benchmark_ticker: Optional[str] = None,
    transaction_cost_pct: float = 0.001,
) -> BacktestResult:
    """
    Simulerar en top-N equal-weight-strategi baserad pa ML-prediktioner.

    Algorithm:
      1. For varje rebalanseringsdatum: rangordna aktier efter predicted_return
      2. Valj top-N aktier (equal weight)
      3. Hall till nasta rebalansering
      4. Berakna portfolio-avkastning baserat pa forward_return_30d
      5. Jamfor med benchmark (SPY/OMXS30)

    Args:
        scored_df: DataFrame med kolumner ['date', 'ticker', 'predicted_return',
                   'forward_return_30d'].
        model: Ignorerad (anvands i rolling_backtest). HÃ¤r anvands
               'predicted_return' direkt fran scored_df.
        start_date: Startdatum (YYYY-MM-DD). Default: forsta datum i scored_df.
        end_date: Slutdatum (YYYY-MM-DD). Default: sista datum i scored_df.
        top_n: Antal aktier i portfoljen (5, 10, 20).
        rebalance_freq: Rebalanseringsfrekvens: 'ME' (manadsvis) eller
                        'W' (veckovis). Default 'ME'.
        max_position_size: Max andel av portfoljen per position (0-1).
        benchmark_ticker: Explicit benchmark-ticker. Om None anvands ingen
                          benchmark.
        transaction_cost_pct: Transaktionskostnad per trade (decimal).
                              Default 0.001 (0.1 %).

    Returns:
        BacktestResult med alla nyckeltal.
    """
    # Validera indata
    required_cols = {"date", "ticker"}
    missing = required_cols - set(scored_df.columns)
    if missing:
        raise ValueError(f"scored_df saknar kolumner: {missing}")

    if "predicted_return" not in scored_df.columns:
        raise ValueError("scored_df maste ha 'predicted_return'-kolumn. "
                         "Kor predict_returns forst.")

    if "forward_return_30d" not in scored_df.columns:
        logger.warning("scored_df saknar 'forward_return_30d' -- "
                       "anvander 'forward_return_30d' om den finns, annars 0")

    df = scored_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    # Filtrera datumintervall
    if start_date:
        df = df[df["date"] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df["date"] <= pd.Timestamp(end_date)]

    if df.empty:
        raise ValueError("Ingen data kvar efter datumfiltrering")

    # Sortera och rensa
    df = df.dropna(subset=["predicted_return"]).sort_values(["date", "ticker"]).reset_index(drop=True)

    if df.empty:
        raise ValueError("Inga giltiga prediktioner efter NaN-rensning")

    # Skapa rebalanseringsdatum
    all_dates = sorted(df["date"].unique())
    date_range = pd.Series(all_dates)

    # Identifiera rebalanseringsdatum baserat pa frekvens
    rebalance_dates = _get_rebalance_dates(all_dates, rebalance_freq)

    if len(rebalance_dates) < 2:
        raise ValueError(
            f"Behover minst 2 rebalanseringsdatum for {rebalance_freq}-frekvens, "
            f"fick {len(rebalance_dates)}"
        )

    logger.info(
        f"Simulerar strategi: top-{top_n}, {rebalance_freq}, "
        f"{len(rebalance_dates)} rebalanseringar, "
        f"transaktionskostnad={transaction_cost_pct:.1%}"
    )

    # Simulera portfoljen
    portfolio_value = 1.0  # Startkapital: 1 (normaliserat)
    equity_curve: list[dict] = []
    trades: list[float] = []
    current_holdings: dict[str, float] = {}  # ticker -> allocation

    # For benchmark
    benchmark_prices = None
    if benchmark_ticker:
        bm_start = all_dates[0].strftime("%Y-%m-%d") if hasattr(all_dates[0], "strftime") else str(all_dates[0])
        bm_end = all_dates[-1].strftime("%Y-%m-%d") if hasattr(all_dates[-1], "strftime") else str(all_dates[-1])
        benchmark_prices = _download_benchmark_if_missing(benchmark_ticker, bm_start, bm_end)

    # Iterera over rebalanseringsperioder
    for i in range(len(rebalance_dates) - 1):
        reb_date = rebalance_dates[i]
        next_reb_date = rebalance_dates[i + 1]

        # Hamta data for denna rebalanseringsdag
        day_data = df[df["date"] == reb_date].copy()

        if day_data.empty:
            continue

        # Rangordna efter predicted_return, valj top-N
        day_data = day_data.sort_values("predicted_return", ascending=False)
        top_tickers = day_data.head(top_n)

        if top_tickers.empty:
            continue

        # Equal weight, begransad av max_position_size
        n_positions = min(top_n, len(top_tickers))
        position_weight = min(1.0 / max(n_positions, 1), max_position_size)

        # Berakna forward return for perioden
        # Forward return ar redan forward_return_30d, sa vi anvander
        # det som proxy for hur aktien utvecklades
        period_data = df[(df["date"] >= reb_date) & (df["date"] < next_reb_date)]

        if not period_data.empty:
            # Hamta faktisk avkastning for valda tickers under perioden
            # Anvand forward_return_30d fran rebalanseringsdagen
            period_returns = {}
            for _, row in top_tickers.iterrows():
                fwd_ret = _safe_float(row.get("forward_return_30d", 0))
                period_returns[row["ticker"]] = fwd_ret

            if period_returns:
                # Portfoljens avkastning = viktat medel
                portfolio_return = sum(
                    position_weight * ret for ret in period_returns.values()
                )
                # Transaktionskostnad (vid rebalansering)
                portfolio_return -= transaction_cost_pct
                portfolio_value *= (1.0 + portfolio_return)
                trades.append(portfolio_return)

        # Skapa equity curve-punkt
        equity_point = {
            "date": reb_date.strftime("%Y-%m-%d") if hasattr(reb_date, "strftime") else str(reb_date),
            "portfolio_value": round(portfolio_value, 6),
        }

        # Benchmark-varde for samma datum
        if benchmark_prices is not None:
            try:
                bm_date = pd.Timestamp(reb_date)
                if bm_date in benchmark_prices.index:
                    bm_price = float(benchmark_prices.loc[bm_date])
                    equity_point["benchmark_value"] = round(bm_price, 2)
            except Exception:
                pass

        equity_curve.append(equity_point)

    # Sista punkten
    if equity_curve:
        last_date = all_dates[-1].strftime("%Y-%m-%d") if hasattr(all_dates[-1], "strftime") else str(all_dates[-1])
        equity_curve.append({
            "date": last_date,
            "portfolio_value": round(portfolio_value, 6),
        })
        if benchmark_prices is not None:
            try:
                if pd.Timestamp(last_date) in benchmark_prices.index:
                    bm_price = float(benchmark_prices.loc[pd.Timestamp(last_date)])
                    equity_curve[-1]["benchmark_value"] = round(bm_price, 2)
            except Exception:
                pass

    # ── Berakna nyckeltal ─────────────────────────────────────────────────────

    if not equity_curve:
        raise ValueError("Ingen equity curve genererad")

    start_value = equity_curve[0]["portfolio_value"]
    end_value = equity_curve[-1]["portfolio_value"]

    # Total return
    total_return = (end_value / start_value) - 1.0 if start_value > 0 else 0.0

    # CAGR
    days_elapsed = (all_dates[-1] - all_dates[0]).days if len(all_dates) >= 2 else 0
    years_elapsed = max(days_elapsed / 365.25, 1 / 365.25)
    cagr = _compute_cagr(start_value, end_value, years_elapsed)

    # Sharpe (fran trade-avkastningar)
    trade_series = pd.Series(trades)
    sharpe = _compute_sharpe(trade_series)

    # Max drawdown fran equity curve
    equity_values = pd.Series([p["portfolio_value"] for p in equity_curve])
    max_dd = _compute_max_drawdown(equity_values)

    # Win rate, avg win/loss
    win_rate, avg_win, avg_loss = _compute_win_rate(trades)

    # Profit factor
    gross_profit = sum(t for t in trades if t > 0)
    gross_loss = sum(t for t in trades if t < 0)
    profit_factor = _compute_profit_factor(gross_profit, gross_loss)

    # Benchmark-nyckeltal
    benchmark_return = 0.0
    benchmark_cagr_val = 0.0
    benchmark_sharpe_val = 0.0
    benchmark_max_dd_val = 0.0

    if benchmark_prices is not None and len(benchmark_prices) >= 2:
        bm_start_price = float(benchmark_prices.iloc[0])
        bm_end_price = float(benchmark_prices.iloc[-1])
        if bm_start_price > 0:
            benchmark_return = (bm_end_price / bm_start_price) - 1.0
            benchmark_cagr_val = _compute_cagr(bm_start_price, bm_end_price, years_elapsed)

        bm_rets = benchmark_prices.pct_change(fill_method=None).dropna()
        if len(bm_rets) >= 5:
            benchmark_sharpe_val = _compute_sharpe(bm_rets)

            # Max drawdown for benchmark
            bm_peak = benchmark_prices.expanding().max()
            bm_dd = (benchmark_prices - bm_peak) / bm_peak
            benchmark_max_dd_val = float(abs(bm_dd.min()))

    result = BacktestResult(
        total_return=round(total_return, 4),
        cagr=round(cagr, 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown=round(max_dd, 4),
        win_rate=round(win_rate, 4),
        avg_win=round(avg_win, 6),
        avg_loss=round(avg_loss, 6),
        profit_factor=round(profit_factor, 4),
        n_trades=len(trades),
        equity_curve=equity_curve,
        benchmark_return=round(benchmark_return, 4),
        benchmark_cagr=round(benchmark_cagr_val, 4),
        benchmark_sharpe=round(benchmark_sharpe_val, 4),
        benchmark_max_dd=round(benchmark_max_dd_val, 4),
        params={
            "top_n": top_n,
            "rebalance_freq": rebalance_freq,
            "max_position_size": max_position_size,
            "transaction_cost_pct": transaction_cost_pct,
            "benchmark_ticker": benchmark_ticker,
            "n_rebalances": len(rebalance_dates),
        },
    )

    logger.info(
        f"Resultat: total_return={result.total_return:.2%}, "
        f"CAGR={result.cagr:.2%}, Sharpe={result.sharpe_ratio:.2f}, "
        f"MaxDD={result.max_drawdown:.2%}, WinRate={result.win_rate:.1%}"
    )

    return result


def _get_rebalance_dates(dates: list[pd.Timestamp], freq: str) -> list[pd.Timestamp]:
    """
    Hittar rebalanseringsdatum baserat pa frekvens.

    Args:
        dates: Sorterad lista av datum.
        freq: 'ME' (manadsvis) eller 'W' (veckovis).

    Returns:
        Lista av rebalanseringsdatum.
    """
    if not dates:
        return []

    if freq == "ME":
        # Valj sista tillgangliga datumet varje manad
        df_dates = pd.Series(dates)
        monthly = df_dates.groupby(df_dates.dt.to_period("M")).max().tolist()
        return monthly
    elif freq == "W":
        # Valj sista tillgangliga datumet varje vecka
        df_dates = pd.Series(dates)
        weekly = df_dates.groupby(df_dates.dt.isocalendar().week).max().tolist()
        return weekly
    else:
        logger.warning(f"Okand frekvens: {freq}, anvander manadsvis")
        return _get_rebalance_dates(dates, "ME")


# ══════════════════════════════════════════════════════════════════════════════
# RULLANDE BACKTEST
# ══════════════════════════════════════════════════════════════════════════════

def rolling_backtest(
    scored_df: pd.DataFrame,
    model: Any = None,
    window_years: int = 2,
    step_months: int = 3,
    top_n: int = 10,
    min_train_rows: int = 500,
) -> list[RollingWindowResult]:
    """
    Rullande backtest over tid (walk-forward analysis).

    Delar upp datan i overlappande fönster:
      - Train:   window_years ar (t.ex. 2 ar)
      - Test:    step_months manader (t.ex. 3 manader)
      - Step:    step_months manader framat

    For varje fönster:
      1. Trana modell pa train-data
      2. Prediktera pa test-data
      3. Berakna IC, hit rate, top-N-return, max drawdown

    Args:
        scored_df: DataFrame med ML-training data (features + forward_return_30d).
        model: Oanvand (modellen trainlas per window).
        window_years: Train-fönstrets storlek i ar.
        step_months: Steg/storlek for test-fonstret i manader.
        top_n: Antal tickers i topp-N-berakningen.
        min_train_rows: Minsta antal train-rader for att kora en window.

    Returns:
        Lista av RollingWindowResult, en per window.
    """
    required_cols = {"date", "ticker", "forward_return_30d"}
    missing = required_cols - set(scored_df.columns)
    if missing:
        raise ValueError(f"scored_df saknar kolumner: {missing}")

    df = scored_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    all_dates = sorted(df["date"].unique())
    if len(all_dates) < 60:
        raise ValueError(
            f"For fa datum for rolling backtest: {len(all_dates)}. "
            f"Behover minst 60."
        )

    window_days = window_years * 252
    step_days = step_months * 21

    # Hitta features (alla TECH_FEATURES som finns i datan)
    from core.ml_predictor import TECH_FEATURES, _make_regressor, _per_date_ic

    available_features = [c for c in TECH_FEATURES if c in df.columns]
    if not available_features:
        raise ValueError("Inga tekniska features hittades i scored_df")

    results: list[RollingWindowResult] = []
    window_idx = 0

    for start_i in range(0, len(all_dates) - window_days, step_days):
        train_start = all_dates[start_i]
        train_end = all_dates[min(start_i + window_days, len(all_dates) - 1)]
        test_start_candidate = start_i + window_days
        if test_start_candidate >= len(all_dates):
            break
        test_end_idx = min(test_start_candidate + step_days, len(all_dates))
        test_end = all_dates[test_end_idx - 1] if test_end_idx > test_start_candidate else all_dates[-1]

        # Valj train/test-data
        train_mask = (df["date"] >= train_start) & (df["date"] < train_end)
        test_mask = (df["date"] >= train_end) & (df["date"] <= test_end)

        train_df = df[train_mask].copy()
        test_df = df[test_mask].copy()

        if len(train_df) < min_train_rows or len(test_df) < 10:
            logger.info(
                f"  Window {window_idx}: hoppar over "
                f"(train={len(train_df)}, test={len(test_df)})"
            )
            window_idx += 1
            continue

        # Trana modell pa train-data
        try:
            window_model = _make_regressor()
            X_tr = train_df[available_features].fillna(0).values
            y_tr = train_df["forward_return_30d"].values
            window_model.fit(X_tr, y_tr)
        except Exception as e:
            logger.warning(f"  Window {window_idx}: training failed: {e}")
            window_idx += 1
            continue

        # Prediktera pa test-data
        try:
            X_te = test_df[available_features].fillna(0).values
            preds = window_model.predict(X_te)
        except Exception as e:
            logger.warning(f"  Window {window_idx}: prediction failed: {e}")
            window_idx += 1
            continue

        # Berakna IC
        y_te = test_df["forward_return_30d"].values
        ic = _per_date_ic(test_df["date"].values, preds, y_te)

        # Hit rate
        hit_rate = float(((preds > 0) == (y_te > 0)).mean()) if len(y_te) > 0 else 0.0

        # Top-N return
        test_with_preds = test_df.copy()
        test_with_preds["predicted_return"] = preds
        test_latest = test_with_preds.loc[
            test_with_preds.groupby("ticker")["date"].idxmax()
        ]
        top_tickers = test_latest.nlargest(top_n, "predicted_return")
        if not top_tickers.empty and "forward_return_30d" in top_tickers.columns:
            top_n_return = float(top_tickers["forward_return_30d"].mean())
        else:
            top_n_return = 0.0

        # Max drawdown i testperioden
        if "forward_return_30d" in test_df.columns:
            dd_series = pd.Series(
                test_df.groupby("date")["forward_return_30d"].mean().values
            )
            max_dd_val = _compute_max_drawdown((1 + dd_series).cumprod())
        else:
            max_dd_val = 0.0

        # Antal unika tickers i test-perioden
        n_tickers = int(test_df["ticker"].nunique())

        results.append(RollingWindowResult(
            window_label=f"Window_{window_idx}",
            train_start=train_start.strftime("%Y-%m-%d"),
            train_end=train_end.strftime("%Y-%m-%d"),
            test_start=test_end.strftime("%Y-%m-%d"),
            test_end=test_end.strftime("%Y-%m-%d"),
            ic=round(ic, 4),
            hit_rate=round(hit_rate, 4),
            top_n_return=round(top_n_return, 4),
            max_drawdown=round(max_dd_val, 4),
            n_tickers_in_universe=n_tickers,
        ))

        logger.info(
            f"  Window {window_idx}: IC={results[-1].ic:.4f}, "
            f"hit_rate={results[-1].hit_rate:.4f}, "
            f"top-{top_n}_return={results[-1].top_n_return:.4f}"
        )

        window_idx += 1

    if not results:
        logger.warning("Inga windows kordes i rolling_backtest -- for lite data?")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# SPARA / LADDA RESULTAT
# ══════════════════════════════════════════════════════════════════════════════

def save_backtest_result(result: BacktestResult, name: str) -> Path:
    """
    Sparar backtest-resultat som JSON.

    Args:
        result: BacktestResult att spara.
        name: Filnamn (utan .json).

    Returns:
        Sökvag till sparad fil.
    """
    out = BACKTEST_DIR / f"{name}.json"
    data = {
        "total_return": result.total_return,
        "cagr": result.cagr,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "win_rate": result.win_rate,
        "avg_win": result.avg_win,
        "avg_loss": result.avg_loss,
        "profit_factor": result.profit_factor,
        "n_trades": result.n_trades,
        "benchmark_return": result.benchmark_return,
        "benchmark_cagr": result.benchmark_cagr,
        "benchmark_sharpe": result.benchmark_sharpe,
        "benchmark_max_dd": result.benchmark_max_dd,
        "params": result.params,
        "created_at": result.created_at,
        # Forkorta equity curve for stora dataset (max 500 punkter)
        "equity_curve": _downsample_equity_curve(result.equity_curve, 500),
    }
    out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info(f"Sparade backtest-resultat: {out}")
    return out


def save_rolling_results(results: list[RollingWindowResult], name: str) -> Path:
    """
    Sparar rolling backtest-resultat som JSON.

    Args:
        results: Lista av RollingWindowResult.
        name: Filnamn (utan .json).

    Returns:
        Sökvag till sparad fil.
    """
    out = BACKTEST_DIR / f"rolling_{name}.json"
    data = {
        "n_windows": len(results),
        "windows": [
            {
                "window_label": r.window_label,
                "train_start": r.train_start,
                "train_end": r.train_end,
                "test_start": r.test_start,
                "test_end": r.test_end,
                "ic": r.ic,
                "hit_rate": r.hit_rate,
                "top_n_return": r.top_n_return,
                "max_drawdown": r.max_drawdown,
                "n_tickers_in_universe": r.n_tickers_in_universe,
            }
            for r in results
        ],
        "summary": _compute_rolling_summary(results),
        "created_at": datetime.now().isoformat(),
    }
    out.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info(f"Sparade rolling-resultat: {out}")
    return out


def _downsample_equity_curve(curve: list[dict], max_points: int = 500) -> list[dict]:
    """Reducerar antalet punkter i en equity curve for lagring."""
    if len(curve) <= max_points:
        return curve
    step = len(curve) // max_points
    return curve[::step] + [curve[-1]]


def _compute_rolling_summary(results: list[RollingWindowResult]) -> dict:
    """Beraknar sammanfattande statistik over rolling windows."""
    if not results:
        return {}

    ics = [r.ic for r in results]
    hit_rates = [r.hit_rate for r in results]
    top_returns = [r.top_n_return for r in results]

    return {
        "avg_ic": round(float(np.mean(ics)), 4),
        "std_ic": round(float(np.std(ics)), 4),
        "min_ic": round(float(min(ics)), 4),
        "max_ic": round(float(max(ics)), 4),
        "avg_hit_rate": round(float(np.mean(hit_rates)), 4),
        "avg_top_n_return": round(float(np.mean(top_returns)), 4),
        "n_windows": len(results),
        "n_windows_positive_ic": sum(1 for ic in ics if ic > 0),
        "n_windows_negative_ic": sum(1 for ic in ics if ic < 0),
    }


def load_backtest_result(name: str) -> dict | None:
    """
    Laddar sparat backtest-resultat.

    Args:
        name: Filnamn (utan .json).

    Returns:
        Dict med resultat, eller None om filen saknas.
    """
    path = BACKTEST_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Kunde inte ladda {path}: {e}")
        return None
