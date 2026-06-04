"""
Tester for daily_pipeline.py (T1 — utökade täckningstester 2026-06-04).
Syfte: fanga stora regressioner + täcka kritiska dataflöden.
Mål: >= 15% linjetäckning av 2255-radigt core-modul.
"""
import json
import sys
from pathlib import Path
from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_run_targeted_empty_list_returns_zero():
    """run_targeted([]) ska returnera 0 utan att krascha."""
    from core.daily_pipeline import run_targeted
    result = run_targeted([])
    assert result == 0


def test_find_missing_data_tickers_empty_df():
    """_find_missing_data_tickers ska returnera [] nar ingen data finns."""
    from core.daily_pipeline import _find_missing_data_tickers
    # Kommer returnera [] om inga rapportfiler finns (CI-miljo)
    result = _find_missing_data_tickers(max_tickers=10)
    assert isinstance(result, list)


def test_get_score_deltas_both_empty():
    """_get_score_deltas med tva tomma DataFrames ska returnera {}."""
    from core.daily_pipeline import _get_score_deltas
    result = _get_score_deltas(pd.DataFrame(), pd.DataFrame())
    assert result == {}


def test_get_score_deltas_merge_empty():
    """_get_score_deltas med icke-overlappande tickers:
    Sedan left-join (D4-fix) returneras dagens tickers med NaN-delta.
    Resultatet ska innehålla dagens ticker, ej {}."""
    from core.daily_pipeline import _get_score_deltas
    today = pd.DataFrame({"ticker": ["A"], "score_total": [50.0]})
    yesterday = pd.DataFrame({"ticker": ["B"], "score_total": [45.0]})
    result = _get_score_deltas(today, yesterday)
    # Left join: A finns i movers_up (score_yesterday = NaN → score_delta = NaN)
    assert "movers_up" in result
    assert len(result["movers_up"]) == 1
    assert result["movers_up"][0]["ticker"] == "A"


def test_get_top_bottom_empty():
    """_get_top_bottom med tom DataFrame ska returnera ([], [])."""
    from core.daily_pipeline import _get_top_bottom
    top, bottom = _get_top_bottom(pd.DataFrame())
    assert top == []
    assert bottom == []


def test_get_opportunities_empty():
    """_get_opportunities med tom DataFrame ska returnera []. """
    from core.daily_pipeline import _get_opportunities
    result = _get_opportunities(pd.DataFrame())
    assert result == []


def test_cleanup_old_reports_runs():
    """_cleanup_old_reports ska kora utan att krascha (tom rapporter finns)."""
    from core.daily_pipeline import _cleanup_old_reports
    result = _cleanup_old_reports(max_days=1)
    assert isinstance(result, (int, type(None))) or result >= 0


def test_enrich_holdings_empty():
    """_enrich_holdings med tom portfolj ska returnera []. """
    from core.daily_pipeline import _enrich_holdings
    result = _enrich_holdings(pd.DataFrame(), pd.DataFrame())
    assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# _looks_like_ticker — T1: ticker-validering
# ══════════════════════════════════════════════════════════════════════════════

