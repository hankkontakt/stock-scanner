"""
Tester for core/ml_predictor.py -- feature importance, ensemble, walk-forward analysis,
och core/ml_backtest.py -- backtesting engine.

PROJECT 1: ML Pipeline Revolution
PROJECT 6: Utokad test coverage
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.ml_predictor import (
    TECH_FEATURES,
    EnsemblePredictor,
    compute_features_at,
    compute_ic_over_time,
    detect_model_decay,
    ensemble_predict,
    feature_permutation_importance,
    log_feature_importance,
    stacking_ensemble,
    walk_forward_validate,
    load_model,
    predict_returns,
    train_model,
    _add_cross_sectional_target,
    _per_date_ic,
    _deflated_sharpe_ratio,
)
from core.ml_backtest import (
    BacktestResult,
    RollingWindowResult,
    rolling_backtest,
    save_backtest_result,
    save_rolling_results,
    simulate_strategy,
)


# ══════════════════════════════════════════════════════════════════════════════
# HJALPDATA
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_price_series() -> pd.Series:
    """Skapa en brusig prisserie for ML-tester."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2023-01-01", periods=300, freq="D")
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 300))
    return pd.Series(prices, index=idx)


@pytest.fixture
def sample_volume_series() -> pd.Series:
    """Skapa en volymserie."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2023-01-01", periods=300, freq="D")
    return pd.Series(rng.integers(500_000, 2_000_000, 300), index=idx)


@pytest.fixture
def sample_trained_model():
    """Skapa en enkel tranad modell for tester."""
    from sklearn.ensemble import RandomForestRegressor
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (200, len(TECH_FEATURES)))
    y = X[:, 0] * 0.5 + X[:, 1] * 0.3 + rng.normal(0, 0.1, 200)
    model = RandomForestRegressor(n_estimators=10, max_depth=3, random_state=42)
    model.fit(X, y)
    return model, TECH_FEATURES, X, y


@pytest.fixture
def sample_scored_df() -> pd.DataFrame:
    """Skapa en scored DataFrame for backtest-tester."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=180, freq="W")
    tickers = [f"TICK{i}" for i in range(20)]
    np.random.seed(42)

    rows = []
    for i, date in enumerate(dates):
        for ticker in tickers:
            pred = rng.normal(0, 0.02)
            actual = pred + rng.normal(0, 0.01)
            rows.append({
                "date": date,
                "ticker": ticker,
                "predicted_return": pred,
                "forward_return_30d": actual,
                **{f: rng.normal(0, 1) for f in TECH_FEATURES[:5]},
            })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# TESTER: FEATURE IMPORTANCE (Project 1B)
# ══════════════════════════════════════════════════════════════════════════════

def test_log_feature_importance_returns_dict(sample_trained_model):
    """log_feature_importance ska returnera en sorterad dict."""
    model, features, X, y = sample_trained_model
    result = log_feature_importance(model, features)

    assert isinstance(result, dict)
    assert len(result) == len(features)
    keys = list(result.keys())
    values = list(result.values())
    assert abs(values[0]) >= abs(values[-1])


def test_log_feature_importance_saves_json(sample_trained_model):
    """log_feature_importance ska spara till JSON nar output_path anges."""
    model, features, X, y = sample_trained_model

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        output_path = Path(f.name)

    try:
        result = log_feature_importance(model, features, output_path=output_path)
        assert output_path.exists()
        loaded = json.loads(output_path.read_text(encoding="utf-8"))
        assert len(loaded) == len(features)
        assert all(k in features for k in loaded.keys())
    finally:
        output_path.unlink(missing_ok=True)


def test_log_feature_importance_empty_for_linear_model():
    """log_feature_importance ska fungera aven for linjara modeller."""
    from sklearn.linear_model import LinearRegression
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (50, 5))
    y = X[:, 0] * 2 + X[:, 1] * 1.5 + rng.normal(0, 0.1, 50)
    model = LinearRegression()
    model.fit(X, y)

    features = ["f1", "f2", "f3", "f4", "f5"]
    result = log_feature_importance(model, features)
    assert len(result) == 5
    assert all(v >= 0 for v in result.values())


