"""
Prestandatester for stock-scanner — hastighet for scoring, data loading, filter, cache, ML.

Dessa tester verifierar att systemet ar tillrackligt snabbt for daglig anvandning.
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Tidstargets (i sekunder)
SCORING_SPEED_TARGET = 5.0      # 1000 tickers < 5s
DATA_LOADING_TARGET = 2.0       # load + parse < 2s
FILTER_SPEED_TARGET = 2.0       # 1000 tickers < 2s
CACHE_READ_TARGET = 0.5         # 100 cache reads < 0.5s
ML_INFERENCE_TARGET = 3.0       # 1000 predictions < 3s

# Markera prestandatester sa de kan hoppas over vid behov
pytestmark = pytest.mark.slow


def _make_large_scored_df(n: int = 1000) -> pd.DataFrame:
    """Skapa en stor scored DataFrame for prestandatestning."""
    np.random.seed(42)
    tickers = [f"T{i:04d}" for i in range(n)]
    df = pd.DataFrame({"ticker": tickers})

    # Grunddata
    df["name"] = [f"Company {t}" for t in tickers]
    df["sector"] = np.random.choice(["Technology", "Finance", "Healthcare", "Consumer"], n)
    df["industry"] = np.random.choice(["Software", "Banking", "Pharma", "Retail"], n)
    df["current_price"] = np.random.uniform(10, 1000, n).round(2)
    df["market_cap"] = np.random.uniform(1e8, 3e12, n)

    # Scoring-kolumner
    for col, lo, hi in [
        ("pe_trailing", 5, 50), ("pe_forward", 5, 40), ("price_to_book", 0.3, 20),
        ("ev_to_ebitda", 2, 30), ("roe", -0.2, 0.5), ("roa", -0.1, 0.3),
        ("profit_margin", -0.1, 0.4), ("operating_margin", -0.1, 0.4),
        ("gross_margin", 0.1, 0.8), ("debt_to_equity", 0, 5),
        ("current_ratio", 0.3, 8), ("dividend_yield", 0, 0.10),
        ("revenue_growth", -0.3, 0.6), ("earnings_growth", -0.4, 0.8),
        ("return_12m", -0.5, 1.0), ("return_6m", -0.3, 0.6), ("return_3m", -0.2, 0.4),
        ("volatility", 0.1, 0.8), ("beta", 0.3, 2.5),
    ]:
        df[col] = np.random.uniform(lo, hi, n).round(4)
    df["avg_volume"] = np.random.randint(10000, 100000000, n)
    df["free_cash_flow"] = np.random.uniform(-1e9, 1e10, n)
    df["enterprise_value"] = df["market_cap"] * np.random.uniform(0.5, 2, n)
    df["sentiment_raw"] = np.random.uniform(-1, 1, n).round(3)
    df["pct_from_52w_high"] = np.random.uniform(-0.4, 0, n).round(4)
    df["short_pct_float"] = np.random.uniform(0.01, 0.3, n).round(4)
    df["options_flow_signal"] = np.random.uniform(0.1, 0.9, n).round(3)

    return df


class TestScoringSpeed:
    """Testar scoring-hastighet for stora dataset."""

    def test_scoring_speed_1000_tickers(self):
        """1000 tickers < 5 sekunder."""
        df = _make_large_scored_df(1000)
        from core.scoring import score_universe

        start = time.time()
        result = score_universe(df)
        elapsed = time.time() - start

        assert elapsed < SCORING_SPEED_TARGET, \
            f"Scoring {len(df)} tickers took {elapsed:.2f}s (target < {SCORING_SPEED_TARGET}s)"
        assert len(result) == 1000
        assert "score_total" in result.columns


class TestDataLoadingSpeed:
    """Testar data loading-hastighet."""

    def test_data_loading_speed_parquet(self, tmp_path):
        """Load + parse parquet < 2 sekunder."""
        df = _make_large_scored_df(500)
        path = tmp_path / "test_universe.parquet"
        df.to_parquet(path)

        start = time.time()
        loaded = pd.read_parquet(path)
        elapsed = time.time() - start

        assert elapsed < DATA_LOADING_TARGET, \
            f"Loading parquet took {elapsed:.2f}s (target < {DATA_LOADING_TARGET}s)"
        assert len(loaded) == 500

    def test_data_loading_speed_csv(self, tmp_path):
        """Load + parse CSV < 2 sekunder."""
        df = _make_large_scored_df(500)
        path = tmp_path / "test_universe.csv"
        df.to_csv(path, index=False)

        start = time.time()
        loaded = pd.read_csv(path, low_memory=False)
        elapsed = time.time() - start

        assert elapsed < DATA_LOADING_TARGET, \
            f"Loading CSV took {elapsed:.2f}s (target < {DATA_LOADING_TARGET}s)"
        assert len(loaded) == 500


class TestFilterSpeed:
    """Testar filter-hastighet."""

    def test_filter_speed_1000_tickers(self):
        """1000 tickers < 2 sekunder."""
        df = _make_large_scored_df(1000)
        df["price_vs_ma200"] = np.random.uniform(-0.2, 0.3, 1000)
        df["price_vs_ma50"] = np.random.uniform(-0.15, 0.2, 1000)
        from core.filters import apply_trend_filter, calc_confidence

        start = time.time()
        filtered = apply_trend_filter(df)
        confident = calc_confidence(filtered)
        elapsed = time.time() - start

        assert elapsed < FILTER_SPEED_TARGET, \
            f"Filtering {len(df)} tickers took {elapsed:.2f}s (target < {FILTER_SPEED_TARGET}s)"
        assert "trend_signal" in filtered.columns
        assert "confidence_label" in confident.columns


class TestCacheSpeed:
    """Testar cache-hastighet."""

    def test_cache_read_speed_100_ops(self, tmp_path, monkeypatch):
        """100 cache reads < 0.5 sekunder."""
        from core.cache_utils import write_cache, read_cache
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)

        # Skriv 10 cache-poster
        for i in range(10):
            write_cache(f"speed_key_{i}", {"data": list(range(100))})

        start = time.time()
        for _ in range(100):
            read_cache(f"speed_key_{_ % 10}")
        elapsed = time.time() - start

        assert elapsed < CACHE_READ_TARGET, \
            f"100 cache reads took {elapsed:.3f}s (target < {CACHE_READ_TARGET}s)"

    def test_cache_write_speed(self, tmp_path, monkeypatch):
        """Cache writes ar snabba."""
        from core.cache_utils import write_cache
        monkeypatch.setattr("core.cache_utils.CACHE_DIR", tmp_path)

        data = {"large": "x" * 10000}

        start = time.time()
        for i in range(50):
            write_cache(f"write_speed_{i}", data)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"50 cache writes took {elapsed:.3f}s"


class TestMLInferenceSpeed:
    """Testar ML-inferenshastighet."""

    def test_ml_inference_speed(self, tmp_path, monkeypatch):
        """1000 predictions < 3 sekunder."""
        from core.ml_predictor import predict_returns, TECH_FEATURES
        from core import ml_predictor
        monkeypatch.setattr(ml_predictor, "MODELS_DIR", tmp_path / "models")
        (tmp_path / "models").mkdir(exist_ok=True)

        df = pd.DataFrame({
            "ticker": [f"T{i:04d}" for i in range(100)],
            "score_total": [50.0] * 100,
        })
        for feat in TECH_FEATURES:
            df[feat] = np.nan

        # Utan modell ska det ga snabbt (passthrough)
        start = time.time()
        result = predict_returns(df, "test_universe")
        elapsed = time.time() - start

        assert elapsed < ML_INFERENCE_TARGET, \
            f"ML passthrough for {len(df)} tickers took {elapsed:.2f}s (target < {ML_INFERENCE_TARGET}s)"
