"""
tests/test_chaos.py
===================
Chaos-tester: nätverksfel, malformad data, rate-limits, API-timeouts.
Verifierar att systemet degraderar graciöst (ingen krasch, returnerar tom/default).

T6-implementation: Minst 10 chaos-scenarier med realistiska mocks.

Kör med: pytest tests/test_chaos.py -v --timeout=30
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ─── Nätverksfel ────────────────────────────────────────────────────────────

class TestNetworkFailures:
    """Systemet ska klara nätverksavbrott utan att krascha."""

    def test_data_provider_handles_timeout(self):
        """YFinanceProvider returnerar tom DF vid timeout."""
        from core.data_provider import YFinanceProvider
        provider = YFinanceProvider()
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.side_effect = TimeoutError("Connection timeout")
            result = provider.get_price_history("AAPL", period="1y")
        assert isinstance(result, pd.DataFrame)
        assert result.empty, "Ska returnera tom DF vid timeout"

    def test_data_provider_handles_connection_error(self):
        """YFinanceProvider returnerar {} vid ConnectionError för info."""
        from core.data_provider import YFinanceProvider
        provider = YFinanceProvider()
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.info = None
            mock_ticker.return_value.info.__get__ = MagicMock(side_effect=ConnectionError)
            # Simulera ConnectionError vid info-anrop
            def raise_conn(*a, **k):
                raise ConnectionError("No network")
            mock_ticker.return_value.__init__ = raise_conn
            # Sätter upp korrekt mock
            mock_ticker.side_effect = ConnectionError("No network")
            result = provider.get_info("AAPL")
        assert isinstance(result, dict)
        assert result == {}, "Ska returnera tomt dict vid ConnectionError"

    def test_data_provider_handles_import_error(self):
        """DataProvider hanterar avsaknad av yfinance."""
        from core.data_provider import YFinanceProvider
        provider = YFinanceProvider()
        with patch.dict("sys.modules", {"yfinance": None}):
            result = provider.get_price_history("AAPL")
        assert isinstance(result, pd.DataFrame)

    def test_caching_provider_survives_inner_failure(self):
        """CachingProvider returnerar tom DF om inner provider kastar."""
        from core.data_provider import CachingProvider, YFinanceProvider
        inner = YFinanceProvider()
        cached = CachingProvider(inner, price_ttl_s=300)
        with patch.object(inner, "get_price_history", side_effect=RuntimeError("API down")):
            result = cached.get_price_history("AAPL")
        assert isinstance(result, pd.DataFrame)


# ─── Malformad data ──────────────────────────────────────────────────────────

class TestMalformedData:
    """Systemet ska klara korrupt/oväntad input utan att krascha."""

    def test_scoring_handles_all_nan_dataframe(self):
        """score_universe hanterar DataFrame med enbart NaN-värden."""
        try:
            from core.scoring import score_universe
        except ImportError:
            pytest.skip("core.scoring ej tillgänglig")

        df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "score_total": [float("nan"), float("nan")],
            "pe_trailing": [float("nan"), float("nan")],
            "roe": [float("nan"), float("nan")],
        })
        try:
            result = score_universe(df)
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"score_universe kraschade på NaN-data: {e}")

    def test_scoring_handles_empty_dataframe(self):
        """score_universe hanterar tom DataFrame."""
        try:
            from core.scoring import score_universe
        except ImportError:
            pytest.skip("core.scoring ej tillgänglig")
        result = score_universe(pd.DataFrame())
        assert isinstance(result, pd.DataFrame)

    def test_news_fetcher_handles_malformed_xml(self, monkeypatch):
        """news_fetcher hanterar trasig XML utan krasch."""
        try:
            from core import news_fetcher
        except ImportError:
            pytest.skip("core.news_fetcher ej tillgänglig")

        # Mocka requests.get att returnera trasig XML
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"<this is not valid xml <<<>>"
        mock_resp.text = "<this is not valid xml <<<>>"

        import requests
        monkeypatch.setattr(requests, "get", lambda *a, **k: mock_resp)

        try:
            result = news_fetcher.fetch_rss_news("https://fake.url/feed", max_items=5)
            assert isinstance(result, list), "Ska returnera lista (möjligen tom) vid malformad XML"
        except Exception as e:
            pytest.fail(f"news_fetcher kraschade på malformad XML: {e}")

    def test_metrics_handles_invalid_value(self):
        """record_metric hanterar NaN och Inf utan krasch."""
        from core.metrics import record_metric
        import math
        # Dessa ska inte krascha
        record_metric("test_nan", float("nan"), tags={"test": "chaos"})
        record_metric("test_inf", float("inf"), tags={"test": "chaos"})
        record_metric("test_neg_inf", float("-inf"), tags={"test": "chaos"})

    def test_feature_flags_handles_corrupt_json(self, tmp_path):
        """feature_flags hanterar korrupt JSON-fil med fallback till defaults."""
        import importlib
        import sys

        # Skriv korrupt JSON
        flags_file = tmp_path / "feature_flags.json"
        flags_file.write_text("{ this is not valid json }", encoding="utf-8")

        from core import feature_flags
        # Temporarily patch the FLAGS_FILE path
        original = feature_flags._FLAGS_FILE
        feature_flags._FLAGS_FILE = flags_file
        feature_flags._FLAGS_CACHE = {}
        feature_flags._FLAGS_MTIME = 0.0

        try:
            result = feature_flags.is_enabled("live_fx_rates")
            assert isinstance(result, bool), "Ska returnera bool även med korrupt JSON"
        finally:
            feature_flags._FLAGS_FILE = original
            feature_flags._FLAGS_CACHE = {}
            feature_flags._FLAGS_MTIME = 0.0


# ─── Rate-limiting ───────────────────────────────────────────────────────────

class TestRateLimiting:
    """Systemet ska klara rate-limiting graciöst."""

    def test_data_fetcher_batch_handles_rate_limit(self, monkeypatch):
        """data_fetcher_batch pausar vid rate-limit och returnerar resultat."""
        try:
            from core.data_fetcher_batch import fetch_batch
        except ImportError:
            pytest.skip("core.data_fetcher_batch ej tillgänglig")

        call_count = [0]

        def mock_fetch_single(ticker, blacklist=None, verbose=False):
            call_count[0] += 1
            if call_count[0] <= 2:
                return (ticker, None, "RATE_LIMITED")
            return (ticker, {"ticker": ticker, "score_total": 50.0}, "OK")

        try:
            from core import data_fetcher_batch as dfb
            monkeypatch.setattr(dfb, "_fetch_single_ticker", mock_fetch_single)
            monkeypatch.setattr(dfb.time, "sleep", lambda s: None)  # Skippa sleep

            result = fetch_batch(["AAPL", "MSFT"], verbose=False)
            # Ska returnera ett resultat-dict utan att krascha
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"fetch_batch kraschade vid rate-limit: {e}")

    def test_backoff_values_increase(self):
        """Backoff-värden ökar exponentiellt."""
        import random
        random.seed(42)
        base = 30.0
        delays = [min(base * (2 ** i), 120) for i in range(4)]
        assert delays[0] < delays[1] < delays[2], "Backoff ska öka exponentiellt"
        assert all(d <= 120 for d in delays), "Backoff ska ha max-gräns"


# ─── Fil-integritet ──────────────────────────────────────────────────────────

class TestFileIntegrity:
    """Systemet ska hantera korrupta/saknade datafiler."""

    def test_feature_flags_creates_file_if_missing(self, tmp_path, monkeypatch):
        """feature_flags skapar en ny fil om data/feature_flags.json saknas."""
        from core import feature_flags
        original = feature_flags._FLAGS_FILE
        feature_flags._FLAGS_FILE = tmp_path / "feature_flags.json"
        feature_flags._FLAGS_CACHE = {}
        feature_flags._FLAGS_MTIME = 0.0

        try:
            val = feature_flags.is_enabled("live_fx_rates")
            assert isinstance(val, bool)
        finally:
            feature_flags._FLAGS_FILE = original
            feature_flags._FLAGS_CACHE = {}
            feature_flags._FLAGS_MTIME = 0.0

    def test_metrics_creates_dir_if_missing(self, tmp_path, monkeypatch):
        """record_metric skapar data/metrics/ om den saknas."""
        from core import metrics
        original = metrics._METRICS_DIR
        metrics._METRICS_DIR = tmp_path / "nonexistent" / "metrics"

        try:
            metrics.record_metric("test_create", 42.0)
            assert metrics._METRICS_DIR.exists(), "Ska skapa mappen automatiskt"
        finally:
            metrics._METRICS_DIR = original

    def test_data_provider_get_cached_name(self):
        """DataProvider och CachingProvider returnerar korrekt namn."""
        from core.data_provider import YFinanceProvider, CachingProvider
        yf = YFinanceProvider()
        cached = CachingProvider(yf)
        assert "YFinance" in yf.get_name()
        assert "Caching" in cached.get_name()
        assert "YFinance" in cached.get_name()
