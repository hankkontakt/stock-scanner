"""
ai_analysis.py – MarketScan AI Engine
======================================
All-in-one AI-modul för DeepSeek-integrering i MarketScan.

Användning:
    from core.ai_analysis import analyze_stock, analyze_portfolio, ai_chat, ...
    
    # One-click aktieanalys
    result = analyze_stock("AAPL", df)       
    
    # Portföljoptimering
    result = analyze_portfolio(holdings, df)  
    
    # Fritextchatt med AI
    result = ai_chat("Vad tycker du om marknaden?")  
    
    # Veckorapport-generering
    result = generate_weekly_ai_analysis(scored, regime_info, sector_mom, news)
"""

import json
import os
import hashlib
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from . import config

# ══════════════════════════════════════════════════════════════════════════════
# KONSTANTER
# ══════════════════════════════════════════════════════════════════════════════

# Använd Path(__file__) för att alltid hamna rätt oavsett cwd (Streamlit Cloud)
_MODULE_DIR  = Path(__file__).resolve().parent.parent   # projektroten
AI_CACHE_DIR = _MODULE_DIR / "data" / "ai_cache"
try:
    AI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    AI_CACHE_DIR = Path(tempfile.gettempdir()) / "marketscan_ai_cache"
    AI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
AI_CACHE_HOURS = 24  # Cachelagra AI-svar i 24h för samma fråga

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS – Anpassade för varje AI-funktion
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_STOCK_ANALYSIS = """Du är en professionell aktieanalytiker som arbetar för MarketScan.
Din uppgift är att analysera en enskild aktie baserat på kvantitativ data och ge en tydlig rekommendation.

Du ska:
1. Analysera aktiens 8 faktorer (value, quality, momentum, growth, risk, size, dividend, sentiment)
2. Kommentera Piotroski F-Score och vad den säger om redovisningskvalitet
3. Analysera tekniska indikatorer (RSI, MACD, MA200, trend)
4. Tolka entry-signalen (STARK/OK/VÄNTA/EJ AKTUELL)
5. Ge en övergripande bedömning och tydlig rekommendation (STARKT KÖP / KÖP / BEVAKA / UNDVIK / SÄLJ)
6. Nämn specifika styrkor och svagheter

Håll analysen koncis men informativ. Skriv på svenska.
Använd fetstil för att betona nyckelinsikter. 
Max 400 ord."""

SYSTEM_PROMPT_PORTFOLIO = """Du är en professionell portföljförvaltare.
Din uppgift är att analysera användarens portfölj och föreslå förbättringar baserat på kvantitativ data.

Du ska:
1. Analysera sektorkoncentration och identifiera risker
2. Bedöma varje innehav baserat på aktuell score och entry-signal
3. Föreslå vilka innehav som bör ökas, behållas eller minskas
4. Rekommendera 2-3 nya aktier från topplistan som skulle förbättra diversifieringen
5. Ge en övergripande portföljhälsa (⭐-betyg 1-5)

Skriv på svenska. Använd fetstil för rekommendationer.
Max 500 ord."""

SYSTEM_PROMPT_WEEKLY_REPORT = """Du är en senior marknadsanalytiker som sammanfattar veckans aktiescan.
Baserat på kvantitativ data från MarketScan-systemet ska du producera en professionell veckoanalys.

Du ska:
1. Sammanfatta marknadsregimen (bull/bear/neutral) och bredden
2. Analysera topp-5 aktierna - varför de leder och om de är köpvärda
3. Bedöm sektorstyrkan: vilka sektorer leder, vilka halkar efter
4. Ge 3 konkreta köprekommendationer för kommande veckan
5. Identifiera 1 varningssignal i marknaden

Skriv på svenska som en professionell fondförvaltare.
Mellan 300-500 ord. Använd fetstil för viktiga punkter."""

SYSTEM_PROMPT_CHAT = """Du är MarketScan AI - en personlig börsanalytiker.
Du kan svara på frågor om aktier, marknader, sektorer och portföljer.

Du har tillgång till data när användaren bifogar den.
Håll svar koncisa, korrekta och användbara för en privatsparare.

Skriv på svenska om inte annat anges. Var gärna lite underhållande och använd emojis."""

SYSTEM_PROMPT_NEWS_ANALYSIS = """Du är en finansiell nyhetsanalytiker.
Din uppgift är att sammanfatta och analysera de senaste nyheterna för en aktie.

Du ska:
1. Sammanfatta varje nyhet på 1 mening
2. Bedöm om nyheten är positiv/negativ/neutral för aktien
3. Ge en övergripande bedömning av nyhetsflödet
4. Bedöm om någon nyhet är kursdrivande

Skriv på svenska. Max 300 ord."""

