"""
data_fetcher.py
===============
Handles all data fetching from yfinance with:
- Local file caching (avoids re-fetching same data)
- Retry logic on failures
- Rate limiting (delay between requests)
- Optional FMP fallback for fundamental data
- Data quality validation
"""

import asyncio
import os
import sys
import time
import json
import socket
import pickle
import hashlib
import random
import functools
import threading
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# Återanvändbar requests.Session för connection pooling
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

try:
    import aiohttp as _aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _aiohttp = None
    _AIOHTTP_AVAILABLE = False

import yfinance as yf
import pandas as pd
import numpy as np


from core import config

import requests
import requests.sessions

# ── Lager 1: socket.setdefaulttimeout ────────────────────────────────────
# Sätts INNAN yfinance importeras. Påverkar alla nya sockets på OS-nivå,
# inklusive SSL-handskakningar i OpenSSL (C-kod) som varken signal.alarm
# eller requests-patchen kan nå. Det enda som stoppar ett äkta C-hang.
socket.setdefaulttimeout(7)


# ── Lager 2: requests.Session.send-patch ─────────────────────────────────
# Sätter explicit (connect, read)-timeout på alla requests-anrop som
# yfinance gör utan att ange timeout själv. Inspekterar också HTTP-status
# för att flippa thread-local flaggor vid 429 (rate-limit) och 404 (delisted).
# yfinance v0.2.x sväljer dessa fel silently, så detta är vår enda
# tillförlitliga signal innan yfinance returnerar tom data.
_original_session_send = requests.sessions.Session.send

def _timeout_session_send(self, request, **kwargs):
    if kwargs.get("timeout") is None:
        kwargs["timeout"] = (3, 5)
    response = _original_session_send(self, request, **kwargs)
    # Inspect status code to set thread-local flags - referenced later by
    # _fetch_single_ticker. The flags are initialised in _reset_rate_limit_flag().
    try:
        sc = getattr(response, "status_code", None)
        if sc == 429:
            import threading as _t
            _tls = globals().get("_RATE_LIMIT_TLS")
            if _tls is not None:
                _tls.hit = True
        elif sc == 404:
            _tls = globals().get("_RATE_LIMIT_TLS")
            if _tls is not None:
                _tls.delisted = True
    except Exception:
        pass
    return response

requests.sessions.Session.send = _timeout_session_send

