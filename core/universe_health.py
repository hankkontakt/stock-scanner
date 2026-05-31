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
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
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
CACHE_DIR = MODULE_DIR / "data" / "cache"
CACHE_TTL_SEC = 86400  # 24 timmars cache for health check-resultat


def load_blacklist() -> list:
    """Ladda svartlistan. Hanterar både dict-format (ticker → info) och list-format (alla historiska)."""
    try:
        if BLACKLIST_FILE.exists():
            data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # Konvertera dict → list för att kunna iterera
                return [
                    {"ticker": k, "reason": v.get("reason", ""), "date": v.get("date", "")}
                    for k, v in data.items()
                ]
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
    """Kolla om tickers i dataframe är avnoterade/ogiltiga.
    Använder ThreadPoolExecutor + caching + timeout för att undvika
    yfinance rate-limit och hängningar."""
    if df.empty or "ticker" not in df.columns:
        return []
    blacklist = {i.get("ticker") for i in load_blacklist()}
    current_tickers = set(df["ticker"].dropna().str.upper().unique())

    # Hoppa över svartlistade direkt — de är redan kända
    remaining = [t for t in current_tickers if t not in blacklist]
    if not remaining:
        return []

    # Ladda cached resultat från förra körningen
    cache_file = CACHE_DIR / "universe_health_cache.json"
    cache = {}
    if cache_file.exists():
        try:
            cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
            cache = cache_data.get("results", {})
            cache_time = cache_data.get("timestamp", 0)
            # Rensa cache om den är äldre än TTL
            if time.time() - cache_time > CACHE_TTL_SEC:
                cache = {}
        except Exception:
            cache = {}

    invalid = []
    skipped_blacklisted = [{"ticker": t, "name": "", "reason": "finns i svartlistan"} for t in current_tickers if t in blacklist]
    invalid.extend(skipped_blacklisted)

    # Kolla cache först
    to_fetch = [t for t in remaining if t not in cache]
    if cache:
        for t in remaining:
            if t in cache and cache[t].get("invalid"):
                invalid.append(cache[t]["info"])

    if not to_fetch:
        return invalid

    # Hämta resterande med ThreadPoolExecutor + timeout
    MAX_WORKERS = 8
    TIMEOUT_SEC = 15

    def _check_one(ticker: str) -> tuple:
        """Kontrollera en enskild ticker med timeout."""
        try:
            import socket
            socket.setdefaulttimeout(TIMEOUT_SEC)
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            quote_type = info.get("quoteType", "")
            if not quote_type or quote_type == "NONE":
                reason = "ingen quoteType – troligen avnoterad"
                name = info.get("shortName", info.get("longName", ""))
                return (ticker, True, {"ticker": ticker, "name": name, "reason": reason})
            exchange = info.get("exchange", "")
            if exchange == "NONE" or exchange == "":
                reason = "tom exchange – ogiltig ticker"
                name = info.get("shortName", info.get("longName", ""))
                return (ticker, True, {"ticker": ticker, "name": name, "reason": reason})
            try:
                hist = stock.history(period="5d")
                if hist.empty or len(hist) == 0:
                    reason = "ingen prisdata senaste 5 dagarna"
                    name = info.get("shortName", info.get("longName", ""))
                    return (ticker, True, {"ticker": ticker, "name": name, "reason": reason})
            except Exception:
                reason = "kunde inte hämta prisdata"
                return (ticker, True, {"ticker": ticker, "name": "", "reason": reason})
            return (ticker, False, None)
        except Exception as e:
            reason = f"yfinance-fel: {str(e)[:80]}"
            return (ticker, True, {"ticker": ticker, "name": "", "reason": reason})

    checked = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_check_one, t): t for t in to_fetch}
        for future in as_completed(futures):
            ticker, is_invalid, info = future.result()
            checked += 1
            if is_invalid and info:
                invalid.append(info)
            # Uppdatera cache
            cache[ticker] = {"invalid": is_invalid, "info": info}

    # Spara cache
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"timestamp": time.time(), "results": cache}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

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


def auto_remove_invalid_tickers(
    invalid_list: list[dict],
    dry_run: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Ta bort ogiltiga/avnoterade tickers fran universe.json och lagg till i blacklist.json.

    Args:
        invalid_list: Lista fran detect_invalid_tickers() — [{"ticker", "name", "reason"}, ...]
        dry_run: Om True, rapportera utan att andra filer
        verbose: Skriv ut detaljer

    Returns:
        dict med antal borttagna och blacklistade
    """
    import json as _json
    universe_path = MODULE_DIR / "data" / "universe.json"
    blacklist_path = DATA_DIR / "blacklist.json"

    if not invalid_list:
        return {"removed": 0, "blacklisted": 0, "not_found": 0}

    # Ladda universe.json
    try:
        universe = _json.loads(universe_path.read_text(encoding="utf-8"))
    except Exception as e:
        if verbose:
            print(f"  Kunde inte lasa universe.json: {e}")
        return {"error": str(e)}

    # Ladda blacklist.json
    try:
        bl = _json.loads(blacklist_path.read_text(encoding="utf-8")) if blacklist_path.exists() else {}
    except Exception:
        bl = {}

    removed = 0
    blacklisted = 0
    not_found = 0

    for inv in invalid_list:
        ticker = inv.get("ticker", "").upper().strip()
        if not ticker:
            continue

        # Kolla om tickern finns i nagot universum
        found = False
        for category_key, category_data in list(universe.items()):
            if not isinstance(category_data, dict):
                continue
            tickers_list = category_data.get("tickers", []) or []
            markets = category_data.get("markets", {})
            all_tickers = list(tickers_list)
            for mkt_key, mkt_tickers in markets.items():
                all_tickers.extend(mkt_tickers)

            if ticker in all_tickers:
                found = True
                # Ta bort fran listor
                if "tickers" in category_data and ticker in category_data["tickers"]:
                    if not dry_run:
                        category_data["tickers"] = [t for t in category_data["tickers"] if t != ticker]
                    if verbose:
                        print(f"  Tar bort {ticker} fran {category_key}.tickers")
                for mkt_key, mkt_tickers in list(markets.items()):
                    if ticker in mkt_tickers:
                        if not dry_run:
                            markets[mkt_key] = [t for t in mkt_tickers if t != ticker]
                        if verbose:
                            print(f"  Tar bort {ticker} fran {category_key}.markets.{mkt_key}")

        if not found:
            if verbose:
                print(f"  {ticker}: finns inte i universe.json (hoppar over)")
            not_found += 1
            continue

        removed += 1

        # Lagg till i blacklist om den inte redan finns
        if ticker not in bl:
            if not dry_run:
                bl[ticker] = {
                    "reason": inv.get("reason", "auto-upptackt av health check"),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                }
            blacklisted += 1
            if verbose:
                print(f"  Lagger till {ticker} i blacklist.json")

    # Spara andringar
    if not dry_run and (removed > 0 or blacklisted > 0):
        try:
            universe_path.write_text(
                _json.dumps(universe, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if verbose:
                print(f"  Sparade universe.json ({removed} borttagna)")
        except Exception as e:
            print(f"  Kunde inte spara universe.json: {e}")

        try:
            blacklist_path.write_text(
                _json.dumps(bl, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if verbose:
                print(f"  Sparade blacklist.json ({blacklisted} tillagda)")
        except Exception as e:
            print(f"  Kunde inte spara blacklist.json: {e}")

    return {
        "removed": removed,
        "blacklisted": blacklisted,
        "not_found": not_found,
    }
