"""
ai_analysis.py – MarketScan AI Engine (Multi-Provider)
======================================================
Stöder både DeepSeek (komplex, kostar) och Google Gemini (enkel, gratis).

Användning:
    from core.ai_analysis import analyze_stock, analyze_portfolio, ai_chat, ...

    # Auto-välj provider baserat på AI_PROVIDER i config
    result = analyze_stock("AAPL", df)

    # Tvinga en specifik provider
    result = analyze_stock("AAPL", df, provider="gemini")
    result = analyze_stock("AAPL", df, provider="deepseek")
"""

import json
import os
import hashlib
import tempfile
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config

# Import news_fetcher (graceful if unavailable)
try:
    from core.news_fetcher import fetch_company_news as _fetch_news_ai
except ImportError:
    _fetch_news_ai = None

_logger = logging.getLogger(__name__)
_token_sanitize = __import__("re").compile(r"(sk-[a-zA-Z0-9]{10,}|AIza[a-zA-Z0-9_-]{20,})")


# ── Runtime-säker secret-läsare ────────────────────────────────────────────
# config.py läser nycklar vid import-tid. På Streamlit Cloud är st.secrets
# inte tillgängligt då. Denna funktion försöker os.environ först (GitHub
# Actions, lokal .env) och faller tillbaka till st.secrets vid runtime.
def _get_secret(key: str, default: str = "") -> str:
    """Läs API-nyckel från miljövariabel. Fallback till st.secrets vid runtime."""
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default


# ── Depth-nivå → max_tokens mapping ──────────────────────────────────────────
DEPTH_MAP = {
    "Snabb":      512,
    "Normal":     2048,
    "Djup":       4096,
    "Extra djup": 8192,
}

def _resolve_depth(depth: str = "Normal") -> int:
    """Mappa användarens depth-val til max_tokens.

    Args:
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"

    Returns:
        max_tokens-värde (int)
    """
    return DEPTH_MAP.get(depth, 1024)


# ── Djup-medveten prompt & data-filtrering ────────────────────────────────────

# Nycklar som visas för varje djupnivå i analyze_stock
SNABB_KEYS = {
    "P/E (trailing)", "ROE", "Momentum", "Revenue Growth",
    "Piotroski F-Score", "Entry Signal",
}

def _build_depth_context(stock_data: dict, depth: str) -> dict:
    """Filtrera stock_data-dict baserat på vald djupnivå.
    'Snabb' → bara de viktigaste 6 nyckeltalen.
    'Normal'/'Djup'/'Extra djup' → returnerar orört (allt som finns)."""
    if depth == "Snabb":
        return {k: v for k, v in stock_data.items() if k in SNABB_KEYS}
    return stock_data   # Normal, Djup, Extra djup: inga filter


def _depth_system_prompt_addon(depth: str) -> str:
    """Returnerar extra instruktion att lägga till i system-prompten."""
    if depth == "Snabb":
        return "\n\nGe ett kortfattat svar på max 3 meningar."
    if depth == "Djup":
        return (
            "\n\nGör en djupgående analys med teknisk analys, sektorjämförelse och "
            "fundamentala nyckeltal. Inkludera en konkret köp/sälj-rekommendation med motivering."
        )
    if depth == "Extra djup":
        return (
            "\n\nGör en heltäckande institutionell analys. Inkludera: "
            "1) FCF-analys och historisk värdering "
            "2) Scenarioanalys (bull/base/bear) "
            "3) Risker och katalysatorer "
            "4) Konkret positionsstorlek och entry/exit"
        )
    return ""   # "Normal" → inga tillägg


def _is_swedish_stock(ticker: str) -> bool:
    return str(ticker).upper().endswith(".ST")


def _k3_accounting_note(ticker: str, depth: str) -> str:
    """För Djup/Extra djup på svenska aktier: notering om K3/K2-redovisning."""
    if depth in ("Djup", "Extra djup") and _is_swedish_stock(ticker):
        return (
            "\n\n**OBS – Svensk redovisning (K3/K2):** Obeskattade reserver kan reducera "
            "redovisat resultat. ROA och marginaler är troligen undervärdering av faktisk lönsamhet."
        )
    return ""


# ── Numpy/pandas-safe JSON-serialisering ─────────────────────────────────────
def _safe_json(obj: dict, **kwargs) -> str:
    """json.dumps som hanterar numpy.int64, numpy.float64, pd.Timestamp m.fl."""
    def _convert(v):
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        if isinstance(v, (np.bool_,)):
            return bool(v)
        if isinstance(v, np.ndarray):
            return v.tolist()
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if isinstance(v, (pd.Series, pd.DataFrame)):
            return v.to_dict() if isinstance(v, pd.Series) else v.to_dict(orient="records")
        return v
    return json.dumps(obj, default=_convert, **kwargs)

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

# Provider-namn för UI
PROVIDER_LABELS = {
    "deepseek": "DeepSeek (komplex, kostar)",
    "gemini":   "Gemini (enkel, gratis)",
}

