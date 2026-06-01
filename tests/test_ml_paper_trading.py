"""Tester för core/ml_paper_trading.py -- separat track record för ML."""
import json
from pathlib import Path

import pandas as pd
import pytest

from core import ml_paper_trading as mlpt


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Isolera test så det inte rör riktiga data/ml_paper_*.json."""
    monkeypatch.setattr(mlpt, "DATA_DIR", tmp_path)


def _sample_scored(predicted_returns: list) -> pd.DataFrame:
    return pd.DataFrame({
        "ticker": [f"T{i}" for i in range(len(predicted_returns))],
        "name": [f"Test {i}" for i in range(len(predicted_returns))],
        "current_price": [100.0 + i for i in range(len(predicted_returns))],
        "predicted_return": predicted_returns,
    })


def test_record_signals_picks_top_n():
    df = _sample_scored([0.1, 0.05, 0.2, -0.1, 0.15, 0.03])
    n = mlpt.record_daily_signals(df, universe="universe", top_n=3)
    assert n == 3
    store = mlpt._load_store("universe")
    # Topp-3 ska vara T2 (0.2), T4 (0.15), T0 (0.1)
    tickers = {t["ticker"] for t in store["trades"]}
    assert tickers == {"T2", "T4", "T0"}


def test_record_signals_idempotent_same_day():
    df = _sample_scored([0.1, 0.2, 0.15])
    n1 = mlpt.record_daily_signals(df, universe="universe", top_n=2)
    n2 = mlpt.record_daily_signals(df, universe="universe", top_n=2)
    assert n1 == 2
    assert n2 == 0  # Samma dag -> ingen ny registrering


def test_get_summary_empty():
    s = mlpt.get_summary("universe")
    assert s["n_trades"] == 0
    assert s["equity"] == mlpt.INITIAL_EQUITY


def test_get_summary_with_open_positions():
    df = _sample_scored([0.1, 0.2])
    mlpt.record_daily_signals(df, universe="universe", top_n=2)
    s = mlpt.get_summary("universe")
    assert s["n_open"] == 2
    assert s["n_closed"] == 0
    assert s["hit_rate"] is None  # inga stängda


def test_universe_smallcap_are_separate():
    df_u = _sample_scored([0.1])
    df_s = _sample_scored([0.2])
    mlpt.record_daily_signals(df_u, universe="universe", top_n=1)
    mlpt.record_daily_signals(df_s, universe="smallcap", top_n=1)
    s_u = mlpt.get_summary("universe")
    s_s = mlpt.get_summary("smallcap")
    assert s_u["n_trades"] == 1
    assert s_s["n_trades"] == 1
    # Två separata filer ska existera
    assert (mlpt.DATA_DIR / "ml_paper_universe.json").exists()
    assert (mlpt.DATA_DIR / "ml_paper_smallcap.json").exists()
