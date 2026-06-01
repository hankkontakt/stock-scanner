"""
ml_predictor.py -- Kvant-ML-prediktor för stock-scanner.

Gemensam kärnmodul som tränas på TVÅ separata datasets:

    universe   ->  models/ml_universe.pkl   (stora aktier, ~800 tickers)
    smallcap   ->  models/ml_smallcap.pkl   (svenska småbolag, ~280 tickers)

Båda har samma kod-bas men separata modeller och separata paper-trading-lager.

Modelltyp: gradient-boosted regressor (XGBoost om installerat, annars
sklearn HistGradientBoostingRegressor som fallback).

Features: tekniska (RSI, MACD, returns, MA-ratios, volatility, volume).
Fundamenta exkluderas i nuläget pga point-in-time-utmaningar i backtest.

Target: forward_return_30d (avkastning de kommande 30 kalenderdagarna).

Output i daily_pipeline: två nya kolumner i scored DataFrame:
    predicted_return  -- modellens prediktion
    ml_rank           -- percentilrang inom universum (0-100, högre = bättre)
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


# ══════════════════════════════════════════════════════════════════════════════
# DEFLATED SHARPE RATIO  (Lopez de Prado 2018)
# ══════════════════════════════════════════════════════════════════════════════

def _deflated_sharpe_ratio(observed_sharpe: float, num_trials: int,
                           T: int, skewness: float, kurtosis: float) -> float:
    """
    Beräknar Deflated Sharpe Ratio enligt Lopez de Prado (2018),
    "Advances in Financial Machine Learning", Wiley.

    Justerar den observerade Sharpekvoten för:
    - Multiple testing bias (antal trial = num_trials)
    - Icke-normal avkastningsfördelning (skewness, excess kurtosis)
    - Kort tidsserie (T)

    Formel:
        DSR = Φ[ (SR*√(T-1) - E*) / √(1 - γ₃*SR + (γ₄-1)/4*SR²) ]

    där:
        E* = E[max_n(SR⁰)]  =  förväntad maximal SR under nollhypotesen
                            ≈  (1-γ)*Φ⁻¹(1-1/n) + γ*Φ⁻¹(1-1/(n*e))
        γ  = Euler-Mascheroni ≈ 0.5772
        γ₃ = skewness,  γ₄ = excess kurtosis

    Returns:
        DSR (0-1): sannolikheten att den observerade SR är genuin.
        Högre = mer robust. Penaliseras starkt av många trials och
        icke-normalitet.
    """
    if T < 2 or observed_sharpe <= 0:
        return 0.0

    import math as _m
    try:
        from scipy.stats import norm as _norm
    except ImportError:
        return 0.0  # Kan inte beräkna DSR utan scipy - returnera 0, inte SR

    EULER_MASCHERONI = 0.5772156649

    # ── E[max_n(SR⁰)]: förväntad maximal Sharpe under nollhypotesen ───────────
    # Baserat på extreme-value-approximation för max av n oberoende N(0,1)-drag.
    # num_trials kläms nedåt till 2 för att undvika log(0) i ppf(1 - 1/n).
    n = max(2, num_trials)
    e_max_sr0 = (
        (1 - EULER_MASCHERONI) * _norm.ppf(1 - 1.0 / n)
        + EULER_MASCHERONI    * _norm.ppf(1 - 1.0 / (n * _m.e))
    )

    # ── Variance adjustment för icke-normalitet ───────────────────────────────
    sr = observed_sharpe
    var_adjust = 1.0 - skewness * sr + (kurtosis - 1) * sr ** 2 / 4.0
    if var_adjust <= 0:
        var_adjust = 1e-8

    # ── DSR-täljare och nämnare ───────────────────────────────────────────────
    numerator   = sr * _m.sqrt(T - 1) - e_max_sr0
    denominator = _m.sqrt(var_adjust)

    if denominator <= 0:
        return 0.0

    dsr = float(_norm.cdf(numerator / denominator))
    return max(0.0, min(1.0, dsr))


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
    # === New features ===
    "log_return_1m",          # Log return (more normally distributed)
    "volatility_skew_30d",    # Downside vs upside volatility asymmetry
    "hurst_exponent_60d",     # Trending (H>0.5) vs mean-reverting (H<0.5)
    "serial_correlation_20d", # Autocorrelation at lag 1 (momentum persistence)
    "volume_price_corr_20d",  # Correlation between returns and volume
    "klinger_oscillator",     # Volume-force momentum
    "max_drawdown_60d",       # Peak-to-trough over last 60 days
    "consecutive_down_days",  # Streak of down days (exhaustion signal)
    "rsi_divergence",         # Price vs RSI divergence (reversal signal)
    "skewness_30d",           # Skew of daily returns (tail risk)
    "kurtosis_30d",           # Kurtosis of daily returns (fat tail risk)
]

# Fundamentala features (point-in-time-säkra om de beräknas från yfinance .info
# som är en punkt-i-tid-snapshot). Dessa läggs till när fundamental data finns
# tillgänglig i scored_df (d.v.s. efter att data_fetcher har körts).
# OBS: Dessa ska INTE användas i historisk backtest där point-in-time
# inte kan garanteras - enbart i live-inference.
FUNDA_FEATURES = [
    "fcf_yield_rank",        # EV-based FCF yield percentil (0-100)
    "piotroski_score",       # Piotroski F-Score (0-9)
    "insider_signal",        # 1 om insider executive buy, 0 annars
    "insider_cluster",       # 1 om cluster buy (>=3 insiders), 0 annars
    "pe_forward_rank",       # Forward P/E percentil (inverterad: högre = lägre P/E)
    "de_rank",               # Debt/Equity percentil (inverterad: högre = lägre skuld)
    "momentum_rank",         # 12-mån momentum percentil
]

# All features = tekniska + fundamentala. Används för träning och inference.
# I träning: används om FUNDA_FEATURES finns i datasetet, annars bara TECH.
# I inference: hämtas från scored_df (för funda) + OHLCV-cache (för tech).
ALL_FEATURES = TECH_FEATURES + FUNDA_FEATURES

# Sector mapping for per-sector ML models.
# Varje sector far en egen modell som lasers separat fran models/ml_sector_*.pkl.
# Sektorer med for fa tickers anvander 'universe'-modellen som fallback.
SECTOR_MODELS = {
    "Technology":           "sector_tech",
    "Healthcare":           "sector_healthcare",
    "Financial Services":  "sector_financial",
    "Consumer Cyclical":   "sector_consumer_cyc",
    "Consumer Defensive":  "sector_consumer_def",
    "Energy":              "sector_energy",
    "Industrials":         "sector_industrial",
    "Basic Materials":     "sector_materials",
    "Real Estate":         "sector_real_estate",
    "Utilities":           "sector_utilities",
    "Communication Services": "sector_communication",
}
SMALL_SECTORS = {"Real Estate", "Utilities", "Energy"}
MIN_SECTOR_ROWS = 2000

# Halvlivstid för exponentiell tidsviktning i träning.
# Data som är 2 år gammalt viktas till 50 %, 4 år -> 25 %, COVID (6 år) -> 12 %.
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


# ── 11 nya feature-hjälpfunktioner (commit 4871bc5 definierade features ──────
# men glömde implementera hjälpfunktionerna -> NameError fångades tyst -> NaN).

def _log_return(close: pd.Series, days: int) -> float:
    """Logaritmisk avkastning över N dagar (mer normalfördelad än aritmetisk)."""
    if len(close) <= days:
        return float("nan")
    try:
        p_now  = float(close.iloc[-1])
        p_prev = float(close.iloc[-days - 1])
        if p_prev <= 0 or p_now <= 0:
            return float("nan")
        return float(np.log(p_now / p_prev))
    except Exception:
        return float("nan")


def _hurst_exponent(close: pd.Series, min_n: int = 60) -> float:
    """Hurst-exponent via R/S-analys (H>0.5=trend, H<0.5=mean-reverting, H≈0.5=random)."""
    if len(close) < min_n:
        return float("nan")
    try:
        series = close.pct_change(fill_method=None).dropna().values
        n = len(series)
        if n < 20:
            return float("nan")
        lags = [max(4, n // 8), max(8, n // 4), max(16, n // 2)]
        rs_vals = []
        lag_vals = []
        for lag in lags:
            if lag >= n:
                continue
            sub = series[:lag]
            mean_sub = sub.mean()
            deviation = (sub - mean_sub).cumsum()
            r = deviation.max() - deviation.min()
            s = sub.std()
            if s > 0:
                rs_vals.append(r / s)
                lag_vals.append(lag)
        if len(rs_vals) < 2:
            return float("nan")
        log_lags = np.log(lag_vals)
        log_rs   = np.log(rs_vals)
        h = float(np.polyfit(log_lags, log_rs, 1)[0])
        return float(np.clip(h, 0.0, 1.0))
    except Exception:
        return float("nan")


def _serial_corr(close: pd.Series, lag: int = 1) -> float:
    """Autokorrelation av dagliga returns vid given lag (momentum-persistens)."""
    if len(close) < lag + 10:
        return float("nan")
    try:
        rets = close.pct_change(fill_method=None).dropna()
        if len(rets) < lag + 5:
            return float("nan")
        return float(rets.autocorr(lag=lag))
    except Exception:
        return float("nan")


def _volume_price_corr(close: pd.Series, volume: pd.Series | None, days: int = 20) -> float:
    """Korrelation mellan dagliga returns och volym de senaste N dagarna."""
    if volume is None or len(close) < days or len(volume) < days:
        return float("nan")
    try:
        rets = close.pct_change(fill_method=None).dropna().tail(days)
        vol  = volume.reindex(rets.index).tail(days)
        if len(rets) < 5 or len(vol) < 5:
            return float("nan")
        corr = rets.corr(vol)
        return float(corr) if not pd.isna(corr) else float("nan")
    except Exception:
        return float("nan")


def _klinger_oscillator(close: pd.Series, volume: pd.Series | None,
                        fast: int = 34, slow: int = 55) -> float:
    """Klinger Volume Oscillator: (EMA_fast - EMA_slow) av Volume Force."""
    if volume is None or len(close) < slow + 1 or len(volume) < slow + 1:
        return float("nan")
    try:
        # Volume Force = volym x riktning (1 om pris stiger, -1 om faller)
        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        vf = volume * direction
        ema_fast = vf.ewm(span=fast, adjust=False).mean()
        ema_slow = vf.ewm(span=slow, adjust=False).mean()
        kvo = (ema_fast - ema_slow).iloc[-1]
        # Normalisera mot volym för jämförbarhet
        avg_vol = float(volume.tail(20).mean() or 1)
        return float(kvo / avg_vol) if avg_vol else float("nan")
    except Exception:
        return float("nan")


def _max_drawdown(close: pd.Series, days: int = 60) -> float:
    """Maximalt peak-to-trough-drawdown de senaste N dagarna (negativt värde)."""
    if len(close) < days:
        return float("nan")
    try:
        window = close.tail(days)
        peak   = window.expanding().max()
        dd     = (window / peak) - 1
        return float(dd.min())
    except Exception:
        return float("nan")


def _consecutive_direction(close: pd.Series, direction: str = "down") -> int:
    """Räknar antal konsekutiva dagar i given riktning (up/down) till idag."""
    if len(close) < 2:
        return 0
    try:
        diffs = close.diff().iloc[1:]
        streak = 0
        for val in reversed(diffs.values):
            if direction == "down" and val < 0:
                streak += 1
            elif direction == "up" and val > 0:
                streak += 1
            else:
                break
        return streak
    except Exception:
        return 0


def _rsi_divergence(close: pd.Series, current_rsi: float, lookback: int = 14) -> float:
    """
    Pris-RSI-divergens: normaliserad skillnad mellan prismömentum och RSI-momentum.
    Positiv = bullish divergens (RSI stiger medan pris faller / RSI stiger snabbare).
    Negativ = bearish divergens.
    """
    if len(close) < lookback * 2 or pd.isna(current_rsi):
        return float("nan")
    try:
        prev_close = close.iloc[-lookback - 1]
        prev_rsi   = _rsi(close.iloc[:-lookback], 14)
        if pd.isna(prev_rsi) or prev_close <= 0:
            return float("nan")
        price_change = (float(close.iloc[-1]) / prev_close) - 1
        rsi_change   = (current_rsi - prev_rsi) / 100.0
        return float(rsi_change - price_change)
    except Exception:
        return float("nan")


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
            daily_ret = close.pct_change(fill_method=None).dropna().tail(30)
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

        # Log return 1m
        out["log_return_1m"] = _log_return(close, 21)

        # Volatility skew: ratio of positive to negative return mean
        returns = close.pct_change(fill_method=None).dropna()
        if len(returns) > 30:
            pos_mean = returns[returns > 0].mean() if (returns > 0).any() else 0.001
            neg_mean = abs(returns[returns < 0].mean()) if (returns < 0).any() else 0.001
            out["volatility_skew_30d"] = float(pos_mean / neg_mean) if neg_mean else float("nan")
        else:
            out["volatility_skew_30d"] = float("nan")

        out["hurst_exponent_60d"] = _hurst_exponent(close.tail(252))
        out["serial_correlation_20d"] = _serial_corr(close.tail(60), lag=1)
        out["volume_price_corr_20d"] = _volume_price_corr(close, volume, days=20)
        out["klinger_oscillator"] = _klinger_oscillator(close, volume)
        out["max_drawdown_60d"] = _max_drawdown(close, days=60)
        out["consecutive_down_days"] = float(_consecutive_direction(close, direction="down"))
        out["rsi_divergence"] = _rsi_divergence(close, out["rsi_14"])

        if len(returns) >= 30:
            ret_30 = returns.tail(30)
            out["skewness_30d"] = float(ret_30.skew()) if len(ret_30) > 2 else float("nan")
            out["kurtosis_30d"] = float(ret_30.kurtosis()) if len(ret_30) > 3 else float("nan")
        else:
            out["skewness_30d"] = float("nan")
            out["kurtosis_30d"] = float("nan")
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


def _add_cross_sectional_target(df: pd.DataFrame) -> pd.DataFrame:
    """Lägger till 'target_cs' = forward_return_30d demeanad PER DATUM.

    Detta är den enskilt viktigaste förbättringen för en aktie-URVALS-modell:
    råa 30-dagars-avkastningar domineras av marknadsbreda rörelser (alla aktier
    rör sig ihop varje månad). Tekniska features kan inte förutsäga "var det en
    bra månad för marknaden" -> IC ≈ 0. Genom att subtrahera datumets medel­avkastning
    tar vi bort marknadsfaktorn och låter modellen lära sig RELATIV styrka
    ("slår denna aktie sina peers denna månad?") -- vilket är exakt vad vi rankar på.
    """
    df = df.copy()
    date_mean = df.groupby("date")["forward_return_30d"].transform("mean")
    df["target_cs"] = df["forward_return_30d"] - date_mean
    return df


def _per_date_ic(dates, preds, actuals) -> float:
    """Beräknar genomsnittlig per-datum Spearman-IC (den meningsfulla urvals-IC:n).

    Poolad IC (alla rader på en gång) blandar tidsserie- och tvärsnittsvarians
    och överskattar/underskattar signal. Per-datum-IC mäter exakt det vi bryr oss
    om: rangordnar modellen aktier korrekt INOM varje datum?
    """
    try:
        from scipy.stats import spearmanr
    except Exception:
        return 0.0
    dfx = pd.DataFrame({"date": list(dates), "pred": list(preds), "actual": list(actuals)})
    ics = []
    for _, g in dfx.groupby("date"):
        if len(g) >= 5 and g["pred"].nunique() > 1 and g["actual"].nunique() > 1:
            ic, _ = spearmanr(g["pred"], g["actual"])
            if not math.isnan(ic):
                ics.append(ic)
    return float(np.mean(ics)) if ics else 0.0


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
        universe: "universe" eller "smallcap" -- används bara för metadata

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

    # Tvärsnittlig target: demeana forward-return per datum (tar bort marknadsfaktor)
    df = _add_cross_sectional_target(df)

    # Time-based split: 80% äldre = train, 20% senare = test
    df = df.sort_values("date")
    split_idx = int(len(df) * 0.8)
    train, test = df.iloc[:split_idx], df.iloc[split_idx:]

    X_tr = train[TECH_FEATURES].fillna(0).values
    y_tr = train["target_cs"].values        # Träna på RELATIV avkastning
    X_te = test[TECH_FEATURES].fillna(0).values
    y_te = test["target_cs"].values

    # Exponentiell tidsviktning -- nyare data viktas högre.
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

    # Per-datum-IC (meningsfull urvals-IC) -- det vi faktiskt bryr oss om
    ic = round(_per_date_ic(test["date"].values, pred_te, y_te), 4)

    # Poolad IC behålls som referens (mindre meningsfull men jämförbar med gammalt)
    try:
        from scipy.stats import spearmanr
        ic_pooled, _ = spearmanr(pred_te, y_te)
        ic_pooled = round(float(ic_pooled), 4) if not math.isnan(ic_pooled) else 0.0
    except Exception:
        ic_pooled = 0.0

    # Hit-rate: korrekt relativ riktning (över/under datumets medel)
    hit_rate = float(((pred_te > 0) == (y_te > 0)).mean())

    metrics = {
        "mae": round(mae, 4),
        "ic": ic,                 # Per-datum-IC (headline)
        "ic_pooled": ic_pooled,   # Referens
        "hit_rate": round(hit_rate, 4),
        "target": "cross_sectional_demeaned",
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
    Combinatorial Purged Cross-Validation (CPCV) -- Lopez de Prado.

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
        return []  # För lite data - hoppa över CPCV

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


def train_with_cpcv(parquet_path: Optional[Path], universe: str,
                    df: Optional[pd.DataFrame] = None) -> Optional[TrainedModel]:
    """
    CPCV-validerad träning. Ersätter train_from_dataset() för bättre
    IC-estimat utan forward-looking bias.

    Steg:
    1. Skapa 6 CPCV-fold med purging + embargo
    2. Beräkna Information Coefficient (IC) per fold
    3. Träna slutgiltig modell på hela datasetet
    4. Returnera modell med CPCV-validerade metrics

    Args:
        parquet_path: Sökväg till träningsdata (ignoreras om df ges).
        universe: Etikett för modellen (universe/smallcap/sector_*).
        df: Förfiltrerad DataFrame (används av sektor-träning) -- om None läses parquet.

    Returns:
        TrainedModel med cpcv_avg_ic i test_metrics, eller None vid fel.
    """
    if df is None:
        if parquet_path is None or not parquet_path.exists():
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

    # Tvärsnittlig target: demeana forward-return per datum (tar bort marknadsfaktor)
    df = _add_cross_sectional_target(df)

    splits = _cpcv_split(df["date"])
    if not splits:
        logger.warning("CPCV: för lite data - för få CPCV-folds, hoppar över denna modell")
        return None

    all_ic     = []
    all_hitrate = []

    for fold_i, (train_idx, test_idx) in enumerate(splits):
        train, test = df.iloc[train_idx], df.iloc[test_idx]

        X_tr = train[TECH_FEATURES].fillna(0).values
        y_tr = train["target_cs"].values        # Träna på RELATIV avkastning
        X_te = test[TECH_FEATURES].fillna(0).values
        y_te = test["target_cs"].values

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

        # Per-datum-IC inom testfolden (meningsfull urvals-IC)
        fold_ic = _per_date_ic(test["date"].values, pred, y_te)
        all_ic.append(fold_ic)

        if len(y_te) > 0:
            all_hitrate.append(float(((pred > 0) == (y_te > 0)).mean()))

        logger.info(f"  CPCV fold {fold_i+1}/{len(splits)}: "
                    f"IC={all_ic[-1]:.4f}, hit_rate={all_hitrate[-1]:.4f}")

    avg_ic      = round(float(np.mean(all_ic)), 4)      if all_ic      else 0.0
    avg_hitrate = round(float(np.mean(all_hitrate)), 4) if all_hitrate else 0.0
    logger.info(f"  CPCV summary: avg_IC={avg_ic}, avg_hit_rate={avg_hitrate}, folds={len(splits)}")

    # ── Deflated Sharpe Ratio ─────────────────────────────────────────────
    # Beräkna DSR från CPCV-foldsen för att straffa multiple testing.
    # Använder prediktionernas Sharpe, skewness och kurtosis över alla folds.
    dsr_value = 0.0
    try:
        all_preds  = np.concatenate([
            _make_regressor().fit(df.iloc[tr][TECH_FEATURES].fillna(0).values,
                                  df.iloc[tr]["target_cs"].values).predict(
                df.iloc[te][TECH_FEATURES].fillna(0).values
            )
            for tr, te in splits[:3]  # Max 3 folds för DSR-beräkning (snabbare)
        ])
        all_actuals = np.concatenate([
            df.iloc[te]["target_cs"].values
            for tr, te in splits[:3]
        ])
        if len(all_preds) > 50:
            excess_returns = all_actuals - np.mean(all_actuals)
            # SR per period (30 dagar) - INTE annualiserad.
            # DSR-formeln kräver att SR och T är på samma tidsskala:
            #   T_obs = antal 30-dagarsperioder -> sharpe_per_period passar.
            #   Annualisering (x√12) skulle ge SR >> T-skalan och DSR ≈ 1.0 alltid.
            sharpe_per_period = float(
                np.mean(excess_returns) / (np.std(excess_returns) + 1e-10)
            )
            from scipy.stats import skew, kurtosis as _kurt
            sk = float(skew(excess_returns))
            ku = float(_kurt(excess_returns, fisher=True))  # Excess kurtosis
            T_obs = len(excess_returns)
            # num_trials = folds x features (approximation of search space)
            num_trials = len(splits) * len(TECH_FEATURES)
            dsr_value = round(_deflated_sharpe_ratio(
                sharpe_per_period, num_trials, T_obs, sk, ku
            ), 4)
            # Logga även annualiserad SR för läsbarhet, men DSR beräknas på per-period
            sharpe_annual = sharpe_per_period * np.sqrt(12)
            logger.info(f"  DSR: {dsr_value:.4f} (SR_annual={sharpe_annual:.4f}, "
                        f"SR_period={sharpe_per_period:.4f}, "
                        f"skew={sk:.3f}, kurt={ku:.3f}, trials={num_trials})")
    except Exception as e:
        logger.warning(f"  ⚠ DSR-beräkning misslyckades: {e}")

    # Slutgiltig modell tränas på ALL data (på tvärsnittlig target)
    X_all = df[TECH_FEATURES].fillna(0).values
    y_all = df["target_cs"].values
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
            "cpcv_avg_ic":      avg_ic,          # Per-datum-IC, genomsnitt över folds
            "ic":               avg_ic,          # Alias så UI/metrics-läsare hittar IC
            "cpcv_avg_hitrate": avg_hitrate,
            "hit_rate":         avg_hitrate,
            "dsr":              dsr_value,
            "target":           "cross_sectional_demeaned",
            "n_folds":          len(splits),
            "n_train_total":    len(df),
        },
    )


def train_sector_models(parquet_path: Path, min_rows: int = MIN_SECTOR_ROWS) -> dict:
    """
    Tränar en separat ML-modell per sektor (handel, banker, industri, …).

    Varje sektor får en egen modell eftersom drivkrafterna skiljer sig: banker
    styrs av räntor/kreditspread, handel av konsumtion, tech av tillväxt osv.
    En sektor-specifik modell kan fånga dessa mönster bättre än en universell.

    Sektorer definieras i SECTOR_MODELS. Sektorer i SMALL_SECTORS eller med
    < min_rows träningsrader hoppas över (använder universe-modellen som fallback
    vid inference via predict_returns_sector).

    Förutsätter att datasetet har en 'sector'-kolumn (byggd av build_ml_dataset).

    Returns:
        dict {sector_key: metrics} för de sektorer som tränades.
    """
    if not parquet_path.exists():
        logger.error(f"Saknar träningsdata: {parquet_path}")
        return {}

    df = pd.read_parquet(parquet_path)
    if "sector" not in df.columns:
        logger.warning("Datasetet saknar 'sector'-kolumn -- bygg om med uppdaterad "
                       "build_ml_dataset.py. Hoppar över sektor-träning.")
        return {}

    results = {}
    for sector_name, model_key in SECTOR_MODELS.items():
        if sector_name in SMALL_SECTORS:
            logger.info(f"  ⏭ {sector_name}: i SMALL_SECTORS -> använder universe-fallback")
            continue
        sector_df = df[df["sector"] == sector_name].copy()
        if len(sector_df) < min_rows:
            logger.info(f"  ⏭ {sector_name}: {len(sector_df)} rader < {min_rows} -> hoppar över")
            continue

        logger.info(f"  🏋️  Tränar sektor-modell: {sector_name} ({model_key}, {len(sector_df)} rader)")
        trained = train_with_cpcv(None, model_key, df=sector_df)
        if trained is None:
            logger.warning(f"  ⚠ {sector_name}: träning misslyckades -- hoppar över")
            continue

        save_model(trained, model_key)
        metrics_file = MODELS_DIR / f"ml_{model_key}_metrics.json"
        metrics_file.write_text(json.dumps({
            "universe": model_key,
            "sector": sector_name,
            "trained_at": trained.trained_at,
            "n_rows": trained.n_rows,
            "feature_cols": trained.feature_cols,
            "test_metrics": trained.test_metrics,
        }, indent=2))
        results[model_key] = trained.test_metrics
        logger.info(f"  ✅ {sector_name}: IC={trained.test_metrics.get('ic')}, "
                    f"sparad -> ml_{model_key}.pkl")

    logger.info(f"  📊 Sektor-modeller tränade: {len(results)}/{len(SECTOR_MODELS)}")
    return results


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
# INFERENCE -- anropas från daily_pipeline
# ══════════════════════════════════════════════════════════════════════════════

def predict_returns(scored_df: pd.DataFrame, universe: str,
                    cache_dir: Optional[Path] = None) -> pd.DataFrame:
    """Lägger till predicted_return + ml_rank-kolumner till scored DataFrame.

    Robust mot saknad modell -- om ingen pickle finns, returneras df
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

    # Identifiera rader där ALLA tekniska features var NaN innan fillna(0).
    # Dessa aktier har ingen prishistorik i cachen -- modellen predikterar
    # ett artefaktvärde (~1.34) för all-zero-vektorer vilket är missvisande.
    # Sätt predicted_return = NaN för dessa rader.
    tech_cols_used = [c for c in model_wrapper.feature_cols if c in TECH_FEATURES]
    if tech_cols_used:
        no_data_mask = tech_df.reindex(columns=tech_cols_used).isna().all(axis=1)
    else:
        no_data_mask = pd.Series(False, index=scored_df.index)

    preds_series = pd.Series(preds, index=scored_df.index, dtype=float)
    preds_series[no_data_mask] = float("nan")

    result["predicted_return"] = preds_series
    # ml_rank: rangordna bara rader med giltig prediktion (NaN -> 0 i ranken)
    result["ml_rank"] = (
        result["predicted_return"]
        .rank(pct=True, ascending=True, na_option="keep")
        .fillna(0) * 100
    ).round(1)

    n_filtered = int(no_data_mask.sum())
    if n_filtered:
        logger.info(f"  ℹ ML: {n_filtered} aktier saknade prisdata och fick ingen prediktion")

    return result