# ── curl_cffi timeout-patch + status-code-detektion ──────────────────────
# yfinance 0.2.37+ använder curl_cffi som HTTP-backend. Den kringgår
# requests.Session-patchen ovan, så vi måste patcha den separat.
try:
    import curl_cffi.requests as _cf_req
    _original_cf_request = _cf_req.Session.request
    def _patched_cf_request(self, method, url, *args, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (10, 20)
        response = _original_cf_request(self, method, url, *args, **kwargs)
        try:
            sc = getattr(response, "status_code", None)
            if sc == 429:
                _tls = globals().get("_RATE_LIMIT_TLS")
                if _tls is not None:
                    _tls.hit = True
            elif sc == 404:
                _tls = globals().get("_RATE_LIMIT_TLS")
                if _tls is not None:
                    _tls.delisted = True
        except Exception:
            pass
        return response
    _cf_req.Session.request = _patched_cf_request
except Exception:
    pass  # curl_cffi saknas - inget att patcha

_FX_CACHE = {}
Path(config.CACHE_DIR).mkdir(parents=True, exist_ok=True)

# Bakåtkompatibilitet: daily_pipeline.py:771 importerar `_CACHE_DIR` (gammalt namn
# från en pre-refaktorering av cache-modulen). Nu lever konstanten i config.CACHE_DIR.
_CACHE_DIR = config.CACHE_DIR

# Fundamentala fält som bara ändras vid kvartalsrapporter -> 30 dagars cache
_STATIC_FIELDS = frozenset({
    "longName", "shortName", "sector", "industry", "country", "currency",
    "sharesOutstanding", "floatShares",
    "returnOnEquity", "returnOnAssets",
    "profitMargins", "operatingMargins", "grossMargins",
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    "debtToEquity", "currentRatio", "quickRatio",
    "freeCashflow", "totalCash", "totalDebt", "totalRevenue",
    "heldPercentInsiders", "heldPercentInstitutions",
    "payoutRatio", "dividendRate", "fiveYearAvgDividendYield",
    "lastDividendValue", "exDividendDate",
})


def _cache_path(key: str) -> Path:
    """Generate a deterministic cache file path from a key."""
    safe_key = hashlib.md5(key.encode()).hexdigest()
    return Path(config.CACHE_DIR) / f"{safe_key}.pkl"


def _read_cache(key: str, max_age_hours: float):
    """Return cached data if it exists and isn't too old, else None."""
    path = _cache_path(key)
    if not path.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    if age > timedelta(hours=max_age_hours):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _write_cache(key: str, data):
    """Save data to cache."""
    path = _cache_path(key)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except Exception as e:
        print(f"  ⚠ Cache write failed: {e}")


def _with_timeout(fn, timeout_sec=15):
    """
    Kör fn() i en daemon-tråd med hård tidsgräns.

    Använder threading.Event istället för t.join():
    - Event.wait(timeout) är mer pålitlig på GitHub Actions (Linux)
    - done.set() i finally garanterar att vi vaknar vid exception
    - curl_cffi-patchen (connect=10s, read=20s) stänger sockets inom 20s
    """
    result    = [None]
    error     = [None]
    done      = threading.Event()

    def worker():
        try:
            result[0] = fn()
        except Exception as e:
            error[0] = e
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    completed = done.wait(timeout=timeout_sec)

    if not completed:
        raise TimeoutError(f"Anrop hängde efter {timeout_sec}s")
    if error[0] is not None:
        raise error[0]
    return result[0]


class _RateLimitError(Exception):
    """Raised when Yahoo Finance returns HTTP 429 Too Many Requests."""
    pass


class _DelistedError(Exception):
    """Raised when Yahoo Finance returns HTTP 404 - ticker is delisted/unknown."""
    pass


# ── RateLimiter (trådsäker) ────────────────────────────────────────────
# Stryper anrop till max MAX_CALLS per PERIOD.
# Används i ThreadPoolExecutor för att undvika 429 från yfinance.

class RateLimiter:
    """Trådsäker rate-limiter med sliding window."""
    def __init__(self, max_calls: int = 8, period: float = 1.0):
        self.max_calls = max_calls
        self.period = period
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def wait(self):
        """Blockera tills ett anrop är tillået."""
        with self._lock:
            now = time.time()
            self._calls = [t for t in self._calls if now - t < self.period]
            if len(self._calls) >= self.max_calls:
                sleep_time = self._calls[0] + self.period - now
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self._calls.append(time.time())


# ── yfinance retry-decorator with exponential backoff + jitter ────────
def yfinance_retry(max_retries: int = 5, base_delay: float = 2.0):
    """Decorator: exponential backoff med jitter för yfinance-anrop."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    err_low = str(e).lower()
                    if "too many requests" in err_low or "rate" in err_low:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    elif attempt < max_retries - 1:
                        delay = base_delay * (attempt + 1.5 ** attempt)
                    else:
                        raise
                    time.sleep(delay)
            raise last_error
        return wrapper
    return decorator


# ── Thread-local flags set by yfinance log handler ─────────────────────
_RATE_LIMIT_TLS = threading.local()


def _is_delist_message(msg: str) -> bool:
    """Detect 404/delisted/unknown-symbol messages from yfinance output."""
    msg = msg.lower()
    # Striktare mönster: kräver "possibly delisted" eller "no data found"
    # eller citat om "not found" från yfinance. Undviker false positives
    # där "404" eller "not found" dyker upp i HTTP-felmeddelanden.
    return (
        "possibly delisted" in msg
        or "no data found, symbol may be delisted" in msg
        or "quote not found for symbol" in msg
        or "no fundamentals data found for symbol" in msg
    )


class _YFinanceLogDetector(__import__("logging").Handler):
    """Logging handler that flips thread-local flags on relevant warnings."""
    def emit(self, record):
        try:
            msg = record.getMessage().lower()
            if "too many requests" in msg or "rate limit" in msg or " 429 " in f" {msg} ":
                _RATE_LIMIT_TLS.hit = True
            if _is_delist_message(msg):
                _RATE_LIMIT_TLS.delisted = True
        except Exception:
            pass


def _install_yf_log_detector():
    """Install detector exactly once on yfinance's root logger."""
    import logging
    yf_logger = logging.getLogger("yfinance")
    # Avoid duplicate handlers if module reloaded
    if not any(isinstance(h, _YFinanceLogDetector) for h in yf_logger.handlers):
        handler = _YFinanceLogDetector()
        handler.setLevel(logging.WARNING)
        yf_logger.addHandler(handler)
        # Make sure yfinance logger actually emits warnings
        if yf_logger.level == logging.NOTSET or yf_logger.level > logging.WARNING:
            yf_logger.setLevel(logging.WARNING)


_install_yf_log_detector()


def _reset_rate_limit_flag():
    _RATE_LIMIT_TLS.hit = False
    _RATE_LIMIT_TLS.delisted = False


def _rate_limit_was_hit() -> bool:
    return getattr(_RATE_LIMIT_TLS, "hit", False)


def _delisted_was_hit() -> bool:
    return getattr(_RATE_LIMIT_TLS, "delisted", False)


def _retry(fn, *args, timeout_sec=12, **kwargs):
    """
    Kör fn() med retry-logik. TimeoutError = direkt fail, ingen retry.

    TimeoutError = ticker hänger i C-kod. Retry ger exakt samma timeout
    och dubblerar dödtiden. En attempt räcker för att konstatera att
    tickern inte svarar.

    Retry sker bara vid nätverksfel (ConnectionError, HTTPError etc.)
    som faktiskt kan lyckas vid nästa försök.

    Rate limit (429) = höjs som _RateLimitError för att skilja dem från
    vanliga fel - fetch_universe_data kan då samla upp dem för pass-2-retry.
    """
    for attempt in range(config.MAX_RETRIES):
        try:
            return _with_timeout(fn, timeout_sec=timeout_sec)
        except TimeoutError:
            raise   # Direkt vidare - ingen retry, ingen sleep
        except Exception as e:
            err_str = str(e)
            # Propagate rate limit immediately - no point retrying here
            if "429" in err_str or "Too Many Requests" in err_str.lower() or "rate limit" in err_str.lower():
                raise _RateLimitError(err_str) from e
            if attempt < config.MAX_RETRIES - 1:
                wait = config.RETRY_BACKOFF_SEC * (attempt + 1)
                time.sleep(wait)
                continue
            raise


def fetch_stock_info(ticker: str) -> dict:
    """
    Fetch fundamental info for a single stock.

    Tvådelad cache:
      info_static:{ticker}  - CACHE_HOURS (720h/30 dagar)
        Fält som bara ändras vid kvartalsrapporter: marginaler, tillväxt,
        skuldsättning, ägande, bolagsnamn/sektor.

      info_dynamic:{ticker} - DYNAMIC_CACHE_HOURS (170h/7 dagar)
        Fält som kan ändras av nyheter varje vecka: P/E, analytikermål,
        blankning, beta, volymsnitt, utdelning.

    Om båda cacharna är giltiga returneras de utan något nätverksanrop.
    Om endera har löpt ut hämtas all data på nytt och båda uppdateras.
    """
    static_key  = f"info_static:{ticker}"
    dynamic_key = f"info_dynamic:{ticker}"

    static_cached  = _read_cache(static_key,  config.CACHE_HOURS)
    dynamic_cached = _read_cache(dynamic_key, config.DYNAMIC_CACHE_HOURS)

    # Sanitetskoll på dynamisk cache: pris > 52v-high = korrupt
    if dynamic_cached is not None:
        cp  = dynamic_cached.get("currentPrice") or dynamic_cached.get("regularMarketPrice") or 0
        h52 = dynamic_cached.get("fiftyTwoWeekHigh") or 0
        if cp and h52 and float(cp) > float(h52) * 1.02:
            _cache_path(dynamic_key).unlink(missing_ok=True)
            dynamic_cached = None

    if static_cached is not None and dynamic_cached is not None:
        return {**static_cached, **dynamic_cached}

    try:
        time.sleep(config.REQUEST_DELAY_SEC)
        stock = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=10)
        info = _retry(lambda: stock.info)

        if not info or len(info) < 5:
            # Returnera vad vi har i cache om hämtningen gav för lite
            return {**(static_cached or {}), **(dynamic_cached or {})}

        static_data  = {k: v for k, v in info.items() if k     in _STATIC_FIELDS}
        dynamic_data = {k: v for k, v in info.items() if k not in _STATIC_FIELDS}

        _write_cache(static_key,  static_data)
        _write_cache(dynamic_key, dynamic_data)
        return info

    except _RateLimitError:
        raise
    except Exception as e:
        err_str = str(e)
        low = err_str.lower()
        if "429" in err_str or "too many requests" in low or "rate limit" in low:
            raise _RateLimitError(err_str) from e
        if "404" in err_str or _is_delist_message(low):
            raise _DelistedError(err_str) from e
        print(f"  ⚠ Failed to fetch info for {ticker}: {e}")
        merged = {**(static_cached or {}), **(dynamic_cached or {})}
        return merged if merged else {}


