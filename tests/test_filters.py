"""Tester för core/filters.py — fokus på strike-idempotens."""
import json
from pathlib import Path

import pandas as pd
import pytest

from core import filters as f


def test_strike_idempotent_same_day(tmp_path, monkeypatch):
    """update_ticker_health får inte räkna upp samma ticker två gånger samma dag."""
    strike_file = tmp_path / "strikes.json"
    blacklist_file = tmp_path / "blacklist.json"
    monkeypatch.setattr(f, "STRIKE_FILE", strike_file)
    monkeypatch.setattr(f, "BLACKLIST_FILE", blacklist_file)

    # Första körningen: 1 strike
    f.update_ticker_health(
        attempted_tickers=["FAILED.ST"],
        survived_tickers=[],
        df_raw=pd.DataFrame(),
        fetch_failed=["FAILED.ST"],
    )
    state1 = json.loads(strike_file.read_text())
    assert state1["FAILED.ST"]["count"] == 1

    # Samma dag, samma fail → ska FORTFARANDE vara 1, inte 2
    f.update_ticker_health(
        attempted_tickers=["FAILED.ST"],
        survived_tickers=[],
        df_raw=pd.DataFrame(),
        fetch_failed=["FAILED.ST"],
    )
    state2 = json.loads(strike_file.read_text())
    assert state2["FAILED.ST"]["count"] == 1, \
        "CI-retry samma dag får inte dubblera strikes mot blacklist"


def test_strike_increments_on_new_day(tmp_path, monkeypatch):
    """Strike ska räknas upp om datumet är annorlunda."""
    strike_file = tmp_path / "strikes.json"
    blacklist_file = tmp_path / "blacklist.json"
    monkeypatch.setattr(f, "STRIKE_FILE", strike_file)
    monkeypatch.setattr(f, "BLACKLIST_FILE", blacklist_file)

    # Förfilla med gammal strike från igår
    strike_file.write_text(json.dumps({
        "FAILED.ST": {"count": 1, "date": "2000-01-01"}
    }))

    f.update_ticker_health(
        attempted_tickers=["FAILED.ST"],
        survived_tickers=[],
        df_raw=pd.DataFrame(),
        fetch_failed=["FAILED.ST"],
    )
    state = json.loads(strike_file.read_text())
    assert state["FAILED.ST"]["count"] == 2


def test_never_blacklist_protected(tmp_path, monkeypatch):
    """Tickers i NEVER_BLACKLIST får inte få strikes."""
    strike_file = tmp_path / "strikes.json"
    blacklist_file = tmp_path / "blacklist.json"
    monkeypatch.setattr(f, "STRIKE_FILE", strike_file)
    monkeypatch.setattr(f, "BLACKLIST_FILE", blacklist_file)

    # Hitta en ticker från NEVER_BLACKLIST att testa med
    protected = next(iter(f.NEVER_BLACKLIST))
    f.update_ticker_health(
        attempted_tickers=[protected],
        survived_tickers=[],
        df_raw=pd.DataFrame(),
        fetch_failed=[protected],
    )
    state = json.loads(strike_file.read_text()) if strike_file.exists() else {}
    assert protected not in state
