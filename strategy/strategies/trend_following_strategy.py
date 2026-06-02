"""
strategy/strategies/trend_following_strategy.py
===============================================
Trendföljningsstrategier.

Innehåller:
- TrendFollowing: Trendföljning med MA-korsning + ADX-filter
- DonchianBreakout: Donchian-kanal breakout
- SupertrendStrategy: Supertrend-indikator
- ParabolicSARStrategy: Parabolic SAR
"""

import numpy as np
import pandas as pd

from strategy.base import Strategy


class TrendFollowing(Strategy):
    """
    Trendföljning med glidande medelvärden och ADX-filter.
    Endast lång i starka trender (ADX > filter_adx).

    Parametrar:
        fast_ma:    Snabbt MA (default 50)
        slow_ma:    Långsamt MA (default 200)
        filter_adx: Minsta ADX för att vara i trend (default 25)
    """

    def __init__(self, name="TrendFollowing", params=None):
        params = params or {}
        params.setdefault("fast_ma", 50)
        params.setdefault("slow_ma", 200)
        params.setdefault("filter_adx", 25)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        high = data.get("High", close)
        low = data.get("Low", close)
        fast = self.params["fast_ma"]
        slow = self.params["slow_ma"]
        filter_adx = self.params["filter_adx"]

        # MA-signal
        ma_fast = close.rolling(fast).mean()
        ma_slow = close.rolling(slow).mean()
        ma_signal = pd.Series(0, index=close.index)
        ma_signal[ma_fast > ma_slow] = 1

        # ADX-beräkning
        adx = self._compute_adx(high, low, close, period=14)

        # Kombinera: endast lång när ADX > tröskel
        signals = pd.Series(0, index=close.index)
        signals[(ma_signal == 1) & (adx > filter_adx)] = 1
        # Kort när MA är bear och ADX > tröskel
        signals[(ma_signal == -1) & (adx > filter_adx)] = -1

        return signals

    def _compute_adx(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Beräkna Average Directional Index."""
        high_low = high - low
        high_close = (high - close.shift(1)).abs()
        low_close = (low - close.shift(1)).abs()

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()

        # +DM och -DM
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = pd.Series(0.0, index=close.index)
        minus_dm = pd.Series(0.0, index=close.index)
        plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
        minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

        plus_di = 100 * plus_dm.rolling(period).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.rolling(period).mean() / atr.replace(0, np.nan)

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(period).mean()

        return adx.fillna(0)

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class DonchianBreakout(Strategy):
    """
    Donchian-kanal breakout.
    Köp när priset slår över entry_period-högsta, sälj när det slår under exit_period-lägsta.

    Parametrar:
        entry_period: Period för entry breakout (default 20)
        exit_period:  Period för exit breakout (default 10)
    """

    def __init__(self, name="DonchianBreakout", params=None):
        params = params or {}
        params.setdefault("entry_period", 20)
        params.setdefault("exit_period", 10)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        high = data.get("High", close)
        low = data.get("Low", close)
        entry_period = self.params["entry_period"]
        exit_period = self.params["exit_period"]

        # Donchian-kanal
        upper = high.rolling(entry_period).max()
        lower = low.rolling(entry_period).min()
        exit_upper = high.rolling(exit_period).max()
        exit_lower = low.rolling(exit_period).min()

        signals = pd.Series(0, index=close.index)

        # Entry-signaler
        long_entry = close > upper.shift(1)
        short_entry = close < lower.shift(1)

        # Exit-signaler
        long_exit = close < exit_lower.shift(1)
        short_exit = close > exit_upper.shift(1)

        # Applicera logik: behåll position tills exit
        position = 0
        for i in range(1, len(signals)):
            if position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1
            elif position == 1 and long_exit.iloc[i]:
                position = 0
            elif position == -1 and short_exit.iloc[i]:
                position = 0
            signals.iloc[i] = position

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class SupertrendStrategy(Strategy):
    """
    Supertrend-indikator.
    Köp/sälj baserat på ATR-justerade band.

    Parametrar:
        atr_period:  ATR-period (default 10)
        multiplier:  Multiplikator för ATR (default 3)
    """

    def __init__(self, name="SupertrendStrategy", params=None):
        params = params or {}
        params.setdefault("atr_period", 10)
        params.setdefault("multiplier", 3)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        high = data.get("High", close)
        low = data.get("Low", close)
        period = self.params["atr_period"]
        multiplier = self.params["multiplier"]

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()

        # Grundläggande band
        hl_avg = (high + low) / 2
        upper_band = hl_avg + multiplier * atr
        lower_band = hl_avg - multiplier * atr

        # Supertrend-logik
        supertrend = pd.Series(1, index=close.index)  # 1 = upp, -1 = ned
        final_upper = upper_band.copy()
        final_lower = lower_band.copy()

        for i in range(1, len(close)):
            # Justera band beroende på föregående trend
            if supertrend.iloc[i - 1] == 1:
                final_lower.iloc[i] = max(lower_band.iloc[i], final_lower.iloc[i - 1])
                if close.iloc[i] < final_lower.iloc[i]:
                    supertrend.iloc[i] = -1
            else:
                final_upper.iloc[i] = min(upper_band.iloc[i], final_upper.iloc[i - 1])
                if close.iloc[i] > final_upper.iloc[i]:
                    supertrend.iloc[i] = 1

        return supertrend

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class ParabolicSARStrategy(Strategy):
    """
    Parabolic SAR (Stop and Reverse).
    Köp när PSAR är under priset (upptrend), sälj när PSAR är över priset (nedtrend).

    Parametrar:
        start: Start-acceleration (default 0.02)
        increment: Accelerationssteg (default 0.02)
        max: Max acceleration (default 0.2)
    """

    def __init__(self, name="ParabolicSARStrategy", params=None):
        params = params or {}
        params.setdefault("start", 0.02)
        params.setdefault("increment", 0.02)
        params.setdefault("max", 0.2)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        high = data.get("High", close)
        low = data.get("Low", close)
        start = self.params["start"]
        increment = self.params["increment"]
        max_accel = self.params["max"]

        # Förenklad PSAR-beräkning
        psar = close.copy()
        af = start
        trend = 1  # 1 = upp, -1 = ned
        ep = high.iloc[0]  # extreme point
        psar.iloc[0] = low.iloc[0]

        for i in range(1, len(close)):
            if trend == 1:
                psar.iloc[i] = psar.iloc[i - 1] + af * (ep - psar.iloc[i - 1])
                if high.iloc[i] > ep:
                    ep = high.iloc[i]
                    af = min(af + increment, max_accel)
                if low.iloc[i] < psar.iloc[i]:
                    trend = -1
                    psar.iloc[i] = ep
                    ep = low.iloc[i]
                    af = start
            else:
                psar.iloc[i] = psar.iloc[i - 1] + af * (ep - psar.iloc[i - 1])
                if low.iloc[i] < ep:
                    ep = low.iloc[i]
                    af = min(af + increment, max_accel)
                if high.iloc[i] > psar.iloc[i]:
                    trend = 1
                    psar.iloc[i] = ep
                    ep = high.iloc[i]
                    af = start

        # Signaler: 1 när pris > psar (upptrend), -1 när pris < psar (nedtrend)
        signals = pd.Series(0, index=close.index)
        signals[close > psar] = 1
        signals[close < psar] = -1

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}
