"""Tester för core/ml_predictor.py — feature-beräkning och robust fallback."""
import numpy as np
import pandas as pd
import pytest

from core.ml_predictor import (
    TECH_FEATURES,
    compute_features_at,
    load_model,
    predict_returns,
)


def _flat_series(price: float = 100.0, n: int = 300) -> pd.Series:
    """Helt platt prisserie för smoke-test."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.Series([price] * n, index=idx)


def _trending_up(start: float = 100.0, daily_pct: float = 0.001, n: int = 300) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.Series([start * (1 + daily_pct) ** i for i in range(n)], index=idx)


def test_compute_features_returns_all_columns_for_long_series():
    close = _trending_up(n=300)
    volume = pd.Series([1_000_000] * 300, index=close.index)
    feats = compute_features_at(close, volume)
    assert set(feats.keys()) == set(TECH_FEATURES)


def test_compute_features_short_series_returns_nan():
    close = pd.Series([100.0] * 5)
    feats = compute_features_at(close, None)
    # alla värden ska vara NaN
    assert all(np.isnan(v) for v in feats.values())


def test_compute_features_flat_series_rsi_neutral():
    """Helt platta priser ska ge RSI = 50 (neutralt), inte 100."""
    close = _flat_series(n=300)
    feats = compute_features_at(close, None)
    # RSI ska ligga runt 50 för platta priser
    assert abs(feats["rsi_14"] - 50.0) < 1.0


def test_compute_features_trending_up_has_positive_returns():
    close = _trending_up(daily_pct=0.002, n=300)
    feats = compute_features_at(close, None)
    assert feats["ret_1m"] > 0
    assert feats["ret_3m"] > 0
    assert feats["price_over_ma200"] > 1.0


def test_load_model_returns_none_when_missing():
    """Robust mot saknad modell — pipelinen får inte krascha."""
    result = load_model("nonexistent_universe_xyz")
    assert result is None


def test_predict_returns_passthrough_when_no_model(tmp_path, monkeypatch):
    """Om modellen saknas ska predict_returns returnera df oförändrad."""
    # Tomma scored DataFrame
    df = pd.DataFrame({"ticker": ["AAPL", "MSFT"], "score_total": [70, 80]})
    monkeypatch.chdir(tmp_path)
    # Pek ut MODELS_DIR till tom temp så ingen modell hittas
    from core import ml_predictor
    monkeypatch.setattr(ml_predictor, "MODELS_DIR", tmp_path / "models")
    (tmp_path / "models").mkdir(exist_ok=True)
    result = predict_returns(df, "universe")
    # Df ska vara oförändrad och inte ha predicted_return-kolumn
    assert "predicted_return" not in result.columns
    assert len(result) == 2
