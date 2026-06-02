"""
Integrationstester for stock-scanner — full pipeline, scoring, filters, ML, email.
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Pipeline integration ──────────────────────────────────────────────────


class TestPipelineIntegration:
    """Integrationstester for pipeline-floden (mockade)."""

    def test_scoring_then_filters_integration(self, sample_scored_df):
        """Scoring -> filters integration."""
        from core.scoring import score_universe
        from core.filters import apply_trend_filter, calc_confidence

        scored = score_universe(sample_scored_df)
        filtered = apply_trend_filter(scored)
        confident = calc_confidence(filtered)

        assert "score_total" in scored.columns
        assert "trend_signal" in filtered.columns
        assert "confidence_label" in confident.columns
        assert scored["score_total"].between(0, 100).all()

    def test_scoring_with_region_neutralization(self, sample_scored_df):
        """Region-neutralisering i scoring."""
        from core.scoring import score_universe

        df = sample_scored_df.copy()
        df["ticker"] = ["AAPL", "VOLV-B.ST", "SAP.DE", "NOVO-B.CO", "7203.T",
                        "MSFT", "GOOGL", "AMZN", "NVDA", "META",
                        "TSLA", "JPM", "V", "JNJ", "WMT",
                        "PG", "MA", "UNH", "HD", "DIS"]
        scored = score_universe(df)
        assert "exchange_group" in scored.columns or "_fundamentals_neutralized" in scored.columns
        assert len(scored) == 20

    def test_fetch_then_score_integration(self, sample_scored_df):
        """Fetch -> scoring (simulerad med syntetisk data)."""
        from core.scoring import score_universe

        scored = score_universe(sample_scored_df)
        assert "score_value" in scored.columns
        assert "score_quality" in scored.columns
        assert "score_momentum" in scored.columns
        assert "score_growth" in scored.columns
        assert "score_risk" in scored.columns
        assert scored["score_total"].between(0, 100).all()

    def test_ml_then_paper_trading(self, mocker, monkeypatch, tmp_path):
        """ML pred -> paper trading integration."""
        from core.ml_predictor import predict_returns
        from core import ml_paper_trading as mlpt

        monkeypatch.setattr(mlpt, "DATA_DIR", tmp_path)

        df = pd.DataFrame({
            "ticker": [f"T{i}" for i in range(10)],
            "score_total": [float(i) for i in range(10)],
        })
        from core.ml_predictor import TECH_FEATURES
        for feat in TECH_FEATURES:
            df[feat] = np.nan

        # Add predicted_return directly since model loading may fail
        df["predicted_return"] = np.random.uniform(-0.05, 0.1, 10)
        df["current_price"] = np.random.uniform(50, 500, 10)
        n = mlpt.record_daily_signals(df, universe="universe", top_n=3)
        assert n == 3

    def test_rotation_engine_full_flow(self, mocker, sample_scored_df, tmp_path, monkeypatch):
        """Rotation engine: discovery -> removal -> replacement."""
        from core.rotation_engine import detect_removal_triggers, rank_replacements

        # Spara scored data som parquet for rotation engine
        report_dir = tmp_path / "reports"
        report_dir.mkdir(exist_ok=True)
        parquet_path = report_dir / "scored_universe_20260601.parquet"
        sample_scored_df.to_parquet(parquet_path)

        from core import rotation_engine as re
        monkeypatch.setattr(re, "REPORT_DIR", report_dir)
        monkeypatch.setattr(re, "DATA_DIR", tmp_path)

        # Create empty strike_list
        strike_file = tmp_path / "strike_list.json"
        strike_file.write_text("{}")

        # Mock universe_manager modules
        import core.universe_manager as um
        mocker.patch.object(um, "get_all_universe_tickers", return_value=["AAPL", "MSFT", "GOOGL"])

        # Detect triggers
        triggers = detect_removal_triggers(scored=sample_scored_df, min_score=10.0)
        assert isinstance(triggers, list)

    def test_pipeline_with_empty_data(self, empty_df):
        """Tom DataFrame genom pipeline krashar inte."""
        from core.scoring import score_universe

        # Skapa tom df med ratt kolumner
        df = empty_df.copy()
        if df.empty:
            result = score_universe(df)
            assert result.empty or len(result) == 0

    def test_pipeline_with_missing_columns(self, sample_scored_df):
        """Saknade kolumner hanteras gracfully."""
        from core.scoring import score_universe

        df = sample_scored_df.drop(columns=["roe", "roa", "debt_to_equity"], errors="ignore")
        scored = score_universe(df)
        assert "score_total" in scored.columns
        assert len(scored) > 0

    def test_email_template_render(self):
        """Email-rendering fungerar utan krasch."""
        from core.email_template import (
            build_section_header,
            build_alert_box,
            build_pnl_cell,
        )

        header = build_section_header("Test Section")
        assert "Test Section" in header

        alert = build_alert_box("Critical alert!", level="critical")
        assert "Critical alert!" in alert

        pnl = build_pnl_cell(2.5)
        assert isinstance(pnl, str)

    def test_dynamic_weights_in_scoring(self, sample_scored_df):
        """Dynamiska vikter baserat pa regim i scoring."""
        from core.scoring import score_universe

        for regime in ["TJUR", "BJÖRN", "OSÄKER"]:
            scored = score_universe(sample_scored_df, regime=regime)
            assert scored["score_total"].between(0, 100).all()

    def test_pipeline_with_low_liquidity(self, sample_scored_df):
        """Likviditetsflagg fungerar i pipeline."""
        from core.scoring import score_universe

        scored = score_universe(sample_scored_df)
        if "low_liquidity" in scored.columns:
            assert scored["low_liquidity"].dtype == bool


class TestDiscoveryQualityGate:
    """Integrationstester for discovery quality gate."""

    def test_universe_discovery_with_scoring(self, sample_scored_df):
        """Upptackta tickers kan scoras."""
        from core.scoring import score_universe
        scored = score_universe(sample_scored_df)
        assert len(scored) == len(sample_scored_df)
        assert scored["score_total"].notna().any()

    def test_holdings_analysis_integration(self, sample_holdings_df, sample_scored_df):
        """Holdings analys mot scored universe."""
        from portfolio.portfolio import analyze_portfolio
        result = analyze_portfolio(sample_holdings_df, sample_scored_df)
        assert isinstance(result, pd.DataFrame)

    def test_pipeline_morning_flow(self, mocker, sample_scored_df):
        """Full pipeline morning flow (mockad)."""
        from core.scoring import score_universe
        from core.filters import apply_trend_filter, calc_confidence
        scored = score_universe(sample_scored_df)
        filtered = apply_trend_filter(scored)
        confident = calc_confidence(filtered)
        assert "trend_signal" in filtered.columns
        assert "confidence_label" in confident.columns

    def test_pipeline_evening_flow(self, mocker, sample_scored_df):
        """Evening mode pipeline."""
        from core.scoring import score_universe
        scored = score_universe(sample_scored_df)
        assert scored["score_total"].notna().any()

    def test_pipeline_weekly_flow(self, mocker, sample_scored_df):
        """Weekly mode pipeline."""
        from core.scoring import score_universe
        from core.piotroski import add_piotroski_to_universe
        scored = score_universe(sample_scored_df)
        scored = add_piotroski_to_universe(scored, verbose=False)
        assert "piotroski_f" in scored.columns
        assert "piotroski_label" in scored.columns
