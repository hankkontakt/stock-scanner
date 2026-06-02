"""
strategy/base.py
================
Basramverk för strategier.

Definierar abstrakta basklassen Strategy, dataclass för resultat,
samt generella backtest- och parameter-sweep-funktioner.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd


# ── Dataclass för backtestresultat ─────────────────────────────────────────────

@dataclass
class StrategyResult:
    """Innehåller all utdata från en backtest."""
    signals: pd.Series
    """Tidsserie med signaler: 1=lång, 0=neutral, -1=kort"""
    positions: pd.Series
    """Tidsserie med positioner (antal aktier eller exponering)"""
    returns: pd.Series
    """Tidsserie med daglig portföljavkastning"""
    trades: pd.DataFrame
    """DataFrame med genomförda trades: entry_date, exit_date, direction, pnl"""
    metrics: dict
    """Prestandamått (Sharpe, CAGR, max DD, etc.)"""
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    """Kumulativ equity-kurva"""
    benchmark_returns: Optional[pd.Series] = None
    """Benchmark-avkastning för jämförelse"""


# ── Abstrakt basklass ──────────────────────────────────────────────────────────

class Strategy(ABC):
    """
    Abstrakt basklass för alla handelsstrategier.

    Subklasser måste implementera generate_signals() och calculate_metrics().
    """

    def __init__(self, name: str, params: dict = None):
        """
        name:   Strategins namn (visas i UI och rapporter)
        params: Dictionary med strategiparametrar
        """
        self.name = name
        self.params = params or {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        Generera handelssignaler från prisdata.

        data: DataFrame med prisdata (måste innehålla 'Close'-kolumn)
        Return: pd.Series med signaler: 1=lång, 0=neutral, -1=kort
        """
        pass

    @abstractmethod
    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        """
        Beräkna prestandamått från signaler och data.

        data:    DataFrame med prisdata
        signals: pd.Series med signaler
        Return:  dict med mått som Sharpe, CAGR, max drawdown m.m.
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', params={self.params})"


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _compute_returns(prices: pd.Series, signals: pd.Series) -> pd.Series:
    """
    Beräkna daglig portföljavkastning baserat på signaler.

    prices:  Pris-serie
    signals: Signal-serie (1, 0, -1)
    Return:  Daglig avkastning (shiftad för att undvika look-ahead)
    """
    daily_ret = prices.pct_change()
    # Shift:a signalen så att dagens position bygger på gårdagens signal
    pos = signals.shift(1).fillna(0)
    return pos * daily_ret


def _compute_equity_curve(strategy_returns: pd.Series) -> pd.Series:
    """Beräkna kumulativ equity-kurva från dagliga avkastningar."""
    return (1 + strategy_returns).cumprod()


def _compute_drawdown(equity: pd.Series) -> pd.Series:
    """Beräkna drawdown-serie från equity-kurva."""
    rolling_max = equity.cummax()
    return (equity - rolling_max) / rolling_max


def _locate_trades(signals: pd.Series, prices: pd.Series) -> pd.DataFrame:
    """
    Hitta alla genomförda trades baserat på signaländringar.

    signals: Signal-serie
    prices:  Pris-serie
    Return:  DataFrame med entry_date, exit_date, direction, entry_price, exit_price, pnl
    """
    # Signaländringar indikerar entry/exit
    signal_shift = signals.shift(1).fillna(0)
    entries = (signals != 0) & (signal_shift == 0)
    exits = (signals == 0) & (signal_shift != 0)

    entry_dates = entries[entries].index
    exit_dates = exits[exits].index

    trades = []
    for entry_date in entry_dates:
        direction = signals[entry_date]
        # Hitta närmaste exit efter entry
        future_exits = exit_dates[exit_dates > entry_date]
        if future_exits.empty:
            # Sista positionen hålls tills slutet
            exit_date = signals.index[-1]
        else:
            exit_date = future_exits[0]

        entry_price = prices.loc[entry_date]
        exit_price = prices.loc[exit_date]
        pnl = (exit_price / entry_price - 1) * direction

        trades.append({
            "entry_date": entry_date,
            "exit_date": exit_date,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
        })

    return pd.DataFrame(trades)


def _sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Annualiserad Sharpe ratio."""
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    return float(np.sqrt(periods_per_year) * excess.mean() / returns.std())


def _sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float:
    """Annualiserad Sortino ratio (straffar bara nedsida)."""
    if len(returns) < 2:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return 0.0
    return float(np.sqrt(periods_per_year) * excess.mean() / downside.std())


def _max_drawdown(equity: pd.Series) -> float:
    """Maximal drawdown i procent."""
    dd = _compute_drawdown(equity)
    return float(dd.min())


