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

import os
import sys
import time
import json
import socket
import pickle
import hashlib
import threading
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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
# yfinance gör utan att ange timeout själv.
_original_session_send = requests.sessions.Session.send

def _timeout_session_send(self, request, **kwargs):
    if kwargs.get("timeout") is None:
        # (3 sekunder connect, 5 sekunder read)
        kwargs["timeout"] = (3, 5)
    return _original_session_send(self, request, **kwargs)

requests.sessions.Session.send = _timeout_session_send

# ── curl_cffi timeout-patch ──────────────────────────────────────────────
# yfinance 0.2.37+ använder curl_cffi som HTTP-backend. Den kringgår
# socket.setdefaulttimeout() och requests.Session-patchen ovan.
# Patch: sätt hård (connect=10s, read=20s) timeout på alla curl_cffi-anrop.
try:
    import curl_cffi.requests as _cf_req
    _original_cf_request = _cf_req.Session.request
    def _patched_cf_request(self, method, url, *args, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (10, 20)
        return _original_cf_request(self, method, url, *args, **kwargs)
    _cf_req.Session.request = _patched_cf_request
except Exception:
    pass  # curl_cffi saknas – inget att patcha

_FX_CACHE = {}
Path(config.CACHE_DIR).mkdir(parents=True, exist_ok=True)

# Fundamentala fält som bara ändras vid kvartalsrapporter → 30 dagars cache
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


def _with_timeout(fn, timeout_sec=12):
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


def _retry(fn, *args, timeout_sec=12, **kwargs):
    """
    Kör fn() med retry-logik. TimeoutError = direkt fail, ingen retry.

    TimeoutError = ticker hänger i C-kod. Retry ger exakt samma timeout
    och dubblerar dödtiden. En attempt räcker för att konstatera att
    tickern inte svarar.

    Retry sker bara vid nätverksfel (ConnectionError, HTTPError etc.)
    som faktiskt kan lyckas vid nästa försök.
    """
    for attempt in range(config.MAX_RETRIES):
        try:
            return _with_timeout(fn, timeout_sec=timeout_sec)
        except TimeoutError:
            raise   # Direkt vidare – ingen retry, ingen sleep
        except Exception as e:
            if attempt < config.MAX_RETRIES - 1:
                wait = config.RETRY_BACKOFF_SEC * (attempt + 1)
                time.sleep(wait)
                continue
            raise


def fetch_stock_info(ticker: str) -> dict:
    """
    Fetch fundamental info for a single stock.

    Tvådelad cache:
      info_static:{ticker}  – CACHE_HOURS (720h/30 dagar)
        Fält som bara ändras vid kvartalsrapporter: marginaler, tillväxt,
        skuldsättning, ägande, bolagsnamn/sektor.

      info_dynamic:{ticker} – DYNAMIC_CACHE_HOURS (170h/7 dagar)
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

    except Exception as e:
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
                    _FX_CACHE[fx_ticker] = raw if raw is not None else pd.Series(dtype=float)
                except Exception:
                    _FX_CACHE[fx_ticker] = pd.Series(dtype=float)  # Hoppa över FX vid fel
            
            fx_hist = _FX_CACHE[fx_ticker]
            
            # Synka datumen (hanterar helgdagar i olika länder).
            # Begränsa ffill till 5 dagar så vi inte propagerar en månadsgammal
            # FX-kurs över långa luckor (kan ge 100-1000x felaktiga SEK-priser).
            fx_aligned = fx_hist.reindex(hist.index).ffill(limit=5).bfill(limit=5)

            # Sanity check: orealistiska dag-till-dag-hopp tyder på datafel.
            if not fx_aligned.empty:
                _ratio = (fx_aligned / fx_aligned.shift(1)).abs()
                if (_ratio > 1.5).any() or (_ratio < 0.67).any():
                    print(f"  ⚠ Misstänkt FX-hopp för {ticker} ({fx_ticker}) – hoppar konvertering")
                    fx_aligned = pd.Series([1.0] * len(hist), index=hist.index)

            # Multiplicera alla priskolumner med växelkursen
            for col in ["Open", "High", "Low", "Close"]:
                if col in hist.columns:
                    hist[col] = hist[col] * fx_aligned

        _write_cache(cache_key, hist)
        return hist

    except Exception as e:
        print(f"  ⚠ Failed to fetch prices for {ticker}: {e}")
        return pd.DataFrame()

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

        # NEW: Earnings surprise (hur ofta slår bolaget estimat)
        "earnings_surprise_pct": info.get("earningsForecastsGrowthRate"),

        # NEW: Omsättning och volym
        "avg_volume":       info.get("averageVolume"),
        "avg_volume_10d":   info.get("averageVolume10days"),
        "volume_ratio":     None,  # Beräknas nedan från prishistorik
    }

    # Prishistorik är alltid färsk (PRICE_CACHE_HOURS=24h) – använd den för
    # marknadskänsliga värden som annars kan vara 7 dagar gamla i info-cachen.
    if not history.empty and len(history) > 20:
        close  = history["Close"]
        volume = history.get("Volume")
        current = float(close.iloc[-1])

        # Aktuellt pris – alltid från färsk prishistorik
        metrics["current_price"] = current

        # 52-veckors high/low – beräkna från prishistorik (max 252 börsdagar)
        tail = close.tail(252)
        high_series = history["High"].tail(252) if "High" in history.columns else tail
        low_series  = history["Low"].tail(252)  if "Low"  in history.columns else tail
        metrics["52_week_high"] = float(high_series.max())
        metrics["52_week_low"]  = float(low_series.min())

        # Marknadsvärde: antal aktier (kvartalsdata, OK att cacha) × färskt pris
        shares = info.get("sharesOutstanding")
        if shares and shares > 0:
            metrics["market_cap"] = float(shares) * current

        # Returns over different periods
        metrics["return_1m"]  = _safe_return(close, 21)
        metrics["return_3m"]  = _safe_return(close, 63)
        metrics["return_6m"]  = _safe_return(close, 126)
        metrics["return_12m"] = _safe_return(close, 252)

        # Distance from 52-week high (negative is below)
        if metrics["52_week_high"]:
            metrics["pct_from_52w_high"] = (current / metrics["52_week_high"]) - 1.0

        # Volatility (annualized)
        returns = close.pct_change().dropna()
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

    return metrics


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
# Med 8 workers kör vi sammanlagt ~8 anrop/sek → säkert.
_YAHOO_RATE_LIMITER = _RateLimiter(calls_per_sec=config.PARALLEL_WORKERS)

# Rate-limit detection state
_RATE_LIMIT_COUNTER = {"consecutive_failures": 0, "last_rate_limit_time": 0.0}
_RATE_LIMIT_LOCK = threading.Lock()

def _is_rate_limited(failed_tickers_n: int, total_tickers: int) -> bool:
    """
    Detektera rate-limiting-mönster:
    1. ≥3 tickers i rad misslyckas med TIMEOUT/ERROR → trolig rate-limit
    2. ≥30% av tickers hittills har misslyckats → trolig rate-limit
    """
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

    try:
        # Rate-limit före varje tickers anrop totalt (info + history)
        _YAHOO_RATE_LIMITER.acquire()

        # Rate-limit detection: om ≥3 tickers i rad har misslyckats,
        # lägg på extra fördröjning för att ge Yahoo API tid att återhämta sig
        with _RATE_LIMIT_LOCK:
            if _RATE_LIMIT_COUNTER["consecutive_failures"] >= 3:
                time.sleep(5.0)

        info = fetch_stock_info(ticker)

        # Try FMP fallback if yfinance returned nothing useful
        if not info or len(info) < 10:
            fmp_data = fetch_fmp_fallback(ticker)
            if fmp_data:
                info = fmp_data

        history = fetch_price_history(ticker, period="1y")

        if not info and history.empty:
            with _RATE_LIMIT_LOCK:
                _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
            return (ticker, None, "FAILED")

        # Success – reset consecutive failure counter
        with _RATE_LIMIT_LOCK:
            _RATE_LIMIT_COUNTER["consecutive_failures"] = 0
        metrics = extract_metrics(ticker, info, history)
        return (ticker, metrics, "OK")

    except TimeoutError:
        with _RATE_LIMIT_LOCK:
            _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
        return (ticker, None, "TIMEOUT")
    except Exception as e:
        with _RATE_LIMIT_LOCK:
            _RATE_LIMIT_COUNTER["consecutive_failures"] += 1
        return (ticker, None, f"ERROR: {e}")


def fetch_universe_data(tickers: list, verbose: bool = True) -> pd.DataFrame:
    """
    Fetch metrics for all stocks in the universe using a ThreadPoolExecutor
    for parallel yfinance calls.

    Med 8 workers och PRICE_CACHE_HOURS=24h-cache blir ~700 tickers klara
    på 2-3 minuter (i stället för 9-10 min sekventiellt).
    Returns a DataFrame with one row per ticker.
    """
    total = len(tickers)

    # Ladda blacklist – skippa kända trasiga tickers
    _bl_path = Path("data/blacklist.json")
    try:
        _blacklist = set(json.loads(_bl_path.read_text()).keys()) if _bl_path.exists() else set()
    except Exception:
        _blacklist = set()

    if verbose:
        print(f"  ⚙  {config.PARALLEL_WORKERS} parallella workers · {total} tickers")

    rows = []
    failed = []
    completed = 0

    # Skicka alla tickers till poolen
    with ThreadPoolExecutor(max_workers=config.PARALLEL_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_single_ticker, t, _blacklist, verbose): t
            for t in tickers
        }

        for future in as_completed(futures):
            ticker, metrics, status = future.result()
            completed += 1

            if verbose:
                # Kompakt utskrift: "✓ AAPL OK" eller "✗ XYZ TIMEOUT"
                icon = "✓" if metrics is not None else "✗"
                print(f"  [{completed}/{total}] {icon} {ticker} {status}")

            if metrics is not None:
                rows.append(metrics)
            else:
                failed.append(ticker)

    df = pd.DataFrame(rows)

    if failed and verbose:
        n = len(failed)
        print(f"  ⚠ {n} tickers misslyckades: "
              f"{', '.join(failed[:10])}{'...' if n > 10 else ''}")
        if n > 15:
            print(f"  💡 Tips: Kör filters.clear_blacklist() om välkända aktier är med i listan")
        print(f"  ✓ {len(df)}/{total} aktier hämtade")

    return df



# ============================================================
# FINNHUB SENTIMENT
# ============================================================

def _ticker_to_finnhub(ticker: str) -> str:
    """
    Convert yfinance ticker to Finnhub format.
    yfinance: VOLV-B.ST  →  Finnhub: VOLV-B (Finnhub uses exchange suffix differently)
    For US stocks they're the same. For others, Finnhub often just needs the base symbol.
    """
    # Remove exchange suffix (.ST, .DE, .L, .PA, .AS, .SW)
    base = ticker.split(".")[0]
    return base


def fetch_finnhub_sentiment(ticker: str) -> float | None:
    """
    Fetch news sentiment score for a ticker from Finnhub.
    Returns a score from -1.0 (very negative) to +1.0 (very positive),
    or None if Finnhub is not configured or request fails.

    Finnhub's /news-sentiment endpoint returns:
      - buzz.articlesInLastWeek: article count
      - sentiment.bearishPercent / bullishPercent
      - companyNewsScore: 0-1 overall score
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

            # Extract bearish/bullish percentages
            sentiment = data.get("sentiment", {})
            bullish = sentiment.get("bullishPercent", 0.5)
            bearish = sentiment.get("bearishPercent", 0.5)

            # Convert to -1 to +1 scale
            # bullish=0.7, bearish=0.3 → score = 0.4 (positive)
            score = bullish - bearish

            # Dampen: if very few articles, move toward neutral
            buzz = data.get("buzz", {})
            articles = buzz.get("articlesInLastWeek", 0)
            if articles < 3:
                score = score * 0.3  # Low confidence → near-neutral

            _write_cache(cache_key, score)
            return score

    except Exception as e:
        pass  # Silently fail – sentiment is optional

    return None


def fetch_sentiment_batch(tickers: list, verbose: bool = True) -> dict:
    """
    Fetch sentiment scores for all tickers using parallel Finnhub calls.

    Gratis Finnhub: 60 calls/min → 50 calls/min med headroom.
    Med 3 parallella workers och tokens-per-interval-rate-limiter håller vi oss
    inom gränsen: requests sprids jämnt över 60-sekundersfönster.
    """
    if not config.FINNHUB_API_KEY:
        if verbose:
            print("  ℹ Finnhub API key not set – skipping sentiment (alla får neutral score)")
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
        import yfinance as yf
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
    except Exception as e:
        return []


# ══════════════════════════════════════════════════════════════
# PRICE-ONLY FETCH – snabb hämtning av ENDAST priser (ingen fundamental data)
# Används för daglig re-scoring i daily_pipeline.py
# ══════════════════════════════════════════════════════════════

def fetch_prices_only(tickers: list, period: str = "6mo",
                      max_workers: int = 12, timeout: int = 30) -> dict:
    """
    Hämta ENDAST priser för en lista med tickers – INGEN fundamental data.
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
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import yfinance as yf

    def _fetch(ticker: str) -> tuple[str, dict | None]:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, auto_adjust=True, timeout=timeout)
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
            daily_returns = close.pct_change().dropna()
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

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, t): t for t in tickers}
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

        # Uppdatera prisberoende kolumner
        for col, val in prices.items():
            if col in df.columns:
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
# BENCHMARK DATA (OMXS30 + SPY) – ersätter daily_scan.fetch_benchmark_performance()
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
