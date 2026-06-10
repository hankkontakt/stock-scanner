"""
ml_ranker.py — LightGBM LambdaRank learning-to-rank scoring-hjärna
====================================================================

Nästa-gen scoringmodell. Tränas som ett RANKINGPROBLEM (LightGBM
LambdaRank/NDCG) istf regression — optimerar direkt för att rangordna
aktier korrekt RELATIVT varandra inom samma datum.

Förbättringar vs XGBoost-regressorn (ml_predictor.py):
  1. Ranking-objektiv: förstår att ordning är viktigare än nivåer
  2. 8 faktor-delscorer som extra-features (value, quality, momentum…)
  3. 1 regim-feature (makro-läge: björn/tjur/neutral)
  4. Walk-forward validering (riktig tidsseriekorrigering)
  5. Fallback till XGBoost om LightGBM ej installerat

IC-mål: > 0.05  (nuvarande XGBoost CPCV: 0.027)
Decil-spread mål: topp-decil > botten-decil med statistisk marginal

Träning:
  python -m scripts.train_ranker --universe universe
  (bygger modell → models/ml_ranker_universe.pkl)

Inference:
  from core.ml_ranker import predict_ranker
  df_with_scores = predict_ranker(scored_df)  # snabb, inga extra DL
"""

from __future__ import annotations

import datetime
import json
import logging
import math
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ── Feature-definitioner ─────────────────────────────────────────────────────

# Tekniska features (importerade från ml_predictor för bakåtkompatibilitet)
from core.ml_predictor import (
    TECH_FEATURES,
    compute_features_at,
    _load_features_from_cache,
    _per_date_ic,
    SAMPLE_WEIGHT_HALFLIFE_YEARS,
)

# Faktor-delscorer: beräknas av scoring.py, finns alltid i scored_universe.parquet.
# Detta är den viktigaste utökningen — de 8 dimensionerna sammanfattar fundamental-
# och teknisk kvalitet på ett robust, jämförbart sätt.
FACTOR_SCORE_FEATURES: list[str] = [
    "score_value",
    "score_quality",
    "score_momentum",
    "score_growth",
    "score_risk",
    "score_size",
    "score_dividend",
    "score_sentiment",
]

# Makro-regim (0.0 = björn, 1.0 = tjur, 0.5 = neutral)
REGIME_FEATURES: list[str] = ["regime_score"]

# Extra signalfeatures från andra system (#5 FI-insiderkluster, #3 MEWS, #7 kvalitativ analys)
# Dessa läggs till i RANKER_FEATURES OM de finns i datasetet.
# VIKTIGT: Dessa är bara backtest-säkra om historiskt laggade värden finns.
# Se BACKTEST_SAFE_FEATURES för detaljer.
EXTRA_SIGNAL_FEATURES: list[str] = [
    "insider_cluster",    # 0/1 — FI insiderkluster (#5)
    "cluster_score",      # kontinuerlig — klusterstyrka (#5)
    "qualitative_score",  # 0–100 — rapportkvalitet (#7)
    "mews_score",         # 0–100 — MEWS mångdubblar-score (#3)
]

# Features som är säkra att använda i backtest (historik finns).
# EXTRA_SIGNAL_FEATURES är ENDAST backtest-säkra om historiskt laggade data finns
# i träningsdatasetet. I live-inference används de alltid om kolumnen finns.
# Om en feature INTE är BACKTEST_SAFE, används den ENDAST i live-inference.
BACKTEST_SAFE_FEATURES: list[str] = [
    # Tekniska features är alltid backtest-säkra (beräknas från OHLCV-historia)
    *TECH_FEATURES,
    # Factor scores från scoring.py — beräknade vid varje historiskt datum
    *FACTOR_SCORE_FEATURES,
    # Regim-score från macro_regime — historiskt beräkningsbar
    *REGIME_FEATURES,
    # MEWS: historiskt laggade värden om datasetet har dem
    "mews_score",
    # Insider-kluster: ENDAST om datasetet har historiskt laggade värden
    # (annars endast live-inference)
]

