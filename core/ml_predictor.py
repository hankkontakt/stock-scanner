"""
ml_predictor.py — Kvant-ML-prediktor för stock-scanner.

Gemensam kärnmodul som tränas på TVÅ separata datasets:

    universe   →  models/ml_universe.pkl   (stora aktier, ~800 tickers)
    smallcap   →  models/ml_smallcap.pkl   (svenska småbolag, ~280 tickers)

Båda har samma kod-bas men separata modeller och separata paper-trading-lager.

Modelltyp: gradient-boosted regressor (XGBoost om installerat, annars
sklearn HistGradientBoostingRegressor som fallback).

Features: tekniska (RSI, MACD, returns, MA-ratios, volatility, volume).
Fundamenta exkluderas i nuläget pga point-in-time-utmaningar i backtest.

Target: forward_return_30d (avkastning de kommande 30 kalenderdagarna).

Output i daily_pipeline: två nya kolumner i scored DataFrame:
    predicted_return  — modellens prediktion
    ml_rank           — percentilrang inom universum (0-100, högre = bättre)
"""

from __future__ import annotations

import datetime
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


# ══════════════════════════════════════════════════════════════════════════════
# FEATURES
# ══════════════════════════════════════════════════════════════════════════════

# Tekniska features beräknade från OHLCV. Robusta över tid (inga point-in-time-fundamenta).
TECH_FEATURES = [
    "ret_1m", "ret_3m", "ret_6m", "ret_12m",
    "rsi_14",
    "macd_hist",
    "ma50_over_ma200",
    "price_over_ma50",
    "price_over_ma200",
    "volatility_30d",
    "volume_ratio_20d",
    "dist_from_52w_high",
    "dist_from_52w_low",
    "bb_position",
    "momentum_3_vs_12",
]

# Fundamentala features (point-in-time-säkra om de beräknas från yfinance .info
# som är en punkt-i-tid-snapshot). Dessa läggs till när fundamental data finns
# tillgänglig i scored_df (d.v.s. efter att data_fetcher har körts).
# OBS: Dessa ska INTE användas i historisk backtest där point-in-time
# inte kan garanteras – enbart i live-inference.
FUNDA_FEATURES = [
    "fcf_yield_rank",        # EV-based FCF yield percentil (0-100)
    "piotroski_score",       # Piotroski F-Score (0-9)
    "insider_signal",        # 1 om insider executive buy, 0 annars
    "insider_cluster",       # 1 om cluster buy (≥3 insiders), 0 annars
    "pe_forward_rank",       # Forward P/E percentil (inverterad: högre = lägre P/E)
    "de_rank",               # Debt/Equity percentil (inverterad: högre = lägre skuld)
    "momentum_rank",         # 12-mån momentum percentil
]

# All features = tekniska + fundamentala. Används för träning och inference.
# I träning: används om FUNDA_FEATURES finns i datasetet, annars bara TECH.
# I inference: hämtas från scored_df (för funda) + OHLCV-cache (för tech).
ALL_FEATURES = TECH_FEATURES + FUNDA_FEATURES

# Halvlivstid för exponentiell tidsviktning i träning.
# Data som är 2 år gammalt viktas till 50 %, 4 år → 25 %, COVID (6 år) → 12 %.
SAMPLE_WEIGHT_HALFLIFE_YEARS: float = 2.0


def _get_feature_cols(df: pd.DataFrame) -> list:
    """Returnerar tillgängliga feature-kolumner (tech + funda som finns i df)."""
    available = [c for c in TECH_FEATURES if c in df.columns]
    # Lägg till fundamenta om de finns i datasetet
    for c in FUNDA_FEATURES:
        if c in df.columns:
            available.append(c)
    return available


def _rsi(close: pd.Series, period: int = 14) -> float:
    """Returns last RSI value or NaN."""
    if len(close) < period + 1:
        return float("nan")
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
    if pd.isna(gain) or pd.isna(loss):
        return float("nan")
    if loss == 0:
        return 50.0 if gain == 0 else 100.0
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> float:
    if len(close) < slow + sig:
        return float("nan")
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=sig, adjust=False).mean()
    hist = (macd - signal).iloc[-1]
    return float(hist) if not pd.isna(hist) else float("nan")