def fetch_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Hämtar historisk prisdata justerad för utdelningar och konverterad till SEK.
    """
    cache_key = f"prices_sek:{ticker}:{period}"
    cached = _read_cache(cache_key, config.PRICE_CACHE_HOURS)
    if cached is not None:
        return cached

    try:
        time.sleep(config.REQUEST_DELAY_SEC)
        stock = _with_timeout(lambda: yf.Ticker(ticker), timeout_sec=10)

        # 1. Aktivera auto_adjust=True för att inkludera utdelningar i priset
        hist = _retry(lambda: stock.history(period=period, auto_adjust=True))

        if hist.empty:
            return pd.DataFrame()

        # 2. Valutakonvertering till SEK om det inte är en svensk aktie
        if not ticker.endswith(".ST"):
            fx_map = {
                ".L":  "GBPSEK=X",  ".OL": "NOKSEK=X",  ".CO": "DKKSEK=X",
                ".DE": "EURSEK=X",  ".PA": "EURSEK=X",  ".AS": "EURSEK=X",
                ".MI": "EURSEK=X",  ".MC": "EURSEK=X",  ".HE": "EURSEK=X",
                ".VI": "EURSEK=X",  ".LS": "EURSEK=X",  ".WA": "PLNSEK=X",
                ".SW": "CHFSEK=X",  ".TO": "CADSEK=X",  ".AX": "AUDSEK=X",
                ".HK": "HKDSEK=X",  ".T":  "JPYSEK=X",  ".TW": "TWDSEK=X",
                ".KS": "KRWSEK=X",  ".NS": "USDSEK=X",  ".SI": "SGDSEK=X",
                ".SA": "BRLSEK=X",
            }

            fx_ticker = "USDSEK=X"  # Default för US-aktier utan suffix
            for suffix, pair in fx_map.items():
                if ticker.endswith(suffix):
                    fx_ticker = pair
                    break

            # Hämta växelkursen med timeout-skydd
            if fx_ticker not in _FX_CACHE:
                try:
                    fx_stock = yf.Ticker(fx_ticker)
                    raw = _with_timeout(
                        lambda: fx_stock.history(period=period, auto_adjust=True)["Close"],
                        timeout_sec=20,
                    )
                    if raw is not None and not raw.empty:
                        _FX_CACHE[fx_ticker] = raw
                    else:
                        print(f"  ⚠ FX-data tom för {fx_ticker} - {ticker} behåller ursprungsvaluta")
                        _FX_CACHE[fx_ticker] = pd.Series(dtype=float)
                except Exception as _fx_err:
                    print(f"  ⚠ FX-fetch misslyckades ({fx_ticker}): {_fx_err} - {ticker} behåller ursprungsvaluta")
                    _FX_CACHE[fx_ticker] = pd.Series(dtype=float)

            fx_hist = _FX_CACHE[fx_ticker]

            # Synka datumen (hanterar helgdagar i olika länder).
            # Begränsa ffill till 5 dagar så vi inte propagerar en månadsgammal
            # FX-kurs över långa luckor (kan ge 100-1000x felaktiga SEK-priser).
            fx_aligned = fx_hist.reindex(hist.index).ffill(limit=5).bfill(limit=5)

            # Fallback: om fx_aligned är tom, all-NaN, eller har partiell NaN
            # (FX-fetch misslyckades eller lucka >5 dagar -> ersätt kvarvarande NaN med 1.0
            # så att prishistorik inte infekteras av NaN i RSI/MACD/return-beräkningar).
            if fx_aligned.empty or fx_aligned.isna().all():
                fx_aligned = pd.Series(1.0, index=hist.index)
            elif fx_aligned.isna().any():
                # Partiell NaN: ersätt med 1.0 för de få datapunkter som saknar FX
                fx_aligned = fx_aligned.fillna(1.0)
            # Sanity check: orealistiska dag-till-dag-hopp tyder på datafel.
            # Körs ALLTID, inte bara vid NaN (buggfix: tidigare inuti elif-blocket)
            _ratio = (fx_aligned / fx_aligned.shift(1)).abs()
            if (_ratio > 1.5).any() or (_ratio < 0.67).any():
                print(f"  ⚠ Misstänkt FX-hopp för {ticker} ({fx_ticker}) - hoppar konvertering")
                fx_aligned = pd.Series(1.0, index=hist.index)

            # Multiplicera alla priskolumner med växelkursen
            for col in ["Open", "High", "Low", "Close"]:
                if col in hist.columns:
                    hist[col] = hist[col] * fx_aligned

        _write_cache(cache_key, hist)
        return hist

    except _RateLimitError:
        raise
    except Exception as e:
        err_str = str(e)
        low = err_str.lower()
        if "429" in err_str or "too many requests" in low or "rate limit" in low:
            raise _RateLimitError(err_str) from e
        if "404" in err_str or _is_delist_message(low):
            raise _DelistedError(err_str) from e
        print(f"  ⚠ Failed to fetch prices for {ticker}: {e}")
        return pd.DataFrame()

def _get_insider_signal(ticker: str) -> dict:
    """
    Analysera insiderhandel via yfinance (senaste 90 dagarna).
    Returnerar:
        insider_cluster (bool): >=3 olika insiders köper inom 30 dagar
        insider_executive_buy (bool): VD/CFO köper inom 90 dagar
    Cachas 24h för att inte spamma Yahoo.
    """
    cache_key = f"insider_signal:{ticker}"
    cached = _read_cache(cache_key, max_age_hours=24)
    if cached is not None:
        return cached

    result = {"insider_cluster": False, "insider_executive_buy": False, "insider_recent_date": None}
    try:
        t = yf.Ticker(ticker)
        txns = t.insider_transactions
        if txns is None or (hasattr(txns, "empty") and txns.empty):
            _write_cache(cache_key, result)
            return result

        txns = txns.copy()
        txns.columns = txns.columns.str.lower().str.replace(" ", "_")

        # Normalisera datumkolumn
        now = pd.Timestamp.now(tz=None)
        date_col = next((c for c in txns.columns if "date" in c), None)
        if date_col:
            txns["_date"] = pd.to_datetime(txns[date_col], errors="coerce").dt.tz_localize(None)
        else:
            _write_cache(cache_key, result)
            return result

        # Transaktionstyp-kolumn
        type_col = next((c for c in txns.columns if "type" in c or "transaction" in c), None)
        if type_col:
            buy_mask = txns[type_col].fillna("").str.lower().str.contains(
                r"buy|purchase|köp|acqui|exercise", regex=True, na=False
            )
        else:
            buy_mask = pd.Series(True, index=txns.index)  # anta alla är köp om kolumn saknas

        recent_90 = txns[txns["_date"] >= (now - pd.Timedelta(days=90))]
        buys_90 = recent_90[buy_mask.reindex(recent_90.index, fill_value=False)]

        # VD/CFO-detektion
        title_col = next((c for c in buys_90.columns if "title" in c or "position" in c or "relation" in c), None)
        if title_col and not buys_90.empty:
            exec_titles = {"ceo", "cfo", "vd", "verkst", "chief executive", "chief financial",
                           "president", "managing director"}
            titles = buys_90[title_col].fillna("").str.lower()
            result["insider_executive_buy"] = bool(titles.apply(
                lambda t: any(e in t for e in exec_titles)
            ).any())

        # Cluster: >=3 distinkta insiders köper inom senaste 30 dagar
        buys_30 = buys_90[buys_90["_date"] >= (now - pd.Timedelta(days=30))]
        name_col = next((c for c in buys_30.columns if "name" in c or "insider" in c), None)
        if name_col and not buys_30.empty:
            result["insider_cluster"] = int(buys_30[name_col].nunique()) >= 3

        # Senaste transaktionsdatum för decay-beräkning
        if not buys_90.empty:
            result["insider_recent_date"] = buys_90["_date"].max().isoformat()

    except Exception:
        pass  # Säkert fallback - returnerar False/False

    # För svenska aktier: komplettera med Finansinspektionens insynsregister
    # (samma källa som Börsdata men gratis och offentlig data)
    if ticker.upper().endswith(".ST") and not (result["insider_cluster"] or result["insider_executive_buy"]):
        try:
            from core.fi_insider_fetcher import get_insider_signal_fi
            fi_result = get_insider_signal_fi(ticker)
            # FI-data har företräde om den hittar signal (yfinance är dålig på svenska insiders)
            if fi_result.get("insider_cluster") or fi_result.get("insider_executive_buy"):
                result.update(fi_result)
        except Exception:
            pass  # FI-modulen är valfri - failar tyst

    _write_cache(cache_key, result)
    return result


def fetch_fmp_fallback(ticker: str) -> dict:
    """
    Fallback to Financial Modeling Prep if yfinance fails.
    Only runs if FMP_API_KEY is configured.
    """
    if not config.FMP_API_KEY:
        return {}

    # Strip exchange suffix for FMP (e.g., VOLV-B.ST -> VOLV-B)
    clean_ticker = ticker.split(".")[0]

    cache_key = f"fmp:{clean_ticker}"
    cached = _read_cache(cache_key, config.CACHE_HOURS)
    if cached is not None:
        return cached

    try:
        url = f"https://financialmodelingprep.com/api/v3/profile/{clean_ticker}"
        params = {"apikey": config.FMP_API_KEY}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                _write_cache(cache_key, data[0])
                return data[0]
    except Exception as e:
        print(f"  ⚠ FMP fallback failed for {ticker}: {e}")

    return {}


def _get_fmp_fundamentals(ticker: str) -> dict:
    """
    Fetch expanded fundamental data from FMP key-metrics endpoint.
    Fills gaps in yfinance data (P/E, P/B, ROE, EV/EBITDA, FCF yield).
    Cached 720h (same as static fundamentals) to stay within free tier limits.
    Only runs if FMP_API_KEY is configured.
    """
    if not config.FMP_API_KEY:
        return {}

    import requests as _requests

    clean = ticker.split(".")[0]
    cache_key = f"fmp_fund:{clean}"
    # Long cache (30 days) -- fundamentals change slowly, free tier = 250 calls/day
    cached = _read_cache(cache_key, max_age_hours=720)
    if cached is not None:
        return cached

    result = {}
    try:
        base = "https://financialmodelingprep.com/api/v3"
        params = {"apikey": config.FMP_API_KEY, "limit": 1}
        r = _requests.get(f"{base}/key-metrics-ttm/{clean}", params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list) and data[0]:
                km = data[0]
                result = {
                    "fmp_pe":              km.get("peRatioTTM"),
                    "fmp_pb":              km.get("pbRatioTTM"),
                    "fmp_roe":             km.get("roeTTM"),
                    "fmp_roa":             km.get("returnOnTangibleAssetsTTM"),
                    "fmp_ev_ebitda":       km.get("evToEbitdaTTM") or km.get("enterpriseValueOverEBITDATTM"),
                    "fmp_fcf_yield":       km.get("freeCashFlowYieldTTM"),
                    "fmp_net_debt_ebitda": km.get("netDebtToEBITDATTM"),
                    "fmp_revenue_growth":  km.get("revenueGrowthTTM"),
                    "fmp_earnings_yield":  km.get("earningsYieldTTM"),
                }
    except Exception as e:
        pass  # Silent fallback -- FMP enrichment is optional

    _write_cache(cache_key, result)
    return result


def extract_metrics(ticker: str, info: dict, history: pd.DataFrame) -> dict:
    """
    Extract all the metrics we need for scoring from raw yfinance data.
    Returns a dict with consistent keys regardless of what yfinance returns.
    """
    metrics = {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "country": info.get("country", "Unknown"),
        "currency": info.get("currency", "USD"),
        "market_cap": info.get("marketCap"),  # Skrivs över nedan med färsk data om prishistorik finns


        # Valuation metrics
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "peg_ratio": info.get("trailingPegRatio") or info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "price_to_sales": info.get("priceToSalesTrailing12Months"),
        "ev_to_revenue": info.get("enterpriseToRevenue"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),

        # Profitability / Quality
        "roe": info.get("returnOnEquity"),
        "roa": info.get("returnOnAssets"),
        "profit_margin": info.get("profitMargins"),
        "operating_margin": info.get("operatingMargins"),
        "gross_margin": info.get("grossMargins"),

        # Growth
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth"),
        "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),

        # Financial health
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "quick_ratio": info.get("quickRatio"),
        "free_cash_flow": info.get("freeCashflow"),
        "total_cash": info.get("totalCash"),
        "total_debt": info.get("totalDebt"),
        "enterprise_value": info.get("enterpriseValue"),

        # Financial statement data (populated from yfinance financials/BS/CF)
        "total_assets":            None,
        "total_assets_prev":       None,
        "revenue_ttm":             None,
        "revenue_prev":            None,
        "revenue_2y_ago":          None,
        "operating_income_ttm":    None,
        "operating_income_prev":   None,
        "net_income_ttm":          None,
        "operating_cashflow_ttm":  None,

        # Dividend
        "dividend_yield":       info.get("dividendYield"),
        "payout_ratio":         info.get("payoutRatio"),
        "dividend_rate":        info.get("dividendRate"),
        "div_yield_5y_avg":     info.get("fiveYearAvgDividendYield"),
        "last_dividend_value":  info.get("lastDividendValue"),
        "ex_dividend_date":     info.get("exDividendDate"),

        # Risk
        "beta": info.get("beta"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "52_week_low": info.get("fiftyTwoWeekLow"),

        # Current state
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "target_mean_price": info.get("targetMeanPrice"),
        "recommendation_mean": info.get("recommendationMean"),  # 1=strong buy, 5=strong sell
        "number_of_analysts": info.get("numberOfAnalystOpinions"),

        # NEW: Short interest
        "short_ratio":      info.get("shortRatio"),          # Dagar att täcka (lägre = mer likvid)
        "short_pct_float":  info.get("shortPercentOfFloat"), # % av float som är blankat

        # NEW: Insider & institutionellt ägande
        "insider_pct":      info.get("heldPercentInsiders"),   # % ägt av insiders
        "institution_pct":  info.get("heldPercentInstitutions"),
        # Insiderhandel-signaler (fyller i nedan efter transaktionsanalys)
        "insider_cluster":       False,
        "insider_executive_buy": False,

        # NEW: Earnings surprise (hur ofta slår bolaget estimat)
        "earnings_revision_rate": info.get("earningsForecastsGrowthRate"),

        # Options flow signal (put/call ratio) -- sätts nedan från extra_data
        "options_flow_signal": None,

        # NEW: Omsättning och volym
        "avg_volume":       info.get("averageVolume"),
        "avg_volume_10d":   info.get("averageVolume10days"),
        "volume_ratio":     None,  # Beräknas nedan från prishistorik
    }

    # Prishistorik är alltid färsk (PRICE_CACHE_HOURS=24h) - använd den för
    # marknadskänsliga värden som annars kan vara 7 dagar gamla i info-cachen.
    if not history.empty and len(history) > 20:
        close  = history["Close"]
        volume = history.get("Volume")
        current = float(close.iloc[-1])

        # Aktuellt pris - alltid från färsk prishistorik
        metrics["current_price"] = current

        # 52-veckors high/low - beräkna från prishistorik (max 252 börsdagar)
        tail = close.tail(252)
        high_series = history["High"].tail(252) if "High" in history.columns else tail
        low_series  = history["Low"].tail(252)  if "Low"  in history.columns else tail
        metrics["52_week_high"] = float(high_series.max())
        metrics["52_week_low"]  = float(low_series.min())

        # Marknadsvärde: antal aktier (kvartalsdata, OK att cacha) x färskt pris
        shares = info.get("sharesOutstanding")
        if shares and shares > 0:
            metrics["market_cap"] = float(shares) * current

        # Returns over different periods -- stored as PERCENTAGE (e.g. 3.5 = 3.5%)
        _r1m  = _safe_return(close, 21)
        _r3m  = _safe_return(close, 63)
        _r6m  = _safe_return(close, 126)
        _r12m = _safe_return(close, 252)
        metrics["return_1m"]  = round(_r1m  * 100, 2) if _r1m  is not None else None
        metrics["return_3m"]  = round(_r3m  * 100, 2) if _r3m  is not None else None
        metrics["return_6m"]  = round(_r6m  * 100, 2) if _r6m  is not None else None
        metrics["return_12m"] = round(_r12m * 100, 2) if _r12m is not None else None

        # Distance from 52-week high (negative is below)
        if metrics["52_week_high"]:
            metrics["pct_from_52w_high"] = (current / metrics["52_week_high"]) - 1.0

        # Volatility (annualized)
        returns = close.pct_change(fill_method=None).dropna()
        if len(returns) > 30:
            metrics["volatility"] = returns.std() * np.sqrt(252)

        # Simple RSI (14-day)
        metrics["rsi_14"] = _calc_rsi(close, 14)

        # Distance from 50-day and 200-day moving averages
        if len(close) >= 50:
            ma50 = close.rolling(50).mean().iloc[-1]
            metrics["price_vs_ma50"] = (current / ma50) - 1.0
        if len(close) >= 200:
            ma200 = close.rolling(200).mean().iloc[-1]
            metrics["price_vs_ma200"] = (current / ma200) - 1.0

        # NEW: Volym-ratio (senaste dag vs 20-dagars snitt)
        # Hög volym vid uppgång = bekräftad rörelse
        if volume is not None and len(volume) > 20:
            avg_vol = volume.tail(20).mean()
            if avg_vol > 0:
                metrics["volume_ratio"] = float(volume.iloc[-1]) / avg_vol

        # NEW: MACD-signal (enkel: 12-26 EMA cross)
        if len(close) >= 26:
            ema12 = close.ewm(span=12).mean()
            ema26 = close.ewm(span=26).mean()
            macd  = ema12 - ema26
            signal = macd.ewm(span=9).mean()
            metrics["macd_above_signal"] = bool(macd.iloc[-1] > signal.iloc[-1])

        # NEW: Bollinger Band position (var i bandet handlas aktien?)
        # 0 = vid nedre band, 0.5 = mitten, 1 = vid övre band
        if len(close) >= 20:
            sma20  = close.rolling(20).mean()
            std20  = close.rolling(20).std()
            upper  = sma20 + 2 * std20
            lower  = sma20 - 2 * std20
            band_w = upper.iloc[-1] - lower.iloc[-1]
            if band_w > 0:
                metrics["bb_position"] = float((current - lower.iloc[-1]) / band_w)

    # ── FMP-berikningn: fyll luckor från yfinance med FMP key-metrics (TTM) ──
    # Körs bara om FMP_API_KEY är konfigurerat. Gratis-tier: 250 anrop/dag,
    # 720h cache -> ~33 anrop/dag för 1 000 aktier med 30-dagars rotation.
    fmp_fund = _get_fmp_fundamentals(ticker)
    if fmp_fund:
        # Fyll bara om yfinance returnerade None/saknade värdet
        if metrics.get("pe_trailing") is None and fmp_fund.get("fmp_pe"):
            metrics["pe_trailing"] = fmp_fund["fmp_pe"]
        if metrics.get("price_to_book") is None and fmp_fund.get("fmp_pb"):
            metrics["price_to_book"] = fmp_fund["fmp_pb"]
        if metrics.get("roe") is None and fmp_fund.get("fmp_roe"):
            metrics["roe"] = fmp_fund["fmp_roe"]
        if metrics.get("roa") is None and fmp_fund.get("fmp_roa"):
            metrics["roa"] = fmp_fund["fmp_roa"]
        if metrics.get("ev_to_ebitda") is None and fmp_fund.get("fmp_ev_ebitda"):
            metrics["ev_to_ebitda"] = fmp_fund["fmp_ev_ebitda"]
        if metrics.get("revenue_growth") is None and fmp_fund.get("fmp_revenue_growth"):
            metrics["revenue_growth"] = fmp_fund["fmp_revenue_growth"]

    # ── Financial statement data för MEWS (#3) ────────────────────────────────
    # Hämtar balansräkning, resultaträkning och kassaflöde från yfinance.
    # Alla fält är best-effort: om något misslyckas blir värdet None/NaN.
    try:
        stock = yf.Ticker(ticker)

        bs = stock.balance_sheet
        if bs is not None and not bs.empty:
            total_assets = _safe_fin_val(bs, "Total Assets")
            if total_assets is not None:
                metrics["total_assets"] = total_assets
            # Previous year
            if len(bs.columns) > 1:
                metrics["total_assets_prev"] = _safe_fin_val(bs.iloc[:, 1], "Total Assets")

        inc = stock.financials
        if inc is not None and not inc.empty:
            metrics["revenue_ttm"]         = _safe_fin_val(inc, "Total Revenue")
            metrics["operating_income_ttm"] = _safe_fin_val(inc, "Operating Income")
            metrics["net_income_ttm"]       = _safe_fin_val(inc, "Net Income")
            # Previous year values
            if len(inc.columns) > 1:
                metrics["revenue_prev"]         = _safe_fin_val(inc.iloc[:, 1], "Total Revenue")
                metrics["operating_income_prev"] = _safe_fin_val(inc.iloc[:, 1], "Operating Income")
            if len(inc.columns) > 2:
                metrics["revenue_2y_ago"] = _safe_fin_val(inc.iloc[:, 2], "Total Revenue")

        cf = stock.cashflow
        if cf is not None and not cf.empty:
            metrics["operating_cashflow_ttm"] = _safe_fin_val(cf, "Operating Cash Flow")
    except Exception:
        pass  # Best-effort: missing financials never crash scoring

    # Insiderhandel-signaler (VD/CFO-köp & cluster-detektion)
    # Görs sist så timeout inte blockerar övrig datahämtning
    ins = _get_insider_signal(ticker)
    metrics["insider_cluster"]       = ins.get("insider_cluster", False)
    metrics["insider_executive_buy"] = ins.get("insider_executive_buy", False)
    metrics["insider_recent_date"]   = ins.get("insider_recent_date")

    # ── Earnings surprise (från earnings_history) ─────────────────────────────
    # Körs inuti extract_metrics för att hålla ihop med övrig datahämtning
    # Cachad 72h i extra_data.py så extra nätverkskostnad är liten från dag 2
    metrics["earnings_surprise"] = 0.5  # neutral default
    try:
        from core.extra_data import fetch_earnings_surprise_signal as _fetch_es
        es = _fetch_es(ticker)
        if es is not None:
            metrics["earnings_surprise"] = es
    except Exception:
        pass

    # Options flow signal (put/call ratio)
    try:
        from core.extra_data import fetch_options_flow_signal as _fetch_of
        of = _fetch_of(ticker)
        if of is not None:
            metrics["options_flow_signal"] = of
    except Exception:
        pass

    # Schema-validering: tvinga numeriska fält, fånga Infinity/None ──────
    _string_fields = frozenset({
        "ticker", "name", "sector", "industry", "country", "currency",
        "insider_cluster", "insider_executive_buy", "insider_recent_date",
        "macd_above_signal", "options_flow_signal",
    })
    for key, value in list(metrics.items()):
        if key in _string_fields or value is None:
            continue
        coerced = _coerce_numeric(value)
        if coerced is None and value is not None:
            pass  # Tyst -- yfinance returnerar ofta "Infinity" eller liknande
        metrics[key] = coerced

    # ── Sanity-filter + enhetsnormalisering ──────────────────────────────
    # Rensar yfinance-skräp (negativ P/E, D/E i %, dividend_yield i % etc.)
    # som annars ger felaktiga rankingar. Körs SIST så att även FMP-fallback-
    # värden och market_cap-överskrivningen (shares x pris) ovan passerar
    # samma regler. Justeringar loggas i metrics["data_warnings"].
    metrics = _sanity_check(metrics)

    return metrics


# ── Statisk FX-tabell för market_cap-normalisering (approximate FX) ────
# Ungefärliga kurser mot USD. Används bara för att få jämförbara
# market_cap-storlekar i rankingen -- ingen nätverkshämtning (no FX-fetch).
_FX_TO_USD = {
    "EUR": 1.08,
    "GBP": 1.27,
    "SEK": 0.095,
    "NOK": 0.090,
    "DKK": 0.145,
    "INR": 0.012,
    "JPY": 0.0068,
    "KRW": 0.00073,
    "PLN": 0.25,
    "CHF": 1.04,
    "CAD": 0.73,
    "AUD": 0.65,
}


def _sanity_check(metrics: dict) -> dict:
    """
    Sanity-filter + enhetsnormalisering av yfinance-rådata.

    yfinance levererar ibland skräp som ger felaktiga rankingar: negativ P/E,
    negativ D/E, dividend_yield i % (2.19 istället för 0.0219), orimliga
    ratios etc. Varje nollat/justerat värde loggas i metrics["data_warnings"]
    (str-lista, tom lista om inget justerades).

    Regler:
    - pe_trailing/pe_forward: icke-finit eller <= 1 eller > 200 -> None
      (fångar negativa AAPL/NVDA-värden och APP:s 0.39)
    - dividend_yield: icke-finit -> None; > 1 -> /100 (yfinance ger % i denna
      miljö: 2.19 -> 0.0219); <= 1 antas redan vara fraktion och lämnas;
      negativt -> None
    - debt_to_equity: icke-finit -> None; < 0 -> 0.0 (clip, INTE None --
      bevara nettokassa-bolag); > 200 -> None
    - current_ratio: icke-finit -> None; < 0 -> 0.0; > 20 -> None
    - roa/roe/gross_margin/operating_margin/profit_margin: icke-finit -> None;
      |v| > 5 -> None
    - Financial Services / Real Estate / Insurance: gross_margin och
      current_ratio sätts till None (meningslösa för banker/försäkring;
      ROE + profit_margin behålls). Ingen ticker-suffix-heuristik.
    - market_cap: om currency != USD -> konvertera med statisk FX-tabell.
      Känd valuta utan tabellpost -> lämna oförändrad + varning.
      Valuta None/blank -> lämna oförändrad.
    """
    warnings = []

    def _finite(v) -> bool:
        """True om v är ett ändligt tal (inte None/NaN/Inf)."""
        try:
            return v is not None and np.isfinite(float(v))
        except (TypeError, ValueError):
            return False

    # 1. P/E-tal: fånga negativa AAPL/NVDA-värden och APP:s 0.39
    for key in ("pe_trailing", "pe_forward"):
        v = metrics.get(key)
        if not _finite(v):
            if v is not None:
                warnings.append(f"{key}: icke-finit -> None")
            metrics[key] = None
        elif v <= 1 or v > 200:
            warnings.append(f"{key}: {v} utanför giltigt intervall (1, 200] -> None")
            metrics[key] = None

    # 2. Dividend yield: beräkna fraktion från dividendRate/currentPrice (robust,
    #    ingen enhetsgissning — yfinance ger % för vissa, fraktion för andra).
    #    Fallback: dividendYield > 0.1 tolkas som % (0.73 = 0.73 %; en äkta
    #    fraktion 20-100 %-yield är orealistisk för alla seriösa aktier).
    rate = metrics.get("dividend_rate")
    price = metrics.get("current_price")
    v = metrics.get("dividend_yield")
    if _finite(rate) and rate is not None and price and price > 0:
        computed = rate / price
        metrics["dividend_yield"] = computed
        if v is not None and _finite(v) and abs(v / 100.0 - computed) > 0.001:
            warnings.append(
                f"dividend_yield: dividendRate({rate})/pris({price:.2f}) = {computed:.6f} "
                f"(yfinance-ytterligare {v} — rate-baserad vinner)"
            )
    elif not _finite(v):
        if v is not None:
            warnings.append("dividend_yield: icke-finit -> None")
        metrics["dividend_yield"] = None
    elif v < 0:
        warnings.append(f"dividend_yield: negativt ({v}) -> None")
        metrics["dividend_yield"] = None
    elif v > 0.1:
        warnings.append(f"dividend_yield: {v} tolkas som % -> /100 = {v / 100:.6f}")
        metrics["dividend_yield"] = v / 100.0
    # <= 0.1: redan fraktion, lämnas oförändrad

    # 3. Debt-to-equity
    v = metrics.get("debt_to_equity")
    if not _finite(v):
        if v is not None:
            warnings.append("debt_to_equity: icke-finit -> None")
        metrics["debt_to_equity"] = None
    elif v < 0:
        warnings.append(f"debt_to_equity: negativt ({v}) -> 0.0 (nettokassa-bolag)")
        metrics["debt_to_equity"] = 0.0
    elif v > 200:
        warnings.append(f"debt_to_equity: {v} > 200 -> None")
        metrics["debt_to_equity"] = None

    # 4. Current ratio
    v = metrics.get("current_ratio")
    if not _finite(v):
        if v is not None:
            warnings.append("current_ratio: icke-finit -> None")
        metrics["current_ratio"] = None
    elif v < 0:
        warnings.append(f"current_ratio: negativt ({v}) -> 0.0")
        metrics["current_ratio"] = 0.0
    elif v > 20:
        warnings.append(f"current_ratio: {v} > 20 -> None")
        metrics["current_ratio"] = None

    # 5. Marginaler/avkastning: |v| > 5 är orimligt (t.ex. 5.43 = 543 %)
    for key in ("roa", "roe", "gross_margin", "operating_margin", "profit_margin"):
        v = metrics.get(key)
        if not _finite(v):
            if v is not None:
                warnings.append(f"{key}: icke-finit -> None")
            metrics[key] = None
        elif abs(v) > 5:
            warnings.append(f"{key}: |{v}| > 5 -> None")
            metrics[key] = None

    # 6. Finanssektorn: gross_margin/current_ratio är meningslösa för banker
    sector = metrics.get("sector")
    if sector in ("Financial Services", "Real Estate", "Insurance"):
        if metrics.get("gross_margin") is not None:
            warnings.append(f"gross_margin: None för sektor {sector}")
            metrics["gross_margin"] = None
        if metrics.get("current_ratio") is not None:
            warnings.append(f"current_ratio: None för sektor {sector}")
            metrics["current_ratio"] = None

    # 7. market_cap: normalisera till USD med statisk FX-tabell
    cap = metrics.get("market_cap")
    currency = metrics.get("currency")
    if _finite(cap) and currency and str(currency).strip().upper() != "USD":
        fx = _FX_TO_USD.get(str(currency).strip().upper())
        if fx is not None:
            new_cap = float(cap) * fx
            warnings.append(f"market_cap: {currency} -> USD (x{fx}) {cap} -> {new_cap:.0f}")
            metrics["market_cap"] = new_cap
        else:
            warnings.append(
                f"market_cap: valuta {currency} saknas i FX-tabell, lämnas oförändrad"
            )

    metrics["data_warnings"] = warnings
    return metrics


def _coerce_numeric(value) -> float | None:
    """Tvinga ett varde till float. Returnerar None om det inte gar (Infinity, NaN, None)."""
    if value is None:
        return None
    try:
        result = pd.to_numeric(value, errors="coerce")
        if np.isinf(result) or pd.isna(result):
            return None
        return float(result)
    except Exception:
        return None


def _safe_return(series: pd.Series, days_back: int):
    """Calculate return over N trading days, return None if not enough data."""
    if len(series) <= days_back:
        return None
    try:
        return (series.iloc[-1] / series.iloc[-days_back - 1]) - 1.0
    except Exception:
        return None


def _calc_rsi(prices: pd.Series, period: int = 14):
    """Calculate Relative Strength Index.

    Returnerar 50 (neutralt) om både gain och loss är 0 (helt stilla pris),
    100 om bara förluster saknas (ren uppgång), 0 om bara gains saknas.
    """
    if len(prices) < period + 1:
        return None
    try:
        delta = prices.diff().dropna()
        gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
        if pd.isna(gain) or pd.isna(loss):
            return None
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except Exception:
        return None


def _safe_fin_val(df, label: str) -> float | None:
    """Safely extract a value from yfinance financials/BS/CF dataframe by index label.

    Returns None (never crashes) if label is missing, value is NaN/None,
    or any other error occurs.
    """
    try:
        if df is not None and label in df.index:
            val = df.loc[label].iloc[0]
            return float(val) if pd.notna(val) else None
    except Exception:
        return None
    return None


# ── Rate-limited semaphore för parallell yfinance ─────────────────────
# Med 8 workers och REQUEST_DELAY_SEC=0.3 blir total takt ~27 anrop/sek,
# vilket är högre än yahoos informella gräns (~10/sek). Semaphore delays
# säkerställer max (1/REQUEST_DELAY_SEC) anrop/sek *över alla workers*.
class _RateLimiter:
    """Sliding-window rate limiter för parallella anrop."""
    def __init__(self, calls_per_sec: float):
        self.min_interval = 1.0 / calls_per_sec if calls_per_sec > 0 else 0
        self._lock = threading.Lock()
        self._last_call = 0.0

    def acquire(self):
        """Block until it's safe to make the next call."""
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            since_last = now - self._last_call
            if since_last < self.min_interval:
                time.sleep(self.min_interval - since_last)
            self._last_call = time.monotonic()

