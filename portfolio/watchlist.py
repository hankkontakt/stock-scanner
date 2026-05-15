"""
watchlist.py
============
Bevakningslista – aktier som bevakas extra noga utanför portföljen.
Sparas i data/watchlist.json och ingår automatiskt i alla tre rapporter.
"""

import json
from datetime import date
from pathlib import Path

from core import config

WATCHLIST_FILE = getattr(config, "WATCHLIST_FILE", "data/watchlist.json")


def load_watchlist() -> list:
    """Returnerar lista av dicts: [{ticker, name, added}, ...]"""
    path = Path(WATCHLIST_FILE)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_watchlist(items: list):
    path = Path(WATCHLIST_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def get_tickers() -> list:
    return [item["ticker"] for item in load_watchlist()]


def add_ticker(ticker: str, name: str = "") -> bool:
    """Lägg till ticker. Returnerar True om ny, False om redan fanns."""
    items = load_watchlist()
    for item in items:
        if item["ticker"] == ticker.upper():
            return False
    items.append({"ticker": ticker.upper(), "name": name, "added": str(date.today())})
    save_watchlist(items)
    return True


def remove_ticker(ticker: str) -> bool:
    """Ta bort ticker. Returnerar True om borttagen."""
    items = load_watchlist()
    before = len(items)
    items = [i for i in items if i["ticker"] != ticker.upper()]
    if len(items) == before:
        return False
    save_watchlist(items)
    return True
