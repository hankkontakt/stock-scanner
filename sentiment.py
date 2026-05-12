"""
sentiment.py
============
Hämtar nyhetsentiment från Finnhub API.
Returnerar ett score 0-100 (50 = neutralt) per aktie.

Gratis Finnhub-nivå: 60 anrop/minut – räcker gott för veckoscanning.
Registrera gratis API-nyckel på: https://finnhub.io
"""

import time
import requests
from pathlib import Path
import pickle
from datetime import datetime, timedelta

CACHE_DIR = "data/cache"
SENTIMENT_CACHE_HOURS = 12  # Nyheter kan cachas kortare än fundamenta


def _cache_path(key: str) -> Path:
    import hashlib
    safe = hashlib.md5(key.encode()).hexdigest()
    return Path(CACHE_DIR) / f"sent_{safe}.pkl"


def _read_cache(key: str):
    p = _cache_path(key)
    if not p.exists():
        return None
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    if age > timedelta(hours=SENTIMENT_CACHE_HOURS):
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _write_cache(key: str, data):
    try:
        with open(_cache_path(key), "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _clean_ticker_for_finnhub(ticker: str) -> str:
    """
    Finnhub använder US-tickers direkt (AAPL).
    För svenska aktier (.ST) och europeiska – ofta ej täckta på gratisnivå.
    Vi försöker ändå och returnerar neutral om det misslyckas.
    """
    # Ta bort exchange-suffix för icke-US marknader
    if "." in ticker:
        base = ticker.split(".")[0]
        # Finnhub täcker inte .ST/.DE/.PA bra på gratis-tier
        # men vi försöker med bas-tickern
        return base
    return ticker


def fetch_news_sentiment(ticker: str, api_key: str, delay: float = 0.3) -> float:
    """
    Hämtar Finnhub news-sentiment för en aktie.
    Returnerar ett värde 0.0–1.0 (0.5 = neutralt).
    Returnerar 0.5 om aktien inte hittas eller API-nyckel saknas.
    """
    if not api_key:
        return 0.5

    cache_key = f"finnhub_sent:{ticker}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    clean = _clean_ticker_for_finnhub(ticker)

    try:
        time.sleep(delay)
        url = "https://finnhub.io/api/v1/news-sentiment"
        resp = requests.get(url, params={"symbol": clean, "token": api_key}, timeout=8)

        if resp.status_code == 429:
            print(f"  ⚠ Finnhub rate limit – väntar 60s...")
            time.sleep(60)
            resp = requests.get(url, params={"symbol": clean, "token": api_key}, timeout=8)

        if resp.status_code != 200:
            _write_cache(cache_key, 0.5)
            return 0.5

        data = resp.json()

        # Kombinera bullish % och company news score
        sentiment = data.get("sentiment", {})
        bullish = sentiment.get("bullishPercent", 0.5)
        news_score = data.get("companyNewsScore", 0.5)

        # Viktad kombination: 60% bullish%, 40% news score
        combined = 0.6 * bullish + 0.4 * news_score

        _write_cache(cache_key, combined)
        return combined

    except Exception:
        _write_cache(cache_key, 0.5)
        return 0.5


def fetch_sentiment_batch(tickers: list, api_key: str, verbose: bool = True) -> dict:
    """
    Hämtar sentiment för en lista aktier.
    Returnerar dict: {ticker: score (0-1)}
    """
    if not api_key:
        if verbose:
            print("  ℹ Finnhub API-nyckel saknas – sentiment sätts till neutralt (50)")
        return {t: 0.5 for t in tickers}

    results = {}
    for i, ticker in enumerate(tickers, 1):
        score = fetch_news_sentiment(ticker, api_key)
        results[ticker] = score
        if verbose and i % 10 == 0:
            print(f"  Sentiment: {i}/{len(tickers)}")

    return results