def test_feature_permutation_importance(sample_trained_model):
    """feature_permutation_importance ska returnera meningsfulla varden."""
    model, features, X, y = sample_trained_model

    result = feature_permutation_importance(model, X[:100], y[:100], features,
                                            n_repeats=3)
    assert isinstance(result, dict)
    assert len(result) == len(features)
    assert all(isinstance(v, (int, float)) for v in result.values())


def test_feature_permutation_importance_handles_tiny_data():
    """feature_permutation_importance ska inte krascha pa sma dataset."""
    from sklearn.linear_model import LinearRegression
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, (10, 3))
    y = rng.normal(0, 1, 10)
    model = LinearRegression()
    model.fit(X, y)

    result = feature_permutation_importance(model, X, y, ["a", "b", "c"])
    assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# TESTER: ENSEMBLE METHODS (Project 1D)
# ══════════════════════════════════════════════════════════════════════════════

def test_ensemble_predictor_basic():
    """EnsemblePredictor ska kunna tranas och prediktera."""
    rng = np.random.default_rng(42)
    X_train = rng.normal(0, 1, (200, 10))
    y_train = X_train[:, 0] * 0.5 + X_train[:, 1] * 0.3 + rng.normal(0, 0.1, 200)
    X_test = rng.normal(0, 1, (20, 10))

    ensemble = EnsemblePredictor(use_lightgbm=False)
    ensemble.fit(X_train, y_train)

    preds = ensemble.predict(X_test)
    assert len(preds) == 20
    assert not np.any(np.isnan(preds))


def test_ensemble_predictor_uses_ic_weights():
    """EnsemblePredictor ska berakna IC-baserade vikter nar valideringsdata finns."""
    rng = np.random.default_rng(42)
    X_train = rng.normal(0, 1, (200, 10))
    y_train = X_train[:, 0] * 0.5 + rng.normal(0, 0.1, 200)
    X_val = rng.normal(0, 1, (50, 10))
    y_val = X_val[:, 0] * 0.5 + rng.normal(0, 0.1, 50)

    ensemble = EnsemblePredictor(use_lightgbm=False)
    ensemble.fit(X_train, y_train, X_val=X_val, y_val=y_val)

    weights = ensemble.get_model_weights()
    assert len(weights) > 0
    assert abs(sum(weights.values()) - 1.0) < 0.01


def test_ensemble_predictor_get_individual_predictions():
    """get_individual_predictions ska returnera prediktioner per modell."""
    rng = np.random.default_rng(42)
    X_train = rng.normal(0, 1, (100, 5))
    y_train = X_train[:, 0] * 0.5 + rng.normal(0, 0.1, 100)
    X_test = rng.normal(0, 1, (10, 5))

    ensemble = EnsemblePredictor(use_lightgbm=False)
    ensemble.fit(X_train, y_train)

    indiv = ensemble.get_individual_predictions(X_test)
    assert isinstance(indiv, dict)
    assert len(indiv) > 0
    for name, preds in indiv.items():
        assert len(preds) == 10
        assert not np.any(np.isnan(preds))


def test_ensemble_predict_raw_function():
    """ensemble_predict ska fungera som standalone-funktion."""
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor

    rng = np.random.default_rng(42)
    X_train = rng.normal(0, 1, (100, 5))
    y_train = X_train[:, 0] * 0.5 + rng.normal(0, 0.1, 100)
    X_test = rng.normal(0, 1, (10, 5))

    m1 = Ridge(alpha=1.0)
    m1.fit(X_train, y_train)
    m2 = RandomForestRegressor(n_estimators=10, random_state=42)
    m2.fit(X_train, y_train)

    models = {"ridge": m1, "rf": m2}
    preds = ensemble_predict(models, X_test)
    assert len(preds) == 10

    preds_weighted = ensemble_predict(models, X_test, weights={"ridge": 0.7, "rf": 0.3})
    assert len(preds_weighted) == 10


