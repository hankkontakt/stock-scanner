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
import time
import pickle
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np
import requests

import config

_FX_CACHE = {}
# Ensure cache directory exists
Path(config.CACHE_DIR).mkdir(parents=True, exist_ok=True)


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
    Kör fn() i en separat tråd med tidsgräns.
    Kastar TimeoutError om den hänger (vanligt med yfinance .info på
    asiatiska/obscura tickers i version 1.3+).
    """
    import threading
    result = [None]
    error  = [None]

    def worker():
        try:
            result[0] = fn()
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_sec)

    if t.is_alive():
        raise TimeoutError(f"Anrop hängde efter {timeout_sec}s")
    if error[0] is not None:
        raise error[0]
    return result[0]


def _retry(fn, *args, timeout_sec=12, **kwargs):
    """Run a function with retry logic on failure, with per-attempt timeout."""
    last_err = None
    for attempt in range(config.MAX_RETRIES):
        try:
            return _with_timeout(fn, timeout_sec=timeout_sec)
        except TimeoutError as e:
            last_err = e
            # Timeout = direkt bail, ingen poäng att försöka igen snabbt
            time.sleep(1)
        except Exception as e:
            last_err = e
            if attempt < config.MAX_RETRIES - 1:
                wait = config.RETRY_BACKOFF_SEC * (attempt + 1)
                time.sleep(wait)
    raise last_err


def fetch_stock_info(ticker: str) -> dict:
    """
    Fetch fundamental info for a single stock.
    Returns a dict with all relevant fields, or empty dict on failure.
    """
    cache_key = f"info:{ticker}"
    cached = _read_cache(cache_key, config.CACHE_HOURS)
    if cached is not None:
        # Validera att priset inte är högre än 52v-high (indikerar korrupt cache)
        cp  = cached.get("currentPrice") or cached.get("regularMarketPrice") or 0
        h52 = cached.get("fiftyTwoWeekHigh") or 0
        if cp and h52 and float(cp) > float(h52) * 1.02:  # 2% marginal för intradag
            import os
            _cache_path(cache_key).unlink(missing_ok=True)  # rensa korrupt cache
        else:
            return cached

    try:
        time.sleep(config.REQUEST_DELAY_SEC)
        stock = yf.Ticker(ticker)
        info = _retry(lambda: stock.info)

        # yfinance sometimes returns very thin info dicts; check quality
        if not info or len(info) < 5:
            return {}

        _write_cache(cache_key, info)
        return info
    except Exception as e:
        print(f"  ⚠ Failed to fetch info for {ticker}: {e}")
        return {}


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
        stock = yf.Ticker(ticker)
        
        # 1. Aktivera auto_adjust=True för att inkludera utdelningar i priset
        hist = _retry(lambda: stock.history(period=period, auto_adjust=True))

        if hist.empty:
            return pd.DataFrame()

        # 2. Valutakonvertering till SEK om det inte är en svensk aktie
        if not ticker.endswith(".ST"):
            # Identifiera rätt valutapar FÖRST
            fx_map = {
                ".L": "GBPSEK=X", ".OL": "NOKSEK=X", ".CO": "DKKSEK=X",
                ".DE": "EURSEK=X", ".PA": "EURSEK=X", ".AS": "EURSEK=X",
                ".MI": "EURSEK=X", ".MC": "EURSEK=X", ".HE": "EURSEK=X"
            }
            
            # Bestäm vilken växelkurs vi behöver
            fx_ticker = "USDSEK=X" # Default
            for suffix, pair in fx_map.items():
                if ticker.endswith(suffix):
                    fx_ticker = pair
                    break
            
            # Hämta växelkursen (använd minnet/cachen om vi redan hämtat den denna körning)
            if fx_ticker not in _FX_CACHE:
                fx_stock = yf.Ticker(fx_ticker)
                # Vi hämtar samma period som aktien för att datumen ska matcha
                _FX_CACHE[fx_ticker] = fx_stock.history(period=period, auto_adjust=True)["Close"]
            
            fx_hist = _FX_CACHE[fx_ticker]
            
            # Synka datumen (hanterar helgdagar i olika länder)
            fx_aligned = fx_hist.reindex(hist.index).ffill().bfill()
            
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
        "market_cap": info.get("marketCap"),

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
        "dividend_yield": info.get("dividendYield"),
        "payout_ratio": info.get("payoutRatio"),

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

    # Add momentum/technical metrics from price history
    if not history.empty and len(history) > 20:
        close  = history["Close"]
        volume = history.get("Volume")
        current = close.iloc[-1]

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
    """Calculate Relative Strength Index."""
    if len(prices) < period + 1:
        return None
    try:
        delta = prices.diff().dropna()
        gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
        loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except Exception:
        return None


def fetch_universe_data(tickers: list, verbose: bool = True) -> pd.DataFrame:
    """
    Fetch metrics for all stocks in the universe.
    Returns a DataFrame with one row per ticker.
    """
    rows = []
    total = len(tickers)
    failed = []

    for i, ticker in enumerate(tickers, 1):
        if verbose:
            print(f"  [{i}/{total}] {ticker}...", end=" ", flush=True)

        info = fetch_stock_info(ticker)

        # Try FMP fallback if yfinance returned nothing useful
        if not info or len(info) < 10:
            fmp_data = fetch_fmp_fallback(ticker)
            if fmp_data:
                info = fmp_data

        history = fetch_price_history(ticker, period="1y")

        if not info and history.empty:
            failed.append(ticker)
            if verbose:
                print("FAILED")
            continue

        metrics = extract_metrics(ticker, info, history)
        rows.append(metrics)

        if verbose:
            quality = sum(1 for v in metrics.values() if v is not None) / len(metrics)
            print(f"OK ({quality:.0%} data)")

    df = pd.DataFrame(rows)

    if failed and verbose:
        print(f"\n  ⚠ Failed to fetch {len(failed)} tickers: {', '.join(failed[:5])}{'...' if len(failed) > 5 else ''}")

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
    Fetch sentiment scores for all tickers.
    Returns dict: {ticker: score} where score is -1 to +1 or None.
    """
    if not config.FINNHUB_API_KEY:
        if verbose:
            print("  ℹ Finnhub API key not set – skipping sentiment (alla får neutral score)")
        return {}

    if verbose:
        print(f"  Fetching Finnhub sentiment for {len(tickers)} tickers...")

    results = {}
    for i, ticker in enumerate(tickers):
        score = fetch_finnhub_sentiment(ticker)
        results[ticker] = score
        # Finnhub free tier: 60 calls/min → ~1 call/sec is safe
        time.sleep(1.1)

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
