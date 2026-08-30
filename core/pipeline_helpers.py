"""
core/pipeline_helpers.py
========================
A1-split: Hjälpfunktioner för MarketScan-pipelinen (data-I/O, utils).

Extraherade från core/daily_pipeline.py som ett led i att bryta upp
monoliten (2600 rader). Denna modul innehåller:
- Fil-I/O: _latest_report, _load_latest_scored, _load_all_recent_scored,
           _save_scored, _save_ai_text
- Data-laddning: _load_portfolio, _load_watchlist, _fetch_live_price
- Utilities: _looks_like_ticker, _cleanup_old_reports

Backward compat: daily_pipeline.py re-importerar allt härifrån.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Sökvägar sätts vid import-tid (speglar daily_pipeline.py)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
AI_CACHE_DIR = ROOT / "data" / "ai_cache"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
AI_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Filhämtning ───────────────────────────────────────────────────────────────

def _latest_report(pattern: str = "scored_universe_*.parquet") -> Optional[Path]:
    """Hitta senaste rapportfil som matchar mönstret.
    Prioriterar .parquet (snabbare), fallback till .csv."""
    files = sorted(REPORT_DIR.glob(pattern), reverse=True)
    if files:
        return files[0]
    # Fallback till .csv om .parquet saknas
    csv_pattern = pattern.replace(".parquet", ".csv")
    csv_files = sorted(REPORT_DIR.glob(csv_pattern), reverse=True)
    return csv_files[0] if csv_files else None


def _apply_sanity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sista försvarslinjen (ROND 5, 2026-08-30): sanera rå yfinance-värden INNAN
    parquet/csv sparas. Speglar data_fetcher._sanity_check men körs även på
    data som lästs från gamla/trackade parquet-filer (t.ex.
    scored_universe_2026-08-29 med NVDA pe=-4.88, divY=0.44 i %, de=-34.9).

    Regler (vektoriserat, loggas via logger):
    - pe_trailing/pe_forward: icke-finit/<=1/>200 -> NA; dessutom pe < 6 -> NA
      (yfinance .info ger ibland pe ~1-5 istället för 20-40 — META 1.15, KO 2.41,
      APP 3.68, CME 3.66, LIN 5.18, LLY 5.59)
    - dividend_yield: >0.1 = % -> /100 (fraktion); <0 -> NA; <=0.1 lämnas
    - debt_to_equity: <0 -> 0 (nettokassa); >200 -> NA
    - current_ratio: <0 -> 0; >20 -> NA
    - roe/roa/gross_margin/operating_margin: |v| > 5 -> NA
    """
    import numpy as np

    def _is_num(s: pd.Series) -> pd.Series:
        return pd.to_numeric(s, errors="coerce")

    for col in ("pe_trailing", "pe_forward"):
        if col in df.columns:
            v = _is_num(df[col])
            df[col] = v.mask(~np.isfinite(v) | (v <= 1) | (v > 200) | (v < 6))

    if "dividend_yield" in df.columns:
        v = _is_num(df["dividend_yield"])
        frac = v.copy()
        frac.loc[v > 0.1] = v.loc[v > 0.1] / 100
        df["dividend_yield"] = frac.mask(~np.isfinite(frac) | (frac < 0))

    if "debt_to_equity" in df.columns:
        v = _is_num(df["debt_to_equity"])
        df["debt_to_equity"] = v.mask(~np.isfinite(v), other=None).clip(lower=0.0)
        df["debt_to_equity"] = df["debt_to_equity"].mask(df["debt_to_equity"] > 200)

    if "current_ratio" in df.columns:
        v = _is_num(df["current_ratio"])
        df["current_ratio"] = v.mask(~np.isfinite(v), other=None).clip(lower=0.0)
        df["current_ratio"] = df["current_ratio"].mask(df["current_ratio"] > 20)

    for col in ("roe", "roa", "gross_margin", "operating_margin"):
        if col in df.columns:
            v = _is_num(df[col])
            df[col] = v.mask(~np.isfinite(v) | (v.abs() > 5))

    return df


def _load_latest_scored(pattern: str = "scored_universe_*.parquet") -> pd.DataFrame:
    """Ladda senaste scored_universe-filen. Returnerar tom DF om ingen finns."""
    path = _latest_report(pattern)
    if path is None:
        logger.info("  ℹ Ingen scored_universe-fil hittades.")
        return pd.DataFrame()
    try:
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, low_memory=False)
        logger.info(f"  📂 Laddade {path.name} ({len(df)} rader)")
        return df
    except Exception as e:
        logger.warning(f"  ⚠ Kunde inte ladda {path.name}: {e}")
        return pd.DataFrame()


