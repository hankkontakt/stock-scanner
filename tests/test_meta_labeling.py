"""Tests for S2 — Meta-labeling + triple-barrier."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.meta_labeling import (
    DEFAULT_MAX_DAYS,
    DEFAULT_SL,
    DEFAULT_TP,
    apply_meta,
    triple_barrier_labels,
)


def _synthetic_prices(n_tickers: int = 3, n_days: int = 60) -> pd.DataFrame:
    """Skapa syntetisk prisdata."""
    rows = []
    np.random.seed(42)
    for t in range(n_tickers):
        price = 100.0
        for d in range(n_days):
            price *= 1 + np.random.normal(0, 0.02)
            rows.append({
                "ticker": f"TICK{t:04d}",
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=d),
                "close": max(price, 1.0),
            })
    return pd.DataFrame(rows)


class TestTripleBarrierLabels:
    def test_basic_labeling(self):
        """Verifiera att labels är 0 eller 1."""
        prices = _synthetic_prices()
        labels = triple_barrier_labels(prices, tp=0.05, sl=0.05, max_days=20)
        assert labels.dtype == int
        assert set(labels.unique()) <= {0, 1}

    def test_high_tp_low_sl(self):
        """Med hög tp och låg sl: fler labels borde vara 0 (SL nås först)."""
        prices = _synthetic_prices(n_days=30)
        labels = triple_barrier_labels(prices, tp=0.20, sl=0.02, max_days=10)
        # Majoriteten borde vara 0 (stop-loss nås först med snävt SL)
        zero_ratio = (labels == 0).mean()
        assert zero_ratio > 0.3, (
            f"Expected mostly 0s with tight SL, got {zero_ratio:.2f}"
        )

    def test_short_horizon(self):
        """Max_days=1 → label baserad på next-day return."""
        prices = _synthetic_prices(n_tickers=1, n_days=10)
        labels = triple_barrier_labels(prices, tp=0.01, sl=0.01, max_days=1)
        assert len(labels) == len(prices)
        assert labels.dtype == int

    def test_empty_input(self):
        """Tom DataFrame → tom serie."""
        prices = pd.DataFrame()
        labels = triple_barrier_labels(prices)
        assert len(labels) == 0

    def test_known_outcome(self):
        """Kontrollerat fall: priset går upp → label=1."""
        rows = [
            {"ticker": "A", "date": pd.Timestamp("2024-01-01"), "close": 100.0},
            {"ticker": "A", "date": pd.Timestamp("2024-01-02"), "close": 105.0},
            {"ticker": "A", "date": pd.Timestamp("2024-01-03"), "close": 115.0},  # +15% → TP hit
            {"ticker": "A", "date": pd.Timestamp("2024-01-04"), "close": 110.0},
        ]
        prices = pd.DataFrame(rows)
        labels = triple_barrier_labels(prices, tp=0.10, sl=0.10, max_days=5)
        # Första raden: TP på 15% nås före SL på 10% → 1
        assert labels.iloc[0] == 1, "First row should be 1 (TP reached before SL)"


class TestApplyMeta:
    def test_no_model(self):
        """Utan meta_model → meta_confidence=0."""
        df = pd.DataFrame({"ml_rank": [50.0, 90.0], "ticker": ["A", "B"]})
        result = apply_meta(df, None)
        assert "meta_confidence" in result.columns
        assert (result["meta_confidence"] == 0.0).all()

    def test_with_dummy_model(self):
        """Med dummy-modell → meta_confidence sätts."""
        df = pd.DataFrame({"ml_rank": [50.0, 90.0], "ticker": ["A", "B"]})
        class DummyModel:
            _feature_cols = ["ml_rank"]
            def predict_proba(self, X):
                return np.array([[0.8, 0.2], [0.3, 0.7]])
        result = apply_meta(df, DummyModel())
        assert "meta_confidence" in result.columns
        assert result["meta_confidence"].iloc[1] > 0.5
