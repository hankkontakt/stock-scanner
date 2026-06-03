"""
data_fetcher_batch.py - Batch/universe data fetching operations.
Single-ticker utilities remain in data_fetcher.py.
"""
import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf
import requests

from core import config
from core.data_fetcher import (
    _fetch_single_ticker,
    _RATE_LIMIT_LOCK,
    _RATE_LIMIT_COUNTER,
    _RateLimiter,
    _read_cache,
    _write_cache,
    _safe_return,
    _with_timeout,
    fetch_finnhub_sentiment,
    _ticker_to_finnhub,
)

logger = logging.getLogger(__name__)

# Återanvändbar requests.Session för connection pooling
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

try:
    import aiohttp as _aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


def fetch_universe_data(tickers: list, verbose: bool = True) -> pd.DataFrame:
    """
    Fetch metrics for all stocks in the universe using a ThreadPoolExecutor
    for parallel yfinance calls.

    Med 8 workers och PRICE_CACHE_HOURS=24h-cache blir ~700 tickers klara
    på 2-3 minuter (i stället för 9-10 min sekventiellt).
    Returns a DataFrame with one row per ticker.
    """
    total = len(tickers)

    # Ladda blacklist - skippa kända trasiga tickers
    _bl_path = Path(__file__).resolve().parent.parent / "data" / "blacklist.json"
    try:
        _blacklist = set(json.loads(_bl_path.read_text()).keys()) if _bl_path.exists() else set()
    except Exception:
        _blacklist = set()

    if verbose:
        print(f"  ⚙  {config.PARALLEL_WORKERS} parallella workers * {total} tickers")

    rows = []
    failed = []
    failed_detail: dict = {}
    rate_limited = []
    delisted = []
    completed = 0

    # Adaptiv batch-storlek
    _adaptive_workers = config.PARALLEL_WORKERS

    # ── Pass 1: parallell hämtning med PARALLEL_WORKERS ────────────────────────
    _pass1_start = time.time()
    with ThreadPoolExecutor(max_workers=_adaptive_workers) as pool:
        futures = {
            pool.submit(_fetch_single_ticker, t, _blacklist, verbose): t
            for t in tickers
        }

        for future in as_completed(futures):
            ticker, metrics, status = future.result()
            completed += 1

            if verbose:
                icon = "✓" if metrics is not None else "✗"
                print(f"  [{completed}/{total}] {icon} {ticker} {status}")

            if metrics is not None:
                rows.append(metrics)
            elif status == "RATE_LIMITED":
                rate_limited.append(ticker)
            elif status == "DELISTED":
                delisted.append(ticker)
            else:
                failed.append(ticker)
                failed_detail[ticker] = {"status": status, "pass": 1}

    # ── Pass 2: retry rate-limited tickers med 1 worker + fördröjning ──────────
    if rate_limited:
        if verbose:
            print(f"\n  ⏳ Pass 2: {len(rate_limited)} rate-limited tickers - väntar 45s för att ge Yahoo tid att återhämta sig...")
        time.sleep(45)

        pass2_completed = 0
        pass2_total = len(rate_limited)
        still_failed = []

        # Reset rate limit counter before pass 2
        with _RATE_LIMIT_LOCK:
            _RATE_LIMIT_COUNTER["consecutive_failures"] = 0

        with ThreadPoolExecutor(max_workers=1) as pool:
            futures2 = {
                pool.submit(_fetch_single_ticker, t, _blacklist, verbose): t
                for t in rate_limited
            }
            for future in as_completed(futures2):
                ticker, metrics, status = future.result()
                pass2_completed += 1
                if verbose:
                    icon = "✓" if metrics is not None else "✗"
                    print(f"  [P2 {pass2_completed}/{pass2_total}] {icon} {ticker} {status}")
                # Throttle between retries (2s between each call, single worker)
                time.sleep(2)
                if metrics is not None:
                    rows.append(metrics)
                elif status == "DELISTED":
                    delisted.append(ticker)
                else:
                    still_failed.append(ticker)
                    failed_detail[ticker] = {"status": status, "pass": 2}

        if verbose and still_failed:
            print(f"  ⚠ Pass 2: {len(still_failed)} tickers fortfarande misslyckade: "
                  f"{', '.join(still_failed[:10])}{'...' if len(still_failed) > 10 else ''}")
        failed.extend(still_failed)

    # ── Auto-blacklist delisted tickers så de hoppas över nästa körning ─────
    if delisted:
        try:
            from datetime import date as _date
            _bl_path.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if _bl_path.exists():
                try:
                    existing = json.loads(_bl_path.read_text())
                except Exception:
                    existing = {}
            today_iso = _date.today().isoformat()
            new_count = 0
            for t in delisted:
                if t not in existing:
                    existing[t] = {
                        "reason": "Yahoo Finance returnerade 404 (delisted/uppköpt/okänd ticker)",
                        "date":   today_iso,
                        "auto":   True,
                    }
                    new_count += 1
            if new_count:
                _bl_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
                if verbose:
                    print(f"  🚫 Auto-blacklistade {new_count} delistade tickers: "
                          f"{', '.join(delisted[:8])}{'...' if len(delisted) > 8 else ''}")
        except Exception as e:
            if verbose:
                print(f"  ⚠ Kunde inte uppdatera blacklist.json: {e}")

    df = pd.DataFrame(rows)

    if verbose:
        if delisted:
            print(f"  🚫 {len(delisted)} delistade tickers (auto-blacklistade): "
                  f"{', '.join(delisted[:10])}{'...' if len(delisted) > 10 else ''}")
        if failed:
            n = len(failed)
            print(f"  ⚠ {n} tickers misslyckades (övriga fel): "
                  f"{', '.join(failed[:10])}{'...' if n > 10 else ''}")
            if n > 15:
                print("  💡 Tips: Kör filters.clear_blacklist() om välkända aktier är med i listan")
        print(f"  ✓ {len(df)}/{total} aktier hämtade")

    # ── Spara detaljerat fellog till data/fetch_errors.json ───────────────
    try:
        from datetime import datetime as _dt
        _errors_path = _bl_path.parent / "fetch_errors.json"
        _error_entry = {
            "timestamp": _dt.utcnow().isoformat(timespec="seconds") + "Z",
            "total": total,
            "n_ok": len(df),
            "n_failed": len(failed),
            "n_delisted": len(delisted),
            "n_rate_limited": len(
                [t for t in rate_limited if t not in [f.get("ticker") for f in failed_detail.values()]]
            ),
            "rate_limited_tickers": list(set(rate_limited) - set(failed)),
            "failed_tickers": [
                {"ticker": t, **v} for t, v in failed_detail.items()
            ],
            "delisted_tickers": delisted,
        }
        # Behåll senaste 10 körningar
        history: list = []
        if _errors_path.exists():
            try:
                history = json.loads(_errors_path.read_text(encoding="utf-8"))
            except Exception:
                history = []
        history.append(_error_entry)
        history = history[-10:]
        _errors_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as _e:
        if verbose:
            print(f"  ⚠ Kunde inte skriva fetch_errors.json: {_e}")

    # ── Record metrics ───────────────────────────────────────────────────────
    try:
        from core.monitoring.metrics import MetricsCollector
        _mc = MetricsCollector()
        _mc.record_ticker_fetched(len(df))
        _mc.record_ticker_failed(len(failed) + len(delisted))
        _mc.record_fetch_duration(time.time() - _pass1_start)
    except Exception:
        pass

    return df