# Yahoo brukar tolerera ~8-10 anrop/sek över längre perioder.
# Med 8 workers kör vi sammanlagt ~8 anrop/sek -> säkert.
_YAHOO_RATE_LIMITER = _RateLimiter(calls_per_sec=config.PARALLEL_WORKERS)

# Rate-limit detection state
_RATE_LIMIT_COUNTER = {
    "consecutive_failures":   0,
    "consecutive_429":        0,    # Räknare specifikt för 429-träffar i rad
    "global_pause_until":     0.0,  # Unix-tidsstämpel: alla workers pausar tills denna tid
    "last_rate_limit_time":   0.0,
}
_RATE_LIMIT_LOCK = threading.Lock()

# Threshold: hur många 429:or i rad innan alla workers tvångspausar
_RATE_LIMIT_CLUSTER_THRESHOLD = 5
# Hur länge pausen ska vara (Yahoo:s rate-limit-fönster är typiskt ~30-60s)
_RATE_LIMIT_PAUSE_SEC         = 30.0


def _record_rate_limit_hit():
    """Räkna en 429-träff. Trigga global paus om många kommer i klump."""
    now = time.time()
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
        _RATE_LIMIT_COUNTER["consecutive_429"] += 1
        _RATE_LIMIT_COUNTER["last_rate_limit_time"] = now
        if _RATE_LIMIT_COUNTER["consecutive_429"] >= _RATE_LIMIT_CLUSTER_THRESHOLD:
            # Kluster av 429 -> tvångspausa alla workers
            new_until = now + _RATE_LIMIT_PAUSE_SEC
            if new_until > _RATE_LIMIT_COUNTER["global_pause_until"]:
                _RATE_LIMIT_COUNTER["global_pause_until"] = new_until
                print(f"  ⏸  Rate-limit-kluster upptäckt ({_RATE_LIMIT_COUNTER['consecutive_429']} i rad) "
                      f"- alla workers pausar {_RATE_LIMIT_PAUSE_SEC:.0f}s")
            # Återställ räknaren så vi inte triggar paus om och om igen
            _RATE_LIMIT_COUNTER["consecutive_429"] = 0


