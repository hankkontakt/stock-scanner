"""
Tester for core/extra_data.py — Insiders, earnings, analyst revisions, short interest, seasonality, options.
"""
import numpy as np
import pandas as pd
import pytest

from core.extra_data import (
    fetch_insider_signal,
    fetch_earnings_surprise_signal,
    fetch_analyst_revision_signal,
    fetch_short_interest_signal,
    fetch_seasonality_signal,
    fetch_options_flow_signal,
)


class TestFetchInsiderTransactions:
    """Testar fetch_insider_signal."""

    def test_fetch_insider_transactions(self, mocker):
        """Mockad insiderhamtning returnerar signal mellan 0-1."""
        mock_ticker = mocker.MagicMock()
        df = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "Transaction": ["Buy", "Buy", "Sale", "Buy", "Sale"],
            "Shares": [1000, 2000, 500, 1500, 300],
        })
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        mock_ticker.insider_transactions = df
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_insider_signal("AAPL")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_insider_empty(self, mocker):
        """Tom insider-data returnerar 0.5 (neutral)."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.insider_transactions = pd.DataFrame()
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_insider_signal("AAPL")
        assert signal == 0.5

    def test_fetch_insider_no_columns(self, mocker):
        """Insider-data utan ratt kolumner returnerar 0.5."""
        mock_ticker = mocker.MagicMock()
        df = pd.DataFrame({"foo": [1, 2], "bar": [3, 4]})
        mock_ticker.insider_transactions = df
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_insider_signal("AAPL")
        assert signal == 0.5

    def test_fetch_insider_cache_hit(self, mocker):
        """Cachad insider-signal returneras direkt."""
        mocker.patch("core.extra_data._rc", return_value=0.75)
        mocker.patch("yfinance.Ticker")

        signal = fetch_insider_signal("AAPL")
        assert signal == 0.75


class TestFetchEarningsSurprise:
    """Testar fetch_earnings_surprise_signal."""

    def test_fetch_earnings_surprise(self, mocker):
        """Mockad earnings surprise returnerar signal mellan 0-1."""
        mock_ticker = mocker.MagicMock()
        df = pd.DataFrame({
            "Quarter": ["Q1", "Q2", "Q3", "Q4"],
            "surprisePercent": [5.0, 3.0, -1.0, 4.0],
        })
        mock_ticker.earnings_history = df
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_earnings_surprise_signal("AAPL")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_earnings_empty(self, mocker):
        """Tom earnings-data returnerar 0.5."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.earnings_history = pd.DataFrame()
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_earnings_surprise_signal("AAPL")
        assert signal == 0.5

    def test_fetch_earnings_cache_hit(self, mocker):
        """Cachad earnings-signal returneras direkt."""
        mocker.patch("core.extra_data._rc", return_value=0.65)
        signal = fetch_earnings_surprise_signal("AAPL")
        assert signal == 0.65


class TestFetchAnalystRevisions:
    """Testar fetch_analyst_revision_signal."""

    def test_fetch_analyst_revisions(self, mocker):
        """Mockad analyst revision returnerar signal mellan 0-1."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.info = {"recommendationMean": 2.0}
        mock_ticker.recommendations = pd.DataFrame()
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_analyst_revision_signal("AAPL")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_analyst_no_info(self, mocker):
        """Utan info-data returneras 0.5."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.info = None
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)

        signal = fetch_analyst_revision_signal("AAPL")
        assert signal == 0.5

    def test_fetch_analyst_finnhub(self, mocker, mock_requests_get):
        """Finnhub-kall returnerar signal."""
        mock_requests_get.return_value.status_code = 200
        mock_requests_get.return_value.json.return_value = [
            {"strongBuy": 5, "buy": 3, "hold": 2, "sell": 1, "strongSell": 0},
            {"strongBuy": 3, "buy": 2, "hold": 4, "sell": 2, "strongSell": 1},
        ]
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_analyst_revision_signal("AAPL", finnhub_key="test_key")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_analyst_cache_hit(self, mocker):
        """Cachad revision returneras direkt."""
        mocker.patch("core.extra_data._rc", return_value=0.72)
        signal = fetch_analyst_revision_signal("AAPL")
        assert signal == 0.72