def compute_features_at(close: pd.Series, volume: pd.Series) -> dict:
    """Räknar ut TECH_FEATURES givet en pris- och volymserie som ENDAR vid målpunkten.

    Anropare ansvarar för att slicea historiken så att inget framtida data
    läcker in. Returnerar dict med NaN för features som inte kan beräknas.
    """
    out = {f: float("nan") for f in TECH_FEATURES}

    if len(close) < 30 or close.empty:
        return out

    try:
        last = float(close.iloc[-1])

        # Returns
        def _ret(days: int) -> float:
            if len(close) <= days:
                return float("nan")
            prev = float(close.iloc[-days - 1])
            return (last / prev - 1) if prev else float("nan")

        out["ret_1m"] = _ret(21)
        out["ret_3m"] = _ret(63)
        out["ret_6m"] = _ret(126)
        out["ret_12m"] = _ret(252)

        # RSI / MACD
        out["rsi_14"] = _rsi(close, 14)
        out["macd_hist"] = _macd_hist(close)

        # Moving averages
        if len(close) >= 200:
            ma50 = float(close.tail(50).mean())
            ma200 = float(close.tail(200).mean())
            if ma200:
                out["ma50_over_ma200"] = ma50 / ma200
                out["price_over_ma200"] = last / ma200
            if ma50:
                out["price_over_ma50"] = last / ma50

        # Volatility 30d (stddev av dagliga returns)
        if len(close) >= 30:
            daily_ret = close.pct_change().dropna().tail(30)
            out["volatility_30d"] = float(daily_ret.std() or 0)

        # Volume ratio (senaste 5 vs 20 dagar)
        if volume is not None and len(volume) >= 20:
            v5 = float(volume.tail(5).mean() or 0)
            v20 = float(volume.tail(20).mean() or 0)
            out["volume_ratio_20d"] = (v5 / v20) if v20 else float("nan")

        # 52-week distance
        if len(close) >= 252:
            high_52w = float(close.tail(252).max())
            low_52w = float(close.tail(252).min())
            if high_52w:
                out["dist_from_52w_high"] = (last / high_52w) - 1
            if low_52w:
                out["dist_from_52w_low"] = (last / low_52w) - 1

        # Bollinger Band position (0=lower, 1=upper)
        if len(close) >= 20:
            window = close.tail(20)
            mean = float(window.mean())
            std = float(window.std() or 0)
            if std:
                upper, lower = mean + 2 * std, mean - 2 * std
                out["bb_position"] = (last - lower) / (upper - lower) if (upper - lower) else float("nan")

        # Momentum-divergens: 3-månaders vs 12-månaders
        r3, r12 = out["ret_3m"], out["ret_12m"]
        if r3 == r3 and r12 == r12:  # ej NaN
            out["momentum_3_vs_12"] = r3 - r12

    except Exception as e:
        logger.warning(f"compute_features_at: {e}")

    return out


# ══════════════════════════════════════════════════════════════════════════════
# TRÄNING
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TrainedModel:
    """Wrapper runt en tränad modell + metadata."""
    model: object
    feature_cols: list
    universe: str
    trained_at: str
    n_rows: int
    test_metrics: dict


def _make_regressor():
    """Returnerar en gradient-boosted regressor. Använder xgboost om
    installerat, annars sklearn HistGradientBoostingRegressor."""
    try:
        import xgboost as xgb
        return xgb.XGBRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingRegressor
        return HistGradientBoostingRegressor(
            max_iter=300,
            max_depth=5,
            learning_rate=0.05,
            random_state=42,
        )