# Gemini-modeller att prova i ordning vid 404 (deprecation eller regionsbegränsning).
# Free-tier-tillgängliga modeller per 2026. gemini-1.5-flash deprecated okt 2024.
GEMINI_FALLBACK_MODELS = [
    "gemini-2.5-flash",          # nyaste stable
    "gemini-2.0-flash",          # föregående stable
    "gemini-flash-latest",       # alias för senaste flash
    "gemini-2.5-flash-lite",     # ännu lättare variant
    "gemini-pro-latest",         # legacy fallback
]

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS – Anpassade för varje AI-funktion
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_STOCK_ANALYSIS = """Du är en professionell aktieanalytiker som arbetar för MarketScan.
Din uppgift är att analysera en enskild aktie baserat på kvantitativ data och nyheter, och ge en tydlig rekommendation.

Du ska:
1. Analysera aktiens 8 faktorer (value, quality, momentum, growth, risk, size, dividend, sentiment)
2. Kommentera Piotroski F-Score och vad den säger om redovisningskvalitet
3. Analysera tekniska indikatorer (RSI, MACD, MA200, trend)
4. Tolka entry-signalen (STARK/OK/VÄNTA/EJ AKTUELL)
5. **Väg in nyheterna** – om nyheter finns med i datan, bedöm hur de påverkar aktien positivt eller negativt
6. Ge en övergripande bedömning och tydlig rekommendation (STARKT KÖP / KÖP / BEVAKA / UNDVIK / SÄLJ)
7. Nämn specifika styrkor och svagheter

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

Du har tillgång till data när användaren bifogar den i sitt meddelande.
Detta inkluderar scandata, nyckeltal OCH nyhetsrubriker som hämtats live via API.
När nyheter finns med i kontexten ska du referera till dem direkt och konkret.
Säg ALDRIG att du saknar tillgång till nyheter – om nyheter bifogas i meddelandet har du dem.

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
# HJÄLPFUNKTIONER – Bestäm provider
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_provider(provider: str = "auto", task_type: str = "light") -> str:
    """Avgör vilken AI-provider som ska användas.
    
    Args:
        provider: "auto" (läs från config), "deepseek", eller "gemini"
        task_type: "light" (standard, gratis), "heavy" (komplex), eller "deep" (endast deepseek)
    
    Returns:
        "deepseek" eller "gemini"
    """
    if provider != "auto":
        return provider
    
    task_mode = getattr(config, "AI_TASK_MODE", "hybrid")
    
    # "gemini": alltid gemini (om man vill spara pengar helt)
    if task_mode == "gemini":
        return "gemini"
    # "deepseek": alltid deepseek (om man vill ha högst kvalitet)
    if task_mode == "deepseek":
        return "deepseek"
    
    # "hybrid" (default): light->gemini, heavy/deep->deepseek
    if task_type in ("deep", "heavy"):
        # Djupa/tunga analyser använder alltid DeepSeek
        return getattr(config, "AI_DEEP_PROVIDER", "deepseek") or "deepseek"
    else:
        # "light": använd standard-provider (nu gemini)
        return getattr(config, "AI_PROVIDER", "gemini") or "gemini"


# ══════════════════════════════════════════════════════════════════════════════
# KÄRN-FUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _deepseek_call(messages: list, system_prompt: str = "",
                   max_tokens: int = None, temperature: float = None) -> str:
    """
    Anropa DeepSeek API med meddelanden och exponential backoff retry.
    
    Retry-logik:
      - 429 (rate-limit):   vänta 5s, 10s, 20s
      - 5xx (server error): vänta 2s, 4s, 8s
      - timeout:            vänta 1s, 2s, 4s
      - 401/403:            ge upp direkt (nyckelproblem)
      
    Returnerar svaret som sträng eller felmeddelande.
    """
    api_key = _get_secret("DEEPSEEK_API_KEY", "")
    if not api_key:
        return "❌ **DeepSeek API-nyckel saknas.**\n\nLägg till `DEEPSEEK_API_KEY` i din `.env`-fil."

    model = getattr(config, "AI_MODEL", "deepseek-chat")
    max_tokens = max_tokens or getattr(config, "AI_MAX_TOKENS", 2048)
    temperature = temperature if temperature is not None else getattr(config, "AI_TEMPERATURE", 0.3)

    payload = {
        "model": model,
        "messages": [],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].extend(messages)

    import time
    import requests

    max_retries = 3
    last_error = ""

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )

            # ✅ Success
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content

            # ❌ 401/403 – nyckelproblem, ge upp direkt
            if resp.status_code in (401, 403):
                try:
                    body = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    body = resp.text[:200]
                body = _token_sanitize.sub("***", body)
                return f"❌ **DeepSeek nekade åtkomst ({resp.status_code}):** {body}"

            # ❌ 429 – rate-limit, vänta längre (exponential backoff)
            if resp.status_code == 429:
                delay = 5.0 * (2 ** attempt)  # 5s, 10s, 20s
                last_error = f"⚠️ DeepSeek rate-limit (429) – väntar {delay:.0f}s (försök {attempt+1}/{max_retries})"
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                # Om sista retryn också är 429, returnera DeepSeek-fel och låt _ai_call falla tillbaka
                return f"⚠️ **DeepSeek rate-limited efter {max_retries} försök.** Försök igen senare."

            # ❌ 5xx – server error, retry med kort backoff
            if 500 <= resp.status_code < 600:
                delay = 2.0 * (2 ** attempt)  # 2s, 4s, 8s
                last_error = f"⚠️ DeepSeek server error ({resp.status_code}) – väntar {delay:.0f}s"
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                return f"⚠️ **DeepSeek svarade {resp.status_code} efter {max_retries} försök.** Försök igen senare."

            # ❌ Övriga statuskoder
            try:
                body = resp.text[:200]
            except Exception:
                body = ""
            last_error = f"⚠️ **DeepSeek svarade {resp.status_code}:** {body}"
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return last_error

        except requests.exceptions.Timeout:
            delay = 1.0 * (2 ** attempt)  # 1s, 2s, 4s
            last_error = f"⚠️ DeepSeek timeout – väntar {delay:.0f}s"
            if attempt < max_retries - 1:
                time.sleep(delay)
                continue
            return f"⚠️ **DeepSeek timeout efter {max_retries} försök.** Kontrollera anslutningen."

        except requests.exceptions.ConnectionError:
            last_error = "⚠️ DeepSeek anslutningsfel (ConnectionError)"
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return f"⚠️ **DeepSeek anslutningsfel efter {max_retries} försök.** Kolla internet/din API-endpoint."

        except Exception as e:
            last_error = f"⚠️ **DeepSeek-anropet misslyckades:** {str(e)}"
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            return last_error

    # Borde inte nå hit, men fallback
    return last_error or "⚠️ **DeepSeek: okänt fel.** Försök igen."


def _gemini_call(messages: list, system_prompt: str = "",
                 max_tokens: int = None, temperature: float = None,
                 use_grounding: bool = False) -> str:
    """
    Anropa Google Gemini API med meddelanden via REST.
    Vid 404 (deprecation) provas automatiskt nästa modell i GEMINI_FALLBACK_MODELS.
    Innehåller retry-logik med exponential backoff vid 429 rate-limit.
    Returnerar svaret som sträng, "" (tomt = fallback till DeepSeek),
    eller felmeddelande som börjar med "⚠️".
    """
    api_key = _get_secret("GEMINI_API_KEY", "")
    if not api_key:
        return ""

    # Bygg modellista: konfigurerad modell först, sedan fallback-kandidater.
    configured = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")
    models_to_try = [configured] + [m for m in GEMINI_FALLBACK_MODELS if m != configured]
    max_tokens = max_tokens or getattr(config, "AI_MAX_TOKENS", 2048)
    temperature = temperature if temperature is not None else getattr(config, "AI_TEMPERATURE", 0.3)

    # Gemini använder system-instruction separat och contents-format
    contents = []
    for msg in messages:
        if msg.get("role") == "user":
            contents.append({
                "role": "user",
                "parts": [{"text": msg.get("content", "")}]
            })
        elif msg.get("role") == "assistant":
            contents.append({
                "role": "model",
                "parts": [{"text": msg.get("content", "")}]
            })

    payload = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        }
    }

    if system_prompt:
        payload["systemInstruction"] = {
            "parts": [{"text": system_prompt}]
        }

    # Google Search Grounding: Gemini söker automatiskt på Google under inference
    # när konfidensen i träningsdata är låg (t.ex. för oklara nyheter om aktier).
    # Gratis upp till 50 grounded queries/dag; triggas bara vid Djup/Extra djup + inget nyhetsflöde.
    if use_grounding:
        payload["tools"] = [{"google_search": {}}]

    import time
    import requests

    max_retries = 3
    last_error = ""
    tried_models = []

    # Yttre loop: iterera över modeller (byt vid 404).
    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        tried_models.append(model)
        model_got_404 = False

        # Inre loop: retry vid 429/timeout/etc för aktuell modell.
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    url,
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=60,
                )

                if resp.status_code == 200:
                    data = resp.json()

                    # Kolla om prompten blockerades (t.ex. SAFETY)
                    prompt_feedback = data.get("promptFeedback", {})
                    block_reason = prompt_feedback.get("blockReason", "")
                    if block_reason:
                        return f"⚠️ **Gemini blockerade frågan ({block_reason}).** Försök omformulera."

                    candidates = data.get("candidates", [])
                    if not candidates:
                        last_error = "⚠️ **Gemini: tomt svar (inga kandidater).** Försök igen."
                        time.sleep(1)
                        continue

                    candidate = candidates[0]
                    finish_reason = candidate.get("finishReason", "STOP")
                    if finish_reason not in ("STOP", "MAX_TOKENS", ""):
                        return f"⚠️ **Gemini avbröt svaret ({finish_reason}).** Försök igen."

                    parts = candidate.get("content", {}).get("parts", [])
                    if not parts:
                        last_error = "⚠️ **Gemini: tomt svar (inga delar).** Försök igen."
                        time.sleep(1)
                        continue

                    text = parts[0].get("text", "").strip()
                    if not text:
                        last_error = "⚠️ **Gemini: tomt svar.** Försök igen."
                        time.sleep(1)
                        continue

                    # Notera vilken modell som faktiskt fungerade om vi var tvungna att byta
                    if model != configured:
                        text += f"\n\n---\n*ℹ️ Använde Gemini-modell `{model}` (konfigurerad `{configured}` ej tillgänglig)*"
                    return text

                elif resp.status_code == 400:
                    try:
                        body = resp.json().get("error", {}).get("message", resp.text[:200])
                    except Exception:
                        body = resp.text[:200]
                    return f"⚠️ **Gemini: ogiltig förfrågan (400):** {body}"

                elif resp.status_code == 403:
                    try:
                        body = resp.json().get("error", {}).get("message", resp.text[:200])
                    except Exception:
                        body = resp.text[:200]
                    if "API_KEY_INVALID" in body or "API key not valid" in body:
                        return ""
                    return f"⚠️ **Gemini nekade åtkomst (403):** {body}"

                elif resp.status_code == 404:
                    # Modellen finns inte → bryt inre loop, gå till nästa modell.
                    last_error = f"⚠️ **Gemini: modell '{model}' hittades inte (404).**"
                    model_got_404 = True
                    break

                elif resp.status_code == 429:
                    delay = 5.0 * (2 ** attempt)  # 5s, 10s, 20s
                    last_error = f"⚠️ **Gemini rate-limit (429)** – väntar {delay:.0f}s..."
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue
                    return ""  # uttömda retries → fallback till DeepSeek

                else:
                    try:
                        body = resp.text[:200]
                    except Exception:
                        body = ""
                    last_error = f"⚠️ **Gemini svarade {resp.status_code}:** {body}"
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    return last_error

            except requests.exceptions.Timeout:
                last_error = "⚠️ **Gemini timeout – försök igen.**"
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return last_error
            except Exception as e:
                last_error = f"⚠️ **Gemini-anropet misslyckades:** {str(e)}"
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                return last_error

        # Om vi inte fick 404, sluta prova fler modeller (felet är inte modellrelaterat).
        if not model_got_404:
            break

    # Alla modeller gav 404 (eller annat fatalt)
    return last_error or f"⚠️ **Gemini: ingen av modellerna fungerade.** Provade: {', '.join(tried_models)}"


def _ai_call(messages: list, system_prompt: str = "",
             max_tokens: int = None, temperature: float = None,
             provider: str = "auto", use_grounding: bool = False) -> str:
    """
    Anropa vald AI-provider med meddelanden.
    Routar automatiskt till DeepSeek eller Gemini baserat på provider-parametern.

    Om Gemini är rate-limited (429) eller returnerar tomt svar,
    faller den automatiskt tillbaka till DeepSeek om nyckeln finns.

    Args:
        messages: Lista med dicts {"role": "user"/"assistant", "content": "..."}
        system_prompt: System-prompt som sätter ton och instruktioner
        max_tokens: Max tokens i svaret
        temperature: Kreativitet (0.0 = deterministisk, 1.0 = slumpmässig)
        provider: "auto", "deepseek" eller "gemini"
        use_grounding: Om True och provider==gemini: aktivera Google Search Grounding

    Returns:
        AI-svar som formaterad text
    """
    resolved = _resolve_provider(provider)

    if resolved == "gemini":
        result = _gemini_call(messages, system_prompt, max_tokens, temperature,
                              use_grounding=use_grounding)
        # Fallback till DeepSeek om Gemini misslyckas:
        #   - tomt svar ""  (ogiltig nyckel, 429 uttömd, 403)
        #   - felmeddelande som börjar med "⚠️" (rate-limit, timeout, blockering)
        gemini_failed = not result or result.startswith("⚠️")
        if gemini_failed:
            deepseek_key = _get_secret("DEEPSEEK_API_KEY", "")
            if deepseek_key:
                ds_result = _deepseek_call(messages, system_prompt, max_tokens, temperature)
                if not ds_result.startswith("⚠️") and not ds_result.startswith("❌"):
                    gemini_reason = result if result else "ingen nyckel/tomt svar"
                    return ds_result + f"\n\n---\n*ℹ️ Gemini ej tillgänglig ({gemini_reason[:60]}) – svar från DeepSeek (fallback)*"
                # DeepSeek misslyckades också – visa Geminis ursprungliga fel
                return result or "⚠️ **Varken Gemini eller DeepSeek svarade.** Kontrollera dina API-nycklar."
            # Ingen DeepSeek-nyckel – visa Geminis fel direkt
            return result or "⚠️ **Gemini ej tillgänglig.** Kontrollera GEMINI_API_KEY i Streamlit Secrets."
        return result
    else:
        return _deepseek_call(messages, system_prompt, max_tokens, temperature)


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
    """Spara svar i cache med atomic write (tmp + rename) för att undvika
    korrupt JSON vid parallella skrivningar."""
    if response is None:
        return
    try:
        cache_file = AI_CACHE_DIR / f"{cache_key}.json"
        tmp_file = cache_file.with_suffix(".json.tmp")
        tmp_file.write_text(json.dumps({
            "cached_at": datetime.now().isoformat(),
            "response": response,
        }, ensure_ascii=False), encoding="utf-8")
        # os.replace är atomic på alla plattformar
        os.replace(tmp_file, cache_file)
    except Exception:
        pass


def _call_with_cache(system_prompt: str, messages: list, cache_key: str,
                     max_tokens: int = None, temperature: float = None,
                     force_refresh: bool = False,
                     provider: str = "auto",
                     use_grounding: bool = False) -> str:
    """Anropa AI med caching. Om force_refresh=True, hoppa över cache."""
    if not force_refresh:
        cached = _get_cached(cache_key)
        if cached:
            return cached

    response = _ai_call(messages, system_prompt, max_tokens, temperature,
                        provider=provider, use_grounding=use_grounding)
    _set_cache(cache_key, response)
    return response


# ══════════════════════════════════════════════════════════════════════════════
# 1. ONE-CLICK AKTIEANALYS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_stock(ticker: str, df: pd.DataFrame = None,
                  force_refresh: bool = False,
                  provider: str = "auto",
                  depth: str = "Normal",
                  user_position: dict | None = None) -> str:
    """
    Analysera en enskild aktie.

    Args:
        ticker: Ticker-symbol (t.ex. "AAPL")
        df: DataFrame med scandata (scored_universe)
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
        user_position: Dict med användarens position, t.ex.
            {"shares": 100, "cost_basis": 245.50, "current_price": 280.0}
            Om angivet läggs info om innehav och P&L till i promoten.

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
                "payout_ratio": "Payout Ratio",
                "div_yield_5y_avg": "5Y Avg Dividend Yield",
                "dividend_rate": "Annual Dividend/Share",
                "free_cash_flow": "Free Cash Flow",
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

            # Extra fält för Djup / Extra djup
            if depth in ("Djup", "Extra djup"):
                extra_fields = {
                    "bb_position":      "Bollinger Band Position",
                    "insider_pct":      "Insider Ownership %",
                    "institution_pct":  "Institution Ownership %",
                    "insider_cluster":  "Insider Cluster Buy",
                    "insider_executive_buy": "VD/CFO Buy",
                    "roa":              "ROA",
                    "operating_margin": "Operating Margin",
                    "gross_margin":     "Gross Margin",
                    "ev_to_ebitda":     "EV/EBITDA",
                    "score_fcf_yield":  "FCF Yield Score",
                    "free_cash_flow":   "Free Cash Flow",
                    "return_1m":        "1m Return",
                }
                for field, label in extra_fields.items():
                    val = row.get(field)
                    if val is not None and not pd.isna(val):
                        stock_data[label] = round(val, 2) if isinstance(val, float) else val

    # Filtrera data baserat på djupnivå och bygg prompt
    filtered_data = _build_depth_context(stock_data, depth)
    data_str = _safe_json(filtered_data, indent=2, ensure_ascii=False) if filtered_data else "Ingen data tillgänglig för denna aktie."
    user_message = f"Analysera aktien **{ticker}**.\n\nTillgänglig data:\n```json\n{data_str}\n```"

    # Berika med användarens personliga position om tillgänglig
    if user_position:
        shares   = user_position.get("shares", 0)
        cost     = user_position.get("cost_basis", 0)
        cur_price = user_position.get("current_price") or stock_data.get("Price")
        position_lines = [
            f"\n\n**Användarens position i {ticker}:**",
            f"- Antal aktier: {shares:.0f} st",
            f"- Genomsnittligt inköpspris: {cost:.2f} kr/st",
        ]
        if cur_price and cost > 0:
            try:
                pnl_pct = (float(cur_price) / float(cost) - 1) * 100
                pnl_kr  = (float(cur_price) - float(cost)) * float(shares)
                position_lines.append(
                    f"- Nuvarande P&L: {pnl_pct:+.1f}% ({pnl_kr:+,.0f} kr totalt)"
                )
            except Exception:
                pass
        user_message += "\n".join(position_lines)

    # Hämta nyheter automatiskt för alla djupnivåer
    news_lines = []
    company_name = stock_data.get("Company Name", "")
    if _fetch_news_ai is not None:
        try:
            news_items = _fetch_news_ai(ticker, days_back=7, company_name=company_name) or []
            for n in news_items[:6]:
                title = n.get("headline", n.get("title", "")).strip()
                src = n.get("source", "")
                age = n.get("age_hours")
                age_s = f" ({age:.0f}h sedan)" if age is not None else ""
                if title:
                    news_lines.append(f"- {title} [{src}]{age_s}")
        except Exception as e:
            _logger.warning("Kunde inte hämta nyheter för %s: %s", ticker, e)

    if news_lines:
        user_message += "\n\n📰 **Senaste nyheter:**\n" + "\n".join(news_lines)

    # Djupanpassad system-prompt
    k3_note = _k3_accounting_note(ticker, depth)
    system_prompt = SYSTEM_PROMPT_STOCK_ANALYSIS + _depth_system_prompt_addon(depth) + k3_note

    # Gemini Search Grounding: Aktiveras vid Djup/Extra djup om inga nyheter hittades.
    # Gemini söker då automatiskt på Google under inference för att komplettera analysen.
    # Gratis upp till 50 queries/dag — täcker normalt 5-20 djupanalyser per dag.
    _use_grounding = (
        not news_lines
        and depth in ("Djup", "Extra djup")
        and _resolve_provider(provider) == "gemini"
    )
    if _use_grounding:
        _logger.info("Activating Gemini grounding for %s (depth=%s, no news found)", ticker, depth)

    # depth + grounding + datum ingår i cache-nyckeln
    today_str = datetime.now().strftime("%Y-%m-%d")
    data_hash = hashlib.md5(data_str.encode()).hexdigest()[:12] if filtered_data else "no_data"
    cache_key = _make_cache_key("analyze_stock", ticker, data_hash, today_str,
                                _resolve_provider(provider), depth,
                                "grounded" if _use_grounding else "")
    return _call_with_cache(
        system_prompt,
        [{"role": "user", "content": user_message}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
        use_grounding=_use_grounding,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. PORTFÖLJOPTIMERING
# ══════════════════════════════════════════════════════════════════════════════

def analyze_portfolio(holdings: pd.DataFrame, df: pd.DataFrame = None,
                      force_refresh: bool = False,
                      provider: str = "auto",
                      depth: str = "Normal") -> str:
    """
    Analysera och optimera portföljen.
    
    Args:
        holdings: DataFrame med portföljinnehav (ticker, shares, cost_basis)
        df: DataFrame med scandata (för aktuella scores)
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    
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

    data_str = _safe_json(portfolio_summary, indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("analyze_portfolio", str(holdings.shape), str(df.shape) if df is not None else "none",
                                resolved, depth)

    return _call_with_cache(
        SYSTEM_PROMPT_PORTFOLIO + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Analysera min portfölj och föreslå förbättringar.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 3. FREE-TEXT AI CHATT
# ══════════════════════════════════════════════════════════════════════════════

def ai_chat(question: str, context: str = "", force_refresh: bool = False,
            provider: str = "auto",
            depth: str = "Normal",
            history: list = None,
            system_prompt_override: str = None) -> str:
    """
    Fritextfråga till AI:n med stöd för konversationshistorik.
    
    Args:
        question: Användarens fråga
        context: Extra kontext (t.ex. aktuell scandata i JSON)
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
        history: Lista med dicts {"role": "user"/"assistant", "content": "..."}
                 från tidigare meddelanden i samma konversation
    
    Returns:
        AI-svar
    """
    user_message = question
    if context:
        # News sections should NOT be in a JSON code block — use plain text
        if "Färska nyheter:" in context:
            # Split: scan data vs news
            parts = context.split("\n\nFärska nyheter:", 1)
            scan_part = parts[0].strip()
            news_part = parts[1].strip() if len(parts) > 1 else ""
            user_message = question
            if scan_part:
                user_message += f"\n\nMarknadsdata:\n```\n{scan_part}\n```"
            if news_part:
                user_message += f"\n\n📰 Färska nyheter (hämtade live via API just nu):\n{news_part}"
        else:
            user_message = f"{question}\n\nKontextdata:\n```\n{context}\n```"
    
    # Bygg meddelanden med historik
    messages = []
    if history:
        # Konvertera sparad historik till AI-format
        for msg in history[-10:]:  # Max 10 tidigare meddelanden
            role = "user" if msg["role"] == "user" else "assistant"
            messages.append({"role": role, "content": msg["content"]})
    
    # Lagg till aktuell fraga
    messages.append({"role": "user", "content": user_message})

    # Ingen cache för chatt - varje fråga är unik
    system_prompt = system_prompt_override if system_prompt_override else SYSTEM_PROMPT_CHAT
    return _ai_call(
        messages,
        system_prompt,
        max_tokens=_resolve_depth(depth),
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 4. VECKORAPPORT-AI
# ══════════════════════════════════════════════════════════════════════════════

def generate_weekly_ai_analysis(scored_df: pd.DataFrame, regime_info: dict,
                                 sector_momentum: dict = None, news: dict = None,
                                 force_refresh: bool = False,
                                 provider: str = "auto",
                                 depth: str = "Normal") -> str:
    """
    Skapa AI-analyssektion för veckorapporten.
    Veckoanalys ar en "heavy" uppgift – anvander DeepSeek i hybrid-lage.

    Args:
        scored_df: DataFrame med scandata
        regime_info: Dict med marknadsregim-info
        sector_momentum: Dict med sektormomentum
        news: Dict med nyhetsdata
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    """
    if provider == "auto":
        provider = _resolve_provider(provider, task_type="heavy")
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
        "factor_weights": getattr(config, "FACTOR_WEIGHTS", {}),
    }

    data_str = _safe_json(data_summary, indent=2, ensure_ascii=False)
    cache_key = _make_cache_key("weekly_ai", datetime.now().strftime("%Y-%m-%d"), provider, depth)

    result = _call_with_cache(
        SYSTEM_PROMPT_WEEKLY_REPORT + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Generera veckoanalys for dagens scan.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=True,  # Alltid fräsch data för veckorapport
        provider=provider,
    )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# 5. NYHETSANALYS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_news(ticker: str, news_items: list = None,
                 force_refresh: bool = False,
                 provider: str = "auto",
                 depth: str = "Normal") -> str:
    """
    Analysera nyheter för en aktie.
    
    Args:
        ticker: Ticker-symbol
        news_items: Lista med nyheter (dict med titel, url, datum, sammanfattning)
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    
    Returns:
        AI-sammanfattning av nyheter
    """
    if not news_items:
        return f"ℹ️ Inga nyheter tillgängliga för **{ticker}**."

    news_text = json.dumps(news_items[:10], indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("analyze_news", ticker, str(len(news_items)), resolved, depth)

    return _call_with_cache(
        SYSTEM_PROMPT_NEWS_ANALYSIS + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Analysera nyheterna för {ticker}.\n\nNyheter:\n{news_text}"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6. MORGONBRIEF
# ══════════════════════════════════════════════════════════════════════════════

def generate_morning_brief(market_data: dict = None,
                            portfolio_data: dict = None,
                            alerts_list: list = None,
                            opportunities: list = None,
                            force_refresh: bool = False,
                            provider: str = "auto",
                            depth: str = "Normal") -> str:
    """
    Skapa AI-genererad morgonbrief.

    Args:
        market_data: Dict med marknadsdata
        portfolio_data: Dict med portföljdata
        alerts_list: Lista med varningar
        opportunities: Lista med opportunities
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    """
    brief_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "market": market_data or {},
        "portfolio": portfolio_data or {},
        "alerts": alerts_list or [],
        "opportunities": opportunities or [],
    }
    
    data_str = _safe_json(brief_data, indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("morning_brief", datetime.now().strftime("%Y-%m-%d"), resolved, depth)

    return _call_with_cache(
        SYSTEM_PROMPT_MORNING_BRIEF + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Skapa dagens morgonbrief.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=True,  # Alltid fräsch
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 7. SEKTORANALYS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_sector(sector_name: str, df: pd.DataFrame = None,
                   force_refresh: bool = False,
                   provider: str = "auto",
                   depth: str = "Normal") -> str:
    """
    Analysera en specifik sektor.
    
    Args:
        sector_name: Sektornamn (t.ex. "Technology")
        df: DataFrame med scandata
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    
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

    data_str = _safe_json(sector_data, indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("analyze_sector", sector_name, str(df.shape) if df is not None else "none",
                                resolved, depth)

    return _call_with_cache(
        SYSTEM_PROMPT_SECTOR_ANALYSIS + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Analysera sektorn {sector_name}.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 8. MÖJLIGHETSANALYS
# ══════════════════════════════════════════════════════════════════════════════

def analyze_opportunity(ticker: str, signal_type: str,
                         stock_data: dict = None,
                         force_refresh: bool = False,
                         provider: str = "auto",
                         depth: str = "Normal") -> str:
    """
    Analysera en opportunity-signal.
    
    Args:
        ticker: Ticker-symbol
        signal_type: "dip", "breakout", "oversold"
        stock_data: Dict med relevant data
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    
    Returns:
        AI-analys av möjligheten
    """
    data = {
        "ticker": ticker,
        "signal_type": signal_type,
        "data": stock_data or {},
    }
    data_str = _safe_json(data, indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("analyze_opportunity", ticker, signal_type, resolved, depth)

    return _call_with_cache(
        SYSTEM_PROMPT_OPPORTUNITY + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Analysera denna möjlighet.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 9. JÄMFÖR TVÅ AKTIER
# ══════════════════════════════════════════════════════════════════════════════

def compare_stocks(ticker_a: str, ticker_b: str, df: pd.DataFrame = None,
                   force_refresh: bool = False,
                   provider: str = "auto",
                   depth: str = "Normal") -> str:
    """
    Jämför två aktier sida vid sida.
    
    Args:
        ticker_a: Första ticker
        ticker_b: Andra ticker
        df: DataFrame med scandata
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    
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

    data_str = _safe_json(comparison, indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("compare_stocks", ticker_a, ticker_b,
                                 str(df.shape) if df is not None else "none", resolved, depth)

    user_msg = f"Jämför aktierna **{ticker_a}** och **{ticker_b}**.\n\nData:\n```json\n{data_str}\n```"
    sys_prompt = """Du jämför två aktier. Ge ett tydligt svar om:
1. Vilken aktie som är starkast totalt
2. Skillnader i momentum, värdering och kvalitet
3. Din rekommendation: vilken är bäst att köpa JUST NU?
4. Varför

Skriv på svenska. Max 300 ord.""" + _depth_system_prompt_addon(depth)

    return _call_with_cache(
        sys_prompt,
        [{"role": "user", "content": user_msg}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 10. MARKNADSSAMMANFATTNING
# ══════════════════════════════════════════════════════════════════════════════

def generate_market_summary(df: pd.DataFrame = None, sc_df: pd.DataFrame = None,
                             regime_info: dict = None,
                             force_refresh: bool = False,
                             provider: str = "auto",
                             depth: str = "Normal") -> str:
    """
    Skapa en kort marknadssammanfattning för dashboard.
    
    Args:
        df: DataFrame med global scandata
        sc_df: DataFrame med smallcap scandata
        regime_info: Dict med marknadsregim-info
        force_refresh: Hoppa över cache
        provider: "auto", "deepseek" eller "gemini"
        depth: "Snabb", "Normal", "Djup" eller "Extra djup"
    
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

    data_str = _safe_json(summary, indent=2, ensure_ascii=False)
    resolved = _resolve_provider(provider)
    cache_key = _make_cache_key("market_summary", datetime.now().strftime("%Y-%m-%d"), resolved, depth)

    return _call_with_cache(
        """Du är MarketScan AI-assistent. Skapa en marknadssammanfattning baserad på dagens scandata.

Analysera datan och inkludera:
1. Marknadsregim och övergripande sentiment
2. Sektor- och breddsanalys (vilka sektorer leder, bredd mm)
3. Starka kontra svaga aktier – mönster i faktorscorer
4. Konkreta takeaways för investeraren

Skriv på svenska, använd emojis. 150-300 ord beroende på datatillgång.""" + _depth_system_prompt_addon(depth),
        [{"role": "user", "content": f"Skapa en marknadssammanfattning.\n\nData:\n```json\n{data_str}\n```"}],
        cache_key,
        max_tokens=_resolve_depth(depth),
        force_refresh=force_refresh,
        provider=provider,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 11. VALIDERING – Testa API-nyckeln
# ══════════════════════════════════════════════════════════════════════════════

def test_api_key(provider: str = "auto") -> dict:
    """
    Testa om vald AI-providers API-nyckel fungerar.
    
    Args:
        provider: "auto", "deepseek" eller "gemini"
    
    Returns:
        dict med status och meddelande
    """
    resolved = _resolve_provider(provider)

    if resolved == "gemini":
        return _test_gemini_key()
    else:
        return _test_deepseek_key()


def _test_deepseek_key() -> dict:
    """Testa DeepSeek API-nyckel."""
    api_key = _get_secret("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "🔴 DeepSeek API-nyckel saknas"}

    try:
        import requests
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return {"status": "ok", "message": "✅ DeepSeek API fungerar!"}
        elif resp.status_code == 401:
            return {"status": "error", "message": "❌ DeepSeek API-nyckel är ogiltig (401)"}
        elif resp.status_code == 402:
            return {"status": "error", "message": "❌ DeepSeek-saldo är slut (402)"}
        elif resp.status_code == 429:
            return {"status": "warning", "message": "⚠️ DeepSeek rate-limited (429)"}
        else:
            body = ""
            try:
                body = resp.text[:200]
            except Exception:
                pass
            return {"status": "warning", "message": f"⚠️ DeepSeek svarade med status {resp.status_code}: {body}"}
    except Exception as e:
        return {"status": "error", "message": f"❌ Kunde inte nå DeepSeek: {e}"}


def _test_gemini_key() -> dict:
    """Testa Gemini API-nyckel."""
    api_key = _get_secret("GEMINI_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "🔴 Gemini API-nyckel saknas"}

    try:
        import requests
        model = getattr(config, "GEMINI_MODEL", "gemini-2.0-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        resp = requests.post(
            url,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                "generationConfig": {"maxOutputTokens": 1},
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return {"status": "ok", "message": "✅ Gemini API fungerar!"}
        elif resp.status_code == 403:
            return {"status": "error", "message": "❌ Gemini API-nyckel är ogiltig (403)"}
        elif resp.status_code == 429:
            return {"status": "warning", "message": "⚠️ Gemini rate-limited (429)"}
        else:
            body = ""
            try:
                body = resp.text[:200]
            except Exception:
                pass
            return {"status": "warning", "message": f"⚠️ Gemini svarade med status {resp.status_code}: {body}"}
    except Exception as e:
        return {"status": "error", "message": f"❌ Kunde inte nå Gemini: {e}"}


def test_all_keys() -> dict:
    """Testa båda API-nycklarna och returnera status för båda."""
    deepseek_status = _test_deepseek_key()
    gemini_status = _test_gemini_key()
    return {
        "deepseek": deepseek_status,
        "gemini": gemini_status,
    }


def clear_cache():
    """Rensa all AI-cache."""
    import shutil
    if AI_CACHE_DIR.exists():
        shutil.rmtree(AI_CACHE_DIR)
        AI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return "✅ AI-cache rensad!"
    return "ℹ️ Ingen cache att rensa."
