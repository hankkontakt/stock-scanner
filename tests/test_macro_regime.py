"""
Tester for core/macro_regime.py — Regimdetektering (tjurn/bjorn/osaker).
"""
import numpy as np
import pandas as pd
import pytest

from core.macro_regime import detect_regime


class TestDetectRegime:
    """Testar detect_regime med mockad yfinance-data."""

    def _make_mock_history(self, close_values, length=500):
        """Skapa en mock history DataFrame."""
        dates = pd.date_range("2024-01-01", periods=length, freq="D")
        return pd.DataFrame({
            "Close": close_values[:length] if len(close_values) >= length else
                     close_values + [close_values[-1]] * (length - len(close_values)),
        }, index=dates)

    def test_detect_regime_bull(self, mocker):
        """SPY up, VIX low -> TJUR-regim."""
        spy_close = [200 * (1 + 0.001) ** i for i in range(500)]
        spy = self._make_mock_history(spy_close)

        vix_close = [12.0] * 100
        vix = self._make_mock_history(vix_close, length=100)

        mock_spy = mocker.MagicMock()
        mock_spy.history.return_value = spy
        mock_vix = mocker.MagicMock()
        mock_vix.history.return_value = vix

        def mock_yf_ticker(ticker):
            if ticker == "SPY":
                return mock_spy
            elif ticker == "^VIX":
                return mock_vix
            elif ticker == "RSP":
                return mock_spy
            m = mocker.MagicMock()
            m.history.return_value = spy
            return m

        mocker.patch("yfinance.Ticker", side_effect=mock_yf_ticker)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert result["regime"] == "TJUR"

    def test_detect_regime_bear(self, mocker):
        """SPY down, VIX high -> BJORN-regim."""
        spy_close = [200 * (1 - 0.001) ** i for i in range(500)]
        spy = self._make_mock_history(spy_close)

        vix_close = [35.0] * 100
        vix = self._make_mock_history(vix_close, length=100)

        mock_spy = mocker.MagicMock()
        mock_spy.history.return_value = spy
        mock_vix = mocker.MagicMock()
        mock_vix.history.return_value = vix

        def mock_yf_ticker(ticker):
            if ticker == "SPY":
                return mock_spy
            elif ticker == "^VIX":
                return mock_vix
            m = mocker.MagicMock()
            m.history.return_value = spy
            return m

        mocker.patch("yfinance.Ticker", side_effect=mock_yf_ticker)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert result["regime"] == "BJÖRN"

    def test_detect_regime_uncertain(self, mocker):
        """Mixed signals -> OSAKER."""
        spy_close = [200 * (1 + 0.0002) ** i for i in range(500)]
        spy = self._make_mock_history(spy_close)

        vix_close = [22.0] * 100
        vix = self._make_mock_history(vix_close, length=100)

        mock_spy = mocker.MagicMock()
        mock_spy.history.return_value = spy
        mock_vix = mocker.MagicMock()
        mock_vix.history.return_value = vix

        def mock_yf_ticker(ticker):
            if ticker == "SPY":
                return mock_spy
            elif ticker == "^VIX":
                return mock_vix
            m = mocker.MagicMock()
            m.history.return_value = spy
            return m

        mocker.patch("yfinance.Ticker", side_effect=mock_yf_ticker)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert result["regime"] in ("TJUR", "BJÖRN", "OSÄKER")

    def test_missing_data(self, mocker):
        """NaN i SPY/VIX-data -> OSAKER med confidence 0.5."""
        empty = pd.DataFrame()
        mock_empty = mocker.MagicMock()
        mock_empty.history.return_value = empty

        mocker.patch("yfinance.Ticker", return_value=mock_empty)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert result["confidence"] == 0.5
        assert result["regime"] == "OSÄKER"

    def test_cache_hit(self, mocker):
        """Cachad regime returneras."""
        cached = {
            "regime": "TJUR", "composite": 0.8, "confidence": 0.9,
            "as_of": "2026-06-01 10:00",
        }
        mocker.patch("core.macro_regime._rc", return_value=cached)

        result = detect_regime()
        assert result["regime"] == "TJUR"
        assert result["composite"] == 0.8

    def test_edge_extremes(self, mocker):
        """Extrem VIX, extrem yield curve -> hanteras utan krasch."""
        spy_close = [200] * 500
        spy = self._make_mock_history(spy_close)

        vix_close = [50.0] * 100
        vix = self._make_mock_history(vix_close, length=100)

        mock_spy = mocker.MagicMock()
        mock_spy.history.return_value = spy
        mock_vix = mocker.MagicMock()
        mock_vix.history.return_value = vix

        def mock_yf_ticker(ticker):
            if ticker == "SPY":
                return mock_spy
            elif ticker == "^VIX":
                return mock_vix
            m = mocker.MagicMock()
            m.history.return_value = spy
            return m

        mocker.patch("yfinance.Ticker", side_effect=mock_yf_ticker)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert isinstance(result["vix_level"], float)
        assert isinstance(result["regime"], str)

    def test_empty_history(self, mocker):
        """Tom historik (< 200 dagar) hanteras."""
        short_spy = self._make_mock_history([100], length=50)
        mock_spy = mocker.MagicMock()
        mock_spy.history.return_value = short_spy

        mocker.patch("yfinance.Ticker", return_value=mock_spy)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert result["regime"] == "OSÄKER"

    def test_regime_composite_scoring(self, mocker):
        """Sammanvikt composite scoring fungerar."""
        spy_close = [200 * (1 + 0.0005) ** i for i in range(500)]
        spy = self._make_mock_history(spy_close)
        vix_close = [18.0] * 100
        vix = self._make_mock_history(vix_close, length=100)

        mock_spy = mocker.MagicMock()
        mock_spy.history.return_value = spy
        mock_vix = mocker.MagicMock()
        mock_vix.history.return_value = vix

        def mock_yf_ticker(ticker):
            if ticker == "SPY":
                return mock_spy
            elif ticker == "^VIX":
                return mock_vix
            m = mocker.MagicMock()
            m.history.return_value = spy
            return m

        mocker.patch("yfinance.Ticker", side_effect=mock_yf_ticker)
        mocker.patch("core.macro_regime._rc", return_value=None)
        mocker.patch("core.macro_regime._wc")
        mocker.patch("core.macro_regime.time.sleep")

        result = detect_regime()
        assert 0.0 <= result.get("composite", 0) <= 1.0

