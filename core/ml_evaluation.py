"""
ml_evaluation.py — Rigorös modell-utvärdering för MarketScan ML

Jämför gamla XGBoost-regressorn mot nya LightGBM-rankern med:
  - Per-datum Spearman IC (rankkorrelation)
  - IC Information Ratio (IR = IC.mean() / IC.std())
  - Decil-spread: topp-20% vs botten-20% genomsnittsavkastning
  - Hit-rate: andel korrekt rankade aktier (> medianen)
  - Kumulativ IC-trend (visar om edge är stabil över tid)

Gate-kriterier för deployment:
  - Ny modell måste slå gamla på IC OCH decil-spread (walk-forward, OOS)
  - Statistisk test: p-value < 0.05 på IC (t-test, one-sided)

Anrop:
    python -m scripts.eval_model
    python -m scripts.eval_model --universe smallcap --plot

Modified: evaluate_model uses purged_walk_forward_folds (Lopez de Prado embargo).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from core.ml_validation import purged_walk_forward_folds

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


# ── Hjälpfunktioner ──────────────────────────────────────────────────────────

def per_date_ic(
    df: pd.DataFrame,
    pred_col: str = "pred",
    actual_col: str = "actual",
    date_col: str = "date",
    min_per_date: int = 5,
) -> pd.Series:
    """Beräknar Spearman IC för varje datum. Returnerar Series indexerad på datum."""
    try:
        from scipy.stats import spearmanr
    except ImportError:
        raise RuntimeError("scipy krävs för IC-beräkning: pip install scipy")

    ics: dict = {}
    for date, group in df.groupby(date_col):
        if len(group) < min_per_date:
            continue
        if group[pred_col].nunique() < 2 or group[actual_col].nunique() < 2:
            continue
        ic, _ = spearmanr(group[pred_col], group[actual_col])
        if not np.isnan(ic):
            ics[date] = float(ic)
    return pd.Series(ics, name="ic").sort_index()


def decile_returns(
    df: pd.DataFrame,
    pred_col: str = "pred",
    actual_col: str = "actual",
    date_col: str = "date",
    n_deciles: int = 5,
    min_per_date: int = 5,
) -> pd.DataFrame:
    """Beräknar genomsnittlig avkastning per decil (genomsnitt över alla datum).

    Returns:
        DataFrame med kolumner: decile (0..n-1), avg_return, count
    """
    all_rows = []
    for _, group in df.groupby(date_col):
        if len(group) < min_per_date:
            continue
        group = group.copy()
        try:
            group["decile"] = pd.qcut(
                group[pred_col].rank(method="first"),
                n_deciles, labels=False, duplicates="drop"
            )
        except Exception:
            continue
        for decile, dg in group.groupby("decile"):
            all_rows.append({"decile": int(decile), "return": float(dg[actual_col].mean())})

    if not all_rows:
        return pd.DataFrame({"decile": range(n_deciles), "avg_return": [0.0] * n_deciles})

    result = (
        pd.DataFrame(all_rows)
        .groupby("decile")["return"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "avg_return", "count": "n_dates"})
    )
    return result


def decile_spread(
    df: pd.DataFrame,
    pred_col: str = "pred",
    actual_col: str = "actual",
    date_col: str = "date",
    min_per_date: int = 5,
) -> float:
    """Topp-quintil minus botten-quintil genomsnittsavkastning (per datum, medel)."""
    spreads = []
    for _, group in df.groupby(date_col):
        if len(group) < min_per_date:
            continue
        sorted_g = group.sort_values(pred_col)
        n = len(sorted_g)
        q = max(1, n // 5)
        bottom_ret = sorted_g[actual_col].iloc[:q].mean()
        top_ret    = sorted_g[actual_col].iloc[-q:].mean()
        spreads.append(top_ret - bottom_ret)
    return float(np.mean(spreads)) if spreads else 0.0


def ic_significance(ic_series: pd.Series) -> dict:
    """t-test för IC ≠ 0 (one-sided: IC > 0).

    Returns dict med mean, std, ir (information ratio), t_stat, p_value.
    """
    try:
        from scipy import stats
    except ImportError:
        return {}

    if len(ic_series) < 3:
        return {"mean": float(ic_series.mean()), "std": 0.0, "ir": 0.0, "t_stat": 0.0, "p_value": 1.0}

    mean = float(ic_series.mean())
    std  = float(ic_series.std())
    ir   = mean / std if std > 0 else 0.0
    t_stat, p_two_sided = stats.ttest_1samp(ic_series.dropna(), 0)
    p_one_sided = float(p_two_sided) / 2.0  # one-sided: H1 = IC > 0

    return {
        "mean":       round(mean, 4),
        "std":        round(std, 4),
        "ir":         round(ir, 4),
        "t_stat":     round(float(t_stat), 4),
        "p_value":    round(p_one_sided, 4),
        "n_periods":  len(ic_series),
        "significant": p_one_sided < 0.05,
    }


# ── Modell-jämförelse ─────────────────────────────────────────────────────────

def evaluate_model(
    parquet_path: Path,
    universe: str = "universe",
    model_type: str = "ranker",   # "ranker" eller "xgboost"
    initial_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
) -> dict:
    """Walk-forward utvärdering av en modell mot träningsdataset.

    Tränar om modellen på varje fold och mäter OOS IC.
    ALDRIG in-sample (forward-looking bias undviks).

    Args:
        parquet_path:    Träningsdata (date, ticker, features, forward_return_30d).
        universe:        "universe" eller "smallcap".
        model_type:      "ranker" (LightGBM) eller "xgboost".
        initial_months:  Minsta träningsperiod.
        test_months:     Längd på testfönster.
        step_months:     Steg mellan foldarna.

    Returns:
        Dict med ic_series, decile_results, summary_stats.
    """
    if not parquet_path.exists():
        logger.error("Träningsdata saknas: %s", parquet_path)
        return {}

    df = pd.read_parquet(parquet_path)
    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df[df["forward_return_30d"].between(-0.9, 5.0)]
    df = df.sort_values("date").reset_index(drop=True)

    if model_type == "ranker":
        from core.ml_ranker import RANKER_FEATURES, _fit_model
        feature_cols = [c for c in RANKER_FEATURES if c in df.columns]
        fit_fn = _fit_model
    else:
        from core.ml_predictor import TECH_FEATURES
        from core.ml_predictor import _make_regressor, _add_cross_sectional_target
        feature_cols = [c for c in TECH_FEATURES if c in df.columns]

        def fit_fn(train_df, feat_cols):
            train_df = _add_cross_sectional_target(train_df)
            X = train_df[feat_cols].fillna(0).values
            y = train_df["target_cs"].values
            m = _make_regressor()
            m.fit(X, y)
            return m, "xgboost"

    all_preds_rows = []

    folds = purged_walk_forward_folds(
        df, date_col="date",
        initial_months=initial_months,
        test_months=test_months,
        step_months=step_months,
    )

    for fold in folds:
        train_df = df.loc[fold.train_idx].copy()
        test_df = df.loc[fold.test_idx].copy()

        if len(train_df) < 200 or len(test_df) < 20:
            continue

        model, _ = fit_fn(train_df, feature_cols)
        if model is None:
            continue

        X_test = test_df[feature_cols].fillna(0).values.astype(np.float32)
        try:
            preds = model.predict(X_test)
        except Exception:
            continue

        for i, (idx, row) in enumerate(test_df.iterrows()):
            all_preds_rows.append({
                "date":   row["date"],
                "pred":   float(preds[i]),
                "actual": float(row["forward_return_30d"]),
            })

    if not all_preds_rows:
        logger.warning("Inga walk-forward-prediktioner för %s/%s", universe, model_type)
        return {}

    all_df = pd.DataFrame(all_preds_rows)

    # IC-analys
    ic_series = per_date_ic(all_df)
    ic_stats = ic_significance(ic_series)

    # Decil-analys
    dec_df = decile_returns(all_df)
    spread = decile_spread(all_df)

    return {
        "model_type":    model_type,
        "universe":      universe,
        "ic_series":     ic_series.to_dict(),
        "ic_stats":      ic_stats,
        "decile_returns": dec_df.to_dict(orient="records"),
        "decile_spread": round(spread, 4),
        "n_predictions": len(all_df),
        "n_dates":       all_df["date"].nunique(),
    }


def compare_models(
    parquet_path: Path,
    universe: str = "universe",
) -> dict:
    """Kör walk-forward för båda modellerna och jämför.

    Returns dict med 'ranker', 'xgboost', 'winner', 'summary'.
    """
    logger.info("Utvärderar LightGBM-ranker...")
    ranker_result = evaluate_model(parquet_path, universe, "ranker")

    logger.info("Utvärderar XGBoost-regressor...")
    xgb_result = evaluate_model(parquet_path, universe, "xgboost")

    if not ranker_result or not xgb_result:
        return {"ranker": ranker_result, "xgboost": xgb_result, "winner": "unknown"}

    ranker_ic = ranker_result["ic_stats"].get("mean", 0.0)
    xgb_ic    = xgb_result["ic_stats"].get("mean", 0.0)
    ranker_spread = ranker_result.get("decile_spread", 0.0)
    xgb_spread    = xgb_result.get("decile_spread", 0.0)

    # Ny modell vinner om den slår på BÅDA metrics
    ranker_wins = (ranker_ic > xgb_ic) and (ranker_spread > xgb_spread)
    winner = "ranker" if ranker_wins else "xgboost"

    summary = {
        "ranker_ic":      round(ranker_ic, 4),
        "xgboost_ic":     round(xgb_ic, 4),
        "ic_improvement": round(ranker_ic - xgb_ic, 4),
        "ranker_spread":  round(ranker_spread, 4),
        "xgboost_spread": round(xgb_spread, 4),
        "ranker_significant": ranker_result["ic_stats"].get("significant", False),
        "winner":         winner,
        "deploy_ranker":  ranker_wins,
    }

    return {
        "ranker":  ranker_result,
        "xgboost": xgb_result,
        "winner":  winner,
        "summary": summary,
    }
