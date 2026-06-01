"""
ai_stock_reviewer.py — Layer 5: AI Final Verdict för universe discovery
=======================================================================
Tar en kandidat som redan klarat Layer 1-4 (hard exclusion, quality gate,
sentiment, fraud detection) och låter Gemini/DeepSeek ge ett holistiskt
beslut om aktien är värd att lägga till i universum.

Kostnadsanalys:
  - Gemini 2.5 Flash free tier: 250 req/dag — mer än nog (7 req/vecka)
  - Betald nivå: ~$0.21/vecka för 50 aktier
  - DeepSeek fallback: ~$0.03/vecka

Strukturerat JSON-svar:
  {
    "recommendation": "ADD" | "SKIP" | "INVESTIGATE",
    "confidence":     0.0–1.0,
    "reasoning":      "2-3 meningar",
    "key_positives":  ["...", "..."],
    "key_risks":      ["...", "..."]
  }

ADD + confidence ≥ 0.75 → auto-add (om HIGH quality tier)
SKIP             → avvisas, loggas som ai_rejected
INVESTIGATE      → pending, kräver manuell granskning
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# Kostnadsskydd: max AI-anrop per discovery-körning
MAX_AI_CALLS_PER_RUN = 25

_call_counter = 0
_last_reset: str = ""


def _reset_counter_if_new_day():
    global _call_counter, _last_reset
    today = date.today().isoformat()
    if today != _last_reset:
        _call_counter = 0
        _last_reset = today


def _budget_ok() -> bool:
    _reset_counter_if_new_day()
    return _call_counter < MAX_AI_CALLS_PER_RUN


def _increment_counter():
    global _call_counter
    _call_counter += 1


def _build_prompt(candidate: dict, news_headlines: Optional[list[str]] = None) -> str:
    """Bygger en kompakt prompt (~1500 tokens) för AI-granskning."""
    ticker  = candidate.get("ticker", "?")
    source  = candidate.get("source", "?")
    region  = candidate.get("region", "?")
    conf    = candidate.get("confidence", 0)
    tier    = candidate.get("quality_tier", "MEDIUM")
    q_score = candidate.get("quality_score", 50)
    fraud   = candidate.get("fraud_flags", [])
    reason  = candidate.get("reason", "")

    yf      = candidate.get("yf_data") or candidate.get("metadata", {})
    name    = yf.get("name", ticker)
    sector  = yf.get("sector", "?")
    country = yf.get("country", "?")
    mc      = yf.get("market_cap", 0) or 0
    price   = yf.get("price", 0)
    vol     = yf.get("volume", 0)

    mc_str = f"${mc/1e9:.1f}B" if mc >= 1e9 else f"${mc/1e6:.0f}M" if mc > 0 else "?"

    # Lägg till nyheter om tillgängliga
    news_str = ""
    if news_headlines:
        news_str = "\n\nSenaste nyheter:\n" + "\n".join(f"- {h}" for h in news_headlines[:3])

    fraud_str = ""
    if fraud:
        fraud_str = f"\n\nVarningsflaggor: {'; '.join(fraud[:2])}"

    prompt = f"""Du är en kvantitativ aktieanalytiker. Granskningsdatum: {date.today().isoformat()}.

En aktie-kandidat har klarat automatiska filter (pris, volym, skuld, kassaflöde) och ska nu granskas holistiskt.

**Kandidat:** {ticker} — {name}
**Sektor:** {sector} | **Region:** {region} | **Land:** {country}
**Market cap:** {mc_str} | **Pris:** {price}
**Källa:** {source} | **Anledning:** {reason[:100]}
**Quality tier:** {tier} (score={q_score:.0f}/100) | **Systemets confidence:** {conf:.0%}{fraud_str}{news_str}

Ge ett kortfattat, strukturerat beslut.
Svara ENBART med giltig JSON (inga kommentarer, inget utanför JSON):

{{
  "recommendation": "ADD" eller "SKIP" eller "INVESTIGATE",
  "confidence": 0.0-1.0,
  "reasoning": "2-3 meningar om det viktigaste för ditt beslut",
  "key_positives": ["max 3 konkreta positiva punkter"],
  "key_risks": ["max 3 konkreta risker"]
}}