def train_from_dataset(parquet_path: Path, universe: str) -> Optional[TrainedModel]:
    """Tränar modell från (ticker, datum, features, forward_return_30d).

    Args:
        parquet_path: Sökväg till träningsdata (skapad av build_ml_dataset.py)
        universe: "universe" eller "smallcap" — används bara för metadata

    Returns:
        TrainedModel eller None om datat var otillräckligt.
    """
    if not parquet_path.exists():
        logger.error(f"Saknar träningsdata: {parquet_path}")
        return None

    df = pd.read_parquet(parquet_path)
    if df.empty:
        logger.error("Tom träningsdata")
        return None

    # Validera kolumner
    required = set(TECH_FEATURES) | {"forward_return_30d", "date"}
    missing = required - set(df.columns)
    if missing:
        logger.error(f"Saknade kolumner i träningsdata: {missing}")
        return None

    # Drop rader utan target eller features
    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df.dropna(subset=TECH_FEATURES, how="all")
    if len(df) < 100:
        logger.error(f"För få träningsrader: {len(df)}")
        return None

    # Vinjet & klipp orealistiska targets (extrema outliers från split/missdata)
    df = df[df["forward_return_30d"].between(-0.9, 5.0)]

    # Time-based split: 80% äldre = train, 20% senare = test
    df = df.sort_values("date")
    split_idx = int(len(df) * 0.8)
    train, test = df.iloc[:split_idx], df.iloc[split_idx:]

    X_tr = train[TECH_FEATURES].fillna(0).values
    y_tr = train["forward_return_30d"].values
    X_te = test[TECH_FEATURES].fillna(0).values
    y_te = test["forward_return_30d"].values

    # Exponentiell tidsviktning — nyare data viktas högre.
    # Halvlivstid = SAMPLE_WEIGHT_HALFLIFE_YEARS (default 2 år).
    # COVID-data (~6 år gammalt) får ~12 % av vikten jämfört med dagens data.
    _today = datetime.date.today()
    _age_days = pd.to_datetime(train["date"]).dt.date.apply(
        lambda d: (_today - d).days
    ).values
    w_tr = np.exp(-np.log(2) / SAMPLE_WEIGHT_HALFLIFE_YEARS * (_age_days / 365.25))
    w_tr = w_tr / w_tr.mean()  # renormalisera till mean=1 (XGBoost-konvention)

    model = _make_regressor()
    model.fit(X_tr, y_tr, sample_weight=w_tr)

    # Metrics
    pred_te = model.predict(X_te)
    mae = float(np.mean(np.abs(pred_te - y_te)))
    # Information coefficient: Spearman-rank-korrelation
    try:
        from scipy.stats import spearmanr
        ic, _ = spearmanr(pred_te, y_te)
        ic = float(ic) if not math.isnan(ic) else 0.0
    except Exception:
        # Fallback: enkel Pearson om scipy ej finns
        ic = float(np.corrcoef(pred_te, y_te)[0, 1]) if len(y_te) > 1 else 0.0

    # Hit-rate: korrekt riktning (upp/ner)
    hit_rate = float(((pred_te > 0) == (y_te > 0)).mean())

    metrics = {
        "mae": round(mae, 4),
        "ic": round(ic, 4),
        "hit_rate": round(hit_rate, 4),
        "n_train": len(train),
        "n_test": len(test),
    }
    logger.info(f"  📊 {universe} metrics: IC={metrics['ic']}, hit_rate={metrics['hit_rate']}, MAE={metrics['mae']}")

    return TrainedModel(
        model=model,
        feature_cols=TECH_FEATURES,
        universe=universe,
        trained_at=pd.Timestamp.utcnow().isoformat(),
        n_rows=len(df),
        test_metrics=metrics,
    )


def _cpcv_split(dates: pd.Series, n_splits: int = 6, embargo_pct: float = 0.01) -> list:
    """
    Combinatorial Purged Cross-Validation (CPCV) — Lopez de Prado.

    Förhindrar dataleakage från överlappande 30-dagars forward returns:
      - Purging: träningsrader vars forward-fönster rör vid testperioden tas bort
      - Embargo: N% av rader direkt efter testperiodens slut hoppas över

    Args:
        dates: Sorterad datumkolumn
        n_splits: Antal fold (6 ger bra bias-variance tradeoff)
        embargo_pct: Andel av datan som används som embargo (standard 1%)

    Returns:
        Lista av (train_indices, test_indices) tuples
    """
    n = len(dates)
    if n < 200:
        return []  # För lite data – hoppa över CPCV

    embargo_size = max(1, int(n * embargo_pct))
    fold_size    = n // n_splits
    splits       = []

    for i in range(n_splits):
        test_start = i * fold_size
        test_end   = test_start + fold_size if i < n_splits - 1 else n

        # Purge: ta bort träningsrader vars 30-dagars forward-fönster
        # överlappar med testperiodens start
        purge_start = max(0, test_start - 30)   # 30 = forward_return_30d horisont

        # Embargo: hoppa över rader direkt efter testslut
        embargo_end = min(n, test_end + embargo_size)

        train_idx = list(range(0, purge_start)) + list(range(embargo_end, n))
        test_idx  = list(range(test_start, test_end))

        if len(train_idx) >= 100 and len(test_idx) >= 20:
            splits.append((train_idx, test_idx))

    return splits