# Alla ranker-features (35 baseline + extra signaler om de finns i datasetet)
RANKER_FEATURES: list[str] = list(dict.fromkeys(
    TECH_FEATURES + FACTOR_SCORE_FEATURES + REGIME_FEATURES + EXTRA_SIGNAL_FEATURES
))

# Halvlivstid för exponentiell tidsviktning
RANKER_HALFLIFE_YEARS: float = 2.0

# Minsta antal stocks i en datumgrupp för att tas med i träning
MIN_GROUP_SIZE: int = 5


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TrainedRanker:
    """Wrapper kring tränad LightGBM/XGBoost ranker + metadata."""
    model: object
    feature_cols: list[str]
    universe: str
    trained_at: str
    n_rows: int
    test_metrics: dict


# ── Hjälpfunktioner ──────────────────────────────────────────────────────────

def _quintile_label(series: pd.Series) -> pd.Series:
    """Konverterar avkastningar till 0-4 quintile-etiketter (kräver non-negative int).

    0 = bottendecil (sämst), 4 = toppecil (bäst).
    Duplicates='drop' hanterar aktier med identisk avkastning.
    """
    try:
        return pd.qcut(series.rank(method="first"), 5, labels=False, duplicates="drop").fillna(2).astype(int)
    except Exception:
        # Fallback om qcut misslyckas (för få unika värden)
        median = series.median()
        return (series > median).astype(int) * 4


def _build_lgbm_dataset(df: pd.DataFrame, feature_cols: list[str]):
    """Bygg LightGBM Dataset med korrekt group-struktur.

    Data MÅSTE vara sorterad efter date innan detta anropas.
    Group = antal stocks per datum (cross-sectional query-grupper).
    """
    try:
        import lightgbm as lgb
    except ImportError:
        return None, None, None

    # Etiketter per datum-grupp (0-4 quintile av forward_return_30d)
    df = df.copy()
    df["label"] = df.groupby("date")["forward_return_30d"].transform(_quintile_label)

    # Group sizes (antal aktier per datum)
    group_sizes = df.groupby("date", sort=False).size().values.tolist()

    X = df[feature_cols].fillna(0).values.astype(np.float32)
    y = df["label"].values.astype(np.float32)

    dataset = lgb.Dataset(
        X, label=y,
        group=group_sizes,
        feature_name=feature_cols,
        free_raw_data=False,
    )
    return dataset, X, y


def _compute_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Träning ───────────────────────────────────────────────────────────────────