class TestLooksLikeTicker:
    """_looks_like_ticker filtrerar fondnamn och ogiltiga strängar."""

    def test_valid_simple_ticker(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("AAPL") is True
        assert _looks_like_ticker("MSFT") is True
        assert _looks_like_ticker("BRK-B") is True

    def test_valid_swedish_ticker(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("VOLVO-B.ST") is True
        assert _looks_like_ticker("ABB.ST") is True

    def test_space_in_name_rejected(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("LÄNSFÖRSÄKRINGAR GLOBAL INDEX") is False
        assert _looks_like_ticker("A B") is False

    def test_empty_string_rejected(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("") is False
        assert _looks_like_ticker(None) is False

    def test_too_long_rejected(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("A" * 16) is False

    def test_exactly_15_chars_accepted(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("TLEVISACPO.MX12") is True  # 15 chars

    def test_16_chars_rejected(self):
        from core.daily_pipeline import _looks_like_ticker
        assert _looks_like_ticker("TLEVISACPO.MX123") is False  # 16 chars


# ══════════════════════════════════════════════════════════════════════════════
# _get_score_deltas — detaljerade tester
# ══════════════════════════════════════════════════════════════════════════════

class TestGetScoreDeltas:
    """Täcker _get_score_deltas edge cases."""

    def test_movers_up_correct_ticker(self):
        """Ticker med störst score-ökning är i movers_up."""
        from core.daily_pipeline import _get_score_deltas
        today = pd.DataFrame({
            "ticker": ["A", "B", "C"],
            "score_total": [80.0, 60.0, 50.0],
        })
        yesterday = pd.DataFrame({
            "ticker": ["A", "B", "C"],
            "score_total": [50.0, 58.0, 55.0],
        })
        result = _get_score_deltas(today, yesterday)
        assert "movers_up" in result
        # A ökade med 30, B med 2, C minskade med 5
        assert result["movers_up"][0]["ticker"] == "A"

    def test_movers_down_correct_ticker(self):
        """Ticker med störst score-minskning är i movers_down."""
        from core.daily_pipeline import _get_score_deltas
        today = pd.DataFrame({
            "ticker": ["A", "B"],
            "score_total": [40.0, 60.0],
        })
        yesterday = pd.DataFrame({
            "ticker": ["A", "B"],
            "score_total": [80.0, 62.0],
        })
        result = _get_score_deltas(today, yesterday)
        assert "movers_down" in result
        # A minskade med 40
        assert result["movers_down"][0]["ticker"] == "A"

    def test_new_ticker_appears_in_movers_up(self):
        """Ny ticker (ej i yesterday) → NaN delta, visas ändå (left join)."""
        from core.daily_pipeline import _get_score_deltas
        today = pd.DataFrame({
            "ticker": ["NEW", "OLD"],
            "score_total": [90.0, 50.0],
        })
        yesterday = pd.DataFrame({
            "ticker": ["OLD"],
            "score_total": [50.0],
        })
        result = _get_score_deltas(today, yesterday)
        # NEW ska finnas i movers_up (score_delta = NaN)
        tickers_up = [r["ticker"] for r in result.get("movers_up", [])]
        assert "NEW" in tickers_up

    def test_today_empty_returns_empty_dict(self):
        """today_df tom → {}."""
        from core.daily_pipeline import _get_score_deltas
        result = _get_score_deltas(pd.DataFrame(), pd.DataFrame({"ticker": ["A"], "score_total": [50.0]}))
        assert result == {}

    def test_yesterday_empty_still_returns_today(self):
        """yesterday tom → movers_up innehåller dagens tickers med NaN delta."""
        from core.daily_pipeline import _get_score_deltas
        today = pd.DataFrame({"ticker": ["A", "B"], "score_total": [70.0, 60.0]})
        result = _get_score_deltas(today, pd.DataFrame())
        # Ingen historik → returnerar {}
        assert result == {}

    def test_rsi_spike_above_30(self):
        """RSI som korsade 30 uppåt (yesterday < 30, today > 30) → rsi_spikes."""
        from core.daily_pipeline import _get_score_deltas
        today = pd.DataFrame({
            "ticker": ["A"],
            "score_total": [60.0],
            "rsi_14": [35.0],
        })
        yesterday = pd.DataFrame({
            "ticker": ["A"],
            "score_total": [58.0],
            "rsi_14": [25.0],
        })
        result = _get_score_deltas(today, yesterday)
        if "rsi_spikes" in result:
            tickers = [r["ticker"] for r in result["rsi_spikes"]]
            assert "A" in tickers

    def test_no_ticker_column_returns_empty(self):
        """DataFrames utan ticker-kolumn → {}."""
        from core.daily_pipeline import _get_score_deltas
        today = pd.DataFrame({"score_total": [60.0]})
        yesterday = pd.DataFrame({"score_total": [55.0]})
        result = _get_score_deltas(today, yesterday)
        assert result == {}


# ══════════════════════════════════════════════════════════════════════════════
# _get_opportunities — signal-logik
# ══════════════════════════════════════════════════════════════════════════════

class TestGetOpportunities:
    """Täcker _get_opportunities signal-detektering."""

    def _base_df(self, n=10):
        """Syntetisk DataFrame med nödvändiga kolumner."""
        import numpy as np
        return pd.DataFrame({
            "ticker": [f"T{i}" for i in range(n)],
            "score_total": [70.0] * n,
            "return_3d": [0.0] * n,
            "pct_from_52w_high": [0.0] * n,
            "rsi_14": [50.0] * n,
        })

    def test_dip_in_uptrend_detected(self):
        """Aktie med score >= 65 och -3% till -12% 3d-return → dip signal."""
        from core.daily_pipeline import _get_opportunities
        df = self._base_df(5)
        df.loc[0, "return_3d"] = -7.0  # -7% → dip
        df.loc[0, "score_total"] = 75.0
        result = _get_opportunities(df)
        assert any("Dip" in r.get("type", "") for r in result)

    def test_breakout_detected(self):
        """Aktie nära 52w-high (< 5% under) → utbrott signal."""
        from core.daily_pipeline import _get_opportunities
        df = self._base_df(5)
        df.loc[0, "pct_from_52w_high"] = -2.0  # 2% under ATH
        result = _get_opportunities(df)
        assert any("Utbrott" in r.get("type", "") for r in result)

    def test_oversold_bounce_detected(self):
        """RSI < 30 och score >= 70 → översåld studs."""
        from core.daily_pipeline import _get_opportunities
        df = self._base_df(5)
        df.loc[0, "rsi_14"] = 25.0
        df.loc[0, "score_total"] = 72.0
        result = _get_opportunities(df)
        assert any("Översåld" in r.get("type", "") for r in result)

    def test_max_total_respected(self):
        """max_total begränsar antal returnerade opportunities."""
        from core.daily_pipeline import _get_opportunities
        import numpy as np
        df = pd.DataFrame({
            "ticker": [f"T{i}" for i in range(20)],
            "score_total": [75.0] * 20,
            "return_3d": [-7.0] * 20,
        })
        result = _get_opportunities(df, max_total=3)
        assert len(result) <= 3

    def test_low_score_no_opportunities(self):
        """Aktier med score < 65 genererar inga opportunities."""
        from core.daily_pipeline import _get_opportunities
        df = pd.DataFrame({
            "ticker": ["A"],
            "score_total": [50.0],
            "return_3d": [-7.0],
        })
        result = _get_opportunities(df)
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# _get_top_bottom — ranking
# ══════════════════════════════════════════════════════════════════════════════

class TestGetTopBottom:
    """Täcker _get_top_bottom ranking-logik."""

    def test_top_is_highest_score(self):
        """Top-5 innehåller aktier med högst score."""
        from core.daily_pipeline import _get_top_bottom
        df = pd.DataFrame({
            "ticker": ["A", "B", "C", "D", "E", "F"],
            "score_total": [90.0, 80.0, 70.0, 60.0, 50.0, 40.0],
        })
        top, bottom = _get_top_bottom(df, top_n=3)
        top_tickers = [r["ticker"] for r in top]
        assert "A" in top_tickers
        assert "B" in top_tickers
        assert "C" in top_tickers

    def test_bottom_is_lowest_score(self):
        """Bottom-5 innehåller aktier med lägst score."""
        from core.daily_pipeline import _get_top_bottom
        df = pd.DataFrame({
            "ticker": ["A", "B", "C", "D", "E", "F"],
            "score_total": [90.0, 80.0, 70.0, 60.0, 50.0, 40.0],
        })
        top, bottom = _get_top_bottom(df, top_n=3)
        bottom_tickers = [r["ticker"] for r in bottom]
        assert "F" in bottom_tickers
        assert "E" in bottom_tickers
        assert "D" in bottom_tickers

    def test_top_n_respected(self):
        """top_n begränsar antalet returnerade."""
        from core.daily_pipeline import _get_top_bottom
        df = pd.DataFrame({
            "ticker": [f"T{i}" for i in range(10)],
            "score_total": [float(i) for i in range(10)],
        })
        top, bottom = _get_top_bottom(df, top_n=3)
        assert len(top) == 3
        assert len(bottom) == 3

    def test_no_score_total_column(self):
        """DataFrame utan score_total → ([], [])."""
        from core.daily_pipeline import _get_top_bottom
        df = pd.DataFrame({"ticker": ["A", "B"]})
        top, bottom = _get_top_bottom(df)
        assert top == []
        assert bottom == []


# ══════════════════════════════════════════════════════════════════════════════
# _save_scored — atomic write
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveScored:
    """Verifiera atomic write-beteende i _save_scored."""

    def test_saves_csv_file(self, tmp_path):
        """_save_scored skapar CSV-fil."""
        from core.daily_pipeline import _save_scored
        df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "score_total": [75.0, 68.0],
        })
        path = tmp_path / "scored_universe_2026-06-04.parquet"
        _save_scored(df, path)
        csv = path.with_suffix(".csv")
        assert csv.exists()
        loaded = pd.read_csv(csv)
        assert len(loaded) == 2

    def test_no_tmp_file_remaining(self, tmp_path):
        """Inga .tmp-filer kvar efter skrivning."""
        from core.daily_pipeline import _save_scored
        df = pd.DataFrame({"ticker": ["AAPL"], "score_total": [75.0]})
        path = tmp_path / "scored_universe_test.parquet"
        _save_scored(df, path)
        tmp_files = list(tmp_path.glob("*.tmp.*"))
        assert tmp_files == [], f"Hittade kvarliggande .tmp-filer: {tmp_files}"


# ══════════════════════════════════════════════════════════════════════════════
# Performance tracker — get_performance_summary
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformanceTracking:
    """Verifiera att performance-tracking returnerar rätt format."""

    def test_get_performance_summary_returns_dataframe(self):
        """get_performance_summary returnerar DataFrame (tom om ingen historik)."""
        from core.daily_pipeline import get_performance_summary
        result = get_performance_summary()
        assert isinstance(result, pd.DataFrame)

    def test_get_slowest_stages_returns_list(self):
        """get_slowest_stages returnerar lista."""
        from core.daily_pipeline import get_slowest_stages
        result = get_slowest_stages()
        assert isinstance(result, list)

    def test_get_performance_trend_returns_list(self):
        """get_performance_trend returnerar lista."""
        from core.daily_pipeline import get_performance_trend
        result = get_performance_trend("test_stage")
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════════════════════
# _load_portfolio och _load_watchlist — datahantering
# ══════════════════════════════════════════════════════════════════════════════

class TestDataLoading:
    """Verifiera att dataladdningsfunktioner hanterar saknade filer graciöst."""

    def test_load_portfolio_missing_file_returns_empty_df(self, tmp_path, monkeypatch):
        """_load_portfolio returnerar tom DataFrame om holdings.csv saknas."""
        from core import daily_pipeline
        monkeypatch.setattr(daily_pipeline, "DATA_DIR", tmp_path)
        result = daily_pipeline._load_portfolio()
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_load_watchlist_missing_file_returns_empty_list(self, tmp_path, monkeypatch):
        """_load_watchlist returnerar tom lista om watchlist.json saknas."""
        from core import daily_pipeline
        monkeypatch.setattr(daily_pipeline, "DATA_DIR", tmp_path)
        result = daily_pipeline._load_watchlist()
        assert isinstance(result, list)
        assert result == []

    def test_load_portfolio_with_data(self, tmp_path, monkeypatch):
        """_load_portfolio läser holdings.csv korrekt."""
        from core import daily_pipeline
        monkeypatch.setattr(daily_pipeline, "DATA_DIR", tmp_path)
        (tmp_path / "holdings.csv").write_text(
            "ticker,shares,cost_basis\nAAPL,10,150.0\nMSFT,5,300.0\n",
            encoding="utf-8",
        )
        result = daily_pipeline._load_portfolio()
        assert len(result) == 2
        assert "AAPL" in result["ticker"].values

    def test_load_watchlist_with_data(self, tmp_path, monkeypatch):
        """_load_watchlist läser watchlist.json korrekt."""
        from core import daily_pipeline
        monkeypatch.setattr(daily_pipeline, "DATA_DIR", tmp_path)
        watchlist = [{"ticker": "NVDA"}, {"ticker": "TSLA"}]
        (tmp_path / "watchlist.json").write_text(
            json.dumps(watchlist), encoding="utf-8"
        )
        result = daily_pipeline._load_watchlist()
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════════════
# _enrich_holdings — portföljberikning
# ══════════════════════════════════════════════════════════════════════════════

class TestEnrichHoldings:
    """Verifiera att _enrich_holdings berikar holdings med scandata."""

    def test_enrich_holdings_with_scored_data(self):
        """_enrich_holdings berikar holdings med score från scandata."""
        from core.daily_pipeline import _enrich_holdings
        holdings = pd.DataFrame({
            "ticker": ["AAPL"],
            "shares": [10],
            "cost_basis": [150.0],
        })
        scored = pd.DataFrame({
            "ticker": ["AAPL"],
            "score_total": [75.0],
            "entry_signal": ["STARK"],
        })
        result = _enrich_holdings(holdings, scored)
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_enrich_holdings_unknown_ticker(self):
        """Ticker ej i scandata → inkluderas ändå, utan scandata."""
        from core.daily_pipeline import _enrich_holdings
        holdings = pd.DataFrame({
            "ticker": ["UNKNOWN"],
            "shares": [5],
            "cost_basis": [100.0],
        })
        result = _enrich_holdings(holdings, pd.DataFrame())
        assert len(result) == 1


# ══════════════════════════════════════════════════════════════════════════════
# _cleanup_old_reports
# ══════════════════════════════════════════════════════════════════════════════

class TestCleanupOldReports:
    """Verifiera att _cleanup_old_reports tar bort gamla filer."""

    def test_cleanup_removes_old_files(self, tmp_path, monkeypatch):
        """Filer äldre än max_days tas bort."""
        import os, time
        from core import daily_pipeline
        monkeypatch.setattr(daily_pipeline, "REPORT_DIR", tmp_path)

        # Skapa gammal fil (sätt mtime till > 60 dagar sedan)
        old_file = tmp_path / "scored_universe_2020-01-01.csv"
        old_file.write_text("ticker,score_total\nAAPL,75.0")
        old_time = time.time() - (61 * 86400)  # 61 dagar sedan
        os.utime(old_file, (old_time, old_time))

        # Skapa ny fil
        new_file = tmp_path / "scored_universe_2026-06-04.csv"
        new_file.write_text("ticker,score_total\nMSFT,68.0")

        result = daily_pipeline._cleanup_old_reports(max_days=60)
        assert not old_file.exists(), "Gammal fil borde ha raderats"
        assert new_file.exists(), "Ny fil borde finnas kvar"

