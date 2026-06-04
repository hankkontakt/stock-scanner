"""
core/ml_features.py
====================
A4-split: Feature engineering för MarketScan ML-modellen.

Extraherade från core/ml_predictor.py som ett led i att bryta upp monoliten.
Innehåller alla feature-beräkningsfunktioner:
- Tekniska indikatorer (RSI, MACD, Hurst, serial correlation etc.)
- compute_features_at() — huvudfunktionen för feature-extraktion

Backward compat: ml_predictor.py re-importerar allt härifrån.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _rsi(close: pd.Series, period: int = 14) -> float:
    """Beräkna RSI (Relative Strength Index)."""
    if len(close) < period + 1:
        return float("nan")
    delta = close.diff().dropna()
    up = delta.where(delta > 0, 0.0)
    down = -delta.where(delta < 0, 0.0)
    avg_up = up.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    avg_dn = down.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if avg_dn == 0:
        return 100.0
    rs = avg_up / avg_dn
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> float:
    """Beräkna MACD-histogram (MACD - signal)."""
    if len(close) < slow + sig:
        return float("nan")
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal = macd_line.ewm(span=sig, adjust=False).mean()
    return float((macd_line - signal).iloc[-1])


def _log_return(close: pd.Series, days: int) -> float:
    """Log-avkastning för N dagar tillbaka."""
    if len(close) < days + 1:
        return float("nan")
    return float(np.log(close.iloc[-1] / close.iloc[-days - 1]))


def _hurst_exponent(close: pd.Series, min_n: int = 60) -> float:
    """Beräkna Hurst-exponenten (persistens vs. mean-reversion)."""
    n = len(close)
    if n < min_n:
        return float("nan")
    log_prices = np.log(close.values)
    lags = [2, 4, 8, 16, 32]
    rs_vals = []
    for lag in lags:
        if lag >= n:
            continue
        chunks = [log_prices[i:i + lag] for i in range(0, n - lag, lag)]
        if not chunks:
            continue
        rs_chunk = []
        for chunk in chunks:
            mean = np.mean(chunk)
            dev = np.cumsum(chunk - mean)
            r = np.max(dev) - np.min(dev)
            s = np.std(chunk)
            if s > 1e-10:
                rs_chunk.append(r / s)
        if rs_chunk:
            rs_vals.append((np.log(lag), np.log(np.mean(rs_chunk))))
    if len(rs_vals) < 3:
        return float("nan")
    x, y = zip(*rs_vals)
    h = np.polyfit(x, y, 1)[0]
    return float(np.clip(h, 0.0, 1.0))


def _serial_corr(close: pd.Series, lag: int = 1) -> float:
    """Seriell autokorrelation för daglig avkastning."""
    if len(close) < lag + 2:
        return float("nan")
    returns = close.pct_change().dropna()
    if len(returns) < lag + 2:
        return float("nan")
    corr = returns.autocorr(lag=lag)
    return float(corr) if not np.isnan(corr) else 0.0


def _volume_price_corr(close: pd.Series, volume: Optional[pd.Series],
                        days: int = 20) -> float:
    """Korrelation mellan pris och volym (20 dagar)."""
    if volume is None or len(close) < days or len(volume) < days:
        return float("nan")
    c = close.iloc[-days:]
    v = volume.iloc[-days:]
    if c.std() < 1e-10 or v.std() < 1e-10:
        return 0.0
    corr = c.corr(v)
    return float(corr) if not np.isnan(corr) else 0.0


def _max_drawdown(close: pd.Series, days: int = 60) -> float:
    """Maximal drawdown under de senaste N dagarna."""
    if len(close) < days:
        return float("nan")
    sub = close.iloc[-days:]
    peak = sub.expanding().max()
    drawdown = (sub - peak) / peak
    return float(drawdown.min())


def compute_features_at(close: pd.Series, volume: Optional[pd.Series]) -> dict:
    """Beräkna ML-features för en aktie.

    Returnerar dict med alla features (eller NaN om data saknas).
    Kallas per ticker vid träning och inference.
    """
    feat: dict = {}

    if close is None or len(close) < 5:
        return feat

    # ── Momentum/returner ──────────────────────────────────────────────────
    for days in [5, 10, 20, 60, 120, 252]:
        feat[f"ret_{days}d"] = _log_return(close, days)

    # ── Tekniska indikatorer ───────────────────────────────────────────────
    feat["rsi_14"] = _rsi(close, 14)
    feat["rsi_7"] = _rsi(close, 7)
    feat["macd_hist"] = _macd_hist(close)

    # ── Volatilitet ────────────────────────────────────────────────────────
    returns = close.pct_change().dropna()
    if len(returns) >= 20:
        feat["vol_20d"] = float(returns.iloc[-20:].std() * np.sqrt(252))
    if len(returns) >= 60:
        feat["vol_60d"] = float(returns.iloc[-60:].std() * np.sqrt(252))

    # ── Avancerade features ────────────────────────────────────────────────
    feat["hurst"] = _hurst_exponent(close)
    feat["serial_corr_1"] = _serial_corr(close, 1)
    feat["serial_corr_5"] = _serial_corr(close, 5)
    feat["max_dd_60d"] = _max_drawdown(close, 60)

    # ── Volym ──────────────────────────────────────────────────────────────
    if volume is not None and len(volume) >= 20:
        feat["vol_price_corr_20d"] = _volume_price_corr(close, volume, 20)
        v20 = volume.iloc[-20:].mean()
        v5 = volume.iloc[-5:].mean()
        feat["vol_ratio_5_20"] = float(v5 / v20) if v20 > 0 else float("nan")

    # ── Positionering ──────────────────────────────────────────────────────
    if len(close) >= 200:
        ma50 = close.iloc[-50:].mean()
        ma200 = close.iloc[-200:].mean()
        price = close.iloc[-1]
        feat["above_ma50"] = float(price > ma50)
        feat["above_ma200"] = float(price > ma200)
        if ma200 > 0:
            feat["ma50_vs_ma200"] = float(ma50 / ma200 - 1)

    # ── 52-veckors high/low ────────────────────────────────────────────────
    if len(close) >= 252:
        hi52 = close.iloc[-252:].max()
        lo52 = close.iloc[-252:].min()
        price = close.iloc[-1]
        if hi52 > 0:
            feat["pct_from_52w_high"] = float(price / hi52 - 1)
        if lo52 > 0:
            feat["pct_from_52w_low"] = float(price / lo52 - 1)

    return feat
