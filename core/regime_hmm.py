"""
regime_hmm.py — Datadriven marknadsregim via Gaussisk HMM.

3 tillstånd: 0=BJÖRN, 1=NEUTRAL, 2=TJUR (sorteras efter medelavkastning).
Features (dagliga): OMX30-avkastning(20d), realiserad vol-kvot(5d/60d),
  VIX-nivå, SPY vs MA200.
Tränas på historik, ger get_current_regime() + regim-sannolikheter.

Beroenden:
    hmmlearn (pip install hmmlearn)
    yfinance (data)
"""
from __future__ import annotations

import logging
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = MODELS_DIR / "regime_hmm.pkl"
CACHE_SECONDS = 6 * 3600  # 6h cache för get_current_regime

HMM_STATES = {0: "BJÖRN", 1: "NEUTRAL", 2: "TJUR"}

# Sökord för yfinance
OMX_SYMBOL = "^OMX"       # OMX Stockholm 30
SPY_SYMBOL = "SPY"
VIX_SYMBOL = "^VIX"

# Antal år historik för träning
TRAIN_YEARS = 5


@dataclass
class RegimeState:
    regime: str           # "BJÖRN"|"NEUTRAL"|"TJUR"
    regime_id: int        # 0|1|2
    probabilities: dict   # {"BJÖRN": p, "NEUTRAL": p, "TJUR": p}
    regime_score: float   # 0..1 (kontinuerlig, för ML-feature)


# ── Cache ──────────────────────────────────────────────────────────────────

_cache: Optional[RegimeState] = None
_cache_time: float = 0.0


