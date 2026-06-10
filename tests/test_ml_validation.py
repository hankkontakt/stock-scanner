"""Tests for core/ml_validation.py — purged walk-forward CV."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from core.ml_validation import (
    WalkForwardFold,
    deflated_sharpe_ratio,
    purged_walk_forward_folds,
)


def _synthetic_df(
    n_days: int = 252 * 4,
    n_tickers: int = 20,
    start: str = "2020-01-01",
) -> pd.DataFrame:
    """Skapa syntetisk df med datum jämnt fördelade över n_days, n_tickers/dag."""
    dates = pd.date_range(start, periods=n_days, freq="B")
    rows = []
    for d in dates:
        for t in range(n_tickers):
            rows.append({
                "date": d,
                "ticker": f"TICK{t:04d}",
                "feature_a": 0.5,
                "forward_return_30d": 0.01,
            })
    df = pd.DataFrame(rows)
    return df


class TestPurgedWalkForwardFolds:
    def test_embargo_enforced(self):
        """Verifiera att INGEN träningsrad har datum i embargo-zonen."""
        df = _synthetic_df(n_days=252 * 4, n_tickers=20)
        folds = purged_walk_forward_folds(
            df,
            date_col="date",
            initial_months=24,
            test_months=6,
            step_months=6,
            embargo_days=35,
        )
        assert len(folds) > 0, "Should produce at least one fold"

        for fold in folds:
            train_dates = df.loc[fold.train_idx, "date"]
            test_start = fold.test_start

            # Ingen träningsrad bör vara i embargo-zonen [test_start - 35d, test_start)
            embargo_start = test_start - timedelta(days=35)
            in_embargo = (train_dates >= embargo_start) & (train_dates < test_start)
            assert not in_embargo.any(), (
                f"Fold test_start={test_start.date()}: found {in_embargo.sum()} "
                f"training rows in embargo zone [{embargo_start.date()}, {test_start.date()})"
            )

    def test_train_end_matches_embargo(self):
        """Verifiera att fold.train_end == test_start - embargo_days."""
        df = _synthetic_df(n_days=252 * 4, n_tickers=20)
        folds = purged_walk_forward_folds(df, date_col="date")
        for fold in folds:
            expected_end = fold.test_start - timedelta(days=35)
            assert fold.train_end == expected_end, (
                f"train_end {fold.train_end.date()} != "
                f"test_start - 35d = {expected_end.date()}"
            )

    def test_no_test_leakage(self):
        """Verifiera att max(train_dates) < test_start - 35d."""
        df = _synthetic_df(n_days=252 * 4, n_tickers=20)
        folds = purged_walk_forward_folds(df, date_col="date")
        for fold in folds:
            train_dates = df.loc[fold.train_idx, "date"]
            if len(train_dates) > 0:
                assert train_dates.max() < fold.test_start - timedelta(days=35), (
                    f"Max train date {train_dates.max().date()} not before embargo cutoff"
                )

    def test_empty_for_short_range(self):
        """Datumspann kortare än initial_months + test_months → 0 folds."""
        df = _synthetic_df(n_days=30, n_tickers=10)
        folds = purged_walk_forward_folds(df, date_col="date")
        assert len(folds) == 0, "Should produce 0 folds for short date range"

    def test_min_rows_filter(self):
        """Sätter min_train_rows högt → 0 folds."""
        df = _synthetic_df(n_days=252 * 4, n_tickers=5)
        folds = purged_walk_forward_folds(
            df, date_col="date", min_train_rows=1_000_000,
        )
        assert len(folds) == 0, "Should skip folds when train data insufficient"

    def test_fold_types(self):
        """Verifiera att folds är WalkForwardFold-objekt."""
        df = _synthetic_df(n_days=252 * 4, n_tickers=20)
        folds = purged_walk_forward_folds(df, date_col="date")
        for fold in folds:
            assert isinstance(fold, WalkForwardFold)
            assert isinstance(fold.train_idx, pd.Index)
            assert isinstance(fold.test_idx, pd.Index)
            assert len(fold.train_idx) > 0
            assert len(fold.test_idx) > 0


class TestDeflatedSharpeRatio:
    def test_no_trials(self):
        assert deflated_sharpe_ratio(1.0, 0, 100) == 0.0

    def test_few_observations(self):
        assert deflated_sharpe_ratio(1.0, 5, 1) == 0.0

    def test_low_sharpe_no_edge(self):
        dsr = deflated_sharpe_ratio(0.1, 10, 252)
        assert dsr < 0.5

    def test_high_sharpe_edge(self):
        dsr = deflated_sharpe_ratio(3.0, 3, 252)
        assert dsr > 0.5