def train_ranker(
    parquet_path: Path,
    universe: str,
    df: Optional[pd.DataFrame] = None,
) -> Optional[TrainedRanker]:
    """Tränar LightGBM LambdaRank-modell. Fallback till XGBoost-regressor.

    Args:
        parquet_path: Sökväg till träningsdata (date, ticker, features, forward_return_30d).
                      Ignoreras om df ges direkt.
        universe:     "universe" eller "smallcap" — används för metadata och filnamn.
        df:           DataFrame att träna på (om du inte vill läsa från disk).

    Returns:
        TrainedRanker med walk-forward IC/decil-spread i test_metrics, eller None.
    """
    # ── Ladda data ──────────────────────────────────────────────────────────
    if df is None:
        if not parquet_path.exists():
            logger.error("Saknar träningsdata: %s", parquet_path)
            return None
        df = pd.read_parquet(parquet_path)

    if df.empty or len(df) < 200:
        logger.error("För lite träningsdata: %d rader", len(df))
        return None

    required = {"forward_return_30d", "date"}
    if not required.issubset(df.columns):
        logger.error("Saknar kolumner: %s", required - set(df.columns))
        return None

    # ── Feature-selektion ────────────────────────────────────────────────────
    # Använd tillgängliga features: tech + factor scores om de finns i datasetet
    feature_cols = [c for c in RANKER_FEATURES if c in df.columns]
    if len(feature_cols) < 5:
        logger.warning("Bara %d features tillgängliga — kör med: %s", len(feature_cols), feature_cols)
        feature_cols = [c for c in TECH_FEATURES if c in df.columns]
    logger.info("  Features (%d): %s", len(feature_cols), feature_cols[:8])

    # ── Rensa data ───────────────────────────────────────────────────────────
    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df[df["forward_return_30d"].between(-0.9, 5.0)]
    df = df.sort_values("date").reset_index(drop=True)

    # Filtrera bort datum med för få aktier (ger meningslösa grupper)
    counts = df.groupby("date")["date"].transform("count")
    df = df[counts >= MIN_GROUP_SIZE].copy()

    if len(df) < 200:
        logger.error("För lite data efter filtrering: %d rader", len(df))
        return None

    # ── Walk-forward validering ──────────────────────────────────────────────
    # Rullande train→test: 24 mån initial träning, 6 mån test, step 6 mån.
    # Ger riktig out-of-sample IC utan forward-looking bias.
    wf_results = _walk_forward_validate(df, feature_cols)

    avg_ic     = round(float(np.mean([r["ic"] for r in wf_results])), 4) if wf_results else 0.0
    avg_spread = round(float(np.mean([r["decile_spread"] for r in wf_results])), 4) if wf_results else 0.0
    avg_hitrate = round(float(np.mean([r["hit_rate"] for r in wf_results])), 4) if wf_results else 0.0
    logger.info("  Walk-forward: IC=%.4f, spread=%.4f, hitrate=%.4f over %d folds",
                avg_ic, avg_spread, avg_hitrate, len(wf_results))

    # ── Slutgiltig modell — träna på ALL data ─────────────────────────────
    final_model, model_type = _fit_model(df, feature_cols)
    if final_model is None:
        logger.error("Modellträning misslyckades för %s", universe)
        return None

    logger.info("  ✅ %s-ranker tränad (%s), IC=%.4f", universe, model_type, avg_ic)

    return TrainedRanker(
        model=final_model,
        feature_cols=feature_cols,
        universe=universe,
        trained_at=pd.Timestamp.now().isoformat(),
        n_rows=len(df),
        test_metrics={
            "wf_avg_ic":        avg_ic,
            "ic":               avg_ic,          # alias för enhetlig läsning
            "wf_avg_spread":    avg_spread,
            "wf_avg_hit_rate":  avg_hitrate,
            "hit_rate":         avg_hitrate,
            "n_folds":          len(wf_results),
            "n_train_total":    len(df),
            "model_type":       model_type,
            "n_features":       len(feature_cols),
            "wf_folds":         wf_results,
        },
    )


