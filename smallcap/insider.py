"""
insider.py - Insiderdata för svenska småbolag.

Datakällor (i prioritetsordning):
  1. yfinance insider_transactions  - köp/sälj sista 12m per ticker
  2. Finansinspektionen (FI) REST-API - marknadssok.fi.se
     Offentlig endpoint, ingen nyckel, men rate-limit ~10 req/s.

Nyckelkolumner som returneras (per ticker):
  insider_pct         - andel aktier ägda av insiders (0.0-1.0)
  insider_net_buy_6m  - netto SEK köpt/sålt av insiders senaste 6m
  insider_buy_count   - antal unika köptransaktioner senaste 6m
  insider_sell_count  - antal unika säljtransaktioner senaste 6m
  insider_signal      - "BUY" | "SELL" | "NEUTRAL" | "N/A"
"""

import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

# ── Cache ─────────────────────────────────────────────────────────────────────
_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
_INSIDER_CACHE_TTL_HOURS = 24   # Insiderdata uppdateras sällan

# ── FI API ────────────────────────────────────────────────────────────────────
# Finansinspektionens öppna API för insynshandel (insiderregister)
# Dokumentation: https://marknadssok.fi.se/
_FI_BASE_URL = "https://marknadssok.fi.se/publiceringsklient/sv/Search/GetSearchResult"
_FI_HEADERS  = {
    "User-Agent":  "StockScanner/1.0 (henth642@student.liu.se)",
    "Accept":      "application/json",
}
_FI_DELAY_S  = 0.15   # 150ms mellan anrop -> ~6 req/s (under limit)


def _cache_path(ticker: str) -> Path:
    safe = ticker.replace(".", "_").replace("/", "_")
    return _CACHE_DIR / f"insider_{safe}.pkl"


def _load_cache(ticker: str) -> Optional[pd.DataFrame]:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    try:
        df = pd.read_pickle(p)
        if "_cached_at" in df.attrs:
            age_h = (datetime.now() - df.attrs["_cached_at"]).total_seconds() / 3600
            if age_h > _INSIDER_CACHE_TTL_HOURS:
                return None
        return df
    except Exception:
        return None


def _save_cache(ticker: str, df: pd.DataFrame) -> None:
    df.attrs["_cached_at"] = datetime.now()
    try:
        df.to_pickle(_cache_path(ticker))
    except Exception:
        pass


# ── yfinance hämtning ─────────────────────────────────────────────────────────

def _yf_insider_transactions(ticker: str) -> pd.DataFrame:
    """Hämtar insider-transaktioner från yfinance (Yahoo Finance)."""
    if not _YF_AVAILABLE:
        return pd.DataFrame()

    cached = _load_cache(ticker)
    if cached is not None:
        return cached

    try:
        t   = yf.Ticker(ticker)
        txn = t.insider_transactions
        if txn is None or txn.empty:
            return pd.DataFrame()

        # Normalisera kolumnnamn (kan variera mellan yfinance-versioner)
        txn.columns = [c.lower().replace(" ", "_") for c in txn.columns]
        txn.attrs["_cached_at"] = datetime.now()
        _save_cache(ticker, txn)
        return txn
    except Exception:
        return pd.DataFrame()


def _yf_insider_pct(ticker: str) -> float:
    """Hämtar heldPercentInsiders (0.0-1.0) via yfinance info."""
    if not _YF_AVAILABLE:
        return float("nan")
    try:
        info = yf.Ticker(ticker).info
        pct  = info.get("heldPercentInsiders", None)
        return float(pct) if pct is not None else float("nan")
    except Exception:
        return float("nan")


# ── FI API-hämtning ───────────────────────────────────────────────────────────

def _fi_fetch_transactions(isin: str, days_back: int = 180) -> pd.DataFrame:
    """
    Hämtar insynshandel från FI:s register för ett givet ISIN.
    Returnerar tom DF om anropet misslyckas.
    """
    try:
        import requests
    except ImportError:
        return pd.DataFrame()

    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    params = {
        "SearchFunctionType":      "Insyn",
        "Utgivare":                "",
        "Isin":                    isin,
        "Transaktionstyp":         "",
        "Handelsdatum_Fran":       cutoff,
        "Handelsdatum_Till":       "",
        "Page":                    1,
        "PageSize":                50,
    }
    try:
        resp = requests.get(_FI_BASE_URL, params=params,
                            headers=_FI_HEADERS, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("SearchResultItems", [])
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


# ── Aggregering per ticker ─────────────────────────────────────────────────────

def _aggregate_insider(txn: pd.DataFrame, months: int = 6) -> dict:
    """
    Aggregerar transaktioner till nyckeltal:
      net_buy_sek  - netto köp minus sälj i SEK
      buy_count    - antal köptransaktioner
      sell_count   - antal säljtransaktioner
      signal       - "BUY" | "SELL" | "NEUTRAL"
    """
    if txn.empty:
        return {"net_buy_sek": 0, "buy_count": 0, "sell_count": 0, "signal": "N/A"}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=months * 30)

    # Datumskolumn heter 'startdate', 'transaction_date', 'date' beroende på källa
    date_col = next((c for c in ["startdate", "transaction_date", "date"]
                     if c in txn.columns), None)
    if date_col:
        try:
            txn = txn.copy()
            txn[date_col] = pd.to_datetime(txn[date_col], utc=True, errors="coerce")
            txn = txn[txn[date_col] >= cutoff]
        except Exception:
            pass

    if txn.empty:
        return {"net_buy_sek": 0, "buy_count": 0, "sell_count": 0, "signal": "NEUTRAL"}

    # Transaktionstyp-kolumn
    type_col  = next((c for c in ["transaction", "transactiontype", "text"]
                      if c in txn.columns), None)
    value_col = next((c for c in ["value", "shares", "volume"]
                      if c in txn.columns), None)

    if type_col and value_col:
        try:
            txn[value_col] = pd.to_numeric(txn[value_col], errors="coerce").fillna(0)
            is_buy  = txn[type_col].str.lower().str.contains("köp|buy|purchase", na=False)
            is_sell = txn[type_col].str.lower().str.contains("sälj|sell|disposal", na=False)

            buy_val  = txn.loc[is_buy,  value_col].sum()
            sell_val = txn.loc[is_sell, value_col].sum()
            net      = buy_val - sell_val
            b_cnt    = int(is_buy.sum())
            s_cnt    = int(is_sell.sum())

            if net > 0 and b_cnt >= 2:
                signal = "BUY"
            elif net < -0.5 * abs(buy_val) or s_cnt > b_cnt * 2:
                signal = "SELL"
            else:
                signal = "NEUTRAL"

            return {"net_buy_sek": net, "buy_count": b_cnt,
                    "sell_count": s_cnt, "signal": signal}
        except Exception:
            pass

    # Fallback: räkna bara transaktioner utan värde
    return {"net_buy_sek": 0, "buy_count": len(txn), "sell_count": 0, "signal": "NEUTRAL"}


