"""Tests for S1 — Uniqueness-viktning (label_uniqueness, combine_weights)."""
from __future__ import annotations

import pandas as pd
import pytest

from core.ml_validation import combine_weights, label_uniqueness


class TestLabelUniqueness:
    def test_single_date(self):
        """Två datum med överlapp → uniqueness varierar med concurrency."""
        dates = pd.Series(["2024-01-01", "2024-01-02"])
        u = label_uniqueness(dates, horizon_days=5)
        # With horizon_days=5, second bar is inside first bar's interval
        # New algorithm: uniqueness = time-averaged 1/concurrency, both bars get weight
        # The second bar has lower concurrency towards the end, so uniqueness >= first
        assert u.iloc[0] > 0, "First date should have non-zero uniqueness"
        assert u.iloc[1] >= u.iloc[0], "Second bar ends later (less overlap at tail)"

    def test_low_uniqueness_for_simultaneous(self):
        """Många samtidiga labels → låg uniqueness."""
        dates = pd.to_datetime([
            "2024-01-01", "2024-01-01", "2024-01-01",
            "2024-01-02", "2024-01-02",
            "2024-01-15",
        ])
        u = label_uniqueness(dates, horizon_days=10)
        # 2024-01-01 har 3 samtidiga → lägre uniqueness
        first_three = u.iloc[:3]
        last_one = u.iloc[5]
        assert first_three.mean() < last_one, (
            "Simultaneous dates should have lower uniqueness than isolated"
        )

    def test_no_overlap(self):
        """Inget överlapp → alla 1.0."""
        dates = pd.Series(["2024-01-01", "2024-02-01", "2024-03-01"])
        u = label_uniqueness(dates, horizon_days=15)
        assert all(u > 0.99), "Non-overlapping dates should be ~1.0"

    def test_empty(self):
        """Tom input → tom serie."""
        dates = pd.Series([], dtype=str)
        u = label_uniqueness(dates)
        assert len(u) == 0

    def test_single_row(self):
        """En rad → 1.0."""
        u = label_uniqueness(pd.Series(["2024-01-01"]))
        assert u.iloc[0] == 1.0


class TestCombineWeights:
    def test_basic_combination(self):
        time_decay = pd.Series([0.8, 1.0, 1.2])
        uniqueness = pd.Series([0.5, 1.0, 0.8])
        w = combine_weights(time_decay, uniqueness)
        assert len(w) == 3
        assert 0.5 < w.mean() < 1.5  # normerad → mean≈1

    def test_identical_inputs(self):
        """Identiska vikter → alla 1.0."""
        time_decay = pd.Series([1.0, 1.0, 1.0])
        uniqueness = pd.Series([1.0, 1.0, 1.0])
        w = combine_weights(time_decay, uniqueness)
        assert all(abs(w - 1.0) < 1e-6)

    def test_zero_uniqueness(self):
        """Noll uniqueness → noll vikt."""
        time_decay = pd.Series([1.0, 1.0])
        uniqueness = pd.Series([0.0, 0.0])
        w = combine_weights(time_decay, uniqueness)
        assert all(w == 0.0) or all(w.isna())
