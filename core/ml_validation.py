"""
ml_validation.py — Läckagefri tidsserievalidering för MarketScan ML.

Purged Walk-Forward CV (Lopez de Prado): när target är forward_return_Nd
överlappar de sista träningssamplernas label-fönster testperioden. Vi PURGE:ar
(tar bort) träningssamples vars label-fönster når in i embargo-zonen, och lägger
en EMBARGO-gap mellan train-slut och test-start.

Används av:
  - core/ml_ranker.py (_walk_forward_validate)
  - core/ml_evaluation.py (evaluate_model)
  - core/regime_ensemble.py (#15)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# Forward-return-horisonten i kalenderdagar. MÅSTE matcha target-kolumnen
# (forward_return_30d). Embargo = horisont + säkerhetsmarginal.
FORWARD_HORIZON_DAYS: int = 30
EMBARGO_DAYS: int = 35  # 30d horisont + 5 handelsdagars marginal


def label_uniqueness(dates: pd.Series, horizon_days: int = 30) -> pd.Series:
    """Andel av varje rads [date, date+horizon] som inte överlappar andra labels.
    1 = helt unik, ~0 = mycket samtidighet. Vikt ∝ uniqueness.

    Räkna samtidiga öppna labels per kalenderdag; varje rads vikt = mean(1/concurrency)
    över sitt fönster. Effektiv implementation: sortera datum, glidande räkning.
    """
    # Input-safety: om dates är en sträng (inte list-lik), wrappa i lista
    if isinstance(dates, str):
        dates = pd.Series([dates])

    if not isinstance(dates, (pd.Series, pd.DatetimeIndex)):
        dates = pd.Series(dates)

    if len(dates) < 2:
        return pd.Series([1.0] * len(dates), index=getattr(dates, 'index', pd.RangeIndex(len(dates))))

    # Normalisera till pd.Series med int-index för att undvika DatetimeIndex-index-problemet
    if isinstance(dates, pd.DatetimeIndex):
        orig_input_index = pd.RangeIndex(len(dates))
        dts_series = pd.Series(dates, index=orig_input_index)
    elif isinstance(dates, pd.Series):
        orig_input_index = dates.index
        dts_series = pd.to_datetime(pd.Series(dates), errors="coerce")
    else:
        orig_input_index = pd.RangeIndex(len(dates))
        dts_series = pd.to_datetime(pd.Series(dates), errors="coerce")

    # Ta bort NaN-datum
    nan_mask = dts_series.isna()
    if nan_mask.any():
        logger.warning("label_uniqueness: %d NaN-datum borttagna", nan_mask.sum())
        dts_series = dts_series.dropna()

    if len(dts_series) < 2:
        return pd.Series([1.0] * len(dates), index=orig_input_index)
    original_order = dts_series.index.copy()
    dts_series_sorted = dts_series.sort_values()
    dts = dts_series_sorted.values  # numpy array for iteration

    n = len(dts)
    events = []
    for i, dt in enumerate(dts):
        events.append((dt, 1, i))
        events.append((dt + pd.Timedelta(days=horizon_days), -1, i))

    events.sort(key=lambda x: (x[0], -x[1]))

    concurrency = 0
    uniqueness = {}
    for ev in events:
        dt, delta, idx = ev
        if delta == 1:
            concurrency += 1
            uniqueness[idx] = 1.0 / max(concurrency, 1)
        else:
            concurrency -= 1

    # Mappa uniqueness från sorterad position [0..n-1] tillbaka till original-index
    # original_order har ursprungsindexen i sorterad ordning
    result = pd.Series(1.0, index=orig_input_index, dtype=float)
    if nan_mask.any():
        # Sätt NaN-rader till neutralt 1.0 (de har inget datum att beräkna uniqueness på)
        pass  # result är redan 1.0 som default
    for sorted_pos, orig_idx in enumerate(original_order):
        result[orig_idx] = uniqueness.get(sorted_pos, 1.0)
    return result


def combine_weights(time_decay: pd.Series, uniqueness: pd.Series) -> pd.Series:
    """Kombinera tidsvikt och uniqueness-vikt.

    w = time_decay * uniqueness, normerad så att mean(w) ≈ 1.
    """
    if len(time_decay) != len(uniqueness):
        raise ValueError(
            f"Length mismatch: time_decay={len(time_decay)}, uniqueness={len(uniqueness)}"
        )
    w = time_decay * uniqueness
    mean_w = w.mean()
    if mean_w > 0:
        w = w / mean_w
    return w


@dataclass
class WalkForwardFold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp      # exklusiv; sista tillåtna label-datum < train_end - embargo
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_idx: pd.Index
    test_idx: pd.Index


def purged_walk_forward_folds(
    df: pd.DataFrame,
    date_col: str = "date",
    initial_months: int = 24,
    test_months: int = 6,
    step_months: int = 6,
    embargo_days: int = EMBARGO_DAYS,
    min_train_rows: int = 200,
    min_test_rows: int = 50,
) -> list[WalkForwardFold]:
    """Generera läckagefria walk-forward-folds.

    PURGE: träningsrad med datum d tas med ENDAST om d + embargo < test_start,
    dvs dess 30-dagars-label hinner realiseras innan testperioden börjar.
    Det innebär i praktiken: train_end_effektiv = test_start - embargo.
    """
    d = df.copy()
    d["_dt"] = pd.to_datetime(d[date_col])
    d = d.sort_values("_dt")
    min_date, max_date = d["_dt"].min(), d["_dt"].max()

    folds: list[WalkForwardFold] = []
    test_start = min_date + pd.DateOffset(months=initial_months)

    while test_start + pd.DateOffset(months=test_months) <= max_date + pd.DateOffset(days=1):
        test_end = test_start + pd.DateOffset(months=test_months)
        # Embargo: träna bara på rader vars label realiserats före test_start
        train_cutoff = test_start - pd.Timedelta(days=embargo_days)

        train_mask = d["_dt"] < train_cutoff
        test_mask = (d["_dt"] >= test_start) & (d["_dt"] < test_end)

        train_idx = d.index[train_mask]
        test_idx = d.index[test_mask]

        if len(train_idx) >= min_train_rows and len(test_idx) >= min_test_rows:
            folds.append(WalkForwardFold(
                train_start=min_date,
                train_end=train_cutoff,
                test_start=test_start,
                test_end=test_end,
                train_idx=train_idx,
                test_idx=test_idx,
            ))
            logger.info("Fold: train<%s | test %s→%s (n_train=%d, n_test=%d)",
                        train_cutoff.date(), test_start.date(), test_end.date(),
                        len(train_idx), len(test_idx))
        else:
            logger.warning(
                "Skipping fold: train=%d rows (min %d), test=%d rows (min %d) — insufficient data",
                len(train_idx), min_train_rows, len(test_idx), min_test_rows,
            )
        test_start += pd.DateOffset(months=step_months)

    if not folds:
        logger.warning(
            "No folds generated. Date range %s to %s with %d initial months, %d test months "
            "produced 0 valid folds.",
            min_date.date(), max_date.date(), initial_months, test_months,
        )

    return folds


def deflated_sharpe_ratio(
    observed_sharpe: float,
    num_trials: int,
    T: int,
    skewness: float | None = None,
    kurtosis: float | None = None,
) -> float:
    """Deflated Sharpe Ratio (DSR) — Lopez de Prado.

    Korrigerar Sharpe ratio för multiple testing (num_trials) och
    icke-normal avkastningsdistribution (skewness, kurtosis).
    Portad från `ml_predictor._deflated_sharpe_ratio`.

    Args:
        observed_sharpe: Sharpe ratio observed in the strategy.
        num_trials: Number of independent trials (strategies tested).
        T: Number of observations (trading days).
        skewness: Skewness of returns. If None, assumed normal (0).
        kurtosis: Kurtosis of returns. If None, assumed normal (3).

    Returns:
        DSR value (probability that the observed Sharpe is not due to luck).
        > 0.5 = significant edge after multiple-testing correction.
    """
    if num_trials < 1 or T < 2:
        return 0.0

    if skewness is None:
        skewness = 0.0
    if kurtosis is None:
        kurtosis = 3.0

    # Standard error of Sharpe ratio under non-normal distribution
    # Mertens (2002): Var(SR) = (1 + 0.5*SR² - skewness*SR + (kurtosis-3)/4 * SR²) / (T-1)
    var_sr = (1 + 0.5 * observed_sharpe**2
              - skewness * observed_sharpe
              + (kurtosis - 3) / 4 * observed_sharpe**2) / (T - 1)
    se_sr = max(np.sqrt(var_sr), 1e-8)

    # Maximum expected Sharpe under null (multiple testing correction)
    # E[max(SR)] ≈ sqrt(var_sr) * ((1 - gamma) * Z⁻¹(1 - 1/num_trials)
    #                                + gamma * Z⁻¹(1 - 1/(num_trials * e)))
    # Simplified: E[max] ≈ sqrt(var_sr) * norm.ppf(1 - 0.5 / num_trials)
    from scipy.stats import norm
    e_max_sr = se_sr * norm.ppf(1 - 0.5 / num_trials)

    # DSR = P(SR > E[max(SR)])
    dsr = norm.cdf((observed_sharpe - e_max_sr) / se_sr)
    return float(dsr)
