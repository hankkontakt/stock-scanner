"""Tester för core/ml_predictor.py -- feature-beräkning och robust fallback."""
import numpy as np
import pandas as pd
import pytest

from core.ml_predictor import (
    TECH_FEATURES,
    compute_features_at,
    load_model,
    predict_returns,
    _add_cross_sectional_target,
    _per_date_ic,
)


# De 11 features som introducerades i commit 4871bc5 men hade saknade
# hjälpfunktioner -> returnerade tyst NaN. Regressionstest så det inte återkommer.
_NEW_FEATURES = [
    "log_return_1m", "volatility_skew_30d", "hurst_exponent_60d",
    "serial_correlation_20d", "volume_price_corr_20d", "klinger_oscillator",
    "max_drawdown_60d", "consecutive_down_days", "rsi_divergence",
    "skewness_30d", "kurtosis_30d",
]


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


def test_new_features_compute_non_nan():
    """REGRESSION: de 11 nya features måste faktiskt beräknas, inte tyst bli NaN.
    (Buggen 4871bc5: hjälpfunktioner saknades -> NameError fångades -> NaN.)"""
    # Brusig trend så alla statistiska features har varians att räkna på
    idx = pd.date_range("2023-01-01", periods=300, freq="D")
    rng = np.random.default_rng(42)
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 300))
    close = pd.Series(prices, index=idx)
    volume = pd.Series(rng.integers(500_000, 2_000_000, 300), index=idx)
    feats = compute_features_at(close, volume)
    for f in _NEW_FEATURES:
        assert f in feats, f"{f} saknas i output"
        assert not (isinstance(feats[f], float) and np.isnan(feats[f])), \
            f"{f} är NaN -- hjälpfunktionen saknas/trasig"


def test_cross_sectional_target_demeans_per_date():
    """target_cs ska ha medel ≈ 0 inom varje datum (marknadsfaktor borttagen)."""
    df = pd.DataFrame({
        "ticker": ["A", "B", "C", "A", "B", "C"],
        "date": ["2024-01-01"] * 3 + ["2024-02-01"] * 3,
        "forward_return_30d": [0.10, 0.12, 0.14, -0.05, -0.03, -0.01],
    })
    out = _add_cross_sectional_target(df)
    for _, g in out.groupby("date"):
        assert abs(g["target_cs"].mean()) < 1e-9


def test_per_date_ic_perfect_ranking():
    """Per-datum-IC = 1.0 när pred rangordnar perfekt inom varje datum."""
    dates = ["d1"] * 5 + ["d2"] * 5
    preds = [1, 2, 3, 4, 5, 5, 4, 3, 2, 1]
    actuals = [1, 2, 3, 4, 5, 5, 4, 3, 2, 1]
    ic = _per_date_ic(dates, preds, actuals)
    assert ic > 0.99


def test_load_model_returns_none_when_missing():
    """Robust mot saknad modell -- pipelinen får inte krascha."""
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
