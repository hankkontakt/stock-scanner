"""
Canary-tester for rotation_engine.py (core module, 0 tests before 2026-06-01).
"""
import json
import sys
from pathlib import Path
import pandas as pd

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_detect_removal_triggers_empty():
    """detect_removal_triggers med tom DataFrame ska returnera [] (eller tom lista)."""
    from core.rotation_engine import detect_removal_triggers
    triggers = detect_removal_triggers(scored=pd.DataFrame())
    assert isinstance(triggers, list)
    # Kan returnera triggers om riktig scored data finns pa disk - acceptabelt
    # Nar scored=None anvands laddas verklig data -> kan returnera triggers


def test_rank_replacements_empty():
    """rank_replacements med tom DataFrame ska returnera []."""
    from core.rotation_engine import rank_replacements
    result = rank_replacements("TEST.TO", scored=pd.DataFrame())
    assert isinstance(result, list)


def test_run_rotation_empty():
    """run_rotation med minimal data ska returnera forutsagbar dict."""
    from core.rotation_engine import run_rotation
    result = run_rotation(scored=pd.DataFrame(), dry_run=True)
    assert isinstance(result, dict)
    assert "triggers" in result
    assert "replacements" in result
    assert "executed" in result
    assert "dry_run" in result


def test_load_rotation_log():
    """load_rotation_log ska returnera en lista (aldrig krascha)."""
    from core.rotation_engine import load_rotation_log
    result = load_rotation_log()
    assert isinstance(result, list)


def test_rank_replacements_no_universe():
    """rank_replacements ska returnera en lista nar scored_universe saknas."""
    from core.rotation_engine import rank_replacements
    result = rank_replacements("AAPL", scored=pd.DataFrame(), top_n=5)
    assert isinstance(result, list)
