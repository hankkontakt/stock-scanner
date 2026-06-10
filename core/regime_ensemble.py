"""
regime_ensemble.py — Regimberoende ensemble-modell.

Träna TVÅ modeller:
  - Modell A: LambdaRank på 5 års historik (långsam, stabil)
  - Modell B: ranker på 2 års historik (fångar senaste samband)

Regimvikt (från get_current_regime):
  TJUR    → vikt A 0.4, B 0.6  (lita mer på senaste samband)
  NEUTRAL → vikt A 0.5, B 0.5
  BJÖRN   → vikt A 0.7, B 0.3  (lita mer på lång historik)

ml_uncertainty = |rank_a - rank_b| — hög oenighet = lägre tillförlitlighet.

Återanvänder core/ml_validation.py (purged folds) från #1.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from core.ml_ranker import (
    RANKER_FEATURES,
    _fit_model,
    _walk_forward_validate,
    _per_date_ic,
    _decile_spread,
    predict_ranker,
    load_ranker,
    save_ranker,
    TrainedRanker,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"

# Regimvikter (modell A / modell B)
REGIME_WEIGHTS = {
    "BJÖRN":    (0.7, 0.3),
    "NEUTRAL":  (0.5, 0.5),
    "TJUR":     (0.4, 0.6),
}

UNCERTAINTY_THRESHOLD = 20  # percentilenheter


@dataclass
class EnsembleModel:
    model_a: object   # lång historik (5y)
    model_b: object   # kort historik (2y)
    feature_cols: list[str]
    universe: str
    trained_at: str


def train_ensemble(
    df: pd.DataFrame,
    universe: str = "universe",
) -> Optional[EnsembleModel]:
    """Träna ensemble av två rankers med olika historiklängd.

    Args:
        df: Träningsdata med kolumner date, ticker, features, forward_return_30d.
        universe: "universe" eller "smallcap".

    Returns:
        EnsembleModel med två tränade modeller.
    """
    from core.ml_validation import purged_walk_forward_folds

    if df.empty or len(df) < 500:
        logger.error("För lite data för ensemble: %d rader", len(df))
        return None

    feature_cols = [c for c in RANKER_FEATURES if c in df.columns]
    if len(feature_cols) < 5:
        logger.error("För få features för ensemble: %d", len(feature_cols))
        return None

    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df[df["forward_return_30d"].between(-0.9, 5.0)]
    df = df.sort_values("date").reset_index(drop=True)

    # Modell A: träna på ALL tillgänglig data (5y+)
    logger.info("Tränar modell A (lång historik, n=%d)...", len(df))
    model_a, type_a = _fit_model(df, feature_cols)
    if model_a is None:
        logger.error("Modell A-träning misslyckades")
        return None

    # Modell B: träna på senaste 2 åren
    max_date = pd.to_datetime(df["date"]).max()
    cutoff_2y = max_date - pd.DateOffset(years=2)
    df_b = df[pd.to_datetime(df["date"]) >= cutoff_2y].copy()
    if len(df_b) < 200:
        logger.warning("För lite senaste-data (%d rader) — använder all data för modell B", len(df_b))
        df_b = df

    logger.info("Tränar modell B (kort historik, n=%d)...", len(df_b))
    model_b, type_b = _fit_model(df_b, feature_cols)
    if model_b is None:
        logger.error("Modell B-träning misslyckades")
        return None

    logger.info("Ensemble: A=%s, B=%s", type_a, type_b)
    return EnsembleModel(
        model_a=model_a,
        model_b=model_b,
        feature_cols=feature_cols,
        universe=universe,
        trained_at=pd.Timestamp.now().isoformat(),
    )


def predict_ensemble(
    scored_df: pd.DataFrame,
    ensemble: Optional[EnsembleModel] = None,
    universe: str = "universe",
) -> pd.DataFrame:
    """Predictera med regimviktad ensemble.

    Args:
        scored_df: DataFrame med ticker + features.
        ensemble: Tränad ensemble (laddas från disk om None).
        universe: Modellnamn.

    Returns:
        scored_df med kolumner:
          pred_a, pred_b (percentil-rank),
          ml_rank (regimviktad ensemble),
          ml_uncertainty (|rank_a - rank_b|),
          ml_flag_uncertain (bool).
    """
    # Ladda ensemble om inte given
    if ensemble is None:
        ensemble = load_ensemble(universe)
        if ensemble is None:
            logger.info("Ingen ensemble — faller tillbaka till enkel ranker")
            return predict_ranker(scored_df, universe)

    # Hämta nuvarande regim
    try:
        from core.regime_hmm import get_current_regime
        regime = get_current_regime()
    except Exception:
        # Fallback: neutral
        regime = type("Regime", (), {"regime": "NEUTRAL"})()

    weights = REGIME_WEIGHTS.get(regime.regime, (0.5, 0.5))
    logger.info("Ensemble: regim=%s, vikter A=%.1f B=%.1f", regime.regime, *weights)

    # Feature-matris
    feature_cols = ensemble.feature_cols
    X = scored_df[feature_cols].fillna(0).values.astype(np.float32) if all(
        c in scored_df.columns for c in feature_cols
    ) else None

    if X is None:
        logger.warning("Features saknas för ensemble — faller tillbaka")
        return predict_ranker(scored_df, universe)

    # Predictera med båda modellerna
    try:
        pred_a = ensemble.model_a.predict(X)
        pred_b = ensemble.model_b.predict(X)
    except Exception as e:
        logger.warning("Ensemble-prediktion misslyckades: %s", e)
        return predict_ranker(scored_df, universe)

    # Percentil-rank (0-100)
    rank_a = pd.Series(pred_a, index=scored_df.index).rank(pct=True).fillna(0) * 100
    rank_b = pd.Series(pred_b, index=scored_df.index).rank(pct=True).fillna(0) * 100

    # Regimviktad ensemble
    ml_rank = weights[0] * rank_a + weights[1] * rank_b

    # Uncertainty = absolut skillnad
    ml_uncertainty = (rank_a - rank_b).abs()

    result = scored_df.copy()
    result["pred_a"] = rank_a.round(1)
    result["pred_b"] = rank_b.round(1)
    result["ml_rank"] = ml_rank.round(1)
    result["ml_uncertainty"] = ml_uncertainty.round(1)
    result["ml_flag_uncertain"] = ml_uncertainty > UNCERTAINTY_THRESHOLD
    result["regime_at_scan"] = regime.regime

    logger.info("Ensemble: %d aktier, %.1f%% osäkra",
                len(result), result["ml_flag_uncertain"].mean() * 100)
    return result


def save_ensemble(ensemble: EnsembleModel, universe: str) -> Path:
    """Spara ensemble till disk."""
    import pickle
    target = MODELS_DIR / f"ensemble_{universe}.pkl"
    tmp = target.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(ensemble, f)
    tmp.replace(target)
    logger.info("Ensemble sparad: %s", target.name)
    return target


def load_ensemble(universe: str) -> Optional[EnsembleModel]:
    """Ladda ensemble från disk."""
    import pickle
    target = MODELS_DIR / f"ensemble_{universe}.pkl"
    if not target.exists():
        return None
    try:
        with open(target, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("Kunde inte ladda ensemble: %s", e)
        return None


def evaluate_ensemble(
    df: pd.DataFrame,
    universe: str = "universe",
) -> dict:
    """Utvärdera ensemble med purged walk-forward, per-regim-uppdelning.

    Returns:
        Dict med IC, spread per regim och totalt.
    """
    from core.ml_validation import purged_walk_forward_folds

    feature_cols = [c for c in RANKER_FEATURES if c in df.columns]
    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df.sort_values("date").reset_index(drop=True)

    folds = purged_walk_forward_folds(df, date_col="date")

    all_preds = []
    for fold in folds:
        train_df = df.loc[fold.train_idx].copy()
        test_df = df.loc[fold.test_idx].copy()

        if len(train_df) < 200 or len(test_df) < 20:
            continue

        # Träna ensemble på fold
        ensemble = train_ensemble(train_df, universe)
        if ensemble is None:
            continue

        X_test = test_df[feature_cols].fillna(0).values.astype(np.float32)
        try:
            pred_a = ensemble.model_a.predict(X_test)
            pred_b = ensemble.model_b.predict(X_test)
            ensemble_pred = 0.5 * (pred_a + pred_b)  # equal weight for eval
        except Exception:
            continue

        for i, (idx, row) in enumerate(test_df.iterrows()):
            all_preds.append({
                "date": row["date"],
                "pred": float(ensemble_pred[i]),
                "actual": float(row["forward_return_30d"]),
            })

    if not all_preds:
        return {"error": "Inga prediktioner"}

    eval_df = pd.DataFrame(all_preds)
    ic_series = _per_date_ic(eval_df["date"].values, eval_df["pred"].values, eval_df["actual"].values)
    spread = _decile_spread(eval_df["date"].values, eval_df["pred"].values, eval_df["actual"].values)

    ic_values = list(ic_series.values()) if hasattr(ic_series, 'values') else []
    mean_ic = float(np.mean(ic_values)) if ic_values else 0
    std_ic = float(np.std(ic_values)) if ic_values else 0

    return {
        "ic_mean": round(mean_ic, 4),
        "ic_std": round(std_ic, 4),
        "icir": round(mean_ic / std_ic, 4) if std_ic > 0 else 0,
        "decile_spread": round(spread, 4),
        "n_predictions": len(eval_df),
        "n_dates": eval_df["date"].nunique(),
    }