SYSTEM_PROMPT_MORNING_BRIEF = """Du är MarketScan AI, skapar en kort morgonbrief varje vardag.
Du ska sammanfatta dagens marknadsläge baserat på tillgänglig data.

Fokusera på:
1. Övergripande marknadssentiment (positivt/negativt/neutralt)
2. Dagens viktigaste händelser för portföljen
3. Eventuella stop-loss eller varningar
4. En aktie att hålla extra koll på idag

Skriv på svenska. Håll det kort - max 200 ord. Använd emojis."""

SYSTEM_PROMPT_SECTOR_ANALYSIS = """Du är en sektoranalytiker.
Analysera sektorns styrka baserat på scoring-data.

Du ska:
1. Bedöm sektorns relativa styrka
2. Kommentera vilka drivkrafter som påverkar sektorn
3. Nämn de starkaste och svagaste aktierna i sektorn
4. Ge en framåtblickande bedömning (1 månad)

Skriv på svenska. Max 300 ord."""

SYSTEM_PROMPT_OPPORTUNITY = """Du är en möjlighetsscanner.
Analysera aktier som uppvisar intressanta mönster (dip i upptrend, utbrott, översåld).

Du ska:
1. Bedöm om signalen är genuin eller en fälla
2. Kombinera teknisk och fundamental data
3. Ge tydlig rekommendation: Agera / Vänta / Undvik
4. Riskbedömning

Skriv på svenska. Max 250 ord per aktie."""


# ══════════════════════════════════════════════════════════════════════════════
# KÄRN-FUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _deepseek_call(messages: list, system_prompt: str = "",
                   max_tokens: int = None, temperature: float = None) -> str:
    """
    Anropa DeepSeek API med meddelanden.
    Returnerar svaret som sträng eller felmeddelande.
    """
    api_key = config.DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return "❌ **DeepSeek API-nyckel saknas.**\n\nLägg till `DEEPSEEK_API_KEY` i din `.env`-fil eller i GitHub Secrets."

    model = config.AI_MODEL
    max_tokens = max_tokens or config.AI_MAX_TOKENS
    temperature = temperature if temperature is not None else config.AI_TEMPERATURE

    payload = {
        "model": model,
        "messages": [],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].extend(messages)

    try:
        import requests
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠️ **AI-anropet misslyckades:** {str(e)}"


def _make_cache_key(*args) -> str:
    """Skapa en hash-nyckel för caching."""
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(cache_key: str, max_age_hours: int = AI_CACHE_HOURS) -> Optional[str]:
    """Hämta cachat svar om det finns och är färskt."""
    cache_file = AI_CACHE_DIR / f"{cache_key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        age = datetime.now() - datetime.fromisoformat(data["cached_at"])
        if age < timedelta(hours=max_age_hours):
            return data["response"]
    except Exception:
        pass
    return None