def _record_success():
    """Återställ klustret-räknaren vid lyckat anrop."""
    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_COUNTER["consecutive_failures"] = 0
        _RATE_LIMIT_COUNTER["consecutive_429"] = 0


def _wait_if_globally_paused():
    """Om global paus är aktiv, vänta tills den är över."""
    while True:
        with _RATE_LIMIT_LOCK:
            until = _RATE_LIMIT_COUNTER["global_pause_until"]
        remaining = until - time.time()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 2.0))

def _is_rate_limited(failed_tickers_n: int, total_tickers: int) -> bool:
    """
    Detektera rate-limiting-mönster:
    1. >=3 tickers i rad misslyckas med TIMEOUT/ERROR -> trolig rate-limit
    2. >=30% av tickers hittills har misslyckats -> trolig rate-limit
    """
    with _RATE_LIMIT_LOCK:
        consecutive = _RATE_LIMIT_COUNTER["consecutive_failures"]
    if consecutive >= 3:
        return True
    # Om många av totalen har misslyckats, bromsa
    if total_tickers > 10 and (failed_tickers_n / total_tickers) > 0.30:
        return True
    return False


def _fetch_single_ticker(
    ticker: str,
    blacklist: set,
    verbose: bool,
) -> tuple:
    """
    Hämta alla data för en enskild ticker.
    Anropas från ThreadPoolExecutor.
    Returnerar (ticker, metrics_dict|None, status_str).
    """
    if ticker in blacklist:
        return (ticker, None, "SKIPPED")

    # Reset thread-local rate-limit flag before each ticker
    _reset_rate_limit_flag()

    try:
        # Vänta om global rate-limit-paus är aktiv (alla workers respekterar den)
        _wait_if_globally_paused()

        # Per-anrop-throttle (calls_per_sec) över hela poolen
        _YAHOO_RATE_LIMITER.acquire()

        info = fetch_stock_info(ticker)

        # Try FMP fallback if yfinance returned nothing useful
        if not info or len(info) < 10:
            fmp_data = fetch_fmp_fallback(ticker)
            if fmp_data:
                info = fmp_data

        history = fetch_price_history(ticker, period="1y")

        if not info and history.empty:
            # Check thread-local flags set by yfinance log handler
            if _rate_limit_was_hit():
                _record_rate_limit_hit()
                return (ticker, None, "RATE_LIMITED")
            if _delisted_was_hit():
                # Don't increment 429 counter for delisted - different problem
                return (ticker, None, "DELISTED")
            with _RATE_LIMIT_LOCK:
                _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
            return (ticker, None, "FAILED")

        # Success - reset all failure counters
        _record_success()
        metrics = extract_metrics(ticker, info, history)
        return (ticker, metrics, "OK")

    except _RateLimitError:
        _record_rate_limit_hit()
        return (ticker, None, "RATE_LIMITED")
    except _DelistedError:
        return (ticker, None, "DELISTED")
    except TimeoutError:
        with _RATE_LIMIT_LOCK:
            _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
        return (ticker, None, "TIMEOUT")
    except Exception as e:
        err_str = str(e)
        low = err_str.lower()
        if "429" in err_str or "too many requests" in low or "rate limit" in low:
            _record_rate_limit_hit()
            return (ticker, None, "RATE_LIMITED")
        if "404" in err_str or _is_delist_message(low):
            return (ticker, None, "DELISTED")
        with _RATE_LIMIT_LOCK:
            _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
        return (ticker, None, f"ERROR: {e}")

