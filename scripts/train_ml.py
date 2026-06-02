"""
train_ml.py -- Tränar ML-modell från träningsdataset.

Använd:
    python -m scripts.train_ml --universe universe
    python -m scripts.train_ml --universe smallcap

Förutsätter att data/ml/<universe>_training.parquet finns
(skapad av scripts.build_ml_dataset).

Sparar modell till models/ml_<universe>.pkl och loggar metrics.

Nya funktioner (PROJECT 1):
  - optimize_hyperparams: Optuna-baserad hyperparameteroptimering
  - bayesian_optimize_weights: Optimerar faktorvikter mot historisk avkastning
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ml_predictor import (  # noqa: E402
    TECH_FEATURES,
    MODELS_DIR,
    log_feature_importance,
    feature_permutation_importance,
    save_model,
    train_from_dataset,
    train_with_cpcv,
    train_sector_models,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


# ══════════════════════════════════════════════════════════════════════════════
# HYPERPARAMETER OPTIMIZATION  (PROJECT 1C)
# ══════════════════════════════════════════════════════════════════════════════

_PREDEFINED_GRID = {
    "n_estimators": [100, 200, 300, 500, 800],
    "max_depth": [3, 4, 5, 6, 8, 10],
    "learning_rate": [0.01, 0.03, 0.05, 0.1, 0.2, 0.3],
    "subsample": [0.6, 0.7, 0.8, 0.9, 1.0],
    "colsample_bytree": [0.6, 0.7, 0.8, 0.9, 1.0],
    "min_child_weight": [1, 3, 5, 7, 10],
    "gamma": [0.0, 0.5, 1.0, 2.0, 5.0],
    "reg_alpha": [0.0, 0.1, 1.0, 5.0, 10.0],
    "reg_lambda": [0.0, 0.1, 1.0, 5.0, 10.0],
}


def _has_optuna() -> bool:
    """Kontrollera om optuna är installerat."""
    try:
        import optuna  # noqa: F401
        return True
    except ImportError:
        return False


def _objective(
    trial: Any,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> float:
    """
    Optuna objective: predikterar IC på valideringsdata.

    Optuna föreslår hyperparametrar, vi tränar och returnerar
    Spearman-IC som målvariabel (högre = bättre).
    """
    try:
        import xgboost as xgb
        from scipy.stats import spearmanr
    except ImportError:
        return -999.0

    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 10.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.0, 10.0),
        "random_state": 42,
        "n_jobs": -1,
        "verbosity": 0,
    }

    try:
        model = xgb.XGBRegressor(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        preds = model.predict(X_val)
        ic_val, _ = spearmanr(preds, y_val)
        return float(ic_val) if not np.isnan(ic_val) else -1.0
    except Exception:
        return -1.0


def optimize_hyperparams(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    n_trials: int = 50,
) -> dict:
    """
    Optimerar XGBoost-hyperparametrar med Optuna eller GridSearchCV.

    Prioriterar Optuna om installerat (snabbare, batre resultat),
    faller tillbaka till sklearn GridSearchCV om optuna saknas.

    Args:
        X_train: Träningsdata.
        y_train: Trainings-target.
        X_val: Valideringsdata.
        y_val: Validerings-target.
        n_trials: Antal Optuna-trials (ignoreras om GridSearch anvands).

    Returns:
        Dict med:
          - 'best_params': dict av basta hyperparametrar
          - 'best_score': basta IC-vardet
          - 'method': 'optuna' eller 'grid_search'
          - 'n_trials': faktiskt antal utvarderade kombinationer
    """
    logger.info(f"Optimerar hyperparametrar (n_trials={n_trials}, method={'optuna' if _has_optuna() else 'grid_search'})")

    if _has_optuna():
        return _optimize_with_optuna(X_train, y_train, X_val, y_val, n_trials)
    else:
        logger.info("Optuna ej installerat -- anvander GridSearchCV med sklearn")
        return _optimize_with_grid_search(X_train, y_train, X_val, y_val)


def _optimize_with_optuna(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    n_trials: int = 50,
) -> dict:
    """Optimerar med Optuna."""
    import optuna

    # Skapa en wrapper sa att objective far en stangning over data
    def objective_wrapper(trial):
        return _objective(trial, X_train, y_train, X_val, y_val)

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=5),
    )
    study.optimize(objective_wrapper, n_trials=n_trials, show_progress_bar=False)

    best_params = study.best_params
    best_score = float(study.best_value)

    logger.info(
        f"Optuna klar: IC={best_score:.4f} efter {len(study.trials)} trials"
    )

    # Aterstall standardparametrar som inte optimerades
    best_params.setdefault("random_state", 42)
    best_params.setdefault("n_jobs", -1)
    best_params.setdefault("verbosity", 0)

    return {
        "best_params": best_params,
        "best_score": round(best_score, 4),
        "method": "optuna",
        "n_trials": len(study.trials),
    }


def _optimize_with_grid_search(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> dict:
    """Optimerar med sklearn GridSearchCV (fallback nar optuna saknas)."""
    try:
        from sklearn.model_selection import GridSearchCV
        from scipy.stats import spearmanr
        import xgboost as xgb
    except ImportError:
        logger.warning("Varken optuna eller sklearn GridSearchCV tillgangligt")
        return {"best_params": {}, "best_score": 0.0, "method": "none", "n_trials": 0}

    # Forenkla griden for GridSearch (annars blir det for manga kombinationer)
    param_grid = {
        "n_estimators": [100, 300, 500],
        "max_depth": [3, 5, 8],
        "learning_rate": [0.01, 0.05, 0.1],
        "subsample": [0.8, 1.0],
        "colsample_bytree": [0.8, 1.0],
    }

    # Slå ihop train + val for CV, anvand annars for mycket split
    X_all = np.vstack([X_train, X_val])
    y_all = np.concatenate([y_train, y_val])

    grid = GridSearchCV(
        xgb.XGBRegressor(random_state=42, n_jobs=-1, verbosity=0),
        param_grid=param_grid,
        scoring="neg_mean_squared_error",
        cv=3,
        n_jobs=-1,
        verbose=0,
    )
    grid.fit(X_all, y_all)

    # Beräkna IC pa valideringssetet med basta modellen
    best_model = grid.best_estimator_
    preds = best_model.predict(X_val)
    ic_val, _ = spearmanr(preds, y_val)
    best_score = float(ic_val) if not np.isnan(ic_val) else 0.0

    logger.info(
        f"GridSearch klar: IC={best_score:.4f}, "
        f"basta params: {grid.best_params_}"
    )

    return {
        "best_params": grid.best_params_,
        "best_score": round(best_score, 4),
        "method": "grid_search",
        "n_trials": np.prod([len(v) for v in param_grid.values()]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BAYESIAN FACTOR WEIGHT OPTIMIZATION  (PROJECT 1C)
# ══════════════════════════════════════════════════════════════════════════════

def _score_portfolio(weights: np.ndarray, factor_scores: np.ndarray,
                     target: np.ndarray) -> float:
    """
    Beräknar en portfoljs Sharpe baserat på faktorvikter.

    Args:
        weights: Faktorvikter (summerar till 1).
        factor_scores: (n_samples, n_factors) matris av faktorscores.
        target: Faktisk avkastning (n_samples,).

    Returns:
        Sharpe-kvot (högre = bättre vikter).
    """
    portfolio_score = factor_scores @ weights
    excess = portfolio_score - target
    if excess.std() < 1e-10:
        return -999.0
    sharpe = excess.mean() / excess.std()
    return float(sharpe)


def bayesian_optimize_weights(
    scoring_df: pd.DataFrame,
    target_col: str = "forward_return_30d",
    n_iterations: int = 100,
    random_state: int = 42,
) -> dict:
    """
    Optimerar faktorvikter mot historisk avkastning.

    Använder Bayesisk optimering (via Optuna eller random search) for att
    hitta faktorvikter som maximerar portfoljens Sharpe-kvot mot faktisk
    avkastning.

    Args:
        scoring_df: DataFrame med faktorscores- och target-kolumner.
                    Måste innehålla factor-weight-kolumner som slutar med '_score'
                    eller '_rank' (t.ex. 'value_score', 'momentum_rank').
        target_col: Kolumnnamn för target (historisk avkastning).
        n_iterations: Antal optimeringsiterationer.
        random_state: Fro for reproducibilitet.

    Returns:
        Dict med:
          - 'best_weights': {factor_name: weight} av de optimerade vikterna
          - 'best_score': basta uppnådda Sharpe
          - 'method': 'optuna' eller 'random_search'
          - 'n_iterations': antal iterationer
    """
    # Hitta faktor-kolumner i DataFrame
    factor_cols = [
        c for c in scoring_df.columns
        if c.endswith("_score") or c.endswith("_rank")
    ]
    # Exkludera specialkolumner
    factor_cols = [
        c for c in factor_cols
        if not c.startswith("ml_") and c not in ("total_score", "final_score")
    ]

    if not factor_cols:
        logger.warning("Inga faktorkolumner hittades i scoring_df")
        return {}

    df = scoring_df.dropna(subset=factor_cols + [target_col]).copy()
    if df.empty or len(df) < 10:
        logger.warning(f"För lite data för viktoptimering: {len(df)} rader")
        return {}

    factor_names = [c.replace("_score", "").replace("_rank", "") for c in factor_cols]
    logger.info(
        f"Optimerar vikter for {len(factor_cols)} faktorer "
        f"({', '.join(factor_names)}), {n_iterations} iterationer"
    )

    # Normalisera faktorscores till 0-100
    factor_scores = df[factor_cols].values
    target = df[target_col].values

    # Antal faktorer
    n_factors = len(factor_cols)

    best_score = -999.0
    best_weights = None

    if _has_optuna():
        # Optuna-baserad optimering
        import optuna

        def optuna_objective(trial):
            # Föreslå vikter som är > 0 och summerar till 1
            weights = np.array([
                trial.suggest_float(f"w_{i}", 0.0, 1.0)
                for i in range(n_factors)
            ])
            weights = weights / (weights.sum() + 1e-10)
            return _score_portfolio(weights, factor_scores, target)

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=random_state),
        )
        study.optimize(optuna_objective, n_trials=n_iterations, show_progress_bar=False)

        best_weights = np.array([
            study.best_params.get(f"w_{i}", 1.0 / n_factors)
            for i in range(n_factors)
        ])
        best_weights = best_weights / (best_weights.sum() + 1e-10)
        best_score = float(study.best_value)
        method = "optuna"

    else:
        # Random search med bayesiansk sampling (skog)
        rng = np.random.default_rng(random_state)

        for _ in range(n_iterations):
            # Dirichlet-fördelning (garanterar sum=1)
            raw = rng.exponential(1.0, size=n_factors)
            weights = raw / raw.sum()
            score = _score_portfolio(weights, factor_scores, target)
            if score > best_score:
                best_score = score
                best_weights = weights.copy()

        method = "random_search"

    # Skapa output-dict
    result = {
        "best_weights": {
            name: round(float(w), 4)
            for name, w in zip(factor_names, best_weights)
        },
        "best_score": round(float(best_score), 4),
        "method": method,
        "n_iterations": n_iterations,
    }

    # Spara till best_params.json
    params_file = MODELS_DIR / "best_params.json"
    existing = {}
    if params_file.exists():
        try:
            existing = json.loads(params_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing["factor_weights"] = result["best_weights"]
    existing["factor_optimization_score"] = result["best_score"]
    existing["factor_optimization_method"] = method
    params_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Basta vikter: {result['best_weights']}")
    logger.info(f"Basta Sharpe: {result['best_score']:.4f}")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING (UTOKAD)
# ══════════════════════════════════════════════════════════════════════════════

def train(
    universe: str,
    parquet_path: Path | None = None,
    use_cpcv: bool = True,
    optimize_hp: bool = False,
    n_hp_trials: int = 50,
) -> dict:
    """
    Tranar ML-modell for givet universum, med valfri hyperparameteroptimering.

    Args:
        universe: 'universe' eller 'smallcap'.
        parquet_path: Sokvag till traningsdata.
        use_cpcv: Anvand CPCV-validering (default True).
        optimize_hp: Kor hyperparameteroptimering innan slutgiltig traning.
        n_hp_trials: Antal optimeringsiterationer.

    Returns:
        Dict med metrics.
    """
    parquet_path = parquet_path or (ROOT / "data" / "ml" / f"{universe}_training.parquet")
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Träningsdata saknas: {parquet_path}\n"
            f"Kör först: python -m scripts.build_ml_dataset --universe {universe}"
        )

    # Ladda data for hyperparameteroptimering
    if optimize_hp:
        df = pd.read_parquet(parquet_path)
        if not df.empty:
            # Forbered data
            from core.ml_predictor import _add_cross_sectional_target
            df = df.dropna(subset=["forward_return_30d"]).copy()
            df = df[df["forward_return_30d"].between(-0.9, 5.0)]
            df = _add_cross_sectional_target(df)
            df = df.sort_values("date")
            split_idx = int(len(df) * 0.8)
            train_df, val_df = df.iloc[:split_idx], df.iloc[split_idx:]

            X_tr = train_df[TECH_FEATURES].fillna(0).values
            y_tr = train_df["target_cs"].values
            X_val = val_df[TECH_FEATURES].fillna(0).values
            y_val = val_df["target_cs"].values

            hp_result = optimize_hyperparams(X_tr, y_tr, X_val, y_val, n_trials=n_hp_trials)

            # Spara bästa parametrar
            best_params = hp_result.get("best_params", {})
            if best_params:
                params_file = MODELS_DIR / "best_params.json"
                existing = {}
                if params_file.exists():
                    try:
                        existing = json.loads(params_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                existing[f"{universe}_hp"] = {
                    "params": best_params,
                    "ic_score": hp_result.get("best_score", 0.0),
                    "method": hp_result.get("method", "unknown"),
                }
                params_file.write_text(
                    json.dumps(existing, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

            logger.info(f"HP-optimering klar: {hp_result}")

    if use_cpcv:
        logger.info(f"Tränar {universe}-modell med CPCV från {parquet_path}")
        trained = train_with_cpcv(parquet_path, universe)
    else:
        logger.info(f"Tränar {universe}-modell (enkel tidssplit) från {parquet_path}")
        trained = train_from_dataset(parquet_path, universe)

    if trained is None:
        raise RuntimeError("Träning misslyckades (för lite data eller felaktig struktur)")

    save_model(trained, universe)

    # Spara metrics + metadata
    metrics_file = MODELS_DIR / f"ml_{universe}_metrics.json"
    metrics_file.write_text(json.dumps({
        "universe": trained.universe,
        "trained_at": trained.trained_at,
        "n_rows": trained.n_rows,
        "feature_cols": trained.feature_cols,
        "test_metrics": trained.test_metrics,
    }, indent=2))
    logger.info(f"Metrics: {metrics_file}")

    # Logga feature importance (Project 1B) -- alltid vid traning
    try:
        if hasattr(trained.model, "feature_importances_"):
            feat_imp = log_feature_importance(
                trained.model,
                trained.feature_cols,
                output_path=MODELS_DIR / "feature_importance.json",
            )
            if feat_imp:
                top_5 = list(feat_imp.items())[:5]
                logger.info(f"  Top-5 features: {top_5}")
    except Exception as e:
        logger.warning(f"Feature importance misslyckades: {e}")

    return trained.test_metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["universe", "smallcap"], required=True)
    ap.add_argument("--parquet", type=Path, default=None,
                    help="Sökväg till träningsdata (default: data/ml/<universe>_training.parquet)")
    ap.add_argument("--sectors", action="store_true",
                    help="Träna även per-sektor-modeller")
    ap.add_argument("--optimize-hp", action="store_true",
                    help="Kör hyperparameteroptimering före träning")
    ap.add_argument("--hp-trials", type=int, default=50,
                    help="Antal Optuna-trials för hyperparameteroptimering")
    ap.add_argument("--optimize-weights", action="store_true",
                    help="Optimera faktorvikter mot historisk avkastning")
    args = ap.parse_args()

    metrics = train(args.universe, args.parquet, optimize_hp=args.optimize_hp,
                    n_hp_trials=args.hp_trials)
    print(json.dumps(metrics, indent=2))

    if args.optimize_weights:
        # Ladda senaste scored_universe for viktoptimering
        reports_dir = ROOT / "reports"
        scored_files = sorted(reports_dir.glob("scored_universe_*.csv"), reverse=True)
        if scored_files:
            logger.info("Optimerar faktorvikter...")
            scoring_df = pd.read_csv(scored_files[0])
            weight_result = bayesian_optimize_weights(scoring_df)
            print(json.dumps(weight_result, indent=2))

    # Per-sektor-modeller
    if args.sectors and args.universe == "universe":
        parquet = args.parquet or (ROOT / "data" / "ml" / f"{args.universe}_training.parquet")
        logger.info("Tränar per-sektor-modeller...")
        sector_metrics = train_sector_models(parquet)
        print(json.dumps({"sector_models": sector_metrics}, indent=2))


if __name__ == "__main__":
    main()
