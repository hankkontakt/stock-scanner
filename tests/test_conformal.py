"""Tests for S3 — Conformal prediction."""
from __future__ import annotations

import numpy as np
import pytest

from core.conformal import calibrate, estimate_uncertainty, predict_interval


class TestCalibrate:
    def test_basic_calibration(self):
        """Grundläggande kalibrering: q ≈ 1.64 för standardnormalfördelning."""
        np.random.seed(42)
        residuals = np.abs(np.random.normal(0, 1, 10000))
        q = calibrate(residuals, alpha=0.1)
        # 90:e percentilen av |N(0,1)| ≈ 1.64
        assert 1.5 < q < 2.0, f"Expected q~1.64, got {q:.4f}"

    def test_empty_residuals(self):
        """Tom array → 0."""
        q = calibrate(np.array([]))
        assert q == 0.0

    def test_all_zero(self):
        """Alla residualer 0 → q=0."""
        q = calibrate(np.zeros(100), alpha=0.1)
        assert q == 0.0

    def test_alpha_effect(self):
        """Lägre alpha → högre q."""
        residuals = np.abs(np.random.normal(0, 1, 5000))
        q_high_alpha = calibrate(residuals, alpha=0.3)   # 70% täckning
        q_low_alpha = calibrate(residuals, alpha=0.05)    # 95% täckning
        assert q_low_alpha > q_high_alpha, "Lower alpha should give larger q"


class TestPredictInterval:
    def test_symmetric(self):
        """Intervallet är symmetriskt kring point_pred."""
        preds = np.array([0.5, 1.0, 2.0])
        lower, upper = predict_interval(preds, q=0.5)
        assert np.allclose(upper - preds, 0.5)
        assert np.allclose(preds - lower, 0.5)

    def test_coverage_property(self):
        """Empirisk täckning ≈ nominell."""
        np.random.seed(42)
        true = np.random.normal(0, 1, 5000)
        pred = true + np.random.normal(0, 0.5, 5000)
        residuals = np.abs(true - pred)
        q = calibrate(residuals, alpha=0.1)
        lower, upper = predict_interval(pred, q)
        coverage = ((true >= lower) & (true <= upper)).mean()
        assert 0.85 <= coverage <= 0.95, f"Expected ~90%, got {coverage:.2%}"


class TestEstimateUncertainty:
    def test_constant_uncertainty(self):
        """Osäkerhet = q för alla."""
        uncertainty = estimate_uncertainty(np.array([0.5, 1.0]), q=0.3)
        assert np.allclose(uncertainty, 0.3)

    def test_shape_match(self):
        """Output har samma form som input."""
        preds = np.random.randn(100)
        uncertainty = estimate_uncertainty(preds, q=0.5)
        assert uncertainty.shape == preds.shape