# ============================================================
# FINNHUB SENTIMENT (single-ticker) - batch version in data_fetcher_batch.py
# ============================================================

def _ticker_to_finnhub(ticker: str) -> str:
    """
    Convert yfinance ticker to Finnhub format.
    yfinance: VOLV-B.ST to Finnhub: VOLV-B (Finnhub uses exchange suffix differently)
    For US stocks they are the same. For others, Finnhub often just needs the base symbol.
    """
    base = ticker.split(".")[0]
    return base


def fetch_finnhub_sentiment(ticker: str) -> float | None:
    """
    Fetch news sentiment score for a ticker from Finnhub.
    Returns a score from -1.0 (very negative) to +1.0 (very positive),
    or None if Finnhub is not configured or request fails.
    """
    if not config.FINNHUB_API_KEY:
        return None

    finnhub_ticker = _ticker_to_finnhub(ticker)
    cache_key = f"finnhub_sentiment:{finnhub_ticker}"
    cached = _read_cache(cache_key, config.SENTIMENT_CACHE_HOURS)
    if cached is not None:
        return cached

    try:
        url = "https://finnhub.io/api/v1/news-sentiment"
        params = {"symbol": finnhub_ticker, "token": config.FINNHUB_API_KEY}
        resp = requests.get(url, params=params, timeout=8)

        if resp.status_code == 200:
            data = resp.json()
            sentiment = data.get("sentiment", {})
            bullish = sentiment.get("bullishPercent", 0.5)
            bearish = sentiment.get("bearishPercent", 0.5)
            score = bullish - bearish
            buzz = data.get("buzz", {})
            articles = buzz.get("articlesInLastWeek", 0)
            if articles < 3:
                score = score * 0.3
            _write_cache(cache_key, score)
            return score

    except Exception:
        pass  # Silently fail - sentiment is optional

    return None


# Re-exports for backwards compatibility.
# Batch/universe operations live in data_fetcher_batch.py.
# These re-exports ensure that "from core.data_fetcher import X" keeps working.
# IMPORTANT: Must be at the end of the file (after all single-ticker symbols
# are defined) to avoid circular import issues.
from core.data_fetcher_batch import (  # noqa: E402,F401
    fetch_universe_data,
    fetch_sentiment_batch,
    fetch_prices_only,
    update_scored_with_prices,
    fetch_benchmark_performance,
    search_stocks,
    fetch_prices_async,
)