def train_with_cpcv(parquet_path: Path, universe: str) -> Optional[TrainedModel]:
    """
    CPCV-validerad träning. Ersätter train_from_dataset() för bättre
    IC-estimat utan forward-looking bias.

    Steg:
    1. Skapa 6 CPCV-fold med purging + embargo
    2. Beräkna Information Coefficient (IC) per fold
    3. Träna slutgiltig modell på hela datasetet
    4. Returnera modell med CPCV-validerade metrics

    Returns:
        TrainedModel med cpcv_avg_ic i test_metrics, eller None vid fel.
    """
    if not parquet_path.exists():
        logger.error(f"Saknar träningsdata: {parquet_path}")
        return None

    df = pd.read_parquet(parquet_path)
    if df.empty or len(df) < 200:
        logger.error(f"För lite träningsdata: {len(df)} rader")
        return None

    required = set(TECH_FEATURES) | {"forward_return_30d", "date"}
    missing = required - set(df.columns)
    if missing:
        logger.error(f"Saknade kolumner: {missing}")
        return None

    df = df.dropna(subset=["forward_return_30d"]).copy()
    df = df[df["forward_return_30d"].between(-0.9, 5.0)]
    df = df.sort_values("date").reset_index(drop=True)

    splits = _cpcv_split(df["date"])
    if not splits:
        logger.warning("CPCV: för lite data – faller tillbaka till train_from_dataset()")
        return train_from_dataset(parquet_path, universe)

    all_ic     = []
    all_hitrate = []

    for fold_i, (train_idx, test_idx) in enumerate(splits):
        train, test = df.iloc[train_idx], df.iloc[test_idx]

        X_tr = train[TECH_FEATURES].fillna(0).values
        y_tr = train["forward_return_30d"].values
        X_te = test[TECH_FEATURES].fillna(0).values
        y_te = test["forward_return_30d"].values

        # Tidsviktning inom fold (nyare data viktas mer)
        _today = datetime.date.today()
        _age   = pd.to_datetime(train["date"]).dt.date.apply(
            lambda d: (_today - d).days
        ).values
        w_tr = np.exp(-np.log(2) / SAMPLE_WEIGHT_HALFLIFE_YEARS * (_age / 365.25))
        w_tr = w_tr / w_tr.mean()

        m = _make_regressor()
        m.fit(X_tr, y_tr, sample_weight=w_tr)
        pred = m.predict(X_te)

        try:
            from scipy.stats import spearmanr
            ic, _ = spearmanr(pred, y_te)
            all_ic.append(float(ic) if not math.isnan(ic) else 0.0)
        except Exception:
            if len(y_te) > 1:
                all_ic.append(float(np.corrcoef(pred, y_te)[0, 1]))

        if len(y_te) > 0:
            all_hitrate.append(float(((pred > 0) == (y_te > 0)).mean()))

        logger.info(f"  CPCV fold {fold_i+1}/{len(splits)}: "
                    f"IC={all_ic[-1]:.4f}, hit_rate={all_hitrate[-1]:.4f}")

    avg_ic      = round(float(np.mean(all_ic)), 4)      if all_ic      else 0.0
    avg_hitrate = round(float(np.mean(all_hitrate)), 4) if all_hitrate else 0.0
    logger.info(f"  CPCV summary: avg_IC={avg_ic}, avg_hit_rate={avg_hitrate}, folds={len(splits)}")

    # Slutgiltig modell tränas på ALL data
    X_all = df[TECH_FEATURES].fillna(0).values
    y_all = df["forward_return_30d"].values
    _today = datetime.date.today()
    _age   = pd.to_datetime(df["date"]).dt.date.apply(
        lambda d: (_today - d).days
    ).values
    w_all = np.exp(-np.log(2) / SAMPLE_WEIGHT_HALFLIFE_YEARS * (_age / 365.25))
    w_all = w_all / w_all.mean()

    final_model = _make_regressor()
    final_model.fit(X_all, y_all, sample_weight=w_all)

    return TrainedModel(
        model=final_model,
        feature_cols=TECH_FEATURES,
        universe=universe,
        trained_at=pd.Timestamp.utcnow().isoformat(),
        n_rows=len(df),
        test_metrics={
            "cpcv_avg_ic":      avg_ic,
            "cpcv_avg_hitrate": avg_hitrate,
            "n_folds":          len(splits),
            "n_train_total":    len(df),
        },
    )