class TestFetchShortInterest:
    """Testar fetch_short_interest_signal."""

    def test_fetch_short_interest(self, mocker):
        """Mockad short interest returnerar signal baserat pa blankningsgrad."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.info = {"shortPercentOfFloat": 0.03}
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_short_interest_signal("AAPL")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_short_interest_finnhub(self, mocker, mock_requests_get):
        """Finnhub-kall med short interest returnerar signal."""
        mock_requests_get.return_value.status_code = 200
        mock_requests_get.return_value.json.return_value = {
            "data": [{"shortInterestPercent": 2.5}]
        }
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_short_interest_signal("AAPL", finnhub_key="test_key")
        assert isinstance(signal, float)

    def test_fetch_short_interest_high(self, mocker):
        """Hog blankning (>15%) = lag signal."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.info = {"shortPercentOfFloat": 0.25}
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_short_interest_signal("AAPL")
        assert signal < 0.5

    def test_fetch_short_interest_no_data(self, mocker):
        """Ingen short interest-data = 0.5."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.info = {"sector": "Technology"}
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_short_interest_signal("AAPL")
        assert signal == 0.5


class TestFetchSeasonality:
    """Testar fetch_seasonality_signal."""

    def test_fetch_seasonality(self, mocker):
        """Mockad seasonality returnerar signal mellan 0-1."""
        mock_ticker = mocker.MagicMock()
        dates = pd.date_range("2019-01-01", periods=1300, freq="D")
        mock_ticker.history.return_value = pd.DataFrame({
            "Close": [100 * (1 + 0.0005) ** i for i in range(1300)],
        }, index=dates)
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_seasonality_signal("AAPL")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_seasonality_too_short(self, mocker):
        """Kort historik (< 252 dagar) returnerar 0.5."""
        mock_ticker = mocker.MagicMock()
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        mock_ticker.history.return_value = pd.DataFrame({
            "Close": [100] * 100,
        }, index=dates)
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_seasonality_signal("AAPL")
        assert signal == 0.5

    def test_fetch_seasonality_cache_hit(self, mocker):
        """Cachad seasonality returneras direkt."""
        mocker.patch("core.extra_data._rc", return_value=0.60)
        signal = fetch_seasonality_signal("AAPL")
        assert signal == 0.60


class TestFetchOptionsFlow:
    """Testar fetch_options_flow_signal."""

    def test_fetch_options_flow(self, mocker, sample_options_chain):
        """Mockad optionskedja returnerar signal."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.options = ("2024-12-20",)
        calls, puts = sample_options_chain
        mock_chain = mocker.MagicMock()
        mock_chain.calls = calls
        mock_chain.puts = puts
        mock_ticker.option_chain.return_value = mock_chain
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_options_flow_signal("AAPL")
        assert isinstance(signal, float)
        assert 0.0 <= signal <= 1.0

    def test_fetch_options_no_expirations(self, mocker):
        """Inga options-datum returnerar 0.5."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.options = ()
        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        signal = fetch_options_flow_signal("AAPL")
        assert signal == 0.5


class TestExtraDataEdgeCases:
    """Testar edge cases for alla extra_data-funktioner."""

    def test_empty_data_all_functions(self, mocker):
        """Alla funktioner hanterar tom data utan krasch."""
        mock_ticker = mocker.MagicMock()
        mock_ticker.insider_transactions = None
        mock_ticker.earnings_history = None
        mock_ticker.info = {}
        mock_ticker.recommendations = pd.DataFrame()
        mock_ticker.options = ()
        mock_ticker.history.return_value = pd.DataFrame()

        mocker.patch("yfinance.Ticker", return_value=mock_ticker)
        mocker.patch("core.extra_data._rc", return_value=None)
        mocker.patch("core.extra_data._wc")

        assert fetch_insider_signal("AAPL") == 0.5
        assert fetch_earnings_surprise_signal("AAPL") == 0.5
        assert fetch_analyst_revision_signal("AAPL") == 0.5
        assert fetch_short_interest_signal("AAPL") == 0.5
        assert fetch_seasonality_signal("AAPL") == 0.5
        assert fetch_options_flow_signal("AAPL") == 0.5

    def test_invalid_ticker(self, mocker):
        """Ogiltig ticker returnerar neutral signal."""
        mocker.patch("yfinance.Ticker", side_effect=Exception("Invalid ticker"))
        mocker.patch("core.extra_data._rc", return_value=None)

        assert fetch_insider_signal("INVALID!!") == 0.5
        assert fetch_earnings_surprise_signal("INVALID!!") == 0.5
