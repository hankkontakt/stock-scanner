"""
universe_discovery.py — Automatisk discovery av nya potentiella aktier
======================================================================
Aggregerar kandidater från flera oberoende källor:

  1. Finviz screener       (finvizfinance, no API key)  — momentum/value/growth
  2. Index-tillägg         (Wikipedia S&P 500 / Nasdaq 100)  — institutionell validering
  3. Nyhetsbaserad         (befintliga RSS-flöden + regexticker-extrahering)
  4. AI-baserad            (DeepSeek/Gemini med strukturerat prompt)
  5. Sektor-ETF-holdings   (Wikipedia ETF-sidor för sektorer)

Varje källa returnerar en lista av CandidateStock-dikt:
  {
    "ticker":     str,
    "source":     str,
    "reason":     str,
    "confidence": float,   # 0.0 – 1.0
    "region":     str,     # US | NORDIC | EUROPE | ASIA | CANADA | UK | OTHER
    "metadata":   dict,    # källspecifik data
  }

Användning:
    from core.universe_discovery import run_discovery
    candidates = run_discovery(sources=["finviz", "index", "news", "ai"])
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ROOT      = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Hur lång tid (sekunder) källors cache är giltig
SOURCE_CACHE_TTL = {
    "finviz":   3600 * 4,    # 4h
    "index":    3600 * 12,   # 12h
    "news":     3600 * 2,    # 2h
    "ai":       3600 * 24,   # 24h
    "etf":      3600 * 12,   # 12h
}

# Tickers som ALDRIG ska föreslås (index-tracker, stablecoin, etc.)
_EXCLUSION_SET = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "GLD", "SLV", "TLT", "HYG",
    "BTC", "ETH", "USDT", "USDC", "BNB",
}

# Kända engelska ord som ser ut som tickers men inte är det
_FALSE_POSITIVE_WORDS = {
    "A", "I", "IT", "IS", "THE", "AND", "OR", "BUT", "FOR", "FROM",
    "AT", "TO", "IN", "ON", "BY", "US", "BE", "AS", "AN", "WITH",
    "NOT", "NO", "SO", "IF", "DO", "ALL", "NEW", "CAN", "AM", "PM",
    "CEO", "CFO", "COO", "IPO", "ETF", "AI", "ML", "EPS", "PE", "ROE",
    "ROA", "YOY", "QOQ", "MOM", "USD", "EUR", "SEK", "NOK", "DKK",
    "GBP", "JPY", "CNY", "BRL", "CAD", "AUD", "NYSE", "NASDAQ",
    "SEC", "FED", "ECB", "RBA", "BOE", "IMF", "GDP", "CPI", "PMI",
    "ESG", "SRI", "VC", "PE", "LBO", "M&A", "SPAC", "EV",
    "Q1", "Q2", "Q3", "Q4", "FY", "H1", "H2",
    "USA", "UK", "EU", "UN", "WHO", "NATO",
}


# ── Cache-hjälpfunktioner ──────────────────────────────────────────────────────

def _cache_path(source: str) -> Path:
    return CACHE_DIR / f"discovery_{source}.json"


def _read_cache(source: str) -> Optional[list]:
    p = _cache_path(source)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) < SOURCE_CACHE_TTL.get(source, 3600):
            return data.get("candidates", [])
    except Exception:
        pass
    return None


def _write_cache(source: str, candidates: list) -> None:
    try:
        _cache_path(source).write_text(
            json.dumps({"ts": time.time(), "candidates": candidates}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _make_candidate(ticker: str, source: str, reason: str,
                    confidence: float = 0.5, region: str = "US",
                    metadata: Optional[dict] = None) -> dict:
    return {
        "ticker":     ticker.upper().strip(),
        "source":     source,
        "reason":     reason,
        "confidence": round(min(max(confidence, 0.0), 1.0), 2),
        "region":     region,
        "discovered": date.today().isoformat(),
        "metadata":   metadata or {},
    }


def _ticker_region(ticker: str) -> str:
    """Gissa region baserat på börs-suffix."""
    t = ticker.upper()
    if any(t.endswith(s) for s in (".ST",)):
        return "NORDIC"
    if any(t.endswith(s) for s in (".CO", ".OL", ".HE")):
        return "NORDIC"
    if any(t.endswith(s) for s in (".L",)):
        return "UK"
    if any(t.endswith(s) for s in (".DE", ".PA", ".AS", ".MI", ".MC", ".VI", ".WA", ".LS", ".SW")):
        return "EUROPE"
    if any(t.endswith(s) for s in (".TO",)):
        return "CANADA"
    if any(t.endswith(s) for s in (".AX", ".T", ".HK", ".TW", ".KS", ".NS", ".BO", ".SI")):
        return "ASIA"
    if any(t.endswith(s) for s in (".SA", ".MX")):
        return "LATAM"
    return "US"


# ══════════════════════════════════════════════════════════════════════════════
# KÄLLA 1: FINVIZ SCREENER
# ══════════════════════════════════════════════════════════════════════════════

def _source_finviz(force: bool = False) -> list:
    """
    Finviz screener via finvizfinance (ingen API-nyckel krävs).
    Tre separata skärmar: momentum, value, growth.
    """
    cached = _read_cache("finviz")
    if cached is not None and not force:
        return cached

    candidates = []
    try:
        from finvizfinance.screener.overview import Overview  # type: ignore[import]
    except ImportError:
        logger.warning("finvizfinance ej installerat — hoppar Finviz-källa. "
                       "Kör: pip install finvizfinance")
        return []

    screens = [
        # (label, filters, reason_template, confidence)
        (
            "momentum",
            {
                "Performance": "Month +10%",
                "Average Volume": "Over 500K",
                "Price": "Over $5",
            },
            "Finviz momentum: +10% senaste månaden, hög volym",
            0.70,
        ),
        (
            "value",
            {
                "P/E": "Under 15",
                "Price/Book": "Under 2",
                "EPS growththis year": "Over 10%",
                "Average Volume": "Over 200K",
            },
            "Finviz value: P/E < 15, P/B < 2, EPS-tillväxt > 10%",
            0.65,
        ),
        (
            "growth",
            {
                "EPS growththis year": "Over 25%",
                "EPS growthnext year": "Over 20%",
                "Sales growthpast 5 years": "Over 10%",
                "Average Volume": "Over 200K",
            },
            "Finviz growth: EPS +25% i år, +20% nästa år",
            0.65,
        ),
        (
            "new_highs",
            {
                "52-Week High/Low": "New High",
                "Average Volume": "Over 500K",
                "Price": "Over $10",
            },
            "Finviz: ny 52-veckors höjdpunkt med hög volym",
            0.60,
        ),
    ]

    for label, filters, reason, conf in screens:
        try:
            fov = Overview()
            fov.set_filter(filters_dict=filters)
            df = fov.screener_view()
            if df is None or df.empty:
                continue
            ticker_col = next(
                (c for c in df.columns if c.lower() in ("ticker", "symbol")), None
            )
            if ticker_col is None:
                continue
            for t in df[ticker_col].dropna().str.upper().unique()[:40]:
                if t in _EXCLUSION_SET or t in _FALSE_POSITIVE_WORDS:
                    continue
                candidates.append(_make_candidate(
                    t, f"finviz_{label}", reason,
                    confidence=conf, region="US",
                    metadata={"screen": label},
                ))
            time.sleep(1.5)  # respektera Finviz
        except Exception as e:
            logger.debug(f"  Finviz {label} misslyckades: {e}")

    _write_cache("finviz", candidates)
    logger.info(f"  Finviz: {len(candidates)} kandidater")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# KÄLLA 2: INDEX-TILLÄGG (Wikipedia)
# ══════════════════════════════════════════════════════════════════════════════

def _source_index_additions(force: bool = False) -> list:
    """
    Parsar Wikipedia-tabeller för S&P 500 och Nasdaq 100 för att hitta
    nyligen tillagda tickers. Inga API-nycklar krävs.
    """
    cached = _read_cache("index")
    if cached is not None and not force:
        return cached

    candidates = []

    # ── S&P 500 nya tillägg ───────────────────────────────────────────────
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            attrs={"id": "constituents"},
        )
        sp500_df = tables[0] if tables else pd.DataFrame()
        # Andra tabellen = historiska tillägg/borttagningar
        all_tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        if len(all_tables) > 1:
            changes = all_tables[1]
            # Kolumner varierar, leta efter "Added" och ticker-kolumn
            change_cols = [c for c in changes.columns if "add" in str(c).lower() or "ticker" in str(c).lower()]
            added_col = next(
                (c for c in changes.columns
                 if "ticker" in str(c).lower() and ("add" in str(changes[c].name).lower() or True)),
                None,
            )
            # Platta ut multi-level headers om de finns
            if isinstance(changes.columns, pd.MultiIndex):
                changes.columns = [" ".join(filter(None, map(str, c))).strip() for c in changes.columns]
            # Hitta ticker-kolumn för tillägg
            added_ticker_col = next(
                (c for c in changes.columns if "added" in c.lower() and "ticker" in c.lower()),
                next(
                    (c for c in changes.columns if "ticker" in c.lower()),
                    None,
                ),
            )
            if added_ticker_col:
                for t in changes[added_ticker_col].dropna().str.upper().unique()[:20]:
                    t = t.strip()
                    if len(t) >= 1 and t not in _EXCLUSION_SET and t not in _FALSE_POSITIVE_WORDS:
                        candidates.append(_make_candidate(
                            t, "index_sp500",
                            "Nyligen tillagd i S&P 500 (institutionell validering)",
                            confidence=0.80, region="US",
                            metadata={"index": "S&P 500"},
                        ))
        time.sleep(1)
    except Exception as e:
        logger.debug(f"  Wikipedia S&P 500 misslyckades: {e}")

    # ── Nasdaq 100 ────────────────────────────────────────────────────────
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        nasdaq_df = next((t for t in tables if "Ticker" in t.columns or "Symbol" in t.columns), None)
        if nasdaq_df is not None:
            ticker_col = "Ticker" if "Ticker" in nasdaq_df.columns else "Symbol"
            for t in nasdaq_df[ticker_col].dropna().str.upper().unique()[:110]:
                t = t.strip()
                if len(t) >= 1 and t not in _EXCLUSION_SET:
                    candidates.append(_make_candidate(
                        t, "index_nasdaq100",
                        "Ingår i Nasdaq 100 (tech/growth-index)",
                        confidence=0.55, region="US",
                        metadata={"index": "Nasdaq 100"},
                    ))
        time.sleep(1)
    except Exception as e:
        logger.debug(f"  Wikipedia Nasdaq 100 misslyckades: {e}")

    # ── Nordiska index: OMX Nordic All-Share (via Wikipedia) ─────────────
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/OMX_Stockholm_30")
        for t_df in tables:
            if "Ticker" in t_df.columns or "Symbol" in t_df.columns:
                col = "Ticker" if "Ticker" in t_df.columns else "Symbol"
                for t in t_df[col].dropna().str.upper().unique():
                    if not t.endswith(".ST"):
                        t = t + ".ST"
                    candidates.append(_make_candidate(
                        t, "index_omx30",
                        "Ingår i OMXS30 (Stockholmsbörsen large cap)",
                        confidence=0.55, region="NORDIC",
                        metadata={"index": "OMXS30"},
                    ))
                break
        time.sleep(1)
    except Exception as e:
        logger.debug(f"  Wikipedia OMXS30 misslyckades: {e}")

    # ── MSCI World Index constituents (via Wikipedia) ────────────────────
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/MSCI_World")
        for t_df in tables:
            cols_lower = [str(c).lower() for c in t_df.columns]
            if "ticker" in cols_lower or "symbol" in cols_lower:
                tc = next(c for c in t_df.columns if str(c).lower() in ("ticker", "symbol"))
                for t in t_df[tc].dropna().str.upper().unique()[:60]:
                    t = t.strip()
                    if len(t) >= 1 and t not in _EXCLUSION_SET and t not in _FALSE_POSITIVE_WORDS:
                        candidates.append(_make_candidate(
                            t, "index_msci_world",
                            "Ingar i MSCI World (brett globalt index)",
                            confidence=0.55,
                            region=_ticker_region(t),
                            metadata={"index": "MSCI World"},
                        ))
                break
        time.sleep(1)
    except Exception as e:
        logger.debug(f"  MSCI World misslyckades: {e}")

    _write_cache("index", candidates)
    logger.info(f"  Index-tillägg: {len(candidates)} kandidater")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# KÄLLA 3: NYHETSBASERAD TICKER-EXTRAHERING
# ══════════════════════════════════════════════════════════════════════════════

# Regex för potentiella tickers: 1-5 versaler, ev. med börs-suffix
_TICKER_RE = re.compile(r"\b([A-Z]{1,5})(?:\.[A-Z]{1,2})?\b")

def _extract_tickers_from_text(text: str) -> list[str]:
    """Extraherar möjliga ticker-symboler ur fritext."""
    raw = _TICKER_RE.findall(text.upper())
    return [
        t for t in set(raw)
        if t not in _FALSE_POSITIVE_WORDS
        and t not in _EXCLUSION_SET
        and len(t) >= 2
    ]


def _source_news(force: bool = False) -> list:
    """
    Hämtar nyheter från befintliga RSS-flöden och extraherar ticker-omnämnanden.
    Filtrerar med en enkel heuristik: omnämns minst 2 gånger = kandidat.
    """
    cached = _read_cache("news")
    if cached is not None and not force:
        return cached

    # RSS-flöden att skrapa (delar dessa med news_fetcher.py)
    RSS_FEEDS = [
        ("Reuters Business",     "https://feeds.reuters.com/reuters/businessNews"),
        ("Reuters Markets",      "https://feeds.reuters.com/reuters/usnews"),
        ("MarketWatch",          "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
        ("Seeking Alpha",        "https://seekingalpha.com/feed.xml"),
        ("Investing.com",        "https://www.investing.com/rss/news.rss"),
        ("Yahoo Finance",        "https://finance.yahoo.com/news/rssindex"),
        ("Placera",              "https://www.placera.se/placera/atom.xml"),
        ("Realtid",              "https://www.realtid.se/rss.xml"),
        ("Affärsvärlden",        "https://www.affarsvarlden.se/rss.xml"),
        ("DI",                   "https://digital.di.se/rss"),
    ]

    ticker_mentions: dict[str, list[str]] = {}  # ticker → [reasons]

    for feed_name, url in RSS_FEEDS:
        try:
            import xml.etree.ElementTree as ET
            r = requests.get(url, timeout=8, headers={"User-Agent": "MarketScan/1.0"})
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for item in items[:30]:
                title_el = item.find("title") or item.find("{http://www.w3.org/2005/Atom}title")
                desc_el  = item.find("description") or item.find("{http://www.w3.org/2005/Atom}summary")
                title = title_el.text or "" if title_el is not None else ""
                desc  = desc_el.text  or "" if desc_el  is not None else ""
                combined = f"{title} {desc}"
                for t in _extract_tickers_from_text(combined):
                    if t not in ticker_mentions:
                        ticker_mentions[t] = []
                    ticker_mentions[t].append(f"{feed_name}: {title[:60]}")
            time.sleep(0.3)
        except Exception:
            pass

    # Kandidater = tickers omnämnda i minst 2 artiklar
    candidates = []
    for ticker, sources in ticker_mentions.items():
        if len(sources) < 2:
            continue
        reason = f"Nämns i {len(sources)} nyhetsartiklar: {sources[0][:80]}"
        conf = min(0.3 + 0.1 * len(sources), 0.70)  # fler omnämnanden = högre conf
        region = _ticker_region(ticker)
        candidates.append(_make_candidate(
            ticker, "news",
            reason, confidence=conf, region=region,
            metadata={"mention_count": len(sources), "feeds": list(dict.fromkeys(
                s.split(":")[0] for s in sources
            ))},
        ))

    candidates.sort(key=lambda c: -c["confidence"])
    _write_cache("news", candidates[:100])
    logger.info(f"  Nyheter: {len(candidates)} kandidater")
    return candidates[:100]


# ══════════════════════════════════════════════════════════════════════════════
# KÄLLA 4: AI-BASERAD DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

def _source_ai(force: bool = False, provider: str = "auto") -> list:
    """
    Använder DeepSeek/Gemini för att föreslå nya intressanta aktier.
    Ber om strukturerat JSON-svar med ticker, region, sektor och motivering.
    Skickar 3 separata prompts för olika teman.
    """
    cached = _read_cache("ai")
    if cached is not None and not force:
        return cached

    try:
        from core.ai_analysis import ai_chat
    except ImportError:
        return []

    today = date.today().isoformat()
    themes = [
        (
            "US growth",
            f"""Du är en kvantitativ aktieanalytiker. Datum: {today}.