def _build_features() -> pd.DataFrame:
    """Bygg feature-matris för HMM-träning från prisdata.

    Features (dagliga):
      1. OMX30 20d-avkastning
      2. OMX30 realiserad vol-kvot (5d / 60d)
      3. VIX-nivå (senaste)
      4. SPY vs MA200 (pris / 200d MA)
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance required for HMM data fetching")
        raise

    end = datetime.now()
    start = end - timedelta(days=TRAIN_YEARS * 365 + 100)

    # Hämta data
    omx = yf.download(OMX_SYMBOL, start=start, end=end, auto_adjust=True, progress=False)
    spy = yf.download(SPY_SYMBOL, start=start, end=end, auto_adjust=True, progress=False)
    vix = yf.download(VIX_SYMBOL, start=start, end=end, auto_adjust=False, progress=False)

    df = pd.DataFrame(index=omx.index)
    df["omx_close"] = omx["Close"]
    df["spy_close"] = spy["Close"]
    df["vix_close"] = vix["Close"]

    # Features
    df["omx_ret_20d"] = df["omx_close"].pct_change(20)
    df["omx_vol_5d"] = df["omx_close"].pct_change().rolling(5).std()
    df["omx_vol_60d"] = df["omx_close"].pct_change().rolling(60).std()
    df["vol_ratio"] = df["omx_vol_5d"] / df["omx_vol_60d"].replace(0, np.nan)
    df["spy_ma200"] = df["spy_close"].rolling(200).mean()
    df["spy_vs_ma200"] = df["spy_close"] / df["spy_ma200"].replace(0, np.nan) - 1
    df["vix_level"] = df["vix_close"]

    # Drop NaN
    df = df.dropna()

    # Feature-kolumner för HMM
    feature_cols = ["omx_ret_20d", "vol_ratio", "spy_vs_ma200", "vix_level"]
    for col in feature_cols:
        # Winsorize 1% och 99% för att hantera extremvärden
        lo, hi = df[col].quantile([0.01, 0.99])
        df[col] = df[col].clip(lo, hi)
        # Standardisera
        df[col] = (df[col] - df[col].mean()) / df[col].std()

    df["features"] = df[feature_cols].values.tolist()
    return df


def train_regime_hmm(n_states: int = 3) -> object:
    """Träna Gaussian HMM på historiska data.

    Args:
        n_states: Antal HMM-tillstånd (default 3: björn/neutral/tjur).

    Returns:
        Tränad GaussianHMM-modell.
    """
    try:
        from hmmlearn import hmm
    except ImportError:
        logger.error("hmmlearn required. Install with: pip install hmmlearn")
        raise

    df = _build_features()
    X = np.vstack(df["features"].values)

    logger.info("Tränar HMM på %d dagar med %d features", len(df), X.shape[1])

    model = hmm.GaussianHMM(
        n_components=n_states,
        covariance_type="full",
        n_iter=1000,
        tol=1e-4,
        random_state=42,
    )

    try:
        model.fit(X)
    except Exception as e:
        logger.warning("HMM fit failed: %s — retrying with 2 components", e)
        model = hmm.GaussianHMM(
            n_components=2,
            covariance_type="full",
            n_iter=1000,
            tol=1e-4,
            random_state=42,
        )
        model.fit(X)

    # Bestäm tillståndsordning baserat på medelavkastning
    states = model.predict(X)

    # Per-tillstånd genomsnittlig OMX-avkastning
    df["state"] = states
    state_returns = df.groupby("state")["omx_ret_20d"].mean()

    # Sortera: 0=lägst avkastning (BJÖRN), 2=högst (TJUR)
    sorted_states = state_returns.sort_values().index.tolist()

    # Skapa omvänd mappning för att normalisera state-ID
    mapping = {old: new for new, old in enumerate(sorted_states)}
    df["state_sorted"] = df["state"].map(mapping)

    # Logga regimegenskaper
    for state_id in range(len(sorted_states)):
        state_data = df[df["state_sorted"] == state_id]
        logger.info("  Tillstånd %d (%s): %.1f%% av dagar, medel OMX-ret=%.4f",
                    state_id, HMM_STATES.get(state_id, f"STATE{state_id}"),
                    len(state_data) / len(df) * 100,
                    state_data["omx_ret_20d"].mean())

    # Spara modellens metadata (inklusive state-ordning)
    metadata = {
        "state_mapping": {str(k): v for k, v in mapping.items()},
        "n_states": model.n_components,
    }

    model_path = MODELS_DIR / "regime_hmm.pkl"
    tmp_path = model_path.with_suffix(".pkl.tmp")
    with open(tmp_path, "wb") as f:
        pickle.dump({"model": model, "metadata": metadata}, f)
    tmp_path.replace(model_path)

    logger.info("HMM tränad och sparad till %s", model_path.name)
    return model


def load_hmm() -> tuple:
    """Ladda tränad HMM-modell.

    Returns:
        (model, metadata) eller (None, None)
    """
    model_path = MODELS_DIR / "regime_hmm.pkl"
    if not model_path.exists():
        return None, None
    try:
        with open(model_path, "rb") as f:
            data = pickle.load(f)
        return data.get("model"), data.get("metadata", {})
    except Exception as e:
        logger.warning("Kunde inte ladda HMM: %s", e)
        return None, None


def get_current_regime() -> RegimeState:
    """Hämta nuvarande marknadsregim (med 6h cache).

    Returns:
        RegimeState med regim, sannolikheter, regime_score.
    """
    global _cache, _cache_time

    now = time.time()
    if _cache and (now - _cache_time) < CACHE_SECONDS:
        return _cache

    # Ladda eller träna HMM
    model, metadata = load_hmm()
    if model is None:
        logger.info("Ingen HMM-modell — tränar ny...")
        model = train_regime_hmm()

        # Ladda metadata från den nytränade modellen
        model, metadata = load_hmm()

    if model is None:
        # Fallback: neutral
        _cache = RegimeState(
            regime="NEUTRAL",
            regime_id=1,
            probabilities={"BJÖRN": 0.33, "NEUTRAL": 0.34, "TJUR": 0.33},
            regime_score=0.5,
        )
        return _cache

    # Bygg features för senaste datum
    df = _build_features()
    if df.empty:
        return RegimeState("NEUTRAL", 1, {"BJÖRN": 0.33, "NEUTRAL": 0.34, "TJUR": 0.33}, 0.5)

    X = np.vstack(df["features"].values)

    # Predicera alla tillstånd
    states = model.predict(X)
    latest_state = states[-1]

    # Tillståndssannolikheter
    probs = model.predict_proba(X)[-1]
    probs_dict = {}

    # Mappa om till ordnade tillstånd om metadata finns
    mapping = metadata.get("state_mapping", {})
    if mapping:
        # Använd mapping från metadata
        sorted_states = {}
        for old_s, new_s in mapping.items():
            sorted_states[int(new_s)] = int(old_s)

        ordered_state = sorted_states.get(int(latest_state), latest_state)
        # Sannolikheter per ordnat tillstånd
        for new_id in range(len(probs)):
            old_id = sorted_states.get(new_id, new_id)
            prob = float(probs[old_id]) if old_id < len(probs) else 0
            regime_name = HMM_STATES.get(new_id, f"STATE{new_id}")
            probs_dict[regime_name] = prob

        regime_name = HMM_STATES.get(ordered_state, f"STATE{ordered_state}")
        regime_id = ordered_state
    else:
        regime_name = HMM_STATES.get(int(latest_state), f"STATE{latest_state}")
        regime_id = int(latest_state)
        for i, p in enumerate(probs):
            probs_dict[HMM_STATES.get(i, f"STATE{i}")] = float(p)

    # Kontinuerlig regime_score (0=BIÖRN, 1=TJUR)
    bjorn_p = probs_dict.get("BJÖRN", 0)
    tjur_p = probs_dict.get("TJUR", 0)
    neutral_p = probs_dict.get("NEUTRAL", 0)

    # Viktad summa: BJÖRN=0, NEUTRAL=0.5, TJUR=1
    regime_score = float(bjorn_p * 0 + neutral_p * 0.5 + tjur_p * 1.0)

    _cache = RegimeState(
        regime=regime_name,
        regime_id=regime_id,
        probabilities=probs_dict,
        regime_score=round(regime_score, 4),
    )
    _cache_time = now

    logger.info("Nuvarande regim: %s (score=%.4f)", regime_name, regime_score)
    return _cache


def label_history(features_df: Optional[pd.DataFrame] = None) -> pd.Series:
    """Tilldela regim-id per historiskt datum.

    Args:
        features_df: DataFrame med features (om None, byggs från yfinance).

    Returns:
        pd.Series med regim-id per datum, index=date.
    """
    model, metadata = load_hmm()
    if model is None:
        logger.warning("Ingen HMM — tränar...")
        model = train_regime_hmm()

    if features_df is None:
        features_df = _build_features()

    X = np.vstack(features_df["features"].values)
    states = model.predict(X)

    mapping = metadata.get("state_mapping", {})
    if mapping:
        sorted_states = {int(k): int(v) for k, v in mapping.items()}
        ordered = np.array([sorted_states.get(s, s) for s in states])
    else:
        ordered = states

    return pd.Series(ordered, index=features_df.index, name="regime_id")
