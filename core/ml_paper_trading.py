"""
ml_paper_trading.py -- Separat paper-trading-lager för ML-modellen.

Varje dag (när pipeline körs) sparas topp-N enligt `predicted_return` som
virtuella köp. Nästa dag/körning beräknas P&L mot dagens close. Equity-kurva
spåras separat per universum.

Lagring:
    data/ml_paper_universe.json    -- för stora aktier
    data/ml_paper_smallcap.json    -- för svenska småbolag

JSON-struktur:
{
  "trades": [
    {"date": "2026-05-20", "ticker": "AAPL", "entry_price": 213.5,
     "predicted_return": 0.034, "exit_date": null, "exit_price": null,
     "realized_return": null},
    ...
  ],
  "equity_curve": [
    {"date": "2026-05-20", "equity": 100000.0, "n_open": 10}
  ]
}

Strategy: enkel "top-N equal-weight, hold 30 dagar". Realistiskt nog för
att jämföra modellprestation mot existerande paper_trading (klassisk score).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INITIAL_EQUITY = 100_000.0
HOLD_DAYS = 30  # Stäng position efter 30 dagar

_DAILY_CHECK_INTERVAL = timedelta(hours=1)  # Kolla exit-villkor varje timme


def _close_expired_positions(store: dict, today: date) -> int:
    """Stäng positioner som passerat HOLD_DAYS.

    Rensar dagar då portföljen inte aktivt handlats (helger/ledighet).
    Returnerar antal stängda positioner.
    """
    closed = 0
    for t in store.get("trades", []):
        if t.get("exit_date") is not None:
            continue
        entry = t.get("date")
        if not entry:
            continue
        try:
            entry_date = datetime.strptime(entry, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        calendar_days = (today - entry_date).days
        if calendar_days >= HOLD_DAYS:
            # Stäng till dagens pris om tillgängligt, annars entry_price
            close_price = t.get("current_price") or t.get("entry_price", 0)
            exit_price = close_price if close_price > 0 else t["entry_price"]
            realized = (exit_price / t["entry_price"]) - 1 if t["entry_price"] else 0
            t["exit_date"] = today.strftime("%Y-%m-%d")
            t["exit_price"] = exit_price
            t["realized_return"] = round(realized, 6)
            closed += 1
    return closed


def _store_path(universe: str) -> Path:
    return DATA_DIR / f"ml_paper_{universe}.json"


def _load_store(universe: str) -> dict:
    path = _store_path(universe)
    if not path.exists():
        return {"trades": [], "equity_curve": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"trades": [], "equity_curve": []}


def _save_store(universe: str, store: dict):
    """Atomic write."""
    path = _store_path(universe)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def record_daily_signals(scored_df: pd.DataFrame, universe: str,
                         top_n: int = 10) -> int:
    """Registrerar dagens topp-N enligt predicted_return som öppna positioner.

    Idempotent: om dagens signaler redan registrerats görs ingenting.
    Returnerar antalet NYA registrerade positioner.
    """
    if "predicted_return" not in scored_df.columns:
        return 0

    today = _today_str()
    store = _load_store(universe)

    # Hoppa över om vi redan har trades från idag
    existing_today = [t for t in store["trades"] if t.get("date") == today]
    if existing_today:
        return 0

    # Välj topp-N baserat på predicted_return, kräver giltigt pris
    price_col = None
    for cand in ("current_price", "close", "price"):
        if cand in scored_df.columns:
            price_col = cand
            break
    if price_col is None:
        logger.warning("Kan inte registrera ML-signaler -- saknar pris-kolumn")
        return 0

    df = scored_df.dropna(subset=["predicted_return", price_col]).copy()
    if df.empty:
        return 0

    top = df.nlargest(top_n, "predicted_return")

    n_added = 0
    for _, row in top.iterrows():
        try:
            entry_price = float(row[price_col])
        except (TypeError, ValueError):
            continue
        if not entry_price or entry_price <= 0:
            continue
        store["trades"].append({
            "date": today,
            "ticker": str(row.get("ticker", "")),
            "name": str(row.get("name", "")),
            "entry_price": entry_price,
            "predicted_return": float(row["predicted_return"]),
            "exit_date": None,
            "exit_price": None,
            "realized_return": None,
        })
        n_added += 1

    # Uppdatera equity-snapshot
    open_trades = [t for t in store["trades"] if t.get("exit_date") is None]
    store["equity_curve"].append({
        "date": today,
        "equity": _compute_equity(store["trades"]),
        "n_open": len(open_trades),
    })

    _save_store(universe, store)
    return n_added


def _compute_equity(trades: list) -> float:
    """Beräkna equity genom att compounda avkastning sekventiellt.

    Varje stängd trade bidrar med (1 + realized_return) multiplikativt.
    Öppna trades räknas inte (orealiserad avkastning ignoreras).
    """
    if not trades:
        return INITIAL_EQUITY
    closed = [t for t in trades if t.get("exit_date") and t.get("realized_return") is not None]
    if not closed:
        return INITIAL_EQUITY
    # Equal-weight: varje trade får INITIAL_EQUITY / max(10, n_trades) i kapital
    capital_per_trade = INITIAL_EQUITY / max(10, len(trades))
    total_equity = INITIAL_EQUITY
    for t in closed:
        trade_pnl = capital_per_trade * t["realized_return"]
        total_equity += trade_pnl
    # Öppna trades mark-to-market (om current_price finns)
    for t in trades:
        if t.get("exit_date") is None and t.get("entry_price", 0) > 0:
            current = t.get("current_price") or t["entry_price"]
            unrealized = (current / t["entry_price"]) - 1
            total_equity += capital_per_trade * unrealized
    return round(total_equity, 2)


def get_summary(universe: str) -> dict:
    """Returnerar sammanfattning för UI: equity, antal trades, hit-rate, etc."""
    store = _load_store(universe)
    trades = store["trades"]
    closed = [t for t in trades if t.get("exit_date")]
    open_trades = [t for t in trades if not t.get("exit_date")]

    if not trades:
        return {
            "universe": universe,
            "equity": INITIAL_EQUITY,
            "total_return_pct": 0.0,
            "n_trades": 0,
            "n_closed": 0,
            "n_open": 0,
            "hit_rate": None,
            "avg_realized": None,
        }

    realized_returns = [t["realized_return"] for t in closed if t.get("realized_return") is not None]
    hit_rate = (sum(1 for r in realized_returns if r > 0) / len(realized_returns)) if realized_returns else None
    avg_realized = (sum(realized_returns) / len(realized_returns)) if realized_returns else None
    equity = _compute_equity(trades)

    return {
        "universe": universe,
        "equity": equity,
        "total_return_pct": round((equity / INITIAL_EQUITY - 1) * 100, 2),
        "n_trades": len(trades),
        "n_closed": len(closed),
        "n_open": len(open_trades),
        "hit_rate": round(hit_rate * 100, 1) if hit_rate is not None else None,
        "avg_realized": round(avg_realized * 100, 2) if avg_realized is not None else None,
    }


def get_equity_curve_df(universe: str) -> pd.DataFrame:
    """Returnerar equity curve som DataFrame för plotting."""
    store = _load_store(universe)
    if not store["equity_curve"]:
        return pd.DataFrame(columns=["date", "equity", "n_open"])
    df = pd.DataFrame(store["equity_curve"])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def get_trades_df(universe: str, only_open: bool = False) -> pd.DataFrame:
    store = _load_store(universe)
    if not store["trades"]:
        return pd.DataFrame()
    df = pd.DataFrame(store["trades"])
    if only_open and "exit_date" in df.columns:
        df = df[df["exit_date"].isna()]
    return df.sort_values("date", ascending=False).reset_index(drop=True)
