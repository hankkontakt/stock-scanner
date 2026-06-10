"""Tests for smallcap/mews.py — MEWS Multi-Bagger Early Warning Score."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smallcap.mews import (
    MEWS_THRESHOLD,
    MEWS_WEIGHTS,
    _f_clean_accruals,
    _f_fcf_yield,
    _f_low_ps,
    _f_operating_leverage,
    _f_revenue_accel,
    _f_small_size,
    score_mews,
)


def _synthetic_df(n=30) -> pd.DataFrame:
    """Skapa syntetisk DataFrame med 30 bolag för MEWS-testning."""
    np.random.seed(42)
    df = pd.DataFrame({
        "ticker": [f"T{i:04d}" for i in range(n)],
        "market_cap": np.random.uniform(50e6, 500e9, n),
        "free_cash_flow": np.random.uniform(-1e9, 10e9, n),
        "price_to_sales": np.random.uniform(0.1, 10, n),
        "revenue_ttm": np.random.uniform(1e8, 1e11, n),
        "revenue_prev": np.random.uniform(1e8, 1e11, n),
        "revenue_2y_ago": np.random.uniform(1e8, 1e11, n),
        "operating_income_ttm": np.random.uniform(-5e8, 5e9, n),
        "operating_income_prev": np.random.uniform(-5e8, 5e9, n),
        "net_income_ttm": np.random.uniform(-1e8, 2e9, n),
        "operating_cashflow_ttm": np.random.uniform(-5e7, 3e9, n),
        "total_assets": np.random.uniform(1e8, 1e11, n),
        "total_assets_prev": np.random.uniform(1e8, 1e11, n),
    })

    # Skapa ett uppenbart "bra" bolag (hög FCF-yield, litet, lågt P/S, hög op-leverage)
    df.loc[0] = {
        "ticker": "BRABOLAG",
        "market_cap": 100e6,      # litet
        "free_cash_flow": 20e6,   # hög FCF-yield
        "price_to_sales": 0.3,    # låg P/S
        "revenue_ttm": 500e6,     # ökande intäkter
        "revenue_prev": 400e6,    # +25% YoY
        "revenue_2y_ago": 350e6,  # +43% 2y CAGR
        "operating_income_ttm": 100e6,   # hög op-leverage
        "operating_income_prev": 60e6,   # +67% vs +25% rev
        "net_income_ttm": 50e6,
        "operating_cashflow_ttm": 60e6,  # hög kvalitet (clean accruals)
        "total_assets": 500e6,
        "total_assets_prev": 480e6,
    }

    # Ett uppenbart "dåligt" bolag (stort, dyrt, negativ FCF)
    df.loc[1] = {
        "ticker": "DALIGT",
        "market_cap": 500e9,      # stort
        "free_cash_flow": -5e8,   # negativ FCF
        "price_to_sales": 8.0,    # högt P/S
        "revenue_ttm": 1e11,
        "revenue_prev": 1.1e11,   # minskande
        "revenue_2y_ago": 1.2e11,
        "operating_income_ttm": 5e8,
        "operating_income_prev": 8e8,  # minskande
        "net_income_ttm": 3e8,
        "operating_cashflow_ttm": -1e8,  # dålig kvalitet
        "total_assets": 2e11,
        "total_assets_prev": 1.9e11,
    }
    return df


class TestScoreMews:
    def test_output_columns(self):
        """Verifiera att score_mews ger alla förväntade kolumner."""
        df = _synthetic_df(10)
        result = score_mews(df)
        expected = [
            "mews_fcf_yield", "mews_small_size", "mews_low_ps",
            "mews_operating_leverage", "mews_revenue_accel", "mews_clean_accruals",
            "mews_score", "mews_flag",
        ]
        for col in expected:
            assert col in result.columns, f"Saknad kolumn: {col}"

    def test_no_nan_in_score(self):
        """Inga NaN i mews_score."""
        df = _synthetic_df(30)
        result = score_mews(df)
        assert result["mews_score"].isna().sum() == 0

    def test_score_range(self):
        """mews_score bör vara 0-100."""
        df = _synthetic_df(30)
        result = score_mews(df)
        assert result["mews_score"].between(0, 100).all()

    def test_good_company_top(self):
        """Bra bolag bör hamna i topp."""
        df = _synthetic_df(30)
        result = score_mews(df)
        top_idx = result["mews_score"].idxmax()
        assert result.loc[top_idx, "ticker"] == "BRABOLAG", (
            f"BRABOLAG borde vara topp, men {result.loc[top_idx, 'ticker']} är det"
        )

    def test_bad_company_bottom(self):
        """Dåligt bolag bör hamna i botten."""
        df = _synthetic_df(30)
        result = score_mews(df)
        # Sortera
        sorted_result = result.sort_values("mews_score")
        bad_idx = sorted_result.index[sorted_result["ticker"] == "DALIGT"].tolist()
        assert len(bad_idx) == 1
        # DALIGT bör vara bland de 5 sämsta
        rank = list(sorted_result.index).index(bad_idx[0])
        assert rank < 5, f"DALIGT borde vara i botten, rank {rank}"

    def test_mews_flag(self):
        """Flaggan bör sättas för högt scoreade bolag."""
        df = _synthetic_df(30)
        result = score_mews(df)
        # BRABOLAG bör ha mews_flag
        brab = result[result["ticker"] == "BRABOLAG"]
        assert brab["mews_flag"].iloc[0] is True or brab["mews_score"].iloc[0] >= MEWS_THRESHOLD

    def test_sub_scores_present(self):
        """Alla 6 delfaktorer finns och har rätt vikt."""
        df = _synthetic_df(10)
        result = score_mews(df)
        for factor, weight in MEWS_WEIGHTS.items():
            col = f"mews_{factor}"
            assert col in result.columns
            assert 0 < weight < 1
        total_weight = sum(MEWS_WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.01

    def test_edge_case_empty(self):
        """Empty DataFrame."""
        df = pd.DataFrame()
        result = score_mews(df)
        assert len(result) == 0