def predict_returns_sector(
    scored_df: pd.DataFrame,
    default_universe: str = "universe",
    cache_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Prediktera avkastning med per-sektor ML-modeller.

    For varje sektor laddas sektorspecifik modell och predikterar.
    Faller tillbaka till default_universe-modellen for:
    - Sektorer utan dedikerad modell (for fa tickers)
    - Tickers dar sektormodellen laddades men prediktion misslyckades
    - Tickers utan sektor-etikett

    Args:
        scored_df: DataFrame med ['ticker', 'sector'] + features
        default_universe: Fallback-modell (default: 'universe')
        cache_dir: OHLCV-cachekatalog

    Returns:
        DataFrame med 'predicted_return' och 'ml_rank' kolumner
    """
    df = scored_df.copy()
    df["predicted_return"] = float("nan")
    df["ml_rank"] = 0.0

    # Ladda default-modell
    default_model = load_model(default_universe)
    if default_model is None:
        logger.info(f"  ⚠ Ingen ML-modell hittad for {default_universe} -- hoppar over sektor-prediktion")
        return df

    # Bygg feature-matris från OHLCV-cache (gemensam for alla sektorer)
    cache_dir = cache_dir or (ROOT / "data" / "cache")
    tech_rows = []
    for ticker in scored_df["ticker"].tolist():
        feats = _load_features_from_cache(ticker, cache_dir)
        tech_rows.append(feats)
    tech_df = pd.DataFrame(tech_rows, index=scored_df.index)

    # Extrahera fundamentala features från scored_df
    funda_cols_available = [c for c in FUNDA_FEATURES if c in scored_df.columns]
    funda_df = None
    if funda_cols_available:
        funda_df = scored_df[funda_cols_available].copy()
        for c in funda_cols_available:
            funda_df[c] = pd.to_numeric(funda_df[c], errors="coerce").fillna(0)

    # Prediktera sektor for sektor
    all_preds = pd.Series(float("nan"), index=df.index)

    if "sector" in df.columns:
        for sector_name, model_key in SECTOR_MODELS.items():
            mask = df["sector"] == sector_name
            if not mask.any():
                continue
            if sector_name in SMALL_SECTORS:
                # For fa tickers -- anvander default-modell istallet
                continue

            sector_model = load_model(model_key)
            if sector_model is None:
                continue

            try:
                # Bygg feature-matris for denna sektor
                idx = df.index[mask]
                X_tech = tech_df.reindex(
                    columns=[c for c in sector_model.feature_cols if c in TECH_FEATURES]
                ).fillna(0).loc[idx].values

                if funda_df is not None:
                    funda_cols_model = [c for c in funda_cols_available if c in sector_model.feature_cols]
                    if funda_cols_model:
                        X_funda = funda_df.loc[idx, funda_cols_model].values
                        X = np.hstack([X_tech, X_funda])
                    else:
                        X = X_tech
                else:
                    X = X_tech

                preds = sector_model.model.predict(X)
                all_preds.loc[idx] = preds
            except Exception:
                pass  # Faller tillbaka till default-modell

    # Fyll kvarvarande med default-modell
    remaining = all_preds.isna()
    if remaining.any():
        try:
            idx = df.index[remaining]
            cols = default_model.feature_cols
            X_tech = tech_df.reindex(
                columns=[c for c in cols if c in TECH_FEATURES]
            ).fillna(0).loc[idx].values

            if funda_df is not None:
                funda_cols_model = [c for c in funda_cols_available if c in cols]
                if funda_cols_model:
                    X_funda = funda_df.loc[idx, funda_cols_model].values
                    X = np.hstack([X_tech, X_funda])
                else:
                    X = X_tech
            else:
                X = X_tech

            preds = default_model.model.predict(X)
            all_preds.loc[idx] = preds
        except Exception as e:
            logger.warning(f"ML-prediktion (fallback) misslyckades: {e}")

    # Sätt NaN for rader utan prisdata
    tech_cols_used = [c for c in default_model.feature_cols if c in TECH_FEATURES]
    if tech_cols_used:
        no_data_mask = tech_df.reindex(columns=tech_cols_used).isna().all(axis=1)
        all_preds[no_data_mask] = float("nan")

    df["predicted_return"] = all_preds
    df["ml_rank"] = (
        df["predicted_return"]
        .rank(pct=True, ascending=True, na_option="keep")
        .fillna(0) * 100
    ).round(1)

    return df


def _load_features_from_cache(ticker: str, cache_dir: Path) -> dict:
    """Försök ladda OHLCV-historik från cachen och beräkna features.
    Returnerar dict med NaN om cachen saknas.
    """
    # data_fetcher cachar prishistorik under nyckel `prices_sek:{ticker}:1y`
    # som MD5-hashat filnamn. Vi söker efter ticker-specifika filer.
    # Fallback-strategi: om vi inte hittar i cachen, gör en kort yfinance-fetch.
    try:
        # fetch_price_history returnerar en OHLCV DataFrame - det vi behöver för features.
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