Föreslå 8 amerikanska aktier med starkt tillväxtmomentum som kan vara värda att ha i ett automatiserat scanningsystem.
Fokusera på: AI/tech, halvledare, biotech, clean energy, SaaS.
Svara ENBART i JSON-format som en lista:
[{{"ticker": "NVDA", "name": "Nvidia", "sector": "Technology", "reason": "...", "confidence": 0.8}}, ...]
Confidence ska vara 0.0-1.0. Inga kommentarer utanför JSON.""",
        ),
        (
            "Nordic/European",
            f"""Du är en nordisk aktieanalytiker. Datum: {today}.
Föreslå 8 nordiska eller europeiska aktier (börssuffix .ST, .CO, .OL, .HE, .DE, .PA, .AS, .L)
som är intressanta just nu baserat på fundamenta, momentum eller sektortrender.
Svara ENBART i JSON:
[{{"ticker": "VOLVO-B.ST", "name": "AB Volvo", "sector": "Industrials", "reason": "...", "confidence": 0.75}}, ...]""",
        ),
        (
            "Global value",
            f"""Du är en global värdeinvesterare. Datum: {today}.
Föreslå 6 undervärderade aktier globalt (PE < 15, stark balansräkning, FCF-positiva) som kan ge
god riskjusterad avkastning. Inkludera gärna Japan (.T), Korea (.KS) eller Kanada (.TO).
Svara ENBART i JSON:
[{{"ticker": "TM", "name": "Toyota", "sector": "Auto", "reason": "...", "confidence": 0.70}}, ...]""",
        ),
    ]

    candidates = []
    for theme_name, prompt in themes:
        try:
            result = ai_chat(prompt, provider=provider, force_refresh=True, depth="Normal")
            cleaned = result.strip()
            if "```" in cleaned:
                parts = cleaned.split("```")
                for part in parts:
                    p = part.strip()
                    if p.startswith("[") or p.startswith("json\n["):
                        cleaned = p.lstrip("json").strip()
                        break
            stocks = json.loads(cleaned)
            if isinstance(stocks, list):
                for s in stocks[:10]:
                    if not isinstance(s, dict):
                        continue
                    t = str(s.get("ticker", "")).upper().strip()
                    if not t or t in _EXCLUSION_SET:
                        continue
                    conf = float(s.get("confidence", 0.6))
                    region = _ticker_region(t)
                    candidates.append(_make_candidate(
                        t, f"ai_{theme_name.replace(' ', '_').replace('/', '_')}",
                        s.get("reason", "AI-förslag"),
                        confidence=conf, region=region,
                        metadata={
                            "name":   s.get("name", ""),
                            "sector": s.get("sector", ""),
                            "theme":  theme_name,
                        },
                    ))
        except Exception as e:
            logger.debug(f"  AI {theme_name} misslyckades: {e}")
        time.sleep(2)  # undvik rate-limiting

    _write_cache("ai", candidates)
    logger.info(f"  AI: {len(candidates)} kandidater")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# KÄLLA 5: SEKTOR-ETF-HOLDINGS
# ══════════════════════════════════════════════════════════════════════════════

# Kända sektorETF:er med Wikipedia-sidor som innehåller holdings
_SECTOR_ETFS = [
    ("XLK",  "Technology",          "https://en.wikipedia.org/wiki/Technology_Select_Sector_SPDR_Fund"),
    ("XLV",  "Healthcare",          "https://en.wikipedia.org/wiki/Health_Care_Select_Sector_SPDR_Fund"),
    ("XLE",  "Energy",              "https://en.wikipedia.org/wiki/Energy_Select_Sector_SPDR_Fund"),
    ("XLF",  "Financials",          "https://en.wikipedia.org/wiki/Financial_Select_Sector_SPDR_Fund"),
    ("XLI",  "Industrials",         "https://en.wikipedia.org/wiki/Industrial_Select_Sector_SPDR_Fund"),
]


def _source_etf_holdings(force: bool = False) -> list:
    """
    Hämtar holdings för sektors-ETF:er via Wikipedia.
    Ger bredare täckning av respektive sektor.
    """
    cached = _read_cache("etf")
    if cached is not None and not force:
        return cached

    candidates = []
    for etf, sector, url in _SECTOR_ETFS:
        try:
            tables = pd.read_html(url)
            for tbl in tables:
                cols_lower = [str(c).lower() for c in tbl.columns]
                if any("ticker" in c or "symbol" in c for c in cols_lower):
                    col = next(
                        c for c, cl in zip(tbl.columns, cols_lower)
                        if "ticker" in cl or "symbol" in cl
                    )
                    for t in tbl[col].dropna().str.upper().unique()[:50]:
                        t = str(t).strip()
                        if len(t) >= 1 and t not in _EXCLUSION_SET and t not in _FALSE_POSITIVE_WORDS:
                            candidates.append(_make_candidate(
                                t, f"etf_{etf}",
                                f"Holdings i sektor-ETF {etf} ({sector})",
                                confidence=0.45, region="US",
                                metadata={"etf": etf, "sector": sector},
                            ))
                    break
            time.sleep(1)
        except Exception as e:
            logger.debug(f"  ETF {etf} misslyckades: {e}")

    _write_cache("etf", candidates)
    logger.info(f"  ETF-holdings: {len(candidates)} kandidater")
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# VALIDERING
# ══════════════════════════════════════════════════════════════════════════════

def validate_candidates(
    candidates: list,
    existing_universe: Optional[set] = None,
    min_volume: int = 100_000,
    min_price: float = 2.0,
    max_workers: int = 8,
    universe_type: str = "universe",
    run_quality_gate: bool = True,
    run_mscore: bool = False,     # Dyr (hämtar finansiella FS) — av som default
    run_ai_review: bool = False,  # Layer 5: AI-granskning — av som default (aktiveras i maintenance)
    ai_provider: str = "auto",
    verbose: bool = True,
) -> list:
    """
    Validerar kandidater mot yfinance OCH kör quality gate (5 lager).

    Nytt i v2:
    - Layer 1: hard_exclude() — penny stocks, extremskuld, shell-bolag
    - Layer 2: compute_quality_score() — sektor-aware kvalitetspoäng (0–100)
    - Layer 3: (valfritt) compute_beneish_mscore() — bedrägeridetektering
    - Layer 4: check_dilution() — aktie-utspädning
    - Layer 5: Confidence-delta appliceras på kandidatens slutpoäng

    Varje kandidat får: valid, quality_tier, quality_score, fraud_flags,
                        confidence (justerad), yf_data.
    """
    from core.discovery_quality_gate import (
        hard_exclude, evaluate_candidate, extract_financials_for_mscore,
    )

    if existing_universe is None:
        existing_universe = set()

    # Deduplicera och filtrera redan kända tickers
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        t = c["ticker"]
        if t in seen or t in existing_universe:
            continue
        seen.add(t)
        unique.append(c)

    if verbose:
        logger.info(
            f"  Validerar {len(unique)} unika kandidater "
            f"(filtrerat {len(candidates) - len(unique)} kända/dubletter)..."
        )

    import yfinance as yf

    def _check(candidate: dict) -> dict:
        ticker = candidate["ticker"]
        result = {**candidate, "valid": False, "yf_data": {}}
        try:
            import socket
            socket.setdefaulttimeout(12)
            yf_ticker = yf.Ticker(ticker)
            info = yf_ticker.info or {}

            price      = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0
            volume     = info.get("averageVolume") or info.get("averageVolume10days") or 0
            market_cap = info.get("marketCap") or 0
            name       = info.get("shortName") or info.get("longName") or ticker
            quote_type = info.get("quoteType", "")

            # Grundläggande check
            if not quote_type or quote_type in ("NONE", ""):
                result["exclude_reason"] = "Ogiltigt quoteType"
                return result
            if price < min_price:
                result["exclude_reason"] = f"Pris {price:.2f} < {min_price}"
                return result
            if volume < min_volume:
                result["exclude_reason"] = f"Volym {volume:.0f} < {min_volume}"
                return result

            yf_data = {
                "name":       name,
                "price":      round(float(price), 2),
                "volume":     int(volume),
                "market_cap": int(market_cap),
                "sector":     info.get("sector", ""),
                "industry":   info.get("industry", ""),
                "country":    info.get("country", ""),
                "quote_type": quote_type,
            }
            result["yf_data"] = yf_data
            result["metadata"].update(yf_data)

            if run_quality_gate:
                # Hämta finansiell data för M-Score om begärt
                fin_data = extract_financials_for_mscore(yf_ticker) if run_mscore else None

                # Kör full evaluering
                eval_result = evaluate_candidate(
                    info, ticker=ticker,
                    universe_type=universe_type,
                    financials=fin_data,
                )
                result.update({
                    "quality_score":  eval_result["quality_score"],
                    "quality_tier":   eval_result["quality_tier"],
                    "quality_flags":  eval_result["quality_flags"],
                    "fraud_flags":    eval_result["fraud_flags"],
                    "m_score":        eval_result["m_score"],
                    "m_score_text":   eval_result["m_score_text"],
                    "dilution_pct":   eval_result["dilution_pct"],
                })

                # Applicera confidence-delta
                orig_conf = float(result.get("confidence", 0.5))
                result["confidence"] = round(
                    max(0.0, min(1.0, orig_conf + eval_result["confidence_delta"])),
                    3,
                )

                # Hard exclusion
                if eval_result["excluded"]:
                    result["exclude_reason"] = eval_result["exclude_reason"]
                    return result

                # Extrem manipulation → exkludera
                m = eval_result.get("m_score")
                if m is not None and m > -1.00:
                    result["exclude_reason"] = f"M-score={m:.2f} > -1.00 (trolig manipulation)"
                    return result

                # Extrem utspädning → exkludera
                if eval_result.get("dilution_pct", 0) > 30:
                    result["exclude_reason"] = f"Utspädning {eval_result['dilution_pct']:.1f}% > 30%"
                    return result

            else:
                # Ingen quality gate — sätt defaults
                result.update({
                    "quality_score": 50.0,
                    "quality_tier":  "MEDIUM",
                    "quality_flags": [],
                    "fraud_flags":   [],
                    "m_score":       None,
                    "m_score_text":  "Ej beräknad",
                    "dilution_pct":  0.0,
                })

            result["valid"] = True

        except Exception as e:
            result["exclude_reason"] = f"Valideringsfel: {str(e)[:80]}"

        return result

    validated = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check, c): c for c in unique}
        for future in as_completed(futures):
            validated.append(future.result())

    n_valid = sum(1 for c in validated if c["valid"])
    n_high  = sum(1 for c in validated if c.get("quality_tier") == "HIGH")
    n_med   = sum(1 for c in validated if c.get("quality_tier") == "MEDIUM")
    n_spec  = sum(1 for c in validated if c.get("quality_tier") == "SPECULATIVE")
    if verbose:
        logger.info(
            f"  Validering klar: {n_valid}/{len(unique)} OK "
            f"(HIGH={n_high}, MEDIUM={n_med}, SPEC={n_spec})"
        )

    # Layer 5: AI-granskning (kör bara på giltiga HIGH/MEDIUM-kandidater)
    if run_ai_review:
        to_review = [
            c for c in validated
            if c.get("valid") and c.get("quality_tier") in ("HIGH", "MEDIUM")
        ]
        if to_review:
            if verbose:
                logger.info(f"  Kör AI-granskning på {len(to_review)} kandidater...")
            try:
                from core.ai_stock_reviewer import batch_review_candidates
                reviewed = batch_review_candidates(to_review, provider=ai_provider)
                # Ersätt validerats objekt med AI-granskade
                reviewed_by_ticker = {c["ticker"]: c for c in reviewed}
                validated = [
                    reviewed_by_ticker.get(c["ticker"], c) for c in validated
                ]
            except Exception as e:
                logger.warning(f"  AI-granskning misslyckades: {e}")

    return validated


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDFUNKTION
# ══════════════════════════════════════════════════════════════════════════════

def run_discovery(
    sources: Optional[list[str]] = None,
    force: bool = False,
    validate: bool = True,
    existing_universe: Optional[set] = None,
    ai_provider: str = "auto",
    run_ai_review: bool = True,
    verbose: bool = True,
) -> list:
    """
    Kör discovery från valda källor och returnerar validerade kandidater.

    Args:
        sources:           Lista av sources att köra. Default: alla.
                           Möjliga: ["finviz", "index", "news", "ai", "etf"]
        force:             Kringgå source-cache och hämta färsk data.
        validate:          Kör yfinance-validering på kandidaterna.
        existing_universe: Set av kända tickers att filtrera bort.
        ai_provider:       AI-provider för AI-källan ("auto", "deepseek", "gemini").
        run_ai_review:     Kör AI-granskning (Layer 5) på HIGH/MEDIUM-kandidater.
        verbose:           Logga framsteg.

    Returns:
        Lista av kandidat-dikt, sorterade på confidence (högst först).
        Varje dict innehåller: ticker, source, reason, confidence, region,
        discovered, metadata, (valid, yf_data om validate=True).
    """
    if sources is None:
        sources = ["finviz", "index", "news", "ai", "etf",
                   "nordic_rss", "earnings_surprise", "analyst_upgrades"]

    all_candidates: list[dict] = []

    def _nordic_rss():
        from core.news_sentiment import fetch_nordic_rss
        return fetch_nordic_rss(existing_universe=existing_universe, force=force)

    def _earnings_surp():
        from core.news_sentiment import fetch_earnings_surprise
        return fetch_earnings_surprise(existing_universe=existing_universe, force=force)

    def _analyst_upg():
        from core.news_sentiment import fetch_analyst_upgrades
        return fetch_analyst_upgrades(existing_universe=existing_universe, force=force)

    source_fn = {
        "finviz":            lambda: _source_finviz(force=force),
        "index":             lambda: _source_index_additions(force=force),
        "news":              lambda: _source_news(force=force),
        "ai":                lambda: _source_ai(force=force, provider=ai_provider),
        "etf":               lambda: _source_etf_holdings(force=force),
        "nordic_rss":        _nordic_rss,
        "earnings_surprise": _earnings_surp,
        "analyst_upgrades":  _analyst_upg,
    }

    for src in sources:
        if src not in source_fn:
            logger.warning(f"  Okänd källa: {src} — hoppar")
            continue
        if verbose:
            logger.info(f"  Hämtar från källa: {src}...")
        try:
            batch = source_fn[src]()
            all_candidates.extend(batch)
        except Exception as e:
            logger.error(f"  Källa {src} kraschade: {e}")

    if verbose:
        logger.info(f"  Totalt {len(all_candidates)} kandidater från {len(sources)} källor")

    # Validera mot yfinance + quality gate
    if validate and all_candidates:
        all_candidates = validate_candidates(
            all_candidates,
            existing_universe=existing_universe,
            universe_type="universe",
            run_quality_gate=True,
            run_mscore=False,   # Sätt True för djupare kontroll (långsammare)
            run_ai_review=run_ai_review,
            verbose=verbose,
        )
        all_candidates = [c for c in all_candidates if c.get("valid", False)]

    # Dedup: behåll kandidat med högst confidence per ticker, samla alla sources
    by_ticker: dict[str, dict] = {}
    for c in sorted(all_candidates, key=lambda x: -x["confidence"]):
        t = c["ticker"]
        if t not in by_ticker:
            by_ticker[t] = c
        else:
            existing_src = by_ticker[t].get("all_sources", [by_ticker[t]["source"]])
            if c["source"] not in existing_src:
                existing_src.append(c["source"])
            by_ticker[t]["all_sources"] = existing_src
            if c["confidence"] > by_ticker[t]["confidence"]:
                by_ticker[t]["confidence"] = c["confidence"]
            # Bevara multi-source confidence-boost (+5% per extra källa)
            n_src = len(by_ticker[t].get("all_sources", []))
            boost = min(0.05 * (n_src - 1), 0.20)
            by_ticker[t]["confidence"] = round(
                min(by_ticker[t]["confidence"] + boost, 1.0), 3
            )

    result = sorted(by_ticker.values(), key=lambda x: -x["confidence"])
    if verbose:
        n_high = sum(1 for c in result if c.get("quality_tier") == "HIGH")
        n_med  = sum(1 for c in result if c.get("quality_tier") == "MEDIUM")
        n_spec = sum(1 for c in result if c.get("quality_tier") == "SPECULATIVE")
        logger.info(
            f"  Discovery klar: {len(result)} kandidater "
            f"(HIGH={n_high}, MEDIUM={n_med}, SPEC={n_spec})"
        )
    return result