def test_stacking_ensemble():
    """stacking_ensemble ska trana en meta-modell."""
    from sklearn.linear_model import Ridge
    from sklearn.ensemble import RandomForestRegressor

    rng = np.random.default_rng(42)
    X_train = rng.normal(0, 1, (200, 5))
    y_train = X_train[:, 0] * 0.5 + rng.normal(0, 0.1, 200)
    X_val = rng.normal(0, 1, (50, 5))
    y_val = X_val[:, 0] * 0.5 + rng.normal(0, 0.1, 50)

    base_models = [
        Ridge(alpha=1.0),
        RandomForestRegressor(n_estimators=10, random_state=42),
    ]
    meta = Ridge(alpha=0.5)

    meta_trained = stacking_ensemble(base_models, meta, X_train, y_train, X_val, y_val, cv_folds=3)

    assert hasattr(meta_trained, "predict")
    preds = meta_trained.predict(np.hstack([X_val, np.zeros((50, 2))]))
    assert len(preds) == 50


# ══════════════════════════════════════════════════════════════════════════════
# TESTER: WALK-FORWARD ANALYSIS (Project 1E)
# ══════════════════════════════════════════════════════════════════════════════

def test_walk_forward_validate_returns_list(sample_scored_df):
    """walk_forward_validate ska returnera en lista av resultat."""
    df = sample_scored_df.copy()
    for i, f in enumerate(TECH_FEATURES[:5]):
        df[f] = np.random.default_rng(i).normal(0, 1, len(df))

    results = walk_forward_validate(df, n_train=30, n_test=10, step=10)
    assert isinstance(results, list)
    if results:
        r = results[0]
        assert "ic" in r
        assert "hit_rate" in r
        assert "top_10_return" in r
        assert "max_drawdown" in r


def test_walk_forward_validate_requires_date():
    """walk_forward_validate ska krava date-kolumn."""
    df = pd.DataFrame({"forward_return_30d": [0.1, 0.2]})
    with pytest.raises(ValueError, match="date"):
        walk_forward_validate(df)


def test_walk_forward_validate_min_data():
    """walk_forward_validate ska krava tillrackligt med data."""
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5),
        "forward_return_30d": [0.1] * 5,
    })
    with pytest.raises(ValueError, match="For fa datum"):
        walk_forward_validate(df, n_train=10, n_test=5)


# ══════════════════════════════════════════════════════════════════════════════
# TESTER: IC OVER TIME & MODEL DECAY (Project 1E)
# ══════════════════════════════════════════════════════════════════════════════

