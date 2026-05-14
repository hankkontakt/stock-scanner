"""
news_fetcher.py
===============
Hämtar nyhetsartiklar med direktlänkar från Finnhub och publika RSS-flöden.

Funktioner:
  fetch_news()              – bolagsspecifika nyheter via Finnhub company-news
  fetch_global_market_news()– generella marknadsnyheter via Finnhub /news
  fetch_swedish_market_news()– svenska börsnyheter via Placera/DI RSS-flöden
  format_market_news_section_md() – bygger markdown för generella marknadsnyheter

Gratis Finnhub-tier täcker US-aktier bra. Svenska/europeiska (.ST, .DE)
försöks med bas-tickern men saknar ibland täckning – returnerar tom lista då.
"""

import time
import pickle
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime

import requests

CACHE_DIR        = "data/cache"
NEWS_CACHE_HOURS = 6   # Nyheter cachas 6h – tillräckligt för daglig körning
MAX_ARTICLES     = 5   # Max artiklar per aktie i rapporten

# Publika RSS-flöden för svenska börsnyheter (ingen API-nyckel krävs)
SWEDISH_RSS_FEEDS = [
    ("Placera",         "https://www.placera.se/placera/atom.xml"),
    ("Dagens Industri", "https://digital.di.se/rss"),
    ("Realtid",         "https://www.realtid.se/rss.xml"),
]

Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)


def _cache_path(key: str) -> Path:
    return Path(CACHE_DIR) / f"news_{hashlib.md5(key.encode()).hexdigest()}.pkl"


def _read_cache(key: str):
    p = _cache_path(key)
    if not p.exists():
        return None
    if datetime.now() - datetime.fromtimestamp(p.stat().st_mtime) > timedelta(hours=NEWS_CACHE_HOURS):
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


def _finnhub_symbol(ticker: str) -> str:
    """Konverterar ticker till Finnhub-format. VOLV-B.ST → VOLVO B, men vi försöker med VOLV."""
    if "." in ticker:
        return ticker.split(".")[0].replace("-", ".")
    return ticker


def fetch_news(ticker: str, api_key: str, days: int = 3) -> list:
    """
    Hämtar nyhetsartiklar för en aktie från Finnhub.

    Returnerar lista av dicts:
        {headline, source, url, datetime_str, age_hours}
    Sorterat nyast först. Tom lista om inga nyheter eller API saknas.
    """
    if not api_key:
        return []

    cache_key = f"news:{ticker}:{days}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    symbol  = _finnhub_symbol(ticker)
    date_to = datetime.now()
    date_from = date_to - timedelta(days=days)

    try:
        time.sleep(0.4)
        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol,
                "from":   date_from.strftime("%Y-%m-%d"),
                "to":     date_to.strftime("%Y-%m-%d"),
                "token":  api_key,
            },
            timeout=8,
        )

        if resp.status_code == 429:
            time.sleep(61)
            resp = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": symbol,
                    "from":   date_from.strftime("%Y-%m-%d"),
                    "to":     date_to.strftime("%Y-%m-%d"),
                    "token":  api_key,
                },
                timeout=8,
            )

        if resp.status_code != 200:
            _write_cache(cache_key, [])
            return []

        articles = resp.json()
        if not isinstance(articles, list):
            _write_cache(cache_key, [])
            return []

        results = []
        for a in sorted(articles, key=lambda x: x.get("datetime", 0), reverse=True):
            headline = a.get("headline", "").strip()
            url      = a.get("url", "").strip()
            source   = a.get("source", "").strip()
            ts       = a.get("datetime", 0)

            if not headline or not url:
                continue

            try:
                dt = datetime.fromtimestamp(ts)
                age_h = (datetime.now() - dt).total_seconds() / 3600
                dt_str = dt.strftime("%d %b %H:%M")
            except Exception:
                age_h  = 999
                dt_str = "—"

            results.append({
                "headline":   headline[:120],
                "source":     source,
                "url":        url,
                "datetime_str": dt_str,
                "age_hours":  round(age_h, 1),
            })

            if len(results) >= MAX_ARTICLES:
                break

        _write_cache(cache_key, results)
        return results

    except Exception:
        _write_cache(cache_key, [])
        return []


def fetch_news_batch(tickers: list, api_key: str, days: int = 3) -> dict:
    """
    Hämtar nyheter för flera aktier.
    Returnerar {ticker: [articles]} – bara tickers som har nyheter.
    """
    result = {}
    for ticker in tickers:
        articles = fetch_news(ticker, api_key, days=days)
        if articles:
            result[ticker] = articles
    return result


