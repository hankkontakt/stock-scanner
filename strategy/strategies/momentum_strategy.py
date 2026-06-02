"""
strategy/strategies/momentum_strategy.py
=========================================
Momentumstrategier.

Innehåller:
- TimeSeriesMomentum: tidsserie-momentum (absolut momentum)
- CrossSectionalMomentum: relativ styrka mellan aktier
- DualMomentum: kombinerar absolut och relativt momentum
- SeasonalityStrategy: kalendereffekter
"""

import numpy as np
import pandas as pd

from strategy.base import Strategy, standard_metrics, _locate_trades, _compute_returns, _compute_equity_curve


class TimeSeriesMomentum(Strategy):
    """
    Tidsserie-momentum.
    Köp om avkastningen över lookback-perioden är positiv, annars kort (eller neutral).

    Parametrar:
        lookback:  Antal dagar för momentumberäkning (default 252 = 1 år)
        hold:      Antal dagar att hålla positionen (default 63 = 3 mån)
        use_binary: True = 1/0/-1 signal, False = kontinuerlig vikt
    """

    def __init__(self, name="TimeSeriesMomentum", params=None):
        params = params or {}
        params.setdefault("lookback", 252)
        params.setdefault("hold", 63)
        params.setdefault("use_binary", True)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        lookback = self.params["lookback"]
        hold = self.params["hold"]

        # Avkastning över lookback-perioden
        ret = close.pct_change(lookback)

        # Binär signal: 1 om positiv, -1 om negativ, 0 om ingen data
        if self.params["use_binary"]:
            signals = pd.Series(0, index=close.index)
            signals[ret > 0] = 1
            signals[ret < 0] = -1
        else:
            signals = ret.fillna(0)

        # Applicera hållperiod: signalen ändras bara var 'hold':e dag
        if hold > 1:
            idx = range(0, len(signals), hold)
            hold_signals = signals.iloc[idx]
            # Fyll framåt
            signals = hold_signals.reindex(signals.index, method="ffill").fillna(0)

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class CrossSectionalMomentum(Strategy):
    """
    Relativ styrka (cross-sectional momentum).
    Jämför avkastning mellan aktier och väljer topp-X%.

    OBS: Denna strategi förväntar sig en multi-kolumn DataFrame med priser för flera aktier.
    Alternativt kan den appliceras på en DataFrame med 'Close' + 'sector' eller liknande.

    Parametrar:
        lookback:  Antal dagar för momentumberäkning (default 252)
        top_pct:   Andel aktier att välja (default 0.2 = 20%)
    """

    def __init__(self, name="CrossSectionalMomentum", params=None):
        params = params or {}
        params.setdefault("lookback", 252)
        params.setdefault("top_pct", 0.2)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        lookback = self.params["lookback"]
        top_pct = self.params["top_pct"]

        # Om data har flera kolumner (multi-asset)
        if isinstance(close, pd.DataFrame) and close.shape[1] > 1:
            return self._multi_asset_signals(close, lookback, top_pct)

        # Single asset: förenklad signal baserad på percentil inom rullande fönster
        ret = close.pct_change(lookback)
        # Ranka inom rullande fönster på 252 dagar
        rolling_rank = ret.rolling(window=252).rank(pct=True)
        signals = pd.Series(0, index=close.index)
        signals[rolling_rank > (1 - top_pct)] = 1
        signals[rolling_rank < top_pct] = -1
        return signals

    def _multi_asset_signals(self, prices: pd.DataFrame, lookback: int, top_pct: float) -> pd.Series:
        """Generera signaler för multi-asset DataFrame."""
        # Beräkna avkastning för varje kolumn
        rets = prices.pct_change(lookback).iloc[-1]

        # Välj topp och botten
        n_top = max(1, int(len(rets) * top_pct))
        top_assets = rets.nlargest(n_top).index.tolist()
        bottom_assets = rets.nsmallest(n_top).index.tolist()

        # Skapa en signal-serie för datumindexet
        signals = pd.Series(0.0, index=prices.index)
        signals[:] = 0.0
        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class DualMomentum(Strategy):
    """
    Dual Momentum (Antonacci).
    1. Absolut momentum: hoppa till riskfri tillgång om totalavkastningen är negativ
    2. Relativt momentum: välj den bäst presterande tillgången

    Parametrar:
        absolute_lookback:  Lookback för absolut momentum (default 252)
        relative_lookback:  Lookback för relativt momentum (default 126)
    """

    def __init__(self, name="DualMomentum", params=None):
        params = params or {}
        params.setdefault("absolute_lookback", 252)
        params.setdefault("relative_lookback", 126)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        abs_lookback = self.params["absolute_lookback"]
        rel_lookback = self.params["relative_lookback"]

        # Förenklad dual momentum för enstaka tillgång
        abs_ret = close.pct_change(abs_lookback)
        rel_ret = close.pct_change(rel_lookback)

        signals = pd.Series(0, index=close.index)
        # Absolut momentum måste vara positivt
        abs_positive = abs_ret > 0
        # Relativt momentum = egen avkastning (jämför med sig själv över kortare tid)
        rel_positive = rel_ret > abs_ret.shift(1)

        signals[abs_positive & rel_positive] = 1
        signals[abs_positive & ~rel_positive] = 0  # neutral istället för kort
        signals[~abs_positive] = 0  # gå till kontanter

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class SeasonalityStrategy(Strategy):
    """
    Säsongsstrategi baserad på kalendereffekter.

    Parametrar:
        month_effect:  Handla månadseffekter (t.ex. "sell in May", "January effect")
        day_of_week:   Handla veckodagseffekter (t.ex. Monday effect)
        long_months:   Lista med månader att vara lång (default [1, 3, 4, 11, 12])
        short_months:  Lista med månader att vara kort (default [5, 6, 7, 8, 9])
        long_days:     Lista med veckodagar att vara lång (default [4, 5] = tors-fre)
        short_days:    Lista med veckodagar att vara kort (default [1] = mån)
    """

    def __init__(self, name="SeasonalityStrategy", params=None):
        params = params or {}
        params.setdefault("month_effect", True)
        params.setdefault("day_of_week", True)
        params.setdefault("long_months", [1, 3, 4, 11, 12])
        params.setdefault("short_months", [5, 6, 7, 8, 9])
        params.setdefault("long_days", [4, 5])
        params.setdefault("short_days", [1])
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        signals = pd.Series(0.0, index=close.index)

        if self.params.get("month_effect"):
            month = close.index.month
            signals[month.isin(self.params["long_months"])] += 0.5
            signals[month.isin(self.params["short_months"])] -= 0.5

        if self.params.get("day_of_week"):
            weekday = close.index.weekday
            signals[weekday.isin(self.params["long_days"])] += 0.5
            signals[weekday.isin(self.params["short_days"])] -= 0.5

        # Normalisera till -1, 0, 1
        signals[signals > 0] = 1
        signals[signals < 0] = -1
        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}
