"""
universe_health.py – AI-driven underhall av aktieuniversum
=================================================================
Upptack avnoterade/inkorrekta tickers, foresl ersattningar
och hitta nya intressanta bolag med hjalp av AI.

Anvandning:
    from core.universe_health import (
        detect_invalid_tickers, suggest_replacements,
        find_new_stocks, run_health_check,
        load_blacklist, add_to_blacklist, remove_from_blacklist,
    )
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from . import config

# –– Sokvagar ––
MODULE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MODULE_DIR / "data"
BLACKLIST_FILE = DATA_DIR / "blacklist.json"
REPORT_DIR = MODULE_DIR / "reports"


def load_blacklist() -> list:
    """Lass svartlistfil bas pa sokmanigar i den."""
    try:
        if BLACKLIST_FILE.exists():
            data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def save_blacklist(items: list):
    """Spara blacklisten till disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BLACKLIST_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def add_to_blacklist(ticker: str, reason: str = "manuell") -> bool:
    """Lag till en ticker i svartlistan."""
    items = load_blacklist()
    ticker = ticker.upper().strip()
    if not any(i.get("ticker") == ticker for i in items):
        items.append({"ticker": ticker, "reason": reason, "added": datetime.now().strftime("%Y-%m-%d")})
        save_blacklist(items)
        return True
    return False


def remove_from_blacklist(ticker: str) -> bool:
    """Ta bort en ticker fran svartlistan."""
    items = load_blacklist()
    ticker = ticker.upper().strip()
    new_items = [i for i in items if i.get("ticker") != ticker]
    if len(new_items) < len(items):
        save_blacklist(new_items)
        return True
    return False


def detect_invalid_tickers(df: pd.DataFrame) -> list:
    """Koll om tickers i dataframe ar avnoterade/ogiltiga."""
    if df.empty or "ticker" not in df.columns:
        return []
    blacklist = {i.get("ticker") for i in load_blacklist()}
    invalid = []
    current_tickers = set(df["ticker"].dropna().str.upper().unique())
    for ticker in current_tickers:
        if ticker in blacklist:
            invalid.append({"ticker": ticker, "name": "", "reason": "finns i svartlistan"})
            continue
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            quote_type = info.get("quoteType", "")
            if not quote_type or quote_type == "NONE":
                invalid.append({"ticker": ticker, "name": info.get("shortName", info.get("longName", "")), "reason": "ingen quoteType – troligen avnoterad"})
                continue
            exchange = info.get("exchange", "")
            if exchange == "NONE" or exchange == "":
                invalid.append({"ticker": ticker, "name": info.get("shortName", info.get("longName", "")), "reason": "tom exchange – ogiltig ticker"})
                continue
            try:
                hist = stock.history(period="5d")
                if hist.empty or len(hist) == 0:
                    invalid.append({"ticker": ticker, "name": info.get("shortName", info.get("longName", "")), "reason": "ingen prisdata senaste 5 dagarna"})
            except Exception:
                invalid.append({"ticker": ticker, "name": "", "reason": "kunde inte hamta prisdata"})
        except Exception as e:
            invalid.append({"ticker": ticker, "name": "", "reason": f"yfinance-fel: {str(e)[:80]}"})
    return invalid


def suggest_replacements(ticker: str, df: pd.DataFrame, top_n: int = 5) -> list:
    """Foresla ersattningar for en bortad ticker."""
    if df.empty or "ticker" not in df.columns:
        return []
    sector = None
    if ticker.upper() in df["ticker"].str.upper().values:
        sector = df[df["ticker"].str.upper() == ticker.upper()].iloc[0].get("sector")
    candidates = df[df["ticker"].str.upper() != ticker.upper()].copy()
    if sector and "sector" in candidates.columns:
        same_sector = candidates[candidates["sector"] == sector]
        if not same_sector.empty:
            candidates = same_sector
    score_col = "score_total" if "score_total" in candidates.columns else "sc_total"
    if score_col in candidates.columns:
        candidates = candidates.sort_values(score_col, ascending=False)
    else:
        return []
    suggestions = []
    for _, r in candidates.head(top_n).iterrows():
        suggestions.append({
            "ticker": r.get("ticker", ""),
            "name": r.get("name", ""),
            "score": round(r.get(score_col, 0), 1) if not pd.isna(r.get(score_col)) else 0,
            "sector": r.get("sector", ""),
            "entry": r.get("entry_signal", ""),
        })
    return suggestions


def find_new_stocks(provider: str = "auto") -> list:
    """Hitta nya intressanta aktier med hjalp av AI."""
    try:
        from core.ai_analysis import ai_chat
        prompt = (
            "Foresla 5 intressanta amerikanska aktier som jag bor titta narmare pa "
            "just nu. For varje aktie, ange ticker, bolagsnamn och en kort motivering "
            "varfor den ar intressant (t.ex. starkt momentum, vardering, sektortrend, "
            "teknisk setup). "
            "SVARA ENDAST i JSON-format: "
            '[{"ticker": "AAPL", "name": "Apple Inc", "reason": "..."}, ...]'
        )
        result = ai_chat(prompt, provider=provider, force_refresh=True)
        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])
            stocks = json.loads(cleaned)
            if isinstance(stocks, list):
                return stocks[:10]
        except (json.JSONDecodeError, TypeError):
            pass
        return []
    except Exception:
        return []


def run_health_check(df: pd.DataFrame = None, provider: str = "auto") -> dict:
    """Kor hela healthchecken - upptacker avnoterade tickers, foreslar ersattningar, hittar nya aktier."""
    result = {
        "invalid_tickers": [],
        "suggestions": {},
        "new_stocks": [],
        "blacklist_count": len(load_blacklist()),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if df is None or df.empty:
        reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
        if reports:
            try:
                df = pd.read_csv(reports[0], low_memory=False)
                df.columns = df.columns.str.strip()
            except Exception:
                return result
    if df is not None and not df.empty and "ticker" in df.columns:
        invalid = detect_invalid_tickers(df)
        result["invalid_tickers"] = invalid
        for inv in invalid:
            ticker = inv["ticker"]
            replacements = suggest_replacements(ticker, df, top_n=5)
            if replacements:
                result["suggestions"][ticker] = replacements
        if provider:
            try:
                result["new_stocks"] = find_new_stocks(provider=provider)
            except Exception:
                pass
    return result
