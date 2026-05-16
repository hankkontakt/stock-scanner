"""Tester för core/data_fetcher.py."""
import pandas as pd
import pytest

from core.data_fetcher import _calc_rsi


def test_rsi_flat_prices_returns_neutral():
    """Helt platta priser (ingen rörelse) ska ge neutral RSI = 50, inte 100."""
    prices = pd.Series([100.0] * 30)
    rsi = _calc_rsi(prices, period=14)
    assert rsi == 50.0


def test_rsi_only_gains_returns_100():
    """Bara uppgång ska ge RSI = 100."""
    prices = pd.Series([100.0 + i for i in range(30)])
    rsi = _calc_rsi(prices, period=14)
    assert rsi == 100.0


def test_rsi_only_losses_returns_low():
    """Bara nedgång ska ge RSI nära 0."""
    prices = pd.Series([100.0 - i for i in range(30)])
    rsi = _calc_rsi(prices, period=14)
    assert rsi is not None
    assert rsi < 5.0


def test_rsi_too_few_prices_returns_none():
    """Färre priser än period+1 ska ge None."""
    prices = pd.Series([100.0, 101.0, 102.0])
    rsi = _calc_rsi(prices, period=14)
    assert rsi is None


def test_rsi_mixed_in_valid_range():
    """Blandad data ska ge ett RSI mellan 0 och 100."""
    prices = pd.Series([100.0, 102.0, 101.0, 103.0, 102.5, 104.0,
                        103.0, 105.0, 104.5, 106.0, 105.0, 107.0,
                        106.5, 108.0, 107.0, 109.0])
    rsi = _calc_rsi(prices, period=14)
    assert rsi is not None
    assert 0.0 <= rsi <= 100.0