Riktlinjer:
- ADD: Klart intressant bolag, rekommenderas för vidare scanning
- SKIP: Uppenbart inte värt att ha med (dålig bransch, dålig trend, högrisk utan kompensation)
- INVESTIGATE: Intressant men kräver djupare analys (osäkert data, speciell situation)"""

    return prompt


def review_candidate(
    candidate: dict,
    news_headlines: Optional[list[str]] = None,
    provider: str = "auto",
) -> dict:
    """
    Kör AI-granskning av en discovery-kandidat.

    Args:
        candidate:       Kandidat-dikt från validate_candidates()
        news_headlines:  Valfria nyhetsrubriker för kontextuell analys
        provider:        "auto" | "gemini" | "deepseek"

    Returns:
        Dikt med: recommendation, confidence, reasoning, key_positives,
                  key_risks, ai_model (vilken modell som användes),
                  ai_skipped (True om budget slut eller fel)
    """
    default = {
        "recommendation": "INVESTIGATE",
        "confidence":     0.5,
        "reasoning":      "AI-granskning ej körd.",
        "key_positives":  [],
        "key_risks":      [],
        "ai_model":       None,
        "ai_skipped":     True,
    }

    if not _budget_ok():
        logger.debug(f"  AI-budget slut för idag ({_call_counter} anrop), hoppar {candidate.get('ticker')}")
        default["reasoning"] = f"AI-budget slut ({_call_counter}/{MAX_AI_CALLS_PER_RUN} anrop/dag)"
        return default

    try:
        from core.ai_analysis import ai_chat
    except ImportError:
        logger.warning("  ai_analysis ej tillgänglig — hoppar AI-granskning")
        return default

    prompt = _build_prompt(candidate, news_headlines)
    ticker = candidate.get("ticker", "?")

    try:
        _increment_counter()
        result_text = ai_chat(
            prompt,
            provider=provider,
            force_refresh=True,
            depth="Normal",
        )

        # Rensa JSON ur svaret
        cleaned = result_text.strip()
        if "```" in cleaned:
            for part in cleaned.split("```"):
                p = part.strip().lstrip("json").strip()
                if p.startswith("{"):
                    cleaned = p
                    break

        verdict = json.loads(cleaned)

        # Validera fält
        rec = str(verdict.get("recommendation", "INVESTIGATE")).upper()
        if rec not in ("ADD", "SKIP", "INVESTIGATE"):
            rec = "INVESTIGATE"

        conf = float(verdict.get("confidence", 0.5))
        conf = max(0.0, min(1.0, conf))

        result = {
            "recommendation": rec,
            "confidence":     round(conf, 2),
            "reasoning":      str(verdict.get("reasoning", ""))[:300],
            "key_positives":  [str(p)[:100] for p in verdict.get("key_positives", [])[:3]],
            "key_risks":      [str(r)[:100] for r in verdict.get("key_risks", [])[:3]],
            "ai_model":       provider,
            "ai_skipped":     False,
        }

        logger.info(
            f"  AI {ticker}: {rec} (conf={conf:.0%}) — {result['reasoning'][:80]}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.debug(f"  AI JSON-parse-fel för {ticker}: {e} — text: {result_text[:200]}")
        default["reasoning"] = "AI returnerade ogiltigt JSON-svar"
        return default
    except Exception as e:
        logger.warning(f"  AI-granskning misslyckades för {ticker}: {e}")
        default["reasoning"] = f"AI-fel: {str(e)[:80]}"
        return default


def batch_review_candidates(
    candidates: list[dict],
    provider: str = "auto",
    delay_sec: float = 0.5,
) -> list[dict]:
    """
    Kör AI-granskning på en lista kandidater (batch).
    Respekterar MAX_AI_CALLS_PER_RUN och lägger till fördröjning mot rate-limiting.

    Returnerar kandidaterna med `ai_verdict`-fältet tillagt.
    """
    results = []
    for c in candidates:
        c_copy = {**c}
        if not _budget_ok():
            c_copy["ai_verdict"] = {
                "recommendation": "INVESTIGATE",
                "confidence": 0.5,
                "reasoning": "AI-budget slut för idag",
                "key_positives": [], "key_risks": [],
                "ai_model": None, "ai_skipped": True,
            }
        else:
            # Hämta nyhetsrubriker ur metadata om tillgängliga
            headlines = (
                c.get("metadata", {}).get("headlines") or
                c.get("metadata", {}).get("feeds") or
                []
            )
            if isinstance(headlines, list) and headlines:
                headlines = [str(h) for h in headlines[:3]]
            else:
                headlines = None

            verdict = review_candidate(c, news_headlines=headlines, provider=provider)
            c_copy["ai_verdict"] = verdict

            # Applicera confidence-delta från AI-verdict
            ai_conf = verdict["confidence"]
            rec = verdict["recommendation"]
            if rec == "ADD" and ai_conf >= 0.75:
                c_copy["confidence"] = round(
                    min(c_copy.get("confidence", 0.5) + 0.08, 1.0), 3
                )
            elif rec == "SKIP":
                c_copy["confidence"] = round(
                    max(c_copy.get("confidence", 0.5) - 0.20, 0.0), 3
                )

            time.sleep(delay_sec)

        results.append(c_copy)

    n_add  = sum(1 for c in results if c.get("ai_verdict", {}).get("recommendation") == "ADD")
    n_skip = sum(1 for c in results if c.get("ai_verdict", {}).get("recommendation") == "SKIP")
    n_inv  = sum(1 for c in results if c.get("ai_verdict", {}).get("recommendation") == "INVESTIGATE")
    logger.info(f"  AI batch klar: ADD={n_add}, SKIP={n_skip}, INVESTIGATE={n_inv}")
    return results