def _fit_model(df: pd.DataFrame, feature_cols: list[str],
                objective_mode: str = "lambdarank_ndcg",
                use_uniqueness: bool = True) -> tuple:
    """Tränar LightGBM LambdaRank. Fallback till XGBoost om LGBM saknas.

    Args:
        objective_mode: "lambdarank_ndcg" (default, nuvarande),
                        "rank_ic" (per-datum rankad target),
                        "xgboost_cs" (XGBoost cross-sectional target).
        use_uniqueness: Applicera Lopez de Prado uniqueness-viktning för att
                        kompensera för överlappande 30d-labels (S1).
    Returns:
        (model, model_type_str)
    """
    df = df.sort_values("date").copy()

    # ── Tidsviktning ─────────────────────────────────────────────────────────
    today = datetime.date.today()
    age_days = pd.to_datetime(df["date"]).dt.date.apply(
        lambda d: (today - d).days
    ).values
    weights = np.exp(-np.log(2) / RANKER_HALFLIFE_YEARS * (age_days / 365.25))
    weights = weights / weights.mean()

    # ── Uniqueness-viktning (S1, Lopez de Prado) ────────────────────────────
    # Överlappande 30d-labels är ej IID; vikta ner samtidiga labels.
    if use_uniqueness and "date" in df.columns:
        try:
            from core.ml_validation import combine_weights, label_uniqueness
            uniqueness = label_uniqueness(df["date"], horizon_days=30)
            weights = combine_weights(pd.Series(weights, index=df.index), uniqueness)
            logger.info("  Uniqueness weighting applied: uniqueness mean=%.4f (1.0=IID)",
                        uniqueness.mean())
        except Exception as e:
            logger.warning("Uniqueness weighting failed (proceeding without): %s", e)

    X = df[feature_cols].fillna(0).values.astype(np.float32)

    # ── XGBoost fallback (enkel regressor) ──────────────────────────────────
    if objective_mode == "xgboost_cs":
        try:
            import xgboost as xgb
            date_mean = df.groupby("date")["forward_return_30d"].transform("mean")
            y_cs = (df["forward_return_30d"] - date_mean).values
            model = xgb.XGBRegressor(
                n_estimators=400, max_depth=5, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                random_state=42, n_jobs=-1, verbosity=0,
            )
            model.fit(X, y_cs, sample_weight=weights)
            return model, "xgboost_regressor"
        except ImportError:
            logger.error("XGBoost ej installerat")

    # ── LightGBM LambdaRank ────────────────────────────────────────────────
    try:
        import lightgbm as lgb

        if objective_mode == "rank_ic":
            # rank_ic: per-datum rankad target (0..1), regressivt,
            # approximerar direkt IC-optimering
            df["label_rank"] = df.groupby("date")["forward_return_30d"].rank(pct=True)
            y = df["label_rank"].values.astype(np.float32)
            # Använd regression för rank_ic-läget
            params = {
                "objective":         "regression",
                "metric":            "rmse",
                "learning_rate":     0.05,
                "num_leaves":        63,
                "max_depth":         6,
                "min_child_samples": 10,
                "feature_fraction":  0.8,
                "bagging_fraction":  0.8,
                "bagging_freq":      5,
                "lambda_l1":         0.1,
                "lambda_l2":         0.1,
                "n_jobs":            -1,
                "verbosity":         -1,
                "seed":              42,
            }
            # NOTE: En full custom LambdaRankIC-loss (arXiv:2605.00501) kräver
            # gradient-hack i LightGBM. Per-datum-rankad regression ger 80%
            # av effekten till 20% av komplexiteten. Custom loss kan testas i batch 2.
            logger.info("  Using rank_ic objective (per-date ranked target)")
        else:
            # Default: lambdarank_ndcg — quintile-etiketter
            df["label"] = df.groupby("date")["forward_return_30d"].transform(_quintile_label)
            group_sizes = df.groupby("date", sort=False).size().values.tolist()
            y = df["label"].values.astype(np.float32)
            params = {
                "objective":         "lambdarank",
                "metric":            "ndcg",
                "ndcg_eval_at":      [1, 3, 5, 10],
                "learning_rate":     0.05,
                "num_leaves":        63,
                "max_depth":         6,
                "min_child_samples": 10,
                "feature_fraction":  0.8,
                "bagging_fraction":  0.8,
                "bagging_freq":      5,
                "lambda_l1":         0.1,
                "lambda_l2":         0.1,
                "n_jobs":            -1,
                "verbosity":         -1,
                "seed":              42,
            }

        group_sizes = df.groupby("date", sort=False).size().values.tolist()

        train_ds = lgb.Dataset(
            X, label=y,
            group=group_sizes if objective_mode == "lambdarank_ndcg" else None,
            weight=weights,
            feature_name=feature_cols,
            free_raw_data=False,
        )
        model = lgb.train(
            params,
            train_ds,
            num_boost_round=400,
            callbacks=[lgb.log_evaluation(period=100)],
        )
        return model, f"lightgbm_{objective_mode}"

    except ImportError:
        logger.warning("LightGBM ej installerat — faller tillbaka till XGBoost-regressor")

    except Exception as e:
        logger.warning("LightGBM-träning misslyckades (%s) — faller tillbaka till XGBoost", e)

    # ── Fallback: XGBoost-regressor ──────────────────────────────────────────
    try:
        import xgboost as xgb

        date_mean = df.groupby("date")["forward_return_30d"].transform("mean")
        y_cs = (df["forward_return_30d"] - date_mean).values

        model = xgb.XGBRegressor(
            n_estimators=400, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, n_jobs=-1, verbosity=0,
        )
        model.fit(X, y_cs, sample_weight=weights)
        return model, "xgboost_regressor"

    except ImportError:
        logger.error("Varken LightGBM eller XGBoost är installerade")
        return None, "none"


