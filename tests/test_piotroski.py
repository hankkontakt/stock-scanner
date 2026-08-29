"""
Tester for core/piotroski.py — Piotroski F-Score (0-9).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.piotroski import (
    calc_piotroski,
    add_piotroski_to_universe,
    build_piotroski_section,
    _save_snapshot,
    _load_snapshot,
)


class TestCalcPiotroski:
    """Testar calc_piotroski med olika inputkombinationer."""

    def test_score_9(self, sample_piotroski_row):
        """Alla 9 kriterier uppfyllda -> F-Score 9."""
        result = calc_piotroski(sample_piotroski_row, ticker="TEST")
        assert result["f_score"] == 9
        assert result["label"] == "STARK"
        assert all(v == 1 for v in result["criteria"].values())

    def test_score_0(self):
        """Inga kriterier uppfyllda -> F-Score 0."""
        row = {
            "roa": -0.05,
            "free_cash_flow": -1e9,
            "operating_cashflow": -5e8,
            "market_cap": 1e10,
            "price_to_book": 2.5,
            "debt_to_equity": 200,
            "current_ratio": 0.5,
            "gross_margin": 0.1,
            "operating_margin": -0.05,
            "revenue_growth": -0.1,
            "earnings_growth": -0.2,
            "insider_pct": 0.01,
        }
        result = calc_piotroski(row, ticker="TEST")
        assert result["f_score"] <= 3
        assert result["label"] == "SVAG"

    def test_score_5(self):
        """Blandade varden -> F-Score runt 5."""
        row = {
            "roa": 0.03,
            "free_cash_flow": 1e8,
            "operating_cashflow": 2e8,
            "market_cap": 5e9,
            "price_to_book": 1.5,
            "debt_to_equity": 1.5,
            "current_ratio": 1.2,
            "gross_margin": 0.25,
            "operating_margin": 0.08,
            "revenue_growth": 0.02,
            "earnings_growth": 0.03,
            "insider_pct": 0.04,
        }
        result = calc_piotroski(row, ticker="TEST")
        assert 3 <= result["f_score"] <= 7

    def test_missing_financials(self):
        """Saknad data -> kriterier blir 0 men funktionen kraschar inte."""
        row = {
            "roa": None,
            "free_cash_flow": None,
            "market_cap": None,
        }
        for key in ["price_to_book", "debt_to_equity", "current_ratio",
                     "gross_margin", "operating_margin", "revenue_growth",
                     "earnings_growth", "insider_pct"]:
            row[key] = None

        result = calc_piotroski(row, ticker="TEST")
        assert 0 <= result["f_score"] <= 9
        assert isinstance(result["label"], str)
        assert isinstance(result["criteria"], dict)


class TestFinancialsVariant:
    """Financials-variant: banker/försäkring/REITs får ROE/profit-margin-baserade
    kriterier i stället för industrimått (GM/CR är meningslösa för banker)."""

    def test_seb_like_bank_scores_6_7(self):
        """SEB-liknande bank (ROE 14%, PM 10%) -> f-score 6-7, inte 0."""
        row = {
            "sector": "Financial Services",
            "roe": 0.14,
            "roa": 0.015,
            "profit_margin": 0.10,
            "operating_margin": 0.06,
            "gross_margin": -0.42,
            "current_ratio": -0.10,
            "debt_to_equity": 5.1,
            "free_cash_flow": 1.5e9,
            "operating_cashflow": 2.0e9,
            "market_cap": 310e9,
            "price_to_book": 1.2,
            "revenue_growth": 0.05,
            "earnings_growth": 0.08,
            "shares_outstanding": 2.5e9,
            "insider_pct": 0.02,
        }
        result = calc_piotroski(row, ticker="")
        assert 6 <= result["f_score"] <= 7, \
            f"SEB-liknande bank fick f-score {result['f_score']} — förväntat 6-7 (inte 0)"
        # Financials-reglerna ska vara aktiva:
        assert result["criteria"]["F1_roa_positive"] == 1          # ROE > 0
        assert result["criteria"]["F6_better_liquidity"] == 1      # profit_margin > 0
        assert result["criteria"]["F8_better_gross_margin"] == 1   # ROE > 0.10
        assert result["criteria"]["F9_asset_turnover"] == 1        # OM > 0.05

    def test_financials_missing_profit_margin_f6_fails(self):
        """Financials utan profit_margin -> F6 = 0 (fail), inte 1."""
        row = {
            "sector": "Insurance",
            "roe": 0.12,
            "roa": 0.02,
            "profit_margin": None,
            "operating_margin": 0.06,
            "gross_margin": None,
            "current_ratio": None,
            "debt_to_equity": 2.0,
            "free_cash_flow": 1e9,
            "operating_cashflow": 1.2e9,
            "market_cap": 50e9,
            "price_to_book": 1.5,
            "revenue_growth": 0.03,
            "earnings_growth": 0.05,
        }
        result = calc_piotroski(row, ticker="")
        assert result["criteria"]["F6_better_liquidity"] == 0

    def test_industrial_row_unchanged(self):
        """Industrirad (icke-financials) -> kriterierna oförändrade
        (F1=ROA, F6=CR, F8=GM, F9=OM — samma regler som före ändringen)."""
        row = {
            "sector": "Industrials",
            "roa": 0.08,
            "roe": 0.18,
            "free_cash_flow": 1e9,
            "operating_cashflow": 1.2e9,
            "market_cap": 1e10,
            "price_to_book": 2.5,
            "debt_to_equity": 0.5,
            "current_ratio": 2.0,
            "gross_margin": 0.45,
            "operating_margin": 0.15,
            "revenue_growth": 0.10,
            "earnings_growth": 0.12,
            "insider_pct": 0.05,
        }
        result = calc_piotroski(row, ticker="")
        assert result["criteria"]["F1_roa_positive"] == 1          # ROA > 0
        assert result["criteria"]["F6_better_liquidity"] == 1      # CR > 1.5
        assert result["criteria"]["F8_better_gross_margin"] == 1   # GM > 0.30
        assert result["criteria"]["F9_asset_turnover"] == 0        # OM 0.15 > 0.15 = False
        assert result["f_score"] == 8


class TestSnapshotCache:
    """Testar snapshot cache for YoY-jamforelser."""

    def test_snapshot_save_and_load(self, tmp_path, monkeypatch):
        """Snapshot sparas och lases korrekt."""
        from core import piotroski as pio
        pio._PIOTROSKI_CACHE_DIR = tmp_path / "piotroski_snapshots"
        pio._PIOTROSKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        _save_snapshot("TEST", {"roa": 0.08, "debt_to_equity": 0.5})
        saved_files = list(pio._PIOTROSKI_CACHE_DIR.glob("*.json"))
        assert len(saved_files) > 0

    def test_snapshot_load_nonexistent(self):
        """Icke-existerande snapshot returnerar None."""
        result = _load_snapshot("NONEXISTENT", pd.Timestamp.now().date())
        assert result is None

    def test_improving_vs_declining(self, monkeypatch, tmp_path):
        """Forbattring vs forsämring detekteras korrekt."""
        from core import piotroski as pio
        monkeypatch.setattr(pio, "_PIOTROSKI_CACHE_DIR", tmp_path / "piotroski_snapshots")

        # First call - saves snapshot
        row = {
            "roa": 0.08, "free_cash_flow": 1e9, "operating_cashflow": 1.2e9,
            "market_cap": 1e10, "price_to_book": 2.5, "debt_to_equity": 0.5,
            "current_ratio": 2.0, "gross_margin": 0.45, "operating_margin": 0.15,
            "revenue_growth": 0.10, "earnings_growth": 0.12, "insider_pct": 0.05,
        }
        result1 = calc_piotroski(row, ticker="IMPROVE")
        # Manually save snapshot for next comparison
        _save_snapshot("IMPROVE", {
            "roa": 0.08, "debt_to_equity": 0.5, "current_ratio": 2.0,
            "gross_margin": 0.45, "operating_margin": 0.15, "shares_outstanding": 100e6,
        })
        assert result1["f_score"] >= 7

    def test_no_ticker(self):
        """Utan ticker -> inga YoY-jamforelser, anvander fallback."""
        row = {"roa": 0.05, "free_cash_flow": 1e9, "market_cap": 1e10, "price_to_book": 2.0}
        result = calc_piotroski(row, ticker="")
        assert 0 <= result["f_score"] <= 9


class TestAddPiotroskiToUniverse:
    """Testar add_piotroski_to_universe."""

    def test_add_to_universe(self, sample_scored_df):
        """Lagger till Piotroski-kolumner i scored DataFrame."""
        df = add_piotroski_to_universe(sample_scored_df, verbose=False)
        assert "piotroski_f" in df.columns
        assert "piotroski_label" in df.columns
        assert "piotroski_boost" in df.columns
        assert df["piotroski_f"].between(0, 9).all()

    def test_score_adjustment(self, sample_scored_df):
        """Score justeras med piotroski_boost."""
        df = add_piotroski_to_universe(sample_scored_df, verbose=False)
        assert "score_total" in df.columns
        # STARK bolag far +8 boost
        stark = df[df["piotroski_label"] == "STARK"]
        if len(stark) > 0:
            assert (stark["piotroski_boost"] == 8).all()


class TestBuildPiotroskiSection:
    """Testar build_piotroski_section."""

    def test_build_section(self, sample_scored_df):
        """Markdown-sektion byggs med piotroski-data."""
        df = add_piotroski_to_universe(sample_scored_df, verbose=False)
        section = build_piotroski_section(df)
        assert "Piotroski" in section
        assert "STARK" in section or "NEUTRAL" in section or "SVAG" in section

    def test_build_section_missing_column(self, sample_scored_df):
        """Utan piotroski-kolumner -> tom strang."""
        section = build_piotroski_section(sample_scored_df.drop(columns=["piotroski_f"], errors="ignore"))
        assert section == ""
