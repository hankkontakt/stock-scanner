"""
news_sentiment.py — Nyhetsbaserade sentimentsignaler för universe discovery
===========================================================================
Tre separata funktioner:

  score_news_sentiment()   — Aggregerar nyhetssentiment per ticker (FinBERT eller VADER)
  fetch_nordic_rss()       — Nasdaq Nordic officiell RSS (bolagsnamn → ticker-mappning)
  fetch_earnings_surprise() — Finnhub earnings calendar (PEAD-signal)
  fetch_analyst_upgrades() — Finnhub upgrade/downgrade (institutionell signal)

Alla nätverksanrop cachas och är skyddade mot timeout/fel.

Mjuka dependencies:
  - transformers: pip install transformers (FinBERT)
  - vaderSentiment: pip install vaderSentiment (fallback)
  - reticker: pip install reticker (bättre ticker-extrahering)
Om de saknas degraderas funktionaliteten graciöst.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ROOT      = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_SENTIMENT_CACHE_TTL = 3600 * 3   # 3h
_NORDIC_RSS_TTL      = 3600 * 1   # 1h (real-time nyheter)
_EARNINGS_TTL        = 3600 * 6   # 6h
_UPGRADES_TTL        = 3600 * 6   # 6h


# ── Cache-helpers ────────────────────────────────────────────────────────────

def _cache_read(name: str, ttl: int) -> Optional[dict]:
    p = CACHE_DIR / f"news_{name}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) < ttl:
            return data.get("payload")
    except Exception:
        pass
    return None


def _cache_write(name: str, payload) -> None:
    try:
        (CACHE_DIR / f"news_{name}.json").write_text(
            json.dumps({"ts": time.time(), "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── Ticker-extrahering ────────────────────────────────────────────────────────

def _extract_tickers(text: str) -> list[str]:
    """
    Extraherar ticker-symboler ur fritext.
    Använder `reticker` om tillgängligt, annars regex-fallback.
    """
    try:
        import reticker  # type: ignore[import]
        result = reticker.TickerExtractor().extract(text)
        return list(set(result)) if result else []
    except ImportError:
        pass

    # Regex-fallback: 1-5 versaler, ev. med börs-suffix
    _FALSE_POS = {
        "A", "I", "IT", "IS", "THE", "AND", "OR", "BUT", "FOR", "FROM",
        "AT", "TO", "IN", "ON", "BY", "US", "BE", "AS", "AN", "WITH",
        "NOT", "NO", "SO", "IF", "DO", "ALL", "NEW", "CAN", "AM", "PM",
        "CEO", "CFO", "COO", "IPO", "ETF", "AI", "ML", "EPS", "PE",
        "USD", "EUR", "SEK", "NOK", "DKK", "GBP", "JPY",
        "NYSE", "NASDAQ", "SEC", "FED", "ECB",
        "Q1", "Q2", "Q3", "Q4", "FY", "H1", "H2",
        "USA", "UK", "EU", "UN", "WHO",
    }
    pattern = re.compile(r"\b([A-Z]{2,5})(?:\.[A-Z]{1,2})?\b")
    found = pattern.findall(text.upper())
    return [t for t in set(found) if t not in _FALSE_POS and len(t) >= 2]


# ══════════════════════════════════════════════════════════════════════════════
# FUNKTION 1 — NEWS SENTIMENT SCORING
# ══════════════════════════════════════════════════════════════════════════════

# Lazy-loaded sentiment model
_finbert_pipeline = None
_vader_analyzer   = None


def _get_finbert():
    global _finbert_pipeline
    if _finbert_pipeline is not None:
        return _finbert_pipeline
    try:
        from transformers import pipeline as tf_pipeline  # type: ignore[import]
        _finbert_pipeline = tf_pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            max_length=512,
            truncation=True,
        )
        logger.info("  FinBERT laddat (ProsusAI/finbert)")
        return _finbert_pipeline
    except Exception as e:
        logger.debug(f"  FinBERT kunde inte laddas: {e}")
        return None


def _get_vader():
    global _vader_analyzer
    if _vader_analyzer is not None:
        return _vader_analyzer
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore[import]
        _vader_analyzer = SentimentIntensityAnalyzer()
        return _vader_analyzer
    except ImportError:
        return None


def _sentiment_score(text: str) -> float:
    """
    Returnerar sentimentscore (-1.0 till +1.0) för en textsträng.
    Försöker FinBERT → VADER → enkelt lexikon-fallback.
    """
    if not text or len(text.strip()) < 5:
        return 0.0

    # FinBERT (bäst)
    pipe = _get_finbert()
    if pipe is not None:
        try:
            res = pipe(text[:512])
            label = res[0]["label"].lower()
            score = res[0]["score"]
            if "positive" in label:
                return score
            elif "negative" in label:
                return -score
            return 0.0
        except Exception:
            pass

    # VADER (fallback)
    vader = _get_vader()
    if vader is not None:
        try:
            scores = vader.polarity_scores(text)
            return scores["compound"]  # -1 till +1
        except Exception:
            pass

    # Enkelt lexikon-fallback
    pos = {"gain", "rise", "surge", "strong", "beat", "growth", "profit",
           "record", "buyback", "upgrade", "positive", "bullish",
           "ökar", "stiger", "rekord", "tillväxt", "vinst"}
    neg = {"fall", "drop", "loss", "miss", "weak", "sell", "downgrade",
           "negative", "bearish", "cut", "decline", "risk",
           "faller", "minskar", "förlust", "svag", "sälj"}
    words = set(text.lower().split())
    p_count = len(pos & words)
    n_count = len(neg & words)
    if p_count + n_count == 0:
        return 0.0
    return (p_count - n_count) / (p_count + n_count)


def score_news_sentiment(
    ticker: str,
    news_articles: list[dict],
) -> dict:
    """
    Aggregerar sentimentscorer för en lista nyhetsartiklar kopplade till en ticker.

    Args:
        ticker:        Tickersymbol (för loggning)
        news_articles: Lista av dikt med "title" och/eller "summary" fält

    Returns:
        {
            "ticker":        str,
            "article_count": int,
            "avg_sentiment": float,   # -1.0 till +1.0
            "pos_count":     int,
            "neg_count":     int,
            "news_signal":   float,   # article_count × max(avg_sentiment, 0)
            "boost":         float,   # confidence-boost (0.0–0.15)
        }
    """
    if not news_articles:
        return {
            "ticker": ticker, "article_count": 0,
            "avg_sentiment": 0.0, "pos_count": 0, "neg_count": 0,
            "news_signal": 0.0, "boost": 0.0,
        }

    scores = []
    for art in news_articles:
        text = " ".join(filter(None, [art.get("title", ""), art.get("summary", "")]))
        s = _sentiment_score(text)
        scores.append(s)

    avg = sum(scores) / len(scores)
    pos = sum(1 for s in scores if s > 0.1)
    neg = sum(1 for s in scores if s < -0.1)
    signal = len(scores) * max(avg, 0.0)

    # Confidence-boost: positiv signal > 1.5 → +0.10
    boost = 0.0
    if signal > 3.0:
        boost = 0.15
    elif signal > 1.5:
        boost = 0.10
    elif signal > 0.5:
        boost = 0.05

    return {
        "ticker":        ticker,
        "article_count": len(scores),
        "avg_sentiment": round(avg, 3),
        "pos_count":     pos,
        "neg_count":     neg,
        "news_signal":   round(signal, 2),
        "boost":         boost,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUNKTION 2 — NASDAQ NORDIC RSS (officiell)
# ══════════════════════════════════════════════════════════════════════════════

# Nasdaq Nordic officiella RSS-feeds
_NORDIC_RSS_FEEDS = [
    ("Nasdaq Nordic Press Releases",
     "https://subscribe.news.eu.nasdaq.com/rss?category=pressrelease&markets=XSTO,XHEL,XCSE,XICE,FNSE"),
    ("Nasdaq Nordic Company Announcements",
     "https://subscribe.news.eu.nasdaq.com/rss?category=announcement&markets=XSTO,XHEL,XCSE,XICE,FNSE"),
]

# Kompletterande nordiska nyhetsflöden
_SUPPLEMENTARY_NORDIC = [
    ("Cision Nasdaq Nordic",    "https://news.cision.com/nasdaq-omx-nordic/rss"),
    ("Realtid",                 "https://www.realtid.se/rss.xml"),
    ("Affärsvärlden",           "https://www.affarsvarlden.se/rss.xml"),
    ("DI",                      "https://digital.di.se/rss"),
]

# Mapp: bolagsnamn (lowercase, stripped) → ticker
# Byggs upp löpande och cachas
_NAME_TICKER_MAP: dict[str, str] = {}


def _resolve_nordic_ticker(company_name: str, universe_tickers: Optional[set] = None) -> Optional[str]:
    """
    Försöker matcha ett bolagsnamn till en ticker.
    Metoder (i ordning): intern cache → universe-sökning → yfinance-search.
    """
    key = company_name.lower().strip()[:50]
    if key in _NAME_TICKER_MAP:
        return _NAME_TICKER_MAP[key]

    # Sök i befintligt universum
    if universe_tickers:
        name_words = set(key.split())
        for t in universe_tickers:
            if any(w in t.lower() for w in name_words if len(w) > 3):
                _NAME_TICKER_MAP[key] = t
                return t

    # yfinance-sökning (sista utväg, kostsam)
    try:
        import yfinance as yf
        results = yf.Search(company_name, max_results=3).quotes
        for r in results:
            sym = r.get("symbol", "")
            exch = r.get("exchange", "")
            if exch in ("STO", "HEL", "CPH", "ICE", "FNS", "FNSE", "NGM"):
                if not sym.endswith(".ST"):
                    sym = sym + ".ST"
                _NAME_TICKER_MAP[key] = sym
                return sym
    except Exception:
        pass

    return None


def fetch_nordic_rss(
    universe_tickers: Optional[set] = None,
    force: bool = False,
) -> list[dict]:
    """
    Hämtar Nasdaq Nordic officiella RSS-feeds och extraherar nya ticker-kandidater.

    Returnerar lista av discovery-kandidater:
    [{"ticker": "VOLVO-B.ST", "source": "nordic_rss",
      "reason": "...", "confidence": 0.60, "region": "NORDIC"}, ...]
    """
    cached = _cache_read("nordic_rss", _NORDIC_RSS_TTL)
    if cached is not None and not force:
        return cached

    import xml.etree.ElementTree as ET

    ticker_news: dict[str, list[str]] = {}  # ticker → [headlines]

    all_feeds = _NORDIC_RSS_FEEDS + _SUPPLEMENTARY_NORDIC

    for feed_name, url in all_feeds:
        try:
            r = requests.get(url, timeout=8,
                             headers={"User-Agent": "MarketScan/1.0 (research)"})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            items = root.findall(".//item") or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )

            for item in items[:40]:
                title_el = item.find("title") or item.find(
                    "{http://www.w3.org/2005/Atom}title"
                )
                title = (title_el.text or "") if title_el is not None else ""

                # Nasdaq Nordic-format: "BOLAGET AB: Delårsrapport Q1 2026"
                company_name = title.split(":")[0].strip() if ":" in title else title[:40]

                # Försök slå upp ticker
                ticker = _resolve_nordic_ticker(company_name, universe_tickers)
                if ticker:
                    if ticker not in ticker_news:
                        ticker_news[ticker] = []
                    ticker_news[ticker].append(title[:80])
                else:
                    # Extrahera tickers direkt ur titeln
                    for t in _extract_tickers(title):
                        if not any(t.endswith(s) for s in
                                   (".ST", ".CO", ".OL", ".HE", ".L", ".DE")):
                            continue
                        if t not in ticker_news:
                            ticker_news[t] = []
                        ticker_news[t].append(title[:80])

            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"  Nordic RSS {feed_name} fel: {e}")

    # Bygg kandidater
    candidates = []
    for ticker, headlines in ticker_news.items():
        n = len(headlines)
        reason = f"Nämns i {n} nordiska nyheter/pressreleaser: {headlines[0][:80]}"
        conf = min(0.45 + 0.05 * n, 0.70)
        candidates.append({
            "ticker":     ticker,
            "source":     "nordic_rss",
            "reason":     reason,
            "confidence": round(conf, 2),
            "region":     "NORDIC",
            "discovered": date.today().isoformat(),
            "metadata":   {"mention_count": n, "headlines": headlines[:3]},
        })

    _cache_write("nordic_rss", candidates)
    logger.info(f"  Nordic RSS: {len(candidates)} kandidater")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# FUNKTION 3 — EARNINGS SURPRISE (Finnhub PEAD-signal)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_earnings_surprise(
    min_surprise_pct: float = 5.0,
    days_back: int = 14,
    existing_universe: Optional[set] = None,
    force: bool = False,
) -> list[dict]:
    """
    Hämtar positiva EPS-överraskningar från Finnhub och returnerar
    tickers som INTE redan finns i universum — PEAD-baserade kandidater.

    Args:
        min_surprise_pct: Minsta EPS-överraskning (%) för att inkludera
        days_back:        Hur långt tillbaka vi letar (PEAD-fönster)
        existing_universe: Set av befintliga tickers
        force:            Kringgå cache

    Returns:
        Lista av discovery-kandidater
    """
    cached = _cache_read("earnings_surprise", _EARNINGS_TTL)
    if cached is not None and not force:
        return cached

    finnhub_key = os.getenv("FINNHUB_API_KEY", "")
    if not finnhub_key:
        logger.debug("  Ingen FINNHUB_API_KEY — hoppar earnings surprise")
        return []

    from_date = (date.today() - timedelta(days=days_back)).isoformat()
    to_date   = date.today().isoformat()

    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": from_date, "to": to_date, "token": finnhub_key},
            timeout=10,
        )
        if r.status_code != 200:
            logger.debug(f"  Finnhub earnings HTTP {r.status_code}")
            return []

        earnings = r.json().get("earningsCalendar", [])
    except Exception as e:
        logger.debug(f"  Finnhub earnings fel: {e}")
        return []

    candidates = []
    existing   = existing_universe or set()

    for e in earnings:
        ticker = str(e.get("symbol", "")).upper()
        if not ticker or ticker in existing:
            continue

        eps_actual   = e.get("epsActual")
        eps_estimate = e.get("epsEstimate")

        if eps_actual is None or eps_estimate is None:
            continue

        # Beräkna surprise %
        try:
            eps_a = float(eps_actual)
            eps_e = float(eps_estimate)
            if eps_e == 0:
                continue
            surprise_pct = ((eps_a - eps_e) / abs(eps_e)) * 100
        except (ValueError, TypeError):
            continue

        if surprise_pct < min_surprise_pct:
            continue

        report_date = e.get("date", "")
        revenue     = e.get("revenueActual")
        rev_est     = e.get("revenueEstimate")

        reason = (
            f"EPS-surprise +{surprise_pct:.1f}% ({report_date}): "
            f"EPS={eps_a:.2f} vs. estimat={eps_e:.2f}"
        )
        if revenue and rev_est:
            try:
                rev_surp = ((float(revenue) - float(rev_est)) / abs(float(rev_est))) * 100
                reason += f" | Revenue +{rev_surp:.1f}%"
            except Exception:
                pass

        conf = min(0.50 + min(surprise_pct, 30) / 100, 0.80)
        candidates.append({
            "ticker":     ticker,
            "source":     "earnings_surprise",
            "reason":     reason,
            "confidence": round(conf, 2),
            "region":     "US",
            "discovered": date.today().isoformat(),
            "metadata":   {
                "eps_surprise_pct": round(surprise_pct, 1),
                "eps_actual":       eps_a,
                "eps_estimate":     eps_e,
                "report_date":      report_date,
            },
        })

    _cache_write("earnings_surprise", candidates)
    logger.info(f"  Earnings surprise: {len(candidates)} kandidater (min={min_surprise_pct}%)")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# FUNKTION 4 — ANALYTIKER-UPPGRADERINGAR (Finnhub)
# ══════════════════════════════════════════════════════════════════════════════

# Från Sell/Hold → Buy = uppgradering
_UPGRADE_PAIRS = {
    ("sell",         "buy"),
    ("sell",         "strong buy"),
    ("underperform", "buy"),
    ("underperform", "outperform"),
    ("hold",         "buy"),
    ("hold",         "strong buy"),
    ("neutral",      "buy"),
    ("neutral",      "outperform"),
    ("market perform", "outperform"),
}


def fetch_analyst_upgrades(
    days_back: int = 7,
    existing_universe: Optional[set] = None,
    force: bool = False,
) -> list[dict]:
    """
    Hämtar analytiker-uppgraderingar från Finnhub och returnerar tickers
    som fått en uppgradering och INTE finns i universum.

    Args:
        days_back:        Hur långt tillbaka vi letar
        existing_universe: Set av befintliga tickers
        force:            Kringgå cache

    Returns:
        Lista av discovery-kandidater
    """
    cached = _cache_read("analyst_upgrades", _UPGRADES_TTL)
    if cached is not None and not force:
        return cached

    finnhub_key = os.getenv("FINNHUB_API_KEY", "")
    if not finnhub_key:
        logger.debug("  Ingen FINNHUB_API_KEY — hoppar analytiker-uppgraderingar")
        return []

    from_date = (date.today() - timedelta(days=days_back)).isoformat()

    # Vi hämtar en lista med aktier att kontrollera (Finviz top 50 är en proxy)
    # Finnhub's upgrade-endpoint kräver symbol, så vi gör batch-hämtning
    # för kända stora aktier + S&P 500 proxy
    sample_tickers = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "JPM", "JNJ",
        "V", "MA", "UNH", "HD", "PG", "BAC", "XOM", "CVX", "ABBV", "MRK",
        "PFE", "KO", "PEP", "WMT", "COST", "TMO", "ACN", "AVGO", "CSCO",
        "INTC", "AMD", "QCOM", "TXN", "NFLX", "CRM", "ORCL", "IBM", "ADBE",
        "NOW", "PANW", "SNOW", "PLTR", "ARM", "SMCI", "MU", "AMAT", "KLAC",
    ]

    existing = existing_universe or set()
    # Filtrera bort de som redan är i universum
    to_check = [t for t in sample_tickers if t not in existing]

    candidates = []
    for ticker in to_check[:30]:  # Begränsa API-anrop
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/stock/recommendation",
                params={"symbol": ticker, "token": finnhub_key},
                timeout=6,
            )
            if r.status_code != 200:
                continue
            recs = r.json()
            if not recs:
                continue

            # Senaste rekommendation
            latest = recs[0]
            rec_date = latest.get("period", "")
            buy  = latest.get("buy", 0)
            hold = latest.get("hold", 0)
            sell = latest.get("sell", 0)
            strong_buy  = latest.get("strongBuy", 0)
            strong_sell = latest.get("strongSell", 0)

            total = buy + hold + sell + strong_buy + strong_sell
            if total == 0:
                continue

            buy_ratio = (buy + strong_buy) / total
            if buy_ratio < 0.60:  # Minst 60% buy-rekommendationer
                continue

            # Kolla om det är en uppgradering jämfört med förra månaden
            if len(recs) >= 2:
                prev = recs[1]
                prev_buy_ratio = ((prev.get("buy", 0) + prev.get("strongBuy", 0)) /
                                  max(sum(prev.get(k, 0) for k in
                                          ["buy", "hold", "sell", "strongBuy", "strongSell"]), 1))
                if buy_ratio <= prev_buy_ratio + 0.05:
                    continue  # Ingen meningsfull förbättring

            reason = (
                f"Analytiker-uppgradering: {buy_ratio*100:.0f}% köp-rekommendationer "
                f"({strong_buy} Strong Buy, {buy} Buy, {hold} Hold) per {rec_date}"
            )
            conf = 0.55 + min(buy_ratio - 0.60, 0.30) / 2
            candidates.append({
                "ticker":     ticker,
                "source":     "analyst_upgrade",
                "reason":     reason,
                "confidence": round(conf, 2),
                "region":     "US",
                "discovered": date.today().isoformat(),
                "metadata":   {
                    "buy_ratio":  round(buy_ratio, 2),
                    "strong_buy": strong_buy,
                    "buy":        buy,
                    "hold":       hold,
                    "rec_date":   rec_date,
                },
            })
            time.sleep(0.2)  # Respektera rate limit
        except Exception:
            pass

    _cache_write("analyst_upgrades", candidates)
    logger.info(f"  Analytiker-uppgraderingar: {len(candidates)} kandidater")
    return candidates