def _walk_forward_validate(
    df: pd.DataFrame,
    feature_cols: list[str],
    initial_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
    objective_mode: str = "lambdarank_ndcg",
) -> list[dict]:
    """Walk-forward validering: rullande träna→testa med purged folds.

    Använder purged walk-forward (Lopez de Prado) för att eliminera
    label-läckage. Träningsrader vars 30d-label-fönster överlappar
    testperioden exkluderas.

    Varje fold: IC + decil-spread (topp vs botten 20%) + hit-rate.
    """
    from core.ml_validation import purged_walk_forward_folds

    df = df.copy()
    folds = purged_walk_forward_folds(
        df, date_col="date",
        initial_months=initial_months,
        test_months=test_months,
        step_months=step_months,
    )

    results = []
    for fold in folds:
        train_df = df.loc[fold.train_idx].copy()
        test_df  = df.loc[fold.test_idx].copy()

        if len(train_df) < 200 or len(test_df) < 50:
            continue

        # Filtrera testgrupper med för få aktier
        test_counts = test_df.groupby("date")["date"].transform("count")
        test_df = test_df[test_counts >= MIN_GROUP_SIZE].copy()

        if len(test_df) < 20:
            continue

        # Träna fold-modell med angivet objektiv
        fold_model, _ = _fit_model(train_df, feature_cols, objective_mode=objective_mode)
        if fold_model is None:
            continue

        # Predictera på test-fold
        X_test = test_df[feature_cols].fillna(0).values.astype(np.float32)
        try:
            preds = fold_model.predict(X_test)
        except Exception:
            continue

        # Per-datum IC (Spearman rank correlation)
        ic = _per_date_ic(test_df["date"].values, preds, test_df["forward_return_30d"].values)

        # Decil-spread: genomsnittlig avkastning topp-20% vs botten-20%
        spread = _decile_spread(test_df["date"].values, preds, test_df["forward_return_30d"].values)

        # Hit-rate: korrekt riktning vs datumsmedel
        cs_target = test_df.groupby("date")["forward_return_30d"].transform("mean")
        cs_actual = test_df["forward_return_30d"] - cs_target
        preds_s = pd.Series(preds, index=cs_actual.index)
        hit_rate = float(((preds_s > preds_s.median()) == (cs_actual > 0)).mean())

        test_start_str = fold.test_start.strftime("%Y-%m-%d")
        test_end_str = fold.test_end.strftime("%Y-%m-%d")

        results.append({
            "train_end":    test_start_str,
            "test_start":   test_start_str,
            "test_end":     test_end_str,
            "ic":           round(ic, 4),
            "decile_spread": round(spread, 4),
            "hit_rate":     round(hit_rate, 4),
            "n_test":       len(test_df),
        })

        logger.info("  WF fold [%s→%s]: IC=%.4f, spread=%.4f, hit=%.4f, n=%d",
                    test_start_str[:7], test_end_str[:7],
                    ic, spread, hit_rate, len(test_df))

    if not results:
        logger.warning("Inga folds genererades för walk-forward-validering")

    return results


