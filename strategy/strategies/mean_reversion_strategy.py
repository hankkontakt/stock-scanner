"""
strategy/strategies/mean_reversion_strategy.py
===============================================
Mean-reversionsstrategier.

Innehåller:
- BollingerMeanReversion: Bollinger Bands reversal
- RSIMeanReversion: RSI-baserad reversal
- PairsTrading: Pairs trading med z-score
- MovingAverageCrossover: MA-korsning
- MACDStrategy: MACD-korsning
"""

import numpy as np
import pandas as pd

from strategy.base import Strategy


class BollingerMeanReversion(Strategy):
    """
    Bollinger Bands mean reversion.
    Köp när priset slår nedre bandet, sälj när det slår övre bandet.

    Parametrar:
        period:  Glidande medelvärde-period (default 20)
        std_dev: Antal standardavvikelser för banden (default 2)
    """

    def __init__(self, name="BollingerMeanReversion", params=None):
        params = params or {}
        params.setdefault("period", 20)
        params.setdefault("std_dev", 2)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        period = self.params["period"]
        std_dev = self.params["std_dev"]

        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = sma + std_dev * std
        lower = sma - std_dev * std

        signals = pd.Series(0, index=close.index)
        # Köp när priset slår under nedre bandet (överköpt på nedsidan -> reversal upp)
        signals[close <= lower] = 1
        # Kort när priset slår över övre bandet
        signals[close >= upper] = -1

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class RSIMeanReversion(Strategy):
    """
    RSI-baserad mean reversion.
    Köp när RSI är under oversold, sälj när RSI är över overbought.

    Parametrar:
        rsi_period:  RSI-period (default 14)
        oversold:    Nivå för överköpt på nedsidan (default 30)
        overbought:  Nivå för överköpt (default 70)
    """

    def __init__(self, name="RSIMeanReversion", params=None):
        params = params or {}
        params.setdefault("rsi_period", 14)
        params.setdefault("oversold", 30)
        params.setdefault("overbought", 70)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        period = self.params["rsi_period"]
        oversold = self.params["oversold"]
        overbought = self.params["overbought"]

        # RSI-beräkning
        delta = close.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()

        # Wilder's smoothing
        for i in range(period, len(avg_gain)):
            avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
            avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))

        signals = pd.Series(0, index=close.index)
        signals[rsi < oversold] = 1
        signals[rsi > overbought] = -1

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class PairsTrading(Strategy):
    """
    Pairs trading med z-score.
    Handlar spreaden mellan två cointgrerade tillgångar.

    Parametrar:
        entry_zscore:  Z-score-tröskel för entry (default 2.0)
        exit_zscore:   Z-score-tröskel för exit (default 0.5)
        lookback:      Lookback för regression (default 60)
        hedge_ratio:   Fix hedge ratio, eller None för OLS-estimering
    """

    def __init__(self, name="PairsTrading", params=None):
        params = params or {}
        params.setdefault("entry_zscore", 2.0)
        params.setdefault("exit_zscore", 0.5)
        params.setdefault("lookback", 60)
        params.setdefault("hedge_ratio", None)
        params.setdefault("asset_a", "")
        params.setdefault("asset_b", "")
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        asset_a = self.params.get("asset_a")
        asset_b = self.params.get("asset_b")

        # Multi-asset: om DataFrame har kolumner med namn
        if isinstance(close, pd.DataFrame) and asset_a and asset_b:
            if asset_a in close.columns and asset_b in close.columns:
                prices_a = close[asset_a]
                prices_b = close[asset_b]
            else:
                # Första två kolumner
                prices_a = close.iloc[:, 0]
                prices_b = close.iloc[:, 1]
        else:
            # Single asset: skapa artificiell spread via differens
            prices_a = close
            prices_b = close.shift(1)  # placeholders

        lookback = self.params["lookback"]
        entry_z = self.params["entry_zscore"]
        exit_z = self.params["exit_zscore"]

        signals = pd.Series(0, index=close.index)

        for i in range(lookback, len(close)):
            hist_a = prices_a.iloc[i - lookback:i]
            hist_b = prices_b.iloc[i - lookback:i]

            if len(hist_a) < lookback or len(hist_b) < lookback:
                continue

            # Beräkna spread
            if self.params.get("hedge_ratio"):
                hr = self.params["hedge_ratio"]
            else:
                # Enkel OLS: price_a ~ price_b
                A = np.vstack([hist_b.values, np.ones(len(hist_b))]).T
                hr, _ = np.linalg.lstsq(A, hist_a.values, rcond=None)[0]

            spread = hist_a.values - hr * hist_b.values
            z_score = (spread[-1] - np.mean(spread)) / np.std(spread) if np.std(spread) > 0 else 0

            if z_score > entry_z:
                signals.iloc[i] = -1  # Kort spreaden (kort A, lång B)
            elif z_score < -entry_z:
                signals.iloc[i] = 1   # Lång spreaden (lång A, kort B)
            elif abs(z_score) < exit_z:
                signals.iloc[i] = 0   # Exit
            else:
                signals.iloc[i] = signals.iloc[i - 1] if i > 0 else 0

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class MovingAverageCrossover(Strategy):
    """
    Moving Average Crossover.
    Köp när snabbt MA korsar över långsamt MA, sälj vid motsatt korsning.

    Parametrar:
        fast:  Snabbt MA-period (default 20)
        slow:  Långsamt MA-period (default 50)
    """

    def __init__(self, name="MovingAverageCrossover", params=None):
        params = params or {}
        params.setdefault("fast", 20)
        params.setdefault("slow", 50)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        fast = self.params["fast"]
        slow = self.params["slow"]

        ma_fast = close.rolling(fast).mean()
        ma_slow = close.rolling(slow).mean()

        signals = pd.Series(0, index=close.index)
        signals[ma_fast > ma_slow] = 1
        signals[ma_fast < ma_slow] = -1

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class MACDStrategy(Strategy):
    """
    MACD (Moving Average Convergence Divergence) crossover.
    Köp när MACD-linjen korsar över signal-linjen.

    Parametrar:
        fast:    Snabbt EMA-period (default 12)
        slow:    Långsamt EMA-period (default 26)
        signal:  Signal-period (default 9)
    """

    def __init__(self, name="MACDStrategy", params=None):
        params = params or {}
        params.setdefault("fast", 12)
        params.setdefault("slow", 26)
        params.setdefault("signal", 9)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        fast = self.params["fast"]
        slow = self.params["slow"]
        signal = self.params["signal"]

        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        signals = pd.Series(0, index=close.index)
        signals[histogram > 0] = 1
        signals[histogram < 0] = -1

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}
