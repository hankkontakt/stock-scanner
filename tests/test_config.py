"""
Test: config.py
Kontrollerar att:
  - Universumet har aktier
  - Faktorvikter summerar till ~1.0
  - SMALLCAP_CONFIG scoring_weights summerar till ~1.0
  - Alla tickers har rätt format
  - Viktiga konstanter är satta
"""
import pytest


class TestConfig:
    """Testar grundläggande konfigurationsintegritet."""

    def test_universe_not_empty(self):
        """Universumet måste innehålla minst 10 tickers."""
        from core import config
        assert len(config.UNIVERSE) >= 10

    def test_factor_weights_sum_to_one(self):
        """FACTOR_WEIGHTS måste summera till 1.0 (±0.001)."""
        from core import config
        total = sum(config.FACTOR_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_smallcap_weights_sum_to_one(self):
        """SMALLCAP_CONFIG scoring_weights måste summera till 1.0 (±0.001)."""
        from core import config
        w = config.SMALLCAP_CONFIG.get("scoring_weights", {})
        assert w, "SMALLCAP_CONFIG saknar scoring_weights"
        total = sum(w.values())
        assert abs(total - 1.0) < 0.001

    def test_all_tickers_are_strings(self):
        """Alla tickers måste vara strängar."""
        from core import config
        for t in config.UNIVERSE:
            assert isinstance(t, str), f"Ticker '{t}' är inte en sträng"

    def test_api_keys_defined(self):
        """API-nycklar måste finnas som attribut."""
        from core import config
        assert hasattr(config, "FMP_API_KEY")
        assert hasattr(config, "FINNHUB_API_KEY")

    def test_parallel_workers_sane(self):
        """PARALLEL_WORKERS måste vara mellan 1 och 32."""
        from core import config
        assert 1 <= config.PARALLEL_WORKERS <= 32

    def test_finnhub_settings_sane(self):
        """FINNHUB-inställningar måste vara inom rimliga gränser."""
        from core import config
        assert 1 <= config.FINNHUB_PARALLEL_WORKERS <= 10
        assert 1 <= config.FINNHUB_CALLS_PER_MINUTE <= 60

    def test_cache_hours_positive(self):
        """Cache-tider måste vara positiva."""
        from core import config
        assert config.CACHE_HOURS > 0
        assert config.DYNAMIC_CACHE_HOURS > 0
        assert config.PRICE_CACHE_HOURS > 0

    def test_min_data_quality_in_range(self):
        """MIN_DATA_QUALITY måste vara mellan 0 och 1."""
        from core import config
        assert 0 < config.MIN_DATA_QUALITY <= 1