# Alias for optimerad version (samma funktion, connection pooling i data_fetcher.py)
fetch_universe_data_optimized = fetch_universe_data


# ═══════════════════════════════════════════════════════════════════════════════
# ASYNC PRISDATA-HÄMTNING (opt-in lager ovanpå sync-pipelinen)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Bakgrund: fetch_universe_data() använder ThreadPoolExecutor (8 workers)
# vilket är snabbt men blockerar på I/O. För 1 000+ tickers ger asyncio/aiohttp
# högre genomströmning utan thread-overhead.
#
# Användning (i daily_pipeline.py eller scan.py):
#   import asyncio
#   from core.data_fetcher import fetch_prices_async
#   price_rows = asyncio.run(fetch_prices_async(tickers))
#
# OBS: Kräver `pip install aiohttp`. Faller automatiskt tillbaka till
# fetch_universe_data() om aiohttp ej är installerat.
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_yahoo_chart_response(ticker: str, data: dict) -> dict | None:
    """
    Tolkar Yahoo Finance chart-API-svar (v8) till samma format som
    extract_metrics() returnerar (enbart prisdata - ingen fundamental).
    Returnerar None om svaret är ogiltigt.
    """
    try:
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        r = result[0]
        meta = r.get("meta", {})
        timestamps = r.get("timestamp", [])
        closes = (r.get("indicators", {})
                   .get("quote", [{}])[0]
                   .get("close", []))
        if not closes or not timestamps:
            return None

        close_series = pd.Series(closes, index=pd.to_datetime(timestamps, unit="s"))
        close_series = close_series.dropna()
        if close_series.empty:
            return None

        current = float(close_series.iloc[-1])
        return {
            "ticker":        ticker,
            "current_price": current,
            "return_1m":     _safe_return(close_series, 21),
            "return_3m":     _safe_return(close_series, 63),
            "return_6m":     _safe_return(close_series, 126),
            "return_12m":    _safe_return(close_series, 252),
            "currency":      meta.get("currency", "USD"),
        }
    except Exception:
        return None