def _decile_spread(dates, preds, actuals) -> float:
    """Beräknar genomsnittlig spread (topp 20% - botten 20%) per datum.

    Högt värde = modellen separerar bra aktier från dåliga korrekt.
    """
    dfx = pd.DataFrame({"date": list(dates), "pred": list(preds), "actual": list(actuals)})
    spreads = []
    for _, g in dfx.groupby("date"):
        if len(g) < 5:
            continue
        g = g.sort_values("pred")
        n = len(g)
        bottom_n = max(1, n // 5)
        top_n    = max(1, n // 5)
        bottom_ret = g["actual"].iloc[:bottom_n].mean()
        top_ret    = g["actual"].iloc[-top_n:].mean()
        spreads.append(top_ret - bottom_ret)
    return float(np.mean(spreads)) if spreads else 0.0


# ── Spara/ladda ───────────────────────────────────────────────────────────────

def save_ranker(ranker: TrainedRanker, universe: str) -> Path:
    """Sparar ranker till models/ml_ranker_<universe>.pkl (atomisk write + SHA256)."""
    target = MODELS_DIR / f"ml_ranker_{universe}.pkl"
    tmp = target.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(ranker, f)
    tmp.replace(target)

    # SHA256-checksumma för tamper-detektion (samma mönster som ml_predictor.save_model)
    import hashlib
    h = hashlib.sha256()
    with open(target, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    checksum = h.hexdigest()
    target.with_suffix(".pkl.sha256").write_text(checksum)

    # Spara metrics separat för lätt läsning utan att ladda modellen
    metrics_path = MODELS_DIR / f"ml_ranker_{universe}_metrics.json"
    metrics_path.write_text(json.dumps({
        "universe":     ranker.universe,
        "trained_at":   ranker.trained_at,
        "n_rows":       ranker.n_rows,
        "feature_cols": ranker.feature_cols,
        "test_metrics": ranker.test_metrics,
    }, indent=2, ensure_ascii=False))

    logger.info("💾 Sparade ranker: %s [SHA256: %s...]", target.name, checksum[:16])
    return target


def load_ranker(universe: str) -> Optional[TrainedRanker]:
    """Laddar tränad ranker med SHA256-verifiering."""
    target = MODELS_DIR / f"ml_ranker_{universe}.pkl"
    if not target.exists():
        return None

    sha_file = target.with_suffix(".pkl.sha256")
    if sha_file.exists():
        import hashlib
        expected = sha_file.read_text().strip()
        h = hashlib.sha256()
        with open(target, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != expected:
            logger.error("❌ SHA256 mismatch för %s — laddar inte", target.name)
            return None

    try:
        with open(target, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("Kunde inte ladda ranker %s: %s", target.name, e)
        return None


def load_ranker_metrics(universe: str) -> Optional[dict]:
    """Laddar bara metrics-JSON (snabbt, utan pickle-deserialisering)."""
    metrics_path = MODELS_DIR / f"ml_ranker_{universe}_metrics.json"
    if not metrics_path.exists():
        return None
    try:
        return json.loads(metrics_path.read_text())
    except Exception:
        return None


# ── Inference ─────────────────────────────────────────────────────────────────

def predict_ranker(
    scored_df: pd.DataFrame,
    universe: str = "universe",
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Predictera ranking med ny LightGBM-ranker. Faller tillbaka till befintlig
    XGBoost om ranker saknas.

    Inference-väg (snabb):
      Använder factor scores (score_value, score_quality, …) direkt från scored_df.
      Dessa finns alltid i parqueten utan extra nedladdningar.
      Om OHLCV-cache finns adderas även tekniska features.

    Args:
        scored_df: DataFrame med minst [ticker] + factor scores.
        universe:  Modellnamn: "universe" eller "smallcap".
        cache_dir: OHLCV-cache (optional, för tekniska features).

    Returns:
        scored_df med uppdaterade kolumner predicted_return och ml_rank.
    """
    ranker = load_ranker(universe)
    if ranker is None:
        # Fallback till gammal XGBoost-modell
        logger.info("  ⚠ Ingen ranker-modell för %s — faller tillbaka till XGBoost", universe)
        try:
            from core.ml_predictor import predict_returns
            return predict_returns(scored_df, universe, cache_dir)
        except Exception as exc:
            logger.warning("XGBoost-fallback misslyckades: %s", exc)
            return scored_df

    if scored_df.empty or "ticker" not in scored_df.columns:
        return scored_df

    cache_dir = cache_dir or (ROOT / "data" / "cache")
    feature_cols = ranker.feature_cols

    # ── Bygg feature-matris ─────────────────────────────────────────────────
    # 1. Factor scores från scored_df (alltid tillgängliga, ingen DL)
    factor_cols_avail = [c for c in FACTOR_SCORE_FEATURES if c in scored_df.columns]
    regime_avail = [c for c in REGIME_FEATURES if c in scored_df.columns]

    # 2. Tekniska features från OHLCV-cache (om tillgängliga)
    tech_cols_needed = [c for c in feature_cols if c in TECH_FEATURES]
    if tech_cols_needed:
        tech_rows = []
        for ticker in scored_df["ticker"].tolist():
            feats = _load_features_from_cache(ticker, cache_dir)
            tech_rows.append(feats)
        tech_df = pd.DataFrame(tech_rows, index=scored_df.index)
    else:
        tech_df = pd.DataFrame(index=scored_df.index)

    # 3. Bygg komplett feature-matris i rätt ordning
    X_parts = []
    for col in feature_cols:
        if col in TECH_FEATURES and col in tech_df.columns:
            X_parts.append(tech_df[col].fillna(0))
        elif col in scored_df.columns:
            X_parts.append(pd.to_numeric(scored_df[col], errors="coerce").fillna(50 if col in FACTOR_SCORE_FEATURES else 0))
        else:
            X_parts.append(pd.Series(0.0, index=scored_df.index))

    X = pd.concat(X_parts, axis=1).values.astype(np.float32)

    # ── Predictera ──────────────────────────────────────────────────────────
    try:
        preds = ranker.model.predict(X)
    except Exception as e:
        logger.warning("Ranker-prediktion misslyckades för %s: %s", universe, e)
        return scored_df

    # ── Markera aktier utan prisdata (alla tech-features är NaN) ────────────
    if tech_cols_needed and len(tech_df.columns) > 0:
        tech_used = [c for c in tech_cols_needed if c in tech_df.columns]
        no_data_mask = tech_df.reindex(columns=tech_used).isna().all(axis=1)
    else:
        no_data_mask = pd.Series(False, index=scored_df.index)

    preds_s = pd.Series(preds, index=scored_df.index, dtype=float)
    preds_s[no_data_mask] = float("nan")

    result = scored_df.copy()
    result["predicted_return"] = preds_s
    result["ml_rank"] = (
        result["predicted_return"]
        .rank(pct=True, ascending=True, na_option="keep")
        .fillna(0) * 100
    ).round(1)

    n_pred = int((~no_data_mask).sum())
    logger.info("  ✅ Ranker: predikterade %d aktier, %d utan prisdata",
                n_pred, int(no_data_mask.sum()))
    return result


def get_ranker_metrics(universe: str = "universe") -> dict:
    """Returnerar metrics-dict för senaste tränade ranker (utan pickle-load).

    Returnerar tom dict om modell saknas.
    """
    metrics = load_ranker_metrics(universe)
    if metrics:
        return metrics

    # Fallback: läs från XGBoost-metricsefil om ranker saknas
    xgb_metrics = MODELS_DIR / f"ml_{universe}_metrics.json"
    if xgb_metrics.exists():
        try:
            return json.loads(xgb_metrics.read_text())
        except Exception:
            pass
    return {}