def _calmar_ratio(returns: pd.Series, equity: pd.Series, periods_per_year: int = 252) -> float:
    """Calmar ratio = CAGR / |Max DD|."""
    cagr = _cagr(returns, periods_per_year)
    mdd = abs(_max_drawdown(equity))
    return cagr / mdd if mdd > 0 else 0.0


def _cagr(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Compound Annual Growth Rate."""
    total = (1 + returns).prod()
    n_years = len(returns) / periods_per_year
    if n_years <= 0:
        return 0.0
    return float(total ** (1 / n_years) - 1)


def _win_rate(trades: pd.DataFrame) -> float:
    """Andel vinnande trades."""
    if trades.empty:
        return 0.0
    return float((trades["pnl"] > 0).mean())


def _profit_factor(trades: pd.DataFrame) -> float:
    """Profit factor = total vinst / total förlust."""
    if trades.empty:
        return 0.0
    total_win = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    total_loss = abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())
    return float(total_win / total_loss) if total_loss > 0 else float("inf")


def _avg_trade(trades: pd.DataFrame) -> float:
    """Genomsnittlig avkastning per trade."""
    if trades.empty:
        return 0.0
    return float(trades["pnl"].mean())


# ── Standardmått för strategier ────────────────────────────────────────────────

def standard_metrics(returns: pd.Series, equity: pd.Series, trades: pd.DataFrame,
                     risk_free_rate: float = 0.02) -> dict:
    """Beräkna standarduppsättning prestandamått."""
    return {
        "cagr": _cagr(returns),
        "sharpe": _sharpe_ratio(returns, risk_free_rate),
        "sortino": _sortino_ratio(returns, risk_free_rate),
        "calmar": _calmar_ratio(returns, equity),
        "max_drawdown": _max_drawdown(equity),
        "volatility": float(returns.std() * np.sqrt(252)),
        "win_rate": _win_rate(trades),
        "profit_factor": _profit_factor(trades),
        "avg_trade_pct": _avg_trade(trades),
        "total_return": float((1 + returns).prod() - 1),
        "n_trades": len(trades),
    }


# ── Huvudfunktioner ────────────────────────────────────────────────────────────

def run_backtest(strategy: Strategy, data: pd.DataFrame,
                 initial_capital: float = 100000.0,
                 risk_free_rate: float = 0.02) -> StrategyResult:
    """
    Kör en fullständig backtest för en given strategi.

    strategy:         Strategy-instans
    data:             DataFrame med prisdata (minst 'Close'-kolumn)
    initial_capital:  Startkapital
    risk_free_rate:   Riskfri ränta (för Sharpe m.m.)

    Return: StrategyResult med signaler, positions, returns, trades, metrics, equity_curve
    """
    # Generera signaler
    signals = strategy.generate_signals(data)

    # Beräkna daglig avkastning
    strategy_returns = _compute_returns(data["Close"], signals)
    strategy_returns = strategy_returns.fillna(0)

    # Equity-kurva
    equity = _compute_equity_curve(strategy_returns) * initial_capital

    # Trades
    trades = _locate_trades(signals, data["Close"])

    # Beräkna positionsstorlek (förenklad: allt kapital vid signal)
    positions = signals * (initial_capital / data["Close"])

    # Standard-mått
    metrics = standard_metrics(strategy_returns, equity, trades, risk_free_rate)

    # Låt strategin lägga till egna mått
    try:
        extra = strategy.calculate_metrics(data, signals)
        metrics.update(extra)
    except Exception:
        pass

    return StrategyResult(
        signals=signals,
        positions=positions,
        returns=strategy_returns,
        trades=trades,
        metrics=metrics,
        equity_curve=equity,
    )


def run_parameter_sweep(strategy_class: type, data: pd.DataFrame,
                         param_grid: dict[str, list],
                         scoring: str = "sharpe",
                         initial_capital: float = 100000.0) -> pd.DataFrame:
    """
    Grid search över parametrar.

    strategy_class:  Strategiklass (inte instans)
    data:            Prisdata
    param_grid:      Dict med parameter-namn -> lista av värden att testa
                     Ex: {"fast_ma": [20, 50, 100], "slow_ma": [100, 200]}
    scoring:         Vilket metric att optimera ("sharpe", "cagr", "sortino", "calmar")
    initial_capital: Startkapital

    Return: DataFrame med alla kombinationer och deras metrics
    """
    from itertools import product

    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    combinations = list(product(*param_values))

    results = []
    for combo in combinations:
        params = dict(zip(param_names, combo))
        try:
            strategy = strategy_class(name=f"grid_{combo}", params=params)
            result = run_backtest(strategy, data, initial_capital)
            metrics = result.metrics
            row = {**params, **metrics}
            results.append(row)
        except Exception as e:
            results.append({**params, "error": str(e)})

    df = pd.DataFrame(results)
    if scoring in df.columns:
        df = df.sort_values(scoring, ascending=False)
    return df