async def _fetch_price_async(
    session,
    ticker: str,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Async-hämtning av prisdata för en ticker via Yahoo Finance chart-API."""
    async with semaphore:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {"interval": "1d", "range": "1y", "includePrePost": "false"}
        try:
            async with session.get(
                url, params=params,
                timeout=_aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                return _parse_yahoo_chart_response(ticker, data)
        except Exception:
            return None


async def fetch_prices_async(
    tickers: list,
    max_concurrent: int = 30,
    verbose: bool = True,
) -> list[dict]:
    """
    Async-hämtning av prisdata för en lista tickers.
    Returnerar lista av metric-dicts (enbart prisdata).
    Faller tillbaka till [] (tom lista) om aiohttp ej är installerat.

    Args:
        tickers: Lista av ticker-symboler
        max_concurrent: Max samtidiga HTTP-anrop (standard 30)
        verbose: Skriv ut framsteg

    Returns:
        Lista av dicts med prisdata per ticker (None-rader filtreras bort)
    """
    if not _AIOHTTP_AVAILABLE:
        if verbose:
            print("  ℹ  aiohttp saknas - kör pip install aiohttp för async-läge")
        return []

    semaphore = asyncio.Semaphore(max_concurrent)
    results = []

    async with _aiohttp.ClientSession() as session:
        tasks = [_fetch_price_async(session, t, semaphore) for t in tickers]
        if verbose:
            print(f"  ⚡ Async-hämtar prisdata för {len(tickers)} tickers "
                  f"(max {max_concurrent} parallella anrop)...")
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        for item in raw:
            if isinstance(item, dict) and item is not None:
                results.append(item)

    if verbose:
        print(f"  ✓ Async: {len(results)}/{len(tickers)} lyckade")
    return results


# ============================================================
# FINNHUB SENTIMENT BATCH
# ============================================================

def fetch_sentiment_batch(tickers: list, verbose: bool = True) -> dict:
    """
    Fetch sentiment scores for all tickers using parallel Finnhub calls.

    Gratis Finnhub: 60 calls/min -> 50 calls/min med headroom.
    Med 3 parallella workers och tokens-per-interval-rate-limiter håller vi oss
    inom gränsen: requests sprids jämnt över 60-sekundersfönster.
    """
    if not config.FINNHUB_API_KEY:
        if verbose:
            print("  ℹ Finnhub API key not set - skipping sentiment (alla får neutral score)")
        return {}

    if verbose:
        print(f"  Fetching Finnhub sentiment for {len(tickers)} tickers...")

    # Token-bucket rate limiter: 50 calls per 60 seconds = ~0.83 calls/sec totalt
    # Med 3 workers blir det ~0.28 calls/sec per worker.
    _finnhub_limiter = _RateLimiter(
        calls_per_sec=config.FINNHUB_CALLS_PER_MINUTE / 60.0
    )

    def _fetch_one(t: str) -> tuple:
        """Hämta sentiment för en ticker. Rate-limited."""
        _finnhub_limiter.acquire()
        return (t, fetch_finnhub_sentiment(t))

    results = {}
    with ThreadPoolExecutor(max_workers=config.FINNHUB_PARALLEL_WORKERS) as pool:
        futures = {pool.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, score = future.result()
            results[ticker] = score

    scored = sum(1 for v in results.values() if v is not None)
    if verbose:
        print(f"  ✓ Got sentiment for {scored}/{len(tickers)} tickers")

    return results


def search_stocks(query: str, max_results: int = 8) -> list:
    """
    Search for stocks by name or ticker using yfinance.
    Returns list of dicts with ticker, name, exchange, type.
    Used by the web UI for the search-and-add feature.
    """
    try:
        search = yf.Search(query, max_results=max_results)
        quotes = search.quotes

        results = []
        for q in quotes:
            # Filter to only stocks/ETFs, skip crypto etc
            q_type = q.get("quoteType", "")
            if q_type not in ("EQUITY", "ETF"):
                continue
            results.append({
                "ticker": q.get("symbol", ""),
                "name": q.get("shortname") or q.get("longname") or q.get("symbol"),
                "exchange": q.get("exchange", ""),
                "type": q_type,
            })
        return results[:max_results]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════
# PRICE-ONLY FETCH - snabb hämtning av ENDAST priser (ingen fundamental data)
# Används för daglig re-scoring i daily_pipeline.py
# ══════════════════════════════════════════════════════════════

def fetch_prices_only(tickers: list, period: str = "6mo",
                      max_workers: int = 12, timeout: int = 30) -> dict:
    """
    Hämta ENDAST priser för en lista med tickers - INGEN fundamental data.
    Mycket snabbare än fetch_stock_info eftersom vi bara hämtar history, inte info.

    Args:
        tickers: Lista med ticker-symboler
        period: t.ex. "6mo", "1y", "3mo"
        max_workers: Trådar för parallell hämtning
        timeout: Max sekunder per anrop

    Returns:
        dict: {ticker: {"current_price": float, "close": pd.Series, ...}}
              eller {} om tickern inte kunde hämtas
    """
    def _fetch(ticker: str) -> tuple[str, dict | None]:
        try:
            t = yf.Ticker(ticker)
            # yfinance Ticker.history() har INTE timeout-parameter
            # timeout hanteras på högre nivå via _with_timeout i data_fetcher
            hist = t.history(period=period, auto_adjust=True)
            if hist.empty:
                return ticker, None

            close = hist["Close"]
            current = float(close.iloc[-1])
            prev_close = float(close.iloc[-2]) if len(close) >= 2 else current

            # Beräkna momentum
            r1m = float(close.iloc[-1] / close.iloc[max(0, len(close)-21)] - 1) if len(close) >= 21 else None
            r3m = float(close.iloc[-1] / close.iloc[max(0, len(close)-63)] - 1) if len(close) >= 63 else None
            r6m = float(close.iloc[-1] / close.iloc[max(0, len(close)-126)] - 1) if len(close) >= 126 else None
            r12m = float(close.iloc[-1] / close.iloc[0] - 1) if len(close) >= 252 else None

            # 52-week high/low
            high_52w = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
            low_52w = float(close.iloc[-252:].min()) if len(close) >= 252 else float(close.min())
            pct_from_high = ((current - high_52w) / high_52w) * 100 if high_52w > 0 else 0

            # RSI (14)
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi = float((100 - (100 / (1 + rs))).iloc[-1]) if not rs.empty and len(rs) >= 14 else None

            # Volatilitet (daglig, 252 dagar)
            daily_returns = close.pct_change(fill_method=None).dropna()
            vol = float(daily_returns.std() * (252 ** 0.5)) if len(daily_returns) > 10 else None

            # Price vs MA50/MA200
            ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
            ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
            vs_ma50 = ((current - ma50) / ma50) * 100 if ma50 else None
            vs_ma200 = ((current - ma200) / ma200) * 100 if ma200 else None

            # Volume ratio (dagens volym / snitt 10d)
            vol_series = hist.get("Volume", pd.Series([0] * len(hist)))
            avg_vol_10d = float(vol_series.tail(10).mean()) if len(vol_series) >= 10 else 0
            current_vol = float(vol_series.iloc[-1]) if len(vol_series) > 0 else 0
            vol_ratio = current_vol / avg_vol_10d if avg_vol_10d > 0 else None

            # 3-dagars retur
            r3d = float(close.iloc[-1] / close.iloc[max(0, len(close)-4)] - 1) if len(close) >= 4 else None

            return ticker, {
                "current_price": current,
                "prev_close": prev_close,
                "change_pct": ((current / prev_close) - 1) * 100,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "pct_from_52w_high": round(pct_from_high, 2),
                "rsi_14": round(rsi, 1) if rsi is not None else None,
                "volatility": round(vol, 4) if vol is not None else None,
                "price_vs_ma50": round(vs_ma50, 2) if vs_ma50 is not None else None,
                "price_vs_ma200": round(vs_ma200, 2) if vs_ma200 is not None else None,
                "volume": int(current_vol),
                "avg_volume_10d": int(avg_vol_10d),
                "volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
                "return_1m": round(r1m * 100, 2) if r1m is not None else None,
                "return_3m": round(r3m * 100, 2) if r3m is not None else None,
                "return_6m": round(r6m * 100, 2) if r6m is not None else None,
                "return_12m": round(r12m * 100, 2) if r12m is not None else None,
                "return_3d": round(r3d * 100, 2) if r3d is not None else None,
            }
        except Exception:
            return ticker, None

    # Filter bort ogiltiga tickers som yfinance tolkar som
    # $N, $., $-, $I etc. och returnerar "possibly delisted" för.
    valid_tickers = [
        t for t in tickers
        if t and isinstance(t, str) and len(t.strip()) >= 2 and not t.strip().startswith("$")
    ]
    dropped = len(tickers) - len(valid_tickers)
    if dropped:
        print(f"  🗑️ Hoppar över {dropped} ogiltiga tickers (tomma/None/$prefix)")

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, t): t for t in valid_tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            if data:
                results[ticker] = data

    return results


def update_scored_with_prices(scored_df: pd.DataFrame, price_data: dict) -> pd.DataFrame:
    """
    Uppdatera en scored_universe DataFrame med nya prisberoende värden.
    Anropar score_universe() efter uppdatering för att få nya scores.

    Args:
        scored_df: Senaste scored_universe DataFrame
        price_data: Output från fetch_prices_only()

    Returns:
        Uppdaterad DataFrame med nya priser, momentum, RSI, scores
    """
    df = scored_df.copy()
    if "ticker" not in df.columns:
        return df

    # Sätt ticker som index för snabb lookup
    df = df.set_index("ticker")

    for ticker, prices in price_data.items():
        if ticker not in df.index:
            continue

        # Only update price/momentum columns, NOT fundamental ones.
        # yfinance daily fetches can return corrupted fundamentals
        # (negative P/E, P/B etc.) that overwrite correct weekly scan data.
        PRICE_ONLY_COLS = {
            "currentPrice", "previousClose", "regularMarketPreviousClose",
            "open", "dayHigh", "dayLow", "volume", "averageVolume",
            "return_1m", "return_3m", "return_6m", "return_12m",
            "return_1d", "pct_from_52w_high", "price_vs_ma50", "price_vs_ma200",
            "rsi_14", "volatility", "beta", "macd_above_signal", "bb_position",
            "volume_ratio", "ma50", "ma200", "dist_from_52w_high", "dist_from_52w_low",
            "momentum_3_vs_12",
        }
        for col, val in prices.items():
            if col in df.columns and col in PRICE_ONLY_COLS:
                df.at[ticker, col] = val

    # Återställ index
    df = df.reset_index()

    # Re-scora med nya priser (momentum, risk, size uppdateras)
    try:
        from core.scoring import score_universe
        df = score_universe(df)
    except Exception:
        pass

    return df


# ══════════════════════════════════════════════════════════════
# BENCHMARK DATA (OMXS30 + SPY) - ersätter daily_scan.fetch_benchmark_performance()
# ══════════════════════════════════════════════════════════════

def fetch_benchmark_performance() -> dict:
    """
    Hämtar OMXS30 (försök ^OMX först, fallback till XACTOMXS3.ST) och SPY.
    Returnerar {name: {change_1d, change_1m, change_ytd}} eller {} vid fel.
    """
    def _fetch_one(ticker: str) -> pd.DataFrame | None:
        """Hämta historik för en benchmark-ticker med timeout-skydd."""
        try:
            hist = _with_timeout(
                lambda: yf.Ticker(ticker).history(period="1y", auto_adjust=True),
                timeout_sec=15,
            )
            if hist is not None and not hist.empty and len(hist) >= 2:
                return hist
        except Exception:
            pass
        return None

    def _calc(close) -> dict:
        curr = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        chg_1d = (curr / prev - 1) * 100
        if len(close) >= 22:
            m1 = float(close.iloc[-22])
            chg_1m = (curr / m1 - 1) * 100
        else:
            chg_1m = None
        ytd = float(close.iloc[0])
        chg_ytd = (curr / ytd - 1) * 100
        return {
            "change_1d":  round(chg_1d, 2),
            "change_1m":  round(chg_1m, 2) if chg_1m is not None else None,
            "change_ytd": round(chg_ytd, 2),
        }

    result = {}

    # OMXS30: försök ^OMX först (om index-data finns), fallback till ETF-proxyn
    omx_hist = _fetch_one("^OMX")
    if omx_hist is None:
        omx_hist = _fetch_one(config.BENCHMARK_OMXS30)
    if omx_hist is not None:
        result["OMXS30"] = _calc(omx_hist["Close"])

    # SPY
    spy_hist = _fetch_one(config.BENCHMARK_SPY)
    if spy_hist is not None:
        result["SPY"] = _calc(spy_hist["Close"])

    return result
