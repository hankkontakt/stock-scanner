"""
relative_strength.py
====================
Beräknar relativ styrka mot sektor och index.

Princip: En aktie som stiger 5% är bra – men inte om sektorn stiger 15%.
Aktier som överpresterar sin sektor tenderar fortsätta överprestera.
"""

import time
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

CACHE_DIR  = "data/cache"
RS_CACHE_H = 12
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _cp(key):
    h = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"rs_{h}.pkl"

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
    except Exception: pass


# Sektor → ETF-mappning
SECTOR_ETFS = {
    "Technology":             "XLK",
    "Healthcare":             "XLV",
    "Financial Services":     "XLF",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Energy":                 "XLE",
    "Industrials":            "XLI",
    "Communication Services": "XLC",
    "Basic Materials":        "XLB",
    "Real Estate":            "XLRE",
    "Utilities":              "XLU",
}


def fetch_etf_return(etf: str, period: str = "3mo") -> float | None:
    """Hämtar avkastning för en ETF över given period."""
    key = f"{etf}:{period}"
    cached = _rc(key, RS_CACHE_H)
    if cached is not None:
        return cached

    try:
        time.sleep(0.3)
        hist = yf.Ticker(etf).history(period=period)
        if hist.empty or len(hist) < 2:
            _wc(key, None)
            return None
        ret = float(hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)
        _wc(key, ret)
        return ret
    except Exception:
        return None


def calc_relative_strength(scored: pd.DataFrame) -> pd.DataFrame:
    """Lägger till relativ styrka mot sektor."""
    df = scored.copy()
    df["sector_return_3m"]  = None
    df["relative_strength"] = None
    df["rs_label"]          = "—"

    if "return_3m" not in df.columns or "sector" not in df.columns:
        return df

    # Cacha sektor-avkastningar
    sector_returns = {}
    sectors_in_df  = df["sector"].dropna().unique()
    for sector in sectors_in_df:
        etf = SECTOR_ETFS.get(sector)
        if etf:
            r = fetch_etf_return(etf, "3mo")
            sector_returns[sector] = r

    # Beräkna relativ styrka per aktie
    for idx, row in df.iterrows():
        sec    = row.get("sector")
        ret_3m = row.get("return_3m")
        if pd.isna(ret_3m) or sec not in sector_returns:
            continue
        sec_ret = sector_returns[sec]
        if sec_ret is None:
            continue
        df.at[idx, "sector_return_3m"]  = sec_ret
        df.at[idx, "relative_strength"] = round(float(ret_3m) - float(sec_ret), 3)

    def lbl(r):
        if r is None or pd.isna(r): return "—"
        if r > 0.05:    return "🟢 STARK"
        if r < -0.05:   return "🔴 SVAG"
        return "⚪ NORMAL"

    df["rs_label"] = df["relative_strength"].apply(lbl)
    return df


def build_rs_summary_section(scored: pd.DataFrame) -> str:
    """Markdown-sammanfattning av relativ styrka per sektor."""
    if "relative_strength" not in scored.columns:
        return ""

    valid = scored[scored["relative_strength"].notna()]
    if valid.empty:
        return ""

    lines = ["\n## 💪 Relativ styrka – topp och botten\n"]
    lines.append("_Aktiens avkastning minus sektorns (3 mån)_\n")

    strong = valid.nlargest(5, "relative_strength")
    if not strong.empty:
        lines.append("### 🟢 Starkast relativt sektorn\n")
        lines.append("| Ticker | Bolag | Sektor | Aktie 3m | Sektor 3m | Diff |")
        lines.append("|--------|-------|--------|----------|-----------|------|")
        for _, row in strong.iterrows():
            r3m  = (row.get("return_3m") or 0) * 100
            sr   = (row.get("sector_return_3m") or 0) * 100
            diff = (row.get("relative_strength") or 0) * 100
            lines.append(
                f"| `{row['ticker']}` | "
                f"{str(row.get('name',''))[:25]} | "
                f"{str(row.get('sector',''))[:15]} | "
                f"{r3m:+.1f}% | {sr:+.1f}% | **{diff:+.1f}pp** |"
            )
        lines.append("")

    weak = valid.nsmallest(5, "relative_strength")
    if not weak.empty:
        lines.append("### 🔴 Svagast relativt sektorn\n")
        lines.append("| Ticker | Bolag | Sektor | Aktie 3m | Sektor 3m | Diff |")
        lines.append("|--------|-------|--------|----------|-----------|------|")
        for _, row in weak.iterrows():
            r3m  = (row.get("return_3m") or 0) * 100
            sr   = (row.get("sector_return_3m") or 0) * 100
            diff = (row.get("relative_strength") or 0) * 100
            lines.append(
                f"| `{row['ticker']}` | "
                f"{str(row.get('name',''))[:25]} | "
                f"{str(row.get('sector',''))[:15]} | "
                f"{r3m:+.1f}% | {sr:+.1f}% | **{diff:+.1f}pp** |"
            )

    return "\n".join(lines)
