"""
Canary-tester for universe_manager.py (core module, 0 tests before 2026-06-01).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_load_candidates_returns_dict():
    """load_candidates() ska alltid returnera en valformaterad dict."""
    from core.universe_manager import load_candidates
    result = load_candidates()
    assert isinstance(result, dict)
    assert "candidates" in result
    assert "auto_added" in result
    assert "auto_removed" in result


def test_get_all_universe_tickers_runs():
    """get_all_universe_tickers() ska returnera ett set."""
    from core.universe_manager import get_all_universe_tickers
    result = get_all_universe_tickers()
    assert isinstance(result, set)


def test_get_pending_candidates_runs():
    """get_pending_candidates() ska returnera en lista."""
    from core.universe_manager import get_pending_candidates
    result = get_pending_candidates()
    assert isinstance(result, list)


def test_guess_category_us():
    """_guess_category for US-tickers ska returnera US_LARGE_CAP."""
    from core.universe_manager import _guess_category
    assert _guess_category("AAPL") == "US_LARGE_CAP"


def test_guess_category_sweden():
    """_guess_category for svenska tickers ska returnera OMX_SE."""
    from core.universe_manager import _guess_category
    assert _guess_category("VOLV-B.ST") == "OMX_SE"


def test_guess_category_europe():
    """_guess_category for europeiska tickers ska returnera ratt kategori."""
    from core.universe_manager import _guess_category
    assert _guess_category("SAP.DE") == "GERMANY"
    assert _guess_category("MC.PA") == "EUROPE"
    assert _guess_category("BP.L") == "UK"


def test_remove_ticker_never_remove_protected():
    """remove_ticker_from_universe() ska inte ta bort skyddade tickers."""
    from core.universe_manager import remove_ticker_from_universe
    # AAPL is in NEVER_REMOVE - should return False without error
    result = remove_ticker_from_universe("AAPL", "test")
    assert result is False


def test_get_removal_candidates_runs():
    """get_removal_candidates() ska returnera en lista."""
    from core.universe_manager import get_removal_candidates
    result = get_removal_candidates()
    assert isinstance(result, list)
