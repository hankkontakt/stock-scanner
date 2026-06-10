"""
meta_labeling.py — Meta-labeling + triple-barrier för MarketScan.

Idé: primärmodell = rankern (vilka aktier ska upp). Sekundär "meta"-modell =
P(signalen korrekt) → filtrera falska positiva, ge konfidens.

Bygger på triple-barrier-metoden (TP=9%, SL=9%, max_hold=29 dagar, parametrar
från arXiv:2504.02249) för att definiera "lyckad" vs "misslyckad" signal.

Användning:
    from core.meta_labeling import train_meta_model, apply_meta, triple_barrier_labels
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
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Triple-barrier standardparametrar (arXiv:2504.02249 optimum)
DEFAULT_TP = 0.09       # take-profit 9 %
DEFAULT_SL = 0.09       # stop-loss 9 %
DEFAULT_MAX_DAYS = 29   # max hålltid i handelsdagar


def triple_barrier_labels(
    prices: pd.DataFrame,
    ticker_col: str = "ticker",
    date_col: str = "date",
    price_col: str = "close",
    tp: float = DEFAULT_TP,
    sl: float = DEFAULT_SL,
    max_days: int = DEFAULT_MAX_DAYS,
) -> pd.Series:
    """Per (ticker, datum): 1 om +tp nås före −sl och före max_days, annars 0.

    För varje rad i prices (sorterad per ticker, datum), titta framåt max_days
    och avgör om take-profit (+tp%) eller stop-loss (−sl%) nås först.

    Args:
        prices: DataFrame med ticker, date, close (OHLCV-prisdata).
        tp: Take-profit-tröskel (decimal, t.ex. 0.09 = 9%).
        sl: Stop-loss-tröskel (decimal, t.ex. 0.09 = 9%).
        max_days: Max antal handelsdagar att hålla positionen.

    Returns:
        pd.Series med 1 (vinst) / 0 (förlust eller timeout), index = prices.index.
    """
    if prices.empty:
        return pd.Series(dtype=int)

    result = pd.Series(0, index=prices.index, dtype=int)
    grouped = prices.sort_values(date_col).groupby(ticker_col, sort=False)

    for ticker, group in grouped:
        group = group.reset_index(drop=False)
        prices_arr = group[price_col].values
        indices = group["index"].values

        for i in range(len(group) - 1):
            start_price = prices_arr[i]
            if pd.isna(start_price) or start_price <= 0:
                continue

            horizon = min(i + max_days + 1, len(prices_arr))
            future_prices = prices_arr[i + 1:horizon]

            if len(future_prices) == 0:
                continue

            # Beräkna returer från startpris
            returns = (future_prices / start_price) - 1.0

            # Kolla om take-profit nås före stop-loss
            tp_hit = np.where(returns >= tp)[0]
            sl_hit = np.where(returns <= -sl)[0]

            if len(tp_hit) > 0 and (len(sl_hit) == 0 or tp_hit[0] < sl_hit[0]):
                result.iloc[indices[i]] = 1
            # Om inget nås inom max_days → 0 (timeout)

    return result


def _build_meta_features(primary_df: pd.DataFrame, rank_col: str = "ml_rank") -> pd.DataFrame:
    """Bygg feature-set för meta-modellen baserat på primärmodellens output.

    Meta-features:
      - ml_rank (percentil)
      - predicted_return
      - decil (topp-20% vs resten)
      - regime_score (marknadskontext)
      - score_total (Totalbetyg)
      - score_value, score_momentum, score_quality (faktorer)
      - mews_score (om tillgängligt)
      - cluster_score (om tillgängligt)
    """
    meta_features = [rank_col]
    if "predicted_return" in primary_df.columns:
        meta_features.append("predicted_return")
    if "regime_score" in primary_df.columns:
        meta_features.append("regime_score")
    for col in ["score_total", "score_value", "score_momentum", "score_quality"]:
        if col in primary_df.columns:
            meta_features.append(col)

    return primary_df[meta_features].copy()


def train_meta_model(
    primary_df: pd.DataFrame,
    prices: pd.DataFrame,
    features: Optional[list[str]] = None,
    rank_col: str = "ml_rank",
    tp: float = DEFAULT_TP,
    sl: float = DEFAULT_SL,
    max_days: int = DEFAULT_MAX_DAYS,
) -> Optional[object]:
    """LightGBM-binärklassificerare på rader där primären sa KÖP (topp-decil ml_rank).

    Target = triple_barrier-träff. Walk-forward via purged_walk_forward_folds.

    Args:
        primary_df: DataFrame med ranker-output (ml_rank, features, forward_return_30d).
        prices: OHLCV-data för triple-barrier-beräkning.
        features: Feature-kolumner för meta-modellen. Default = auto-build.
        rank_col: Kolumn med ranker-output (percentil 0-100).

    Returns:
        Tränad LightGBM-klassificerare, eller None om träning misslyckas.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        logger.warning("LightGBM ej installerat — meta-model kräver det")
        return None

    # Filtrera till KÖP-signaler (topp-decil)
    buy_df = primary_df[primary_df[rank_col] >= 90].copy()
    if len(buy_df) < 50:
        logger.warning("För få KÖP-signaler (%d) för meta-model", len(buy_df))
        return None

    # Beräkna triple-barrier-etiketter för KÖP-signalerna
    buy_df["meta_target"] = triple_barrier_labels(
        prices, tp=tp, sl=sl, max_days=max_days
    )

    # Ta bort rader där vi inte kan beräkna target (slutet av pris-serien)
    buy_df = buy_df.dropna(subset=["meta_target"])
    if len(buy_df) < 30:
        logger.warning("För få rader med meta-target (%d)", len(buy_df))
        return None

    # Bygg features
    if features is None:
        meta_df_features = _build_meta_features(buy_df, rank_col)
    else:
        meta_df_features = buy_df[features].fillna(0).copy()

    feature_cols = meta_df_features.columns.tolist()
    X = meta_df_features.values.astype(np.float32)
    y = buy_df["meta_target"].values.astype(np.float32)

    # Walk-forward träning för meta-modellen
    folds = purged_walk_forward_folds(
        buy_df, date_col="date",
        initial_months=24, test_months=6, step_months=6,
    )

    models = []
    for fold in folds:
        train_mask = buy_df.index.isin(fold.train_idx)
        test_mask = buy_df.index.isin(fold.test_idx)

        if train_mask.sum() < 30 or test_mask.sum() < 10:
            continue

        X_train = X[train_mask.values]
        y_train = y[train_mask.values]
        X_test = X[test_mask.values]
        y_test = y[test_mask.values]

        meta_model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
            verbosity=-1,
        )
        meta_model.fit(X_train, y_train)

        # Evaluate
        train_acc = meta_model.score(X_train, y_train)
        test_acc = meta_model.score(X_test, y_test)
        logger.info(
            "  Meta fold: train_acc=%.3f, test_acc=%.3f, n_train=%d, n_test=%d",
            train_acc, test_acc, len(y_train), len(y_test),
        )
        models.append(meta_model)

    if not models:
        logger.warning("Inga meta-modeller tränades")
        return None

    # Träna slutgiltig modell på ALLA KÖP-data
    final_model = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    )
    final_model.fit(X, y)
    final_model._feature_cols = feature_cols  # type: ignore[attr-defined]

    hit_rate = (y == final_model.predict(X)).mean()
    logger.info("  Meta-model trained: hit_rate=%.3f, n=%d", hit_rate, len(y))

    return final_model