def format_news_section_md(
    news_by_ticker: dict,
    ticker_names:   dict = None,
    header:         str  = "📰 Nyheter",
) -> str:
    """
    Bygger markdown-sektionen med nyheter och direktlänkar.

    Args:
        news_by_ticker: {ticker: [articles]}
        ticker_names:   {ticker: name} för visningsnamn
        header:         rubrik för sektionen
    """
    if not news_by_ticker:
        return ""

    lines = [f"## {header}\n"]

    for ticker, articles in news_by_ticker.items():
        if not articles:
            continue
        name = (ticker_names or {}).get(ticker, ticker)
        lines.append(f"**`{ticker}`** {name}")
        for a in articles:
            icon = "🔴" if a["age_hours"] < 6 else "🟡" if a["age_hours"] < 24 else "⚪"
            lines.append(
                f"{icon} [{a['headline']}]({a['url']})  \n"
                f"   _{a['source']} · {a['datetime_str']}_"
            )
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# GLOBALA MARKNADSNYHETER (Finnhub)
# ══════════════════════════════════════════════════════════════

def fetch_global_market_news(api_key: str, max_articles: int = 5) -> list:
    """
    Hämtar generella marknadsnyheter från Finnhub (/api/v1/news?category=general).
    Returnerar [{headline, source, url, datetime_str, age_hours}] nyast först.
    """
    if not api_key:
        return []

    cache_key = f"market_news_global:{max_articles}"
    cached    = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        time.sleep(0.4)
        resp = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": api_key},
            timeout=8,
        )
        if resp.status_code == 429:
            time.sleep(61)
            resp = requests.get(
                "https://finnhub.io/api/v1/news",
                params={"category": "general", "token": api_key},
                timeout=8,
            )
        if resp.status_code != 200:
            _write_cache(cache_key, [])
            return []

        articles = resp.json()
        if not isinstance(articles, list):
            _write_cache(cache_key, [])
            return []

        results = []
        for a in sorted(articles, key=lambda x: x.get("datetime", 0), reverse=True):
            headline = a.get("headline", "").strip()
            url      = a.get("url", "").strip()
            source   = a.get("source", "").strip()
            ts       = a.get("datetime", 0)
            if not headline or not url:
                continue
            try:
                dt    = datetime.fromtimestamp(ts)
                age_h = (datetime.now() - dt).total_seconds() / 3600
                dt_s  = dt.strftime("%d %b %H:%M")
            except Exception:
                age_h = 999
                dt_s  = "—"
            results.append({
                "headline":     headline[:130],
                "source":       source,
                "url":          url,
                "datetime_str": dt_s,
                "age_hours":    round(age_h, 1),
            })
            if len(results) >= max_articles:
                break

        _write_cache(cache_key, results)
        return results

    except Exception:
        _write_cache(cache_key, [])
        return []


# ══════════════════════════════════════════════════════════════
# SVENSKA BÖRSNYHETER (RSS)
# ══════════════════════════════════════════════════════════════