def _load_all_recent_scored(max_age_days: int = 14,
                             pattern: str = "scored_universe_*.parquet") -> list[pd.DataFrame]:
    """Ladda alla scored_universe-filer inom senaste N dagar.
    Returnerar lista av DataFrames (nyast först)."""
    cutoff = time.time() - max_age_days * 86400
    files = sorted(REPORT_DIR.glob(pattern), reverse=True)
    if not files:
        files = sorted(REPORT_DIR.glob(pattern.replace(".parquet", ".csv")), reverse=True)
    result = []
    for f in files:
        if f.stat().st_mtime < cutoff:
            break
        try:
            df = pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f, low_memory=False)
            if not df.empty:
                result.append(df)
        except Exception:
            pass
    return result


def _save_scored(df: pd.DataFrame, path: Path):
    """Spara DataFrame som både .parquet (zstd) och .csv (för bakåtkompatibilitet).

    Använder atomisk skrivning: skriver till .tmp, sedan rename.
    Förhindrar korrupta filer vid krasch mitt i skrivningen.

    ROND 5 (2026-08-30): kör _apply_sanity() innan sparning. Tidigare committades
    råa yfinance-värden (pe=-4.88, divY=0.44 i %, de=-34.9) till main av pipeline-
    commits (daily_scan.yml "Committa CSV och rapportdata"), vilket förgiftade
    alla efterföljande morning/evening-körningar som läser senaste parquet.
    Nu garanteras att ALLA sparade parquets/csv är sanerade.
    """
    df = _apply_sanity(df)
    csv_path = path.with_suffix(".csv")
    csv_tmp = csv_path.with_suffix(".tmp.csv")
    df.to_csv(csv_tmp, index=False)
    csv_tmp.replace(csv_path)  # Atomisk: tmp → rename

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        parquet_path = path.with_suffix(".parquet")
        tmp_path = parquet_path.with_suffix(".tmp.parquet")
        table = pa.Table.from_pandas(df)
        pq.write_table(table, tmp_path, compression="zstd")
        tmp_path.replace(parquet_path)
        logger.info(f"  💾 Sparade {parquet_path.name} + {csv_path.name}")
    except ImportError:
        logger.warning("  ⚠ pyarrow saknas — sparar enbart .csv")
        logger.info(f"  💾 Sparade {csv_path.name}")


def _save_ai_text(mode: str, date_str: str, text: str):
    """Spara AI-genererad text i ai_cache/ för lazy-load."""
    path = AI_CACHE_DIR / f"ai_{mode}_{date_str}.md"
    path.write_text(text, encoding="utf-8")
    logger.info(f"  💾 Sparade AI-text: {path.name}")


# ── Data-laddning ─────────────────────────────────────────────────────────────

def _load_portfolio() -> pd.DataFrame:
    """Ladda holdings.csv."""
    path = DATA_DIR / "holdings.csv"
    if path.exists():
        try:
            df = pd.read_csv(path)
            df["ticker"] = df["ticker"].str.upper().str.strip()
            logger.info(f"  📂 Laddade portfölj ({len(df)} innehav)")
            return df
        except Exception as e:
            logger.warning(f"  ⚠ Kunde inte ladda portfölj: {e}")
    return pd.DataFrame(columns=["ticker", "shares", "cost_basis"])


def _load_watchlist() -> list:
    """Ladda watchlist.json."""
    path = DATA_DIR / "watchlist.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info(f"  📂 Laddade watchlist ({len(data)} tickers)")
            return data
        except Exception as e:
            logger.warning(f"  ⚠ Kunde inte ladda watchlist: {e}")
    return []


def _fetch_live_price(ticker: str) -> float | None:
    """Fetch a single live price from yfinance for holdings not in the scored universe."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


# ── Utilities ─────────────────────────────────────────────────────────────────

# Ticker-validering (bredd pattern: 1-25 tecken, bokstäver/siffror/.-^)
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-\^]{0,24}$")


def _looks_like_ticker(s: str) -> bool:
    """Returnerar True om strängen ser ut som ett giltigt ticker-symbol."""
    if not isinstance(s, str):
        return False
    s = s.strip().upper()
    return bool(_TICKER_RE.match(s))


def _cleanup_old_reports(max_days: int = 60) -> int:
    """Ta bort gamla rapportfiler. Returnerar antal borttagna filer."""
    cutoff = time.time() - max_days * 86400
    deleted = 0
    patterns = ["scored_universe_*.csv", "scored_universe_*.parquet",
                 "smallcap_scored_*.csv", "smallcap_scored_*.parquet", "*.md"]
    for pattern in patterns:
        for path in REPORT_DIR.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    deleted += 1
            except Exception:
                pass
    if deleted > 0:
        logger.info(f"  🧹 Rensade {deleted} gamla rapportfiler (>={max_days} dagar)")
    return deleted