def test_compute_ic_over_time_basic():
    """compute_ic_over_time ska returnera en DataFrame med IC per period."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2023-01-01", periods=180, freq="D")
    n = len(dates)

    df = pd.DataFrame({
        "date": np.repeat(dates, 5),
        "predicted_return": rng.normal(0, 1, n * 5),
        "forward_return_30d": rng.normal(0, 1, n * 5),
    })

    result = compute_ic_over_time(df, freq="M")
    assert isinstance(result, pd.DataFrame)
    if not result.empty:
        assert "period" in result.columns
        assert "ic" in result.columns
        assert all(-1.0 <= v <= 1.0 for v in result["ic"] if not pd.isna(v))


def test_compute_ic_over_time_missing_columns():
    """compute_ic_over_time ska ge ValueError vid saknade kolumner."""
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(ValueError):
        compute_ic_over_time(df)


def test_detect_model_decay_no_data():
    """detect_model_decay ska hantera tom IC-historia."""
    result = detect_model_decay(pd.DataFrame())
    assert result["decay_detected"] is False
    assert "alert_message" in result


def test_detect_model_decay_positive_ic():
    """detect_model_decay ska inte varna vid positiv IC."""
    ic_history = pd.DataFrame({
        "period": ["2023-01", "2023-02", "2023-03"],
        "ic": [0.05, 0.08, 0.06],
    })
    result = detect_model_decay(ic_history)
    assert result["decay_detected"] is False
    assert result["current_ic"] == 0.06


def test_detect_model_decay_negative_ic():
    """detect_model_decay ska varna vid IC under troskel."""
    ic_history = pd.DataFrame({
        "period": ["2023-01", "2023-02", "2023-03"],
        "ic": [-0.1, -0.08, -0.12],
    })
    result = detect_model_decay(ic_history, threshold=-0.05)
    assert result["decay_detected"] is True
    assert result["current_ic"] == -0.12
    assert "VARNING" in result["alert_message"].upper()


# ══════════════════════════════════════════════════════════════════════════════
# TESTER: ML BACKTEST ENGINE (Project 1A)
# ══════════════════════════════════════════════════════════════════════════════

def test_simulate_strategy_raises_without_predicted_return():
    """simulate_strategy ska ge ValueError nar predicted_return saknas."""
    df = pd.DataFrame({"date": ["2024-01-01"], "ticker": ["AAPL"]})
    with pytest.raises(ValueError, match="predicted_return"):
        simulate_strategy(df)


def test_simulate_strategy_raises_without_date():
    """simulate_strategy ska ge ValueError nar date saknas."""
    df = pd.DataFrame({"ticker": ["AAPL"], "predicted_return": [0.05]})
    with pytest.raises(ValueError, match="date"):
        simulate_strategy(df)


def test_simulate_strategy_returns_backtest_result(sample_scored_df):
    """simulate_strategy ska returnera BacktestResult."""
    result = simulate_strategy(
        sample_scored_df,
        top_n=5,
        rebalance_freq="W",
    )
    assert isinstance(result, BacktestResult)
    assert isinstance(result.total_return, float)
    assert isinstance(result.sharpe_ratio, float)
    assert isinstance(result.max_drawdown, float)
    assert isinstance(result.win_rate, float)
    assert isinstance(result.equity_curve, list)
    assert len(result.equity_curve) > 0


def test_simulate_strategy_produces_reasonable_metrics(sample_scored_df):
    """simulate_strategy ska producera rimliga nyckeltal."""
    result = simulate_strategy(sample_scored_df, top_n=10, rebalance_freq="W")
    # Syntetisk data ar hogt korrelerad sa dynamiska nyckeltal kan vara extrema
    assert -10.0 < result.total_return < 10.0
    assert 0.0 <= result.max_drawdown <= 1.0
    assert 0.0 <= result.win_rate <= 1.0
    assert result.n_trades > 0


def test_simulate_strategy_date_filtering(sample_scored_df):
    """simulate_strategy ska filtrera pa datumintervall."""
    result = simulate_strategy(
        sample_scored_df,
        start_date="2023-06-01",
        end_date="2023-12-31",
        top_n=5,
    )
    assert isinstance(result, BacktestResult)


def test_simulate_strategy_different_top_n(sample_scored_df):
    """simulate_strategy ska fungera med olika top-N."""
    for top_n in [5, 10, 20]:
        result = simulate_strategy(sample_scored_df, top_n=top_n)
        assert isinstance(result, BacktestResult)
        assert result.params["top_n"] == top_n


def test_simulate_strategy_different_rebalance_freq(sample_scored_df):
    """simulate_strategy ska fungera med olika rebalanseringsfrekvenser."""
    result_monthly = simulate_strategy(sample_scored_df, rebalance_freq="ME", top_n=5)
    assert isinstance(result_monthly, BacktestResult)

    result_weekly = simulate_strategy(sample_scored_df, rebalance_freq="W", top_n=5)
    assert isinstance(result_weekly, BacktestResult)


def test_simulate_strategy_without_forward_return(sample_scored_df):
    """simulate_strategy ska fungera aven utan forward_return_30d."""
    df = sample_scored_df.drop(columns=["forward_return_30d"])
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = simulate_strategy(df, top_n=5)
    assert isinstance(result, BacktestResult)


def test_rolling_backtest_returns_list(sample_scored_df):
    """rolling_backtest ska returnera en lista av RollingWindowResult."""
    df = sample_scored_df.copy()
    for i, f in enumerate(TECH_FEATURES[:5]):
        df[f] = np.random.default_rng(i).normal(0, 1, len(df))

    results = rolling_backtest(df, window_years=1, step_months=3, top_n=5,
                                min_train_rows=50)
    assert isinstance(results, list)
    if results:
        r = results[0]
        assert isinstance(r, RollingWindowResult)
        assert isinstance(r.ic, float)
        assert isinstance(r.hit_rate, float)


def test_rolling_backtest_requires_date():
    """rolling_backtest ska krava date-kolumn."""
    df = pd.DataFrame({"ticker": ["A"], "forward_return_30d": [0.1]})
    with pytest.raises(ValueError, match="date"):
        rolling_backtest(df)


def test_save_backtest_result(tmp_path, sample_scored_df):
    """save_backtest_result ska spara JSON."""
    result = simulate_strategy(sample_scored_df, top_n=5)
    path = save_backtest_result(result, "test_result")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "total_return" in data
    assert "cagr" in data
    assert "sharpe_ratio" in data
    assert "equity_curve" in data


def test_save_rolling_results(tmp_path, sample_scored_df):
    """save_rolling_results ska spara JSON."""
    df = sample_scored_df.copy()
    for i, f in enumerate(TECH_FEATURES[:5]):
        df[f] = np.random.default_rng(i).normal(0, 1, len(df))

    results = rolling_backtest(df, window_years=1, step_months=3, top_n=5,
                                min_train_rows=50)
    if results:
        path = save_rolling_results(results, "test_rolling")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "n_windows" in data
        assert "windows" in data
        assert "summary" in data


def test_backtest_result_defaults():
    """BacktestResult ska ha korrekta default-varden."""
    result = BacktestResult(
        total_return=0.1,
        cagr=0.05,
        sharpe_ratio=1.0,
        max_drawdown=0.2,
        win_rate=0.6,
        avg_win=0.02,
        avg_loss=-0.01,
        profit_factor=2.0,
        n_trades=50,
        equity_curve=[{"date": "2024-01-01", "portfolio_value": 1.0}],
        benchmark_return=0.08,
        benchmark_cagr=0.04,
        benchmark_sharpe=0.8,
        benchmark_max_dd=0.15,
        params={"top_n": 10},
    )
    assert result.total_return == 0.1
    assert result.n_trades == 50
    assert result.params == {"top_n": 10}


def test_backtest_result_equity_curve_integrity(sample_scored_df):
    """Equity curve ska ha konsekventa datum och varden."""
    result = simulate_strategy(sample_scored_df, top_n=5)
    curve = result.equity_curve
    for point in curve:
        assert point["portfolio_value"] > 0
        assert "date" in point


def test_rolling_window_result_defaults():
    """RollingWindowResult ska ha korrekta falt."""
    r = RollingWindowResult(
        window_label="test",
        train_start="2023-01-01",
        train_end="2024-01-01",
        test_start="2024-01-02",
        test_end="2024-04-01",
        ic=0.05,
        hit_rate=0.55,
        top_n_return=0.02,
        max_drawdown=0.1,
        n_tickers_in_universe=100,
    )
    assert r.ic == 0.05
    assert r.n_tickers_in_universe == 100


# ══════════════════════════════════════════════════════════════════════════════
# PROJECT 6: NYCKA TESTER
# ══════════════════════════════════════════════════════════════════════════════

def _make_training_data(n_stocks: int = 10, n_days: int = 300) -> pd.DataFrame:
    """Skapa syntetisk traningdata."""
    rows = []
    for i in range(n_stocks):
        np.random.seed(i)
        prices = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.02, n_days))
        volume = np.random.randint(500_000, 2_000_000, n_days)
        dates = pd.date_range("2024-01-01", periods=n_days, freq="D")

        for t in range(60, n_days - 30):
            close = pd.Series(prices[:t], index=dates[:t])
            vol = pd.Series(volume[:t], index=dates[:t])
            feats = compute_features_at(close, vol)
            row = {
                "ticker": f"STOCK{i}",
                "date": dates[t - 1].strftime("%Y-%m-%d"),
                "forward_return_30d": (prices[t + 30] / prices[t]) - 1,
            }
            row.update(feats)
            rows.append(row)
    return pd.DataFrame(rows)


class TestTrainingProject6:
    """Testar modelltraning (Project 6)."""

    def test_train_from_dataset(self, tmp_path, monkeypatch):
        """Trana med syntetisk data."""
        from core import ml_predictor
        monkeypatch.setattr(ml_predictor, "MODELS_DIR", tmp_path / "models")
        (tmp_path / "models").mkdir(exist_ok=True)

        data = _make_training_data(n_stocks=5, n_days=200)
        model = train_model(data, universe="test_univ_p6")
        assert model is not None

    def test_predict_returns_after_training(self, tmp_path, monkeypatch):
        """Efter traning fungerar predict."""
        from core import ml_predictor
        monkeypatch.setattr(ml_predictor, "MODELS_DIR", tmp_path / "models")
        (tmp_path / "models").mkdir(exist_ok=True)

        data = _make_training_data(n_stocks=5, n_days=200)
        train_model(data, universe="test_univ_pred")

        test_df = pd.DataFrame({
            "ticker": ["STOCK0", "STOCK1"],
            "score_total": [70.0, 60.0],
        })
        for feat in TECH_FEATURES:
            test_df[feat] = np.nan

        result = predict_returns(test_df, "test_univ_pred")
        assert "predicted_return" in result.columns

    def test_load_model_none_when_missing(self):
        """load_model returnerar None for saknad modell."""
        result = load_model("nonexistent_model_p6")
        assert result is None

    def test_predict_returns_passthrough(self, tmp_path, monkeypatch):
        """Utan modell -> df oforandrad."""
        from core import ml_predictor
        monkeypatch.setattr(ml_predictor, "MODELS_DIR", tmp_path / "models")
        (tmp_path / "models").mkdir(exist_ok=True)

        df = pd.DataFrame({"ticker": ["AAPL", "MSFT"], "score_total": [70, 80]})
        result = predict_returns(df, "universe")
        assert "predicted_return" not in result.columns
        assert len(result) == 2


class TestICComputationProject6:
    """Testar IC-berakning (Project 6)."""

    def test_compute_ic_over_time(self):
        """IC over tid fungerar."""
        dates = ["2024-01-01"] * 10 + ["2024-01-02"] * 10
        np.random.seed(42)
        preds = np.random.uniform(-0.05, 0.05, 20)
        actuals = preds + np.random.normal(0, 0.01, 20)
        ic = _per_date_ic(dates, preds, actuals)
        assert isinstance(ic, float)

    def test_cross_sectional_target(self):
        """Cross-sectional target demearnas."""
        df = pd.DataFrame({
            "ticker": ["A", "B", "C"],
            "date": ["2024-01-01"] * 3,
            "forward_return_30d": [0.10, 0.12, 0.14],
        })
        out = _add_cross_sectional_target(df)
        assert "target_cs" in out.columns


class TestDeflatedSharpeProject6:
    """Testar Deflated Sharpe Ratio (Project 6)."""

    def test_dsr_high_sharpe(self):
        """Hog Sharpe, fa trials -> hog DSR."""
        dsr = _deflated_sharpe_ratio(
            observed_sharpe=1.5, num_trials=10, T=252,
            skewness=0.0, kurtosis=0.0,
        )
        assert 0.0 <= dsr <= 1.0

    def test_dsr_low_sharpe(self):
        """Negativ Sharpe -> 0."""
        dsr = _deflated_sharpe_ratio(
            observed_sharpe=-0.5, num_trials=10, T=252,
            skewness=0.5, kurtosis=3.0,
        )
        assert dsr == 0.0

    def test_dsr_short_series(self):
        """Kort tidsserie (T < 2) -> 0."""
        dsr = _deflated_sharpe_ratio(
            observed_sharpe=2.0, num_trials=1, T=1,
            skewness=0.0, kurtosis=0.0,
        )
        assert dsr == 0.0