def fetch_swedish_market_news(max_articles: int = 5) -> list:
    """
    Hämtar svenska börsnyheter från Placera/DI/Realtid RSS-flöden.
    Provar varje källa i tur och ordning tills vi har tillräckligt med artiklar.
    Returnerar [{headline, source, url, datetime_str, age_hours}] nyast först.
    """
    cache_key = f"market_news_swedish:{max_articles}"
    cached    = _read_cache(cache_key)
    if cached is not None:
        return cached

    results = []

    for source_name, rss_url in SWEDISH_RSS_FEEDS:
        if len(results) >= max_articles:
            break
        try:
            time.sleep(0.3)
            resp = requests.get(rss_url, timeout=8, headers={
                "User-Agent": "MarketScan/1.0 (stock scanner)"
            })
            if resp.status_code != 200:
                continue

            root = ET.fromstring(resp.content)
            ns   = {"atom": "http://www.w3.org/2005/Atom"}

            # Stöd både RSS 2.0 (<item>) och Atom (<entry>)
            items = root.findall(".//item") or root.findall(".//atom:entry", ns)

            for item in items:
                if len(results) >= max_articles:
                    break

                # Rubrik
                title_el = item.find("title") or item.find("atom:title", ns)
                headline = (title_el.text or "").strip() if title_el is not None else ""
                if not headline:
                    continue

                # URL
                link_el = item.find("link") or item.find("atom:link", ns)
                if link_el is not None:
                    url = (link_el.get("href") or link_el.text or "").strip()
                else:
                    url = ""
                if not url:
                    continue

                # Datum
                pub_el = (
                    item.find("pubDate") or
                    item.find("published") or
                    item.find("atom:published", ns)
                )
                age_h = 999
                dt_s  = "—"
                if pub_el is not None and pub_el.text:
                    try:
                        dt    = parsedate_to_datetime(pub_el.text.strip())
                        age_h = (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600
                        dt_s  = dt.strftime("%d %b %H:%M")
                    except Exception:
                        try:
                            dt    = datetime.fromisoformat(pub_el.text.strip().replace("Z", "+00:00"))
                            age_h = (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600
                            dt_s  = dt.strftime("%d %b %H:%M")
                        except Exception:
                            pass

                # Filtrera bort artiklar äldre än 48h
                if age_h > 48:
                    continue

                # Undvik duplicerade rubriker
                if any(r["headline"][:60] == headline[:60] for r in results):
                    continue

                results.append({
                    "headline":     headline[:130],
                    "source":       source_name,
                    "url":          url,
                    "datetime_str": dt_s,
                    "age_hours":    round(age_h, 1),
                })
        except Exception:
            continue

    results = sorted(results, key=lambda x: x["age_hours"])[:max_articles]
    _write_cache(cache_key, results)
    return results


# ══════════════════════════════════════════════════════════════
# MARKDOWN-FORMATERARE – MARKNADSNYHETER
# ══════════════════════════════════════════════════════════════

def format_market_news_section_md(
    global_news:  list,
    swedish_news: list,
    compact:      bool = False,
) -> str:
    """
    Bygger en markdown-sektion med generella marknadsnyheter.

    compact=True → kortare format för morgonbrevet (3+3 max)
    compact=False → fullständigt format för fredagssammanfattning
    """
    if not global_news and not swedish_news:
        return ""

    max_n = 3 if compact else 5
    lines = ["## 🌐 Marknadsnyheter\n"]

    if swedish_news:
        lines.append("### 🇸🇪 Sverige\n")
        for a in swedish_news[:max_n]:
            icon = "🔴" if a["age_hours"] < 6 else "🟡" if a["age_hours"] < 24 else "⚪"
            lines.append(
                f"{icon} [{a['headline']}]({a['url']})  \n"
                f"   _{a['source']} · {a['datetime_str']}_\n"
            )

    if global_news:
        lines.append("### 🌍 Globalt\n")
        for a in global_news[:max_n]:
            icon = "🔴" if a["age_hours"] < 6 else "🟡" if a["age_hours"] < 24 else "⚪"
            lines.append(
                f"{icon} [{a['headline']}]({a['url']})  \n"
                f"   _{a['source']} · {a['datetime_str']}_\n"
            )

    return "\n".join(lines)


# Veckans marknadsfaktoider – roterar baserat på veckonummer
WEEKLY_FACTOIDS = [
    "Stockholmsbörsen är upp ~2 500% sedan 1993 – justerat för inflation ca +800%.",
    "'Sell in May' gäller statistiskt i 7 av 10 år sedan 2000 på OMXS30.",
    "Januari-effekten: aktier stiger historiskt mer i januari än någon annan månad.",
    "OMXS30 har i genomsnitt gett ~10% per år de senaste 30 åren.",
    "En investering på 10 000 kr i Investor B år 2000 är idag värd ~280 000 kr.",
    "Sverige har en av världens högsta aktieägarandelar per capita.",
    "Volvo grundades 1927 – aktien har sedan börsnoteringen 1935 gett >30 000% totalavkastning.",
    "Ericsson var på 1990-talet ett av världens mest värdefulla bolag – nuvarande kurs är ~1% av toppnivån 2000.",
    "H&M är ett av världens 20 mest sålda klädbrand – trots det har aktien halverats på 10 år.",
    "Alfa Laval grundades 1883 – bolagets separatorteknik används i 100+ länder.",
    "Historiskt slår small-cap aktier large-cap med ~2% per år på lång sikt.",
    "Utdelningsåterinvestering (DRIP) kan fördubbla avkastningen jämfört med att ta ut utdelningen.",
    "P/E-talet för OMXS30 är historiskt runt 14-16x i normala marknader.",
    "Diversifiering över 15-20 aktier eliminerar ~90% av bolagsspecifik risk.",
    "Momentum-faktorn (köp vinnare, sälj förlorare) har fungerat i 200 år av finanshistoria.",
    "Investmentbolag som Investor och Industrivärden handlas ofta med 10-20% rabatt mot NAV.",
    "Balanserade portföljer (60% aktier / 40% räntor) har historiskt gett Sharpe ~0.5.",
    "Kortsäljning av aktier stod för ~8% av OMXS-volymen 2023.",
    "Kasinobranschen på börsen (Evolution) är Stockholmsbörsens bäst presterande aktie 2012–2022.",
    "Norges oljefond (NBIM) äger i genomsnitt 1.5% av alla börsnoterade bolag i världen.",
]


def get_weekly_factoid() -> str:
    week = datetime.now().isocalendar()[1]
    return WEEKLY_FACTOIDS[week % len(WEEKLY_FACTOIDS)]