def _set_cache(cache_key: str, response: str):
    """Spara svar i cache."""
    try:
        cache_file = AI_CACHE_DIR / f"{cache_key}.json"
        cache_file.write_text(json.dumps({
            "cached_at": datetime.now().isoformat(),
            "response": response,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _call_with_cache(system_prompt: str, messages: list, cache_key: str,
                     max_tokens: int = None, temperature: float = None,
                     force_refresh: bool = False) -> str:
    """Anropa DeepSeek med caching. Om force_refresh=True, hoppa över cache."""
    if not force_refresh:
        cached = _get_cached(cache_key)
        if cached:
            return cached

    response = _deepseek_call(messages, system_prompt, max_tokens, temperature)
    _set_cache(cache_key, response)
    return response


# ══════════════════════════════════════════════════════════════════════════════
# 1. ONE-CLICK AKTIEANALYS (Feature 2b + 3)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_stock(ticker: str, df: pd.DataFrame = None, force_refresh: bool = False) -> str:
    """
    Analysera en enskild aktie.
    
    Args:
        ticker: Ticker-symbol (t.ex. "AAPL")
        df: DataFrame med scandata (scored_universe)
        force_refresh: Hoppa över cache
    
    Returns:
        AI-analys som formaterad text
    """
    ticker = ticker.upper().strip()

    # Hämta aktiens data från DataFrame
    stock_data = {}
    if df is not None and not df.empty and "ticker" in df.columns:
        match = df[df["ticker"] == ticker]
        if not match.empty:
            row = match.iloc[0]
            # Samla all relevant data för analys
            factor_fields = {
                "score_total": "Total Score",
                "score_value": "Value", "score_quality": "Quality",
                "score_momentum": "Momentum", "score_growth": "Growth",
                "score_risk": "Risk", "score_size": "Size",
                "score_dividend": "Dividend", "score_sentiment": "Sentiment",
                "entry_signal": "Entry Signal", "confidence_label": "Confidence",
                "trend_signal": "Trend",
                "pe_trailing": "P/E (trailing)", "pe_forward": "P/E (forward)",
                "price_to_book": "P/B", "roe": "ROE",
                "revenue_growth": "Revenue Growth", "earnings_growth": "Earnings Growth",
                "debt_to_equity": "D/E", "current_ratio": "Current Ratio",
                "dividend_yield": "Dividend Yield",
                "piotroski_f": "Piotroski F-Score",
                "rsi_14": "RSI (14)", "price_vs_ma50": "vs MA50",
                "price_vs_ma200": "vs MA200", "macd_above_signal": "MACD above Signal",
                "return_1m": "1m Return", "return_3m": "3m Return",
                "return_6m": "6m Return", "return_12m": "12m Return",
                "volatility": "Volatility", "beta": "Beta",
                "sector": "Sector", "name": "Company Name",
                "current_price": "Price",
            }
            for field, label in factor_fields.items():
                val = row.get(field)
                if val is not None and not pd.isna(val):
                    if isinstance(val, float):
                        stock_data[label] = round(val, 2)
                    else:
                        stock_data[label] = val

    # Bygg prompt
    data_str = json.dumps(stock_data, indent=2, ensure_ascii=False) if stock_data else "Ingen data tillgänglig för denna aktie."
    user_message = f"Analysera aktien **{ticker}**.\n\nTillgänglig data:\n```json\n{data_str}\n```"

    cache_key = _make_cache_key("analyze_stock", ticker, data_str[:500] if stock_data else "no_data")
    return _call_with_cache(
        SYSTEM_PROMPT_STOCK_ANALYSIS,
        [{"role": "user", "content": user_message}],
        cache_key,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. PORTFÖLJOPTIMERING (Feature 4)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_portfolio(holdings: pd.DataFrame, df: pd.DataFrame = None,
                      force_refresh: bool = False) -> str:
    """
    Analysera och optimera portföljen.
    
    Args:
        holdings: DataFrame med portföljinnehav (ticker, shares, cost_basis)
        df: DataFrame med scandata (för aktuella scores)
        force_refresh: Hoppa över cache
    
    Returns:
        AI-analys med rekommendationer
    """
    if holdings.empty:
        return "⚠️ **Portföljen är tom.** Lägg till innehav först."

    # Berika med scan-data
    enriched = []
    total_value = 0
    score_lookup = {}
    if df is not None and not df.empty and "ticker" in df.columns:
        score_lookup = df.set_index("ticker").to_dict("index")

    for _, h in holdings.iterrows():
        t = str(h.get("ticker", "")).upper()
        shares = float(h.get("shares", 0))
        cost = float(h.get("cost_basis", 0))
        sc = score_lookup.get(t, {})
        price = sc.get("current_price", 0)
        mv = price * shares if price and shares else 0
        total_value += mv
        pnl = ((price / cost) - 1) * 100 if price and cost > 0 else 0
        enriched.append({
            "ticker": t,
            "shares": shares,
            "cost_basis": cost,
            "current_price": round(price, 2) if price else "N/A",
            "market_value": round(mv, 0),
            "pnl_pct": round(pnl, 1),
            "score": sc.get("score_total", "N/A"),
            "sector": sc.get("sector", "N/A"),
            "entry_signal": sc.get("entry_signal", "N/A"),
            "trend": sc.get("trend_signal", "N/A"),
        })

    # Hitta topp-10 aktier som inte är i portföljen
    top_candidates = []
    if df is not None and not df.empty and "ticker" in df.columns:
        held_tickers = {h.get("ticker", "").upper() for h in enriched}
        top_df = df[~df["ticker"].isin(held_tickers)].head(10)
        for _, r in top_df.iterrows():
            top_candidates.append({
                "ticker": r.get("ticker"),
                "name": r.get("name", ""),
                "score": r.get("score_total", 0),
                "sector": r.get("sector", ""),
                "entry": r.get("entry_signal", ""),
            })

    portfolio_summary = {
        "total_value": round(total_value, 0),
        "num_positions": len(enriched),
        "holdings": enriched,
        "top_candidates": top_candidates,
    }

    data_str = json.dumps(portfolio_summary, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("analyze_portfolio", str(holdings.shape), str(df.shape) if df is not None else "none")

    return _call_with_cache(
        SYSTEM_PROMPT_PORTFOLIO,
        [{"role": "user", "content": f"Analysera min portfölj och föreslå förbättringar.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3. FREE-TEXT AI CHATT (Feature 2a)
# ══════════════════════════════════════════════════════════════════════════════

def ai_chat(question: str, context: str = "", force_refresh: bool = False) -> str:
    """
    Fritextfråga till AI:n.
    
    Args:
        question: Användarens fråga
        context: Extra kontext (t.ex. aktuell scandata i JSON)
        force_refresh: Hoppa över cache
    
    Returns:
        AI-svar
    """
    user_message = question
    if context:
        user_message = f"{question}\n\nKontextdata:\n```json\n{context}\n```"

    # Ingen cache för chatt - varje fråga är unik
    return _deepseek_call(
        [{"role": "user", "content": user_message}],
        SYSTEM_PROMPT_CHAT,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. VECKORAPPORT-AI (Feature 1)
# ══════════════════════════════════════════════════════════════════════════════

def generate_weekly_ai_analysis(scored_df: pd.DataFrame, regime_info: dict,
                                 sector_momentum: dict = None, news: dict = None,
                                 force_refresh: bool = False) -> str:
    """
    Skapa AI-analyssektion för veckorapporten.
    Anropas från scan.py -> build_report().
    """
    if scored_df.empty:
        return ""

    # Sammanställ datalager
    top5 = scored_df.head(5)
    top5_data = []
    for _, r in top5.iterrows():
        entry = {k: (None if isinstance(v, float) and pd.isna(v) else v)
                 for k, v in r.to_dict().items()
                 if k in ["ticker", "name", "sector", "score_total", "entry_signal",
                          "confidence_label", "trend_signal", "rs_label",
                          "score_value", "score_quality", "score_momentum",
                          "score_growth", "score_risk", "score_sentiment",
                          "pe_trailing", "return_1m", "return_3m", "return_6m"]}
        top5_data.append(entry)

    # Sektorinfo
    sector_info = {}
    if "sector" in scored_df.columns and "score_total" in scored_df.columns:
        sector_agg = scored_df.groupby("sector")["score_total"].agg(["mean", "count", "max"])
        sector_info = sector_agg.to_dict("index")

    # Marknadsregim
    regime = (regime_info or {}).get("regime", "OSÄKER")
    spy_vs_ma200 = (regime_info or {}).get("spy_vs_ma200", "N/A")
    breadth = (regime_info or {}).get("breadth_delta", "N/A")
    vix = (regime_info or {}).get("vix_level", "N/A")

    data_summary = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "universe_size": len(scored_df),
        "regime": regime,
        "spy_vs_ma200_pct": spy_vs_ma200,
        "market_breadth_delta": breadth,
        "vix": vix,
        "top_5": top5_data,
        "sectors": {str(k): v for k, v in sector_info.items()},
        "factor_weights": config.FACTOR_WEIGHTS,
    }

    data_str = json.dumps(data_summary, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("weekly_ai", datetime.now().strftime("%Y-%m-%d"))

    result = _call_with_cache(
        SYSTEM_PROMPT_WEEKLY_REPORT,
        [{"role": "user", "content": f"Generera veckoanalys för dagens scan.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=2048,
        force_refresh=True,  # Alltid fräsch data för veckorapport
    )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 5. NYHETSANALYS (Feature 5)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_news(ticker: str, news_items: list = None, force_refresh: bool = False) -> str:
    """
    Analysera nyheter för en aktie.
    
    Args:
        ticker: Ticker-symbol
        news_items: Lista med nyheter (dict med titel, url, datum, sammanfattning)
        force_refresh: Hoppa över cache
    
    Returns:
        AI-sammanfattning av nyheter
    """
    if not news_items:
        return f"ℹ️ Inga nyheter tillgängliga för **{ticker}**."

    news_text = json.dumps(news_items[:10], indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("analyze_news", ticker, str(len(news_items)))

    return _call_with_cache(
        SYSTEM_PROMPT_NEWS_ANALYSIS,
        [{"role": "user", "content": f"Analysera nyheterna för {ticker}.\n\nNyheter:\n{news_text}"}],
        cache_key,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6. MORGONBRIEF (Feature 6)
# ══════════════════════════════════════════════════════════════════════════════

def generate_morning_brief(market_data: dict = None,
                            portfolio_data: dict = None,
                            alerts_list: list = None,
                            opportunities: list = None,
                            force_refresh: bool = False) -> str:
    """
    Skapa AI-genererad morgonbrief.
    Anropas från morning_scan.py.
    """
    brief_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market": market_data or {},
        "portfolio": portfolio_data or {},
        "alerts": alerts_list or [],
        "opportunities": opportunities or [],
    }
    
    data_str = json.dumps(brief_data, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("morning_brief", datetime.now().strftime("%Y-%m-%d"))

    return _call_with_cache(
        SYSTEM_PROMPT_MORNING_BRIEF,
        [{"role": "user", "content": f"Skapa dagens morgonbrief.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=1024,
        force_refresh=True,  # Alltid fräsch
    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. SEKTORANALYS (Feature 2d)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_sector(sector_name: str, df: pd.DataFrame = None,
                   force_refresh: bool = False) -> str:
    """
    Analysera en specifik sektor.
    
    Args:
        sector_name: Sektornamn (t.ex. "Technology")
        df: DataFrame med scandata
        force_refresh: Hoppa över cache
    
    Returns:
        AI-sektoranalys
    """
    sector_data = {}
    if df is not None and not df.empty and "sector" in df.columns and "score_total" in df.columns:
        sector_df = df[df["sector"] == sector_name]
        if not sector_df.empty:
            sector_data = {
                "sector": sector_name,
                "num_stocks": len(sector_df),
                "avg_score": round(sector_df["score_total"].mean(), 1),
                "top_stocks": sector_df.nlargest(3, "score_total")[
                    ["ticker", "score_total", "entry_signal", "return_6m"]
                ].fillna("N/A").to_dict("records"),
                "bottom_stocks": sector_df.nsmallest(3, "score_total")[
                    ["ticker", "score_total", "entry_signal", "return_6m"]
                ].fillna("N/A").to_dict("records"),
                "avg_metrics": {
                    "avg_pe": round(sector_df["pe_trailing"].mean(), 1) if "pe_trailing" in sector_df.columns else "N/A",
                    "avg_momentum": round(sector_df["score_momentum"].mean(), 1) if "score_momentum" in sector_df.columns else "N/A",
                    "avg_value": round(sector_df["score_value"].mean(), 1) if "score_value" in sector_df.columns else "N/A",
                }
            }

    if not sector_data:
        return f"⚠️ Ingen data för sektorn **{sector_name}**."

    data_str = json.dumps(sector_data, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("analyze_sector", sector_name, str(df.shape) if df is not None else "none")

    return _call_with_cache(
        SYSTEM_PROMPT_SECTOR_ANALYSIS,
        [{"role": "user", "content": f"Analysera sektorn {sector_name}.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 8. MÖJLIGHETSANALYS (Feature 7)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_opportunity(ticker: str, signal_type: str,
                         stock_data: dict = None,
                         force_refresh: bool = False) -> str:
    """
    Analysera en opportunity-signal.
    
    Args:
        ticker: Ticker-symbol
        signal_type: "dip", "breakout", "oversold"
        stock_data: Dict med relevant data
        force_refresh: Hoppa över cache
    
    Returns:
        AI-analys av möjligheten
    """
    data = {
        "ticker": ticker,
        "signal_type": signal_type,
        "data": stock_data or {},
    }
    data_str = json.dumps(data, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("analyze_opportunity", ticker, signal_type)

    return _call_with_cache(
        SYSTEM_PROMPT_OPPORTUNITY,
        [{"role": "user", "content": f"Analysera denna möjlighet.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=1024,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 9. JÄMFÖR TVÅ AKTIER (Feature 2c)
# ══════════════════════════════════════════════════════════════════════════════

def compare_stocks(ticker_a: str, ticker_b: str, df: pd.DataFrame = None,
                   force_refresh: bool = False) -> str:
    """
    Jämför två aktier sida vid sida.
    
    Args:
        ticker_a: Första ticker
        ticker_b: Andra ticker
        df: DataFrame med scandata
        force_refresh: Hoppa över cache
    
    Returns:
        AI-jämförelse
    """
    comparison = {"ticker_a": {}, "ticker_b": {}}
    if df is not None and not df.empty and "ticker" in df.columns:
        for ticker, key in [(ticker_a, "ticker_a"), (ticker_b, "ticker_b")]:
            match = df[df["ticker"] == ticker.upper()]
            if not match.empty:
                row = match.iloc[0]
                fields = ["score_total", "score_value", "score_quality",
                          "score_momentum", "score_growth", "score_risk",
                          "entry_signal", "trend_signal",
                          "pe_trailing", "roe", "revenue_growth",
                          "rsi_14", "price_vs_ma200",
                          "return_1m", "return_3m", "return_6m", "return_12m",
                          "sector", "name", "current_price"]
                for f in fields:
                    val = row.get(f)
                    if val is not None and not pd.isna(val):
                        comparison[key][f] = round(val, 2) if isinstance(val, float) else val

    data_str = json.dumps(comparison, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("compare_stocks", ticker_a, ticker_b,
                                 str(df.shape) if df is not None else "none")

    user_msg = f"Jämför aktierna **{ticker_a}** och **{ticker_b}**.\n\nData:\n```json\n{data_str}\n```"
    sys_prompt = """Du jämför två aktier. Ge ett tydligt svar om:
1. Vilken aktie som är starkast totalt
2. Skillnader i momentum, värdering och kvalitet
3. Din rekommendation: vilken är bäst att köpa JUST NU?
4. Varför

Skriv på svenska. Max 300 ord."""

    return _call_with_cache(
        sys_prompt,
        [{"role": "user", "content": user_msg}],
        cache_key,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 10. MARKNADSSAMMANFATTNING (Feature 8)
# ══════════════════════════════════════════════════════════════════════════════

def generate_market_summary(df: pd.DataFrame = None, sc_df: pd.DataFrame = None,
                             regime_info: dict = None,
                             force_refresh: bool = False) -> str:
    """
    Skapa en kort marknadssammanfattning för dashboard.
    
    Args:
        df: DataFrame med global scandata
        sc_df: DataFrame med smallcap scandata
        regime_info: Dict med marknadsregim-info
        force_refresh: Hoppa över cache
    
    Returns:
        AI-marknadssammanfattning (kort)
    """
    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "regime": (regime_info or {}).get("regime", "N/A"),
        "global": {},
        "smallcap": {},
    }

    if df is not None and not df.empty:
        summary["global"] = {
            "n_stocks": len(df),
            "avg_score": round(df["score_total"].mean(), 1) if "score_total" in df.columns else "N/A",
            "n_top": int((df.get("entry_signal") == "STARK").sum()) if "entry_signal" in df.columns else 0,
            "top_ticker": df.nlargest(1, "score_total").iloc[0].get("ticker", "N/A") if "score_total" in df.columns else "N/A",
            "top_score": round(df.nlargest(1, "score_total").iloc[0].get("score_total", 0), 1) if "score_total" in df.columns else 0,
        }

    if sc_df is not None and not sc_df.empty:
        score_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
        summary["smallcap"] = {
            "n_stocks": len(sc_df),
            "avg_score": round(sc_df[score_col].mean(), 1) if score_col in sc_df.columns else "N/A",
        }

    data_str = json.dumps(summary, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("market_summary", datetime.now().strftime("%Y-%m-%d"))

    return _call_with_cache(
        """Du är MarketScan AI-assistent. Skapa en KORT marknadssammanfattning (max 150 ord).
Skriv på svenska, använd emojis. Fokusera på dagens viktigaste insikter.""",
        [{"role": "user", "content": f"Skapa en kort marknadssammanfattning.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=512,
        force_refresh=force_refresh,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 10. VALIDERING – Testa API-nyckeln
# ══════════════════════════════════════════════════════════════════════════════

def test_api_key() -> dict:
    """
    Testa om DeepSeek API-nyckeln fungerar.
    Returnerar dict med status och meddelande.
    """
    api_key = config.DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API-nyckel saknas"}

    try:
        import requests
        resp = requests.post(
            "https://api.deepseek.com/v1/models",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return {"status": "ok", "message": f"API-nyckel fungerar! Modell: {config.AI_MODEL}"}
        elif resp.status_code == 401:
            return {"status": "error", "message": "API-nyckel är ogiltig (401)"}
        else:
            return {"status": "warning", "message": f"API svarade med status {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"Kunde inte nå DeepSeek API: {e}"}


def clear_cache():
    """Rensa all AI-cache."""
    import shutil
    if AI_CACHE_DIR.exists():
        shutil.rmtree(AI_CACHE_DIR)
        AI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return "✅ AI-cache rensad!"
    return "ℹ️ Ingen cache att rensa."