# ── Publik gränssnitt ──────────────────────────────────────────────────────────

def fetch_insider_data(tickers: list, delay: float = 0.3) -> pd.DataFrame:
    """
    Hämtar insiderdata för en lista tickers.

    Returnerar DataFrame med kolumner:
      ticker, insider_pct, insider_net_buy_6m,
      insider_buy_count, insider_sell_count, insider_signal

    Använder yfinance som primär källa. FI-API kan läggas till som
    komplement när ISIN-mappning finns.
    """
    rows = []
    n = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        if i % 10 == 0:
            print(f"    Insider: {i}/{n} ...", end="\r", flush=True)

        # Ägarandel
        insider_pct = _yf_insider_pct(ticker)

        # Transaktioner
        txn = _yf_insider_transactions(ticker)
        agg = _aggregate_insider(txn, months=6)

        rows.append({
            "ticker":            ticker,
            "insider_pct":       insider_pct,
            "insider_net_buy_6m": agg["net_buy_sek"],
            "insider_buy_count":  agg["buy_count"],
            "insider_sell_count": agg["sell_count"],
            "insider_signal":     agg["signal"],
        })

        time.sleep(delay)

    print(f"    Insider: {n}/{n} klart.   ")
    return pd.DataFrame(rows)


def merge_insider_data(df: pd.DataFrame, insider_df: pd.DataFrame) -> pd.DataFrame:
    """
    Sammanfogar insiderdata med huvud-DataFrame.
    df måste ha kolumnen 'ticker'.

    OBS: Droppar kolumner som redan finns i insider_df från df innan merge
    för att undvika _x/_y-suffix (pandas beteende vid kollidering).
    insider_df:s värden är primärkällan - de härrör från en dedikerad
    hämtning och är mer tillförlitliga.
    """
    if insider_df is None or insider_df.empty:
        for col in ["insider_pct", "insider_net_buy_6m",
                    "insider_buy_count", "insider_sell_count", "insider_signal"]:
            if col not in df.columns:
                df[col] = np.nan if "pct" in col or "buy" in col or "count" in col else "N/A"
        return df

    # Ta bort kolumner från df som även finns i insider_df (förutom join-nyckeln)
    overlap = [c for c in insider_df.columns if c != "ticker" and c in df.columns]
    df_clean = df.drop(columns=overlap, errors="ignore")
    return df_clean.merge(insider_df, on="ticker", how="left")


def get_insider_summary(df: pd.DataFrame, top_n: int = 5) -> str:
    """
    Returnerar en kort markdown-sammanfattning av insider-aktivitet.
    Används i rapporten.
    """
    if "insider_signal" not in df.columns:
        return "_Ingen insiderdata tillgänglig._\n"

    buyers  = df[df["insider_signal"] == "BUY"].sort_values(
        "insider_net_buy_6m", ascending=False).head(top_n)
    sellers = df[df["insider_signal"] == "SELL"].sort_values(
        "insider_net_buy_6m", ascending=True).head(3)

    lines = []

    if not buyers.empty:
        lines.append("**Tickers med tydliga insiderköp (senaste 6m):**")
        for _, r in buyers.iterrows():
            pct  = f"{r.get('insider_pct', 0)*100:.0f}%" if pd.notna(r.get("insider_pct")) else "?"
            nkp  = r.get("insider_net_buy_6m", 0) or 0
            cnt  = int(r.get("insider_buy_count", 0) or 0)
            lines.append(f"  • **{r['ticker']}** -- {cnt} köp, "
                         f"netto {nkp:+,.0f} SEK, insider äger {pct}")

    if not sellers.empty:
        lines.append("\n**Tickers med säljtryck från insiders:**")
        for _, r in sellers.iterrows():
            cnt = int(r.get("insider_sell_count", 0) or 0)
            lines.append(f"  • **{r['ticker']}** -- {cnt} sälj (varningssignal)")

    if not lines:
        lines.append("_Inga tydliga insidersignaler hittades._")

    return "\n".join(lines) + "\n"
