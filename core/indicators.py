
"""
indicators.py — Gemensamma tekniska indikatorer.
Centraliserar ATR, RSI, EMA och andra indikatorer som tidigare
fanns duplicerade i portfolio.py, portfolio/portfolio.py, portfolio/paper_trading.py m.fl.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def calc_atr(ticker: str, period: int = 14, timeout: int = 15) -> Optional[float]:
    """
    Berakna Average True Range for en ticker.

    Args:
        ticker: Tickersymbol.
        period: Rullande period for ATR (default 14).
        timeout: Max sekunder for yfinance-anrop.

    Returns:
        ATR-varde (float) eller None om data saknas.
    """
    try:
        hist = yf.Ticker(ticker).history(period=f"{max(period * 2, 30)}d", timeout=timeout)
        if hist.empty or len(hist) < period + 1:
            return None

        high = hist["High"]
        low = hist["Low"]
        close = hist["Close"]

        tr = pd.concat([
            (high - low).abs(),
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)

        atr = tr.rolling(period).mean().iloc[-1]
        return round(float(atr), 4)
    except Exception:
        return None


def calc_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    """Berakna RSI for en slutspris-serie."""
    if close.empty or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)


def calc_sma(close: pd.Series, period: int) -> Optional[float]:
    """Berakna enkelt glidande medelvarde."""
    if close.empty or len(close) < period:
        return None
    return float(close.rolling(period).mean().iloc[-1])


def calc_ema(close: pd.Series, period: int) -> Optional[float]:
    """Berakna exponentiellt glidande medelvarde."""
    if close.empty or len(close) < period:
        return None
    return float(close.ewm(span=period, adjust=False).mean().iloc[-1])
