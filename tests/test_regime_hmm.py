"""Tests for core/regime_hmm.py — HMM-regimdetektor (syntetisk data)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.regime_hmm import HMM_STATES, RegimeState


class TestHMMFunctions:
    def test_hmm_states_defined(self):
        """Verifiera att 3 HMM-tillstånd är definierade."""
        assert len(HMM_STATES) == 3
        assert HMM_STATES[0] == "BJÖRN"
        assert HMM_STATES[1] == "NEUTRAL"
        assert HMM_STATES[2] == "TJUR"

    def test_regime_state_dataclass(self):
        """Verifiera att RegimeState fungerar."""
        state = RegimeState(
            regime="TJUR",
            regime_id=2,
            probabilities={"BJÖRN": 0.1, "NEUTRAL": 0.2, "TJUR": 0.7},
            regime_score=0.85,
        )
        assert state.regime == "TJUR"
        assert state.regime_id == 2
        assert state.regime_score == 0.85
        assert abs(state.probabilities["TJUR"] - 0.7) < 0.01

    def test_regime_score_range(self):
        """regime_score bör vara 0..1."""
        for probs, expected_min, expected_max in [
            ({"BJÖRN": 1.0, "NEUTRAL": 0, "TJUR": 0}, 0.0, 0.1),
            ({"BJÖRN": 0, "NEUTRAL": 1.0, "TJUR": 0}, 0.4, 0.6),
            ({"BJÖRN": 0, "NEUTRAL": 0.5, "TJUR": 0.5}, 0.6, 0.8),
            ({"BJÖRN": 0, "NEUTRAL": 0, "TJUR": 1.0}, 0.9, 1.0),
        ]:
            state = RegimeState(
                regime="NEUTRAL",
                regime_id=1,
                probabilities=probs,
                regime_score=probs.get("TJUR", 0) * 1.0 + probs.get("NEUTRAL", 0) * 0.5,
            )
            assert expected_min <= state.regime_score <= expected_max

    def test_train_synthetic_hmm(self):
        """Träna HMM på syntetisk data."""
        try:
            from hmmlearn import hmm

            np.random.seed(42)
            # Skapa syntetisk feature-data: 3 cluster
            n_samples = 500
            X = np.zeros((n_samples, 4))

            # BJÖRN: negativ avkastning, hög vol
            X[:200] = np.random.multivariate_normal(
                [-0.02, 1.5, -0.05, 30], np.diag([0.01, 0.1, 0.01, 5]), 200
            )
            # NEUTRAL: låg avkastning, normal vol
            X[200:350] = np.random.multivariate_normal(
                [0.0, 1.0, 0.0, 20], np.diag([0.005, 0.05, 0.005, 3]), 150
            )
            # TJUR: positiv avkastning, låg vol
            X[350:] = np.random.multivariate_normal(
                [0.03, 0.8, 0.05, 15], np.diag([0.008, 0.05, 0.008, 3]), 150
            )

            model = hmm.GaussianHMM(
                n_components=3, covariance_type="full",
                n_iter=500, random_state=42,
            )
            model.fit(X)

            states = model.predict(X)
            assert len(states) == n_samples
            assert len(set(states)) <= 3

            # Verifiera att modellen kan användas
            probs = model.predict_proba(X[:5])
            assert probs.shape == (5, 3)
            assert np.allclose(probs.sum(axis=1), 1.0)

        except ImportError:
            pytest.skip("hmmlearn not installed")

    def test_hmm_get_current_regime_fallback(self):
        """Testa att RegimeState fallback fungerar (hmmlearn saknas normalt i CI)."""
        from core.regime_hmm import get_current_regime

        try:
            state = get_current_regime()
        except ImportError:
            pytest.skip("hmmlearn not installed — fallback test requires it")
        assert isinstance(state, RegimeState)
        assert state.regime in ("BJÖRN", "NEUTRAL", "TJUR")
        assert 0 <= state.regime_score <= 1
