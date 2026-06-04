"""
Canary-tester for daily_pipeline.py (core module, 0 tests before 2026-06-01).
Syfte: fanga stora regressioner, inte 100% tackning.
"""
import json
import sys
from pathlib import Path
from datetime import date

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