def apply_meta(scored_df: pd.DataFrame, meta_model) -> pd.DataFrame:
    """Lägg kolumn meta_confidence (0–1) baserat på meta-modellen.

    STARK-rankade aktier med hög meta_confidence prioriteras.

    Args:
        scored_df: DataFrame med ranker-output.
        meta_model: Tränad meta-modell.

    Returns:
        DataFrame med extra kolumn: meta_confidence.
    """
    result = scored_df.copy()
    result["meta_confidence"] = 0.0

    if meta_model is None:
        return result

    # Bygg features för meta-modellen
    feature_cols = getattr(meta_model, "_feature_cols", None)
    if feature_cols is None:
        # Försök bygga auto
        meta_features = _build_meta_features(scored_df)
        feature_cols = meta_features.columns.tolist()
    else:
        meta_features = scored_df[[c for c in feature_cols if c in scored_df.columns]].fillna(0)

    if meta_features.empty or len(meta_features.columns) == 0:
        return result

    X = meta_features.values.astype(np.float32)

    try:
        # Predict_proba ger [P(0), P(1)]; vi tar P(1) = confidence
        proba = meta_model.predict_proba(X)
        if proba.shape[1] > 1:
            result["meta_confidence"] = proba[:, 1]
        else:
            result["meta_confidence"] = proba[:, 0]
    except Exception as e:
        logger.warning("Meta prediction failed: %s", e)

    return result


def save_meta_model(model: object, path: Optional[Path] = None) -> Path:
    """Spara meta-modell till disk."""
    if path is None:
        path = MODELS_DIR / "meta_labeling.pkl"
    import pickle
    tmp = path.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(model, f)
    tmp.replace(path)
    logger.info("Meta-model saved: %s", path)
    return path


def load_meta_model(path: Optional[Path] = None) -> Optional[object]:
    """Ladda meta-modell från disk."""
    if path is None:
        path = MODELS_DIR / "meta_labeling.pkl"
    if not path.exists():
        return None
    import pickle
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("Could not load meta-model: %s", e)
        return None