def save_model(trained: TrainedModel, universe: str) -> Path:
    """Sparar tränad modell till models/ml_<universe>.pkl (atomic write)."""
    target = MODELS_DIR / f"ml_{universe}.pkl"
    tmp = target.with_suffix(".pkl.tmp")
    with open(tmp, "wb") as f:
        pickle.dump(trained, f)
    tmp.replace(target)
    logger.info(f"💾 Sparade modell: {target}")
    return target


def load_model(universe: str) -> Optional[TrainedModel]:
    """Laddar tränad modell. Returnerar None om filen saknas/korrupt."""
    target = MODELS_DIR / f"ml_{universe}.pkl"
    if not target.exists():
        return None
    try:
        with open(target, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"Kunde inte ladda {target}: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# INFERENCE — anropas från daily_pipeline
# ══════════════════════════════════════════════════════════════════════════════

def predict_returns(scored_df: pd.DataFrame, universe: str,
                    cache_dir: Optional[Path] = None) -> pd.DataFrame:
    """Lägger till predicted_return + ml_rank-kolumner till scored DataFrame.

    Robust mot saknad modell — om ingen pickle finns, returneras df
    oförändrad utan att krascha pipelinen.

    Hämtar features från OHLCV-cachen (samma cache som data_fetcher
    använder) per ticker.
    """
    model_wrapper = load_model(universe)
    if model_wrapper is None:
        logger.info(f"  ⚠ Ingen ML-modell hittad för {universe} (modeller/ml_{universe}.pkl saknas)")
        return scored_df

    if scored_df.empty or "ticker" not in scored_df.columns:
        return scored_df

    cache_dir = cache_dir or (ROOT / "data" / "cache")

    # Bygg feature-matris från OHLCV-cache per ticker (tekniska features)
    tech_rows = []
    for ticker in scored_df["ticker"].tolist():
        feats = _load_features_from_cache(ticker, cache_dir)
        tech_rows.append(feats)

    tech_df = pd.DataFrame(tech_rows, index=scored_df.index)

    # Extrahera fundamentala features från scored_df (direkt, point-in-time)
    funda_cols_available = [c for c in FUNDA_FEATURES if c in scored_df.columns]
    if funda_cols_available:
        funda_df = scored_df[funda_cols_available].copy()
        # Konvertera till numeriska och fyll NaN
        for c in funda_cols_available:
            funda_df[c] = pd.to_numeric(funda_df[c], errors="coerce").fillna(0)
    else:
        funda_df = None

    # Bara mata in features modellen tränades på
    cols = model_wrapper.feature_cols
    X_tech = tech_df.reindex(columns=[c for c in cols if c in TECH_FEATURES]).fillna(0).values

    if funda_df is not None and funda_cols_available:
        funda_cols_model = [c for c in funda_cols_available if c in cols]
        if funda_cols_model:
            X_funda = funda_df[funda_cols_model].values
            X = np.hstack([X_tech, X_funda])
        else:
            X = X_tech
    else:
        X = X_tech

    try:
        preds = model_wrapper.model.predict(X)
    except Exception as e:
        logger.warning(f"ML-prediktion misslyckades för {universe}: {e}")
        return scored_df

    result = scored_df.copy()
    result["predicted_return"] = preds
    # Rank: 0-100, högre = bättre prediktion
    result["ml_rank"] = (
        result["predicted_return"]
        .rank(pct=True, ascending=True)
        .fillna(0) * 100
    ).round(1)
    return result


def _load_features_from_cache(ticker: str, cache_dir: Path) -> dict:
    """Försök ladda OHLCV-historik från cachen och beräkna features.
    Returnerar dict med NaN om cachen saknas.
    """
    # data_fetcher cachar prishistorik under nyckel `prices_sek:{ticker}:1y`
    # som MD5-hashat filnamn. Vi söker efter ticker-specifika filer.
    # Fallback-strategi: om vi inte hittar i cachen, gör en kort yfinance-fetch.
    try:
        # fetch_price_history returnerar en OHLCV DataFrame – det vi behöver för features.
        # (fetch_prices_only returnerar ett dict med färdiga nyckeltal, inte rådata.)
        from core.data_fetcher import fetch_price_history
        hist = fetch_price_history(ticker, period="1y")
        if hist is None or hist.empty:
            return {f: float("nan") for f in TECH_FEATURES}
        close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
        volume = hist["Volume"] if "Volume" in hist.columns else None
        return compute_features_at(close, volume)
    except Exception as e:
        logger.debug(f"Kunde inte hämta features för {ticker}: {e}")
        return {f: float("nan") for f in TECH_FEATURES}
