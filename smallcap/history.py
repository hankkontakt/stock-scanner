"""
history.py - Trendspårning mellan körningar.

Sparar senaste körningens totalpoäng per ticker och jämför med
aktuell körning för att visa trendindikatorer i rapporten.

  ▲  = poäng ökat >2p sedan förra körning
  ▼  = poäng minskat >2p sedan förra körning
  ->  = stabil eller ny ticker
  •  = ny ticker (saknas i historik)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

_HISTORY_DIR  = Path(__file__).parent.parent / "data"
_SCORES_FILE  = _HISTORY_DIR / "smallcap_scores_prev.json"
_TREND_THRESH = 2.0   # Minsta poängförändring för att visa pil


def save_scores(scored: pd.DataFrame) -> None:
    """Sparar aktuella sc_total-poäng till JSON för nästa körning."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, float] = {}
    for _, row in scored.iterrows():
        ticker = row.get("ticker")
        score  = row.get("sc_total")
        if ticker and score is not None:
            try:
                data[str(ticker)] = round(float(score), 2)
            except (ValueError, TypeError):
                pass
    try:
        _SCORES_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def load_prev_scores() -> dict[str, float]:
    """Läser föregående körnings poäng. Returnerar {} om ingen historik."""
    try:
        if _SCORES_FILE.exists():
            return json.loads(_SCORES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def arrow(ticker: str, current_score: float, prev: dict[str, float]) -> str:
    """
    Returnerar trendpil baserat på poängförändring sedan förra körning.
      ▲  ökat >2p
      ▼  minskat >2p
      ->  stabilt
      •  ny ticker
    """
    if ticker not in prev:
        return "•"
    delta = current_score - prev[ticker]
    if delta > _TREND_THRESH:
        return "▲"
    if delta < -_TREND_THRESH:
        return "▼"
    return "->"


def delta_str(ticker: str, current_score: float, prev: dict[str, float]) -> str:
    """Returnerar poängdelta som sträng, t.ex. '+3.2' eller 'ny'."""
    if ticker not in prev:
        return "ny"
    d = current_score - prev[ticker]
    return f"{d:+.1f}"
