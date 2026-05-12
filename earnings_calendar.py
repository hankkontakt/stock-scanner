"""
earnings_calendar.py
====================
Hämtar kommande kvartalsrapporter och varnar för aktier
som rapporterar inom kort (gap-risk vid köp/sälj precis innan rapport).
"""

import time
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

CACHE_DIR        = "data/cache"
CALENDAR_CACHE_H = 24
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _cp(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"earnings_cal_{h}.pkl"

def _rc(key, max_h):
    p = _cp(key)
    if not p.exists(): return None
    if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > timedelta(hours=max_h):
        return None
    try:
        with open(p, "rb") as f: return pickle.load(f)
    except: return None

def _wc(key, data):
    try:
        with open(_cp(key), "wb") as f: pickle.dump(data, f)
    except: pass


def fetch_earnings_date(ticker: str) -> dict | None:
    """Hämtar nästa earnings-datum via yfinance."""
    cached = _rc(f"date:{ticker}", CALENDAR_CACHE_H)
    if cached is not None:
        return cached

    try:
        time.sleep(0.3)
        stock = yf.Ticker(ticker)
        cal   = stock.calendar

        if cal is None:
            _wc(f"date:{ticker}", None)
            return None

        earnings_date = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, list) and ed:
                earnings_date = ed[0]
            elif ed:
                earnings_date = ed
        elif hasattr(cal, "index") and "Earnings Date" in cal.index:
            try:
                earnings_date = cal.loc["Earnings Date"].iloc[0]
            except Exception:
                pass

        if earnings_date is None:
            _wc(f"date:{ticker}", None)
            return None

        try:
            ed_ts = pd.to_datetime(earnings_date)
        except Exception:
            _wc(f"date:{ticker}", None)
            return None

        result = {
            "ticker":        ticker,
            "earnings_date": ed_ts.strftime("%Y-%m-%d"),
            "days_until":    (ed_ts.date() - datetime.now().date()).days,
        }

        _wc(f"date:{ticker}", result)
        return result

    except Exception:
        return None


def fetch_calendar_for_tickers(tickers: list, verbose: bool = True) -> pd.DataFrame:
    """Hämtar earnings-datum för en lista tickers."""
    rows = []
    for i, ticker in enumerate(tickers, 1):
        if verbose and i % 25 == 0:
            print(f"  Earnings: {i}/{len(tickers)}...")

        info = fetch_earnings_date(ticker)
        if info and info["days_until"] is not None:
            rows.append(info)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("days_until")


def upcoming_in_portfolio(holdings: pd.DataFrame, scored: pd.DataFrame,
                          days_ahead: int = 30) -> pd.DataFrame:
    """Innehav som rapporterar inom X dagar."""
    if holdings.empty:
        return pd.DataFrame()

    tickers = list(holdings["ticker"])
    cal = fetch_calendar_for_tickers(tickers, verbose=False)

    if cal.empty:
        return pd.DataFrame()

    cal = cal[(cal["days_until"] >= 0) & (cal["days_until"] <= days_ahead)].copy()

    if not cal.empty and not scored.empty:
        cal = cal.merge(
            scored[["ticker", "name", "score_total"]],
            on="ticker", how="left"
        )

    return cal


def upcoming_in_top(scored: pd.DataFrame, top_n: int = 50,
                    days_ahead: int = 14) -> pd.DataFrame:
    """Topp-N-aktier som rapporterar inom X dagar."""
    if scored.empty:
        return pd.DataFrame()

    top_tickers = list(scored.head(top_n)["ticker"])
    cal         = fetch_calendar_for_tickers(top_tickers, verbose=False)

    if cal.empty:
        return pd.DataFrame()

    cal = cal[(cal["days_until"] >= 0) & (cal["days_until"] <= days_ahead)].copy()

    if not cal.empty:
        cal = cal.merge(
            scored[["ticker", "name", "score_total", "rank"]],
            on="ticker", how="left"
        ).sort_values("days_until")

    return cal


def build_earnings_section(portfolio_cal: pd.DataFrame,
                            top_cal: pd.DataFrame) -> str:
    """Markdown-sektion för rapporten."""
    if portfolio_cal.empty and top_cal.empty:
        return ""

    lines = ["\n## 📅 Earnings-kalender\n"]

    if not portfolio_cal.empty:
        lines.append("### ⚠ Dina innehav som rapporterar inom 30 dagar\n")
        lines.append("| Datum | Dagar kvar | Ticker | Bolag | Score |")
        lines.append("|-------|-----------|--------|-------|-------|")
        for _, row in portfolio_cal.iterrows():
            score = row.get("score_total", "—")
            score_str = f"{score:.0f}" if isinstance(score, (int, float)) and pd.notna(score) else "—"
            lines.append(
                f"| {row['earnings_date']} | "
                f"**{row['days_until']}** | "
                f"`{row['ticker']}` | "
                f"{str(row.get('name', ''))[:30]} | "
                f"{score_str} |"
            )
        lines.append("")

    if not top_cal.empty:
        lines.append("### 🔔 Topp-aktier som rapporterar inom 14 dagar\n")
        lines.append("_Var försiktig med köp precis innan rapport (gap-risk)_\n")
        lines.append("| Datum | Dagar kvar | Rank | Ticker | Bolag | Score |")
        lines.append("|-------|-----------|------|--------|-------|-------|")
        for _, row in top_cal.head(10).iterrows():
            score = row.get("score_total", "—")
            score_str = f"{score:.0f}" if isinstance(score, (int, float)) and pd.notna(score) else "—"
            lines.append(
                f"| {row['earnings_date']} | "
                f"**{row['days_until']}** | "
                f"#{row.get('rank', '?')} | "
                f"`{row['ticker']}` | "
                f"{str(row.get('name', ''))[:30]} | "
                f"{score_str} |"
            )

    return "\n".join(lines)
