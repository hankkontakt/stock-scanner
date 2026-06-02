"""
core/providers/gemini_provider.py - Google Gemini API Provider.
Anropar Gemini API via REST med modell-fallback vid 404 (deprecation).
"""

import json
import logging
import re
import time
from typing import Optional

import requests

from core.config import _get_secret
from .base import BaseProvider, AiResponse, TokenUsage

_logger = logging.getLogger(__name__)


# Gemini-modeller att prova i ordning vid 404
GEMINI_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-pro-latest",
]


class GeminiProvider(BaseProvider):
    """Provider för Google Gemini API (gratis, rate-limited)."""

    PROVIDER_CONFIG = {
        "cost_per_1m_input": 0.0,
        "cost_per_1m_output": 0.0,
    }
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str = "", model: str = "", config: dict = None):
        super().__init__(api_key, model, config)
        if not self.api_key:
            self.api_key = _get_secret("GEMINI_API_KEY", "")
        if not self.model:
            self.model = self.DEFAULT_MODEL

    def _build_contents(self, messages: list) -> tuple:
        """Konvertera standard messages-lista till Gemini-format.

        Returns:
            (contents, system_prompt) tuple
        """
        contents = []
        system_prompt = ""

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_prompt += content + "\n"
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})

        return contents, system_prompt.strip()

    def generate(self, messages: list,
                 max_tokens: int = 2048,
                 temperature: float = 0.3,
                 **kwargs) -> AiResponse:
        """Anropa Gemini API med modell-fallback vid 404."""
        if not self.api_key:
            return AiResponse(
                text="",
                success=False,
                error="Gemini API-nyckel saknas",
                provider="gemini",
            )

        contents, system_prompt = self._build_contents(messages)

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            }
        }

        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        # Google Search Grounding
        use_grounding = kwargs.get("use_grounding", False)
        if use_grounding:
            payload["tools"] = [{"google_search": {}}]

        # Modellista: konfigurerad modell först, sedan fallback
        configured = self.model
        models_to_try = [configured] + [m for m in GEMINI_FALLBACK_MODELS if m != configured]

        max_retries = 3
        last_error = ""
        tried_models = []

        # Yttre loop: iterera över modeller (byt vid 404)
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            tried_models.append(model)
            model_got_404 = False

            for attempt in range(max_retries):
                try:
                    resp = requests.post(
                        url,
                        params={"key": self.api_key},
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=kwargs.get("timeout", 60),
                    )

                    if resp.status_code == 200:
                        data = resp.json()

                        # Kolla om prompten blockerades (SAFETY)
                        prompt_feedback = data.get("promptFeedback", {})
                        block_reason = prompt_feedback.get("blockReason", "")
                        if block_reason:
                            return AiResponse(
                                text="",
                                success=False,
                                error=f"Gemini blockerade frågan ({block_reason})",
                                provider="gemini",
                                model=model,
                            )

                        candidates = data.get("candidates", [])
                        if not candidates:
                            last_error = "Gemini: tomt svar (inga kandidater)"
                            time.sleep(1)
                            continue

                        candidate = candidates[0]
                        finish_reason = candidate.get("finishReason", "STOP")
                        if finish_reason not in ("STOP", "MAX_TOKENS", ""):
                            return AiResponse(
                                text="",
                                success=False,
                                error=f"Gemini avbröt svaret ({finish_reason})",
                                provider="gemini",
                                model=model,
                            )

                        parts = candidate.get("content", {}).get("parts", [])
                        if not parts:
                            last_error = "Gemini: tomt svar (inga delar)"
                            time.sleep(1)
                            continue

                        text = parts[0].get("text", "").strip()
                        if not text:
                            last_error = "Gemini: tomt svar"
                            time.sleep(1)
                            continue

                        # Lägg notering om modell-fallback
                        if model != configured:
                            text += (f"\n\n---\n*ℹ️ Använde Gemini-modell `{model}` "
                                     f"(konfigurerad `{configured}` ej tillgänglig)*")

                        # Token-uppskattning (Gemini returnerar inte tokens i free tier)
                        usage = data.get("usageMetadata", {})
                        input_tokens = usage.get("promptTokenCount", 0)
                        output_tokens = usage.get("candidatesTokenCount", 0)

                        return AiResponse(
                            text=text,
                            usage=TokenUsage(
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                total_tokens=input_tokens + output_tokens,
                            ),
                            model=model,
                            provider="gemini",
                        )

                    elif resp.status_code == 400:
                        try:
                            body = resp.json().get("error", {}).get("message", resp.text[:200])
                        except Exception:
                            body = resp.text[:200]
                        return AiResponse(
                            text="",
                            success=False,
                            error=f"Gemini: ogiltig förfrågan (400): {body}",
                            provider="gemini",
                            model=model,
                        )

                    elif resp.status_code == 403:
                        try:
                            body = resp.json().get("error", {}).get("message", resp.text[:200])
                        except Exception:
                            body = resp.text[:200]
                        if "API_KEY_INVALID" in body or "API key not valid" in body:
                            return AiResponse(
                                text="",
                                success=False,
                                error="Gemini API-nyckel ogiltig (403)",
                                provider="gemini",
                            )
                        return AiResponse(
                            text="",
                            success=False,
                            error=f"Gemini nekade åtkomst (403): {body}",
                            provider="gemini",
                            model=model,
                        )

                    elif resp.status_code == 404:
                        last_error = f"Gemini: modell '{model}' hittades inte (404)"
                        model_got_404 = True
                        break

                    elif resp.status_code == 429:
                        delay = 5.0 * (2 ** attempt)
                        _logger.warning("Gemini rate-limit (429) - väntar %.0fs", delay)
                        if attempt < max_retries - 1:
                            time.sleep(delay)
                            continue
                        return AiResponse(
                            text="",
                            success=False,
                            error="Gemini rate-limited efter max retries",
                            provider="gemini",
                        )

                    else:
                        try:
                            body = resp.text[:200]
                        except Exception:
                            body = ""
                        last_error = f"Gemini svarade {resp.status_code}: {body}"
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        return AiResponse(
                            text="",
                            success=False,
                            error=last_error,
                            provider="gemini",
                            model=model,
                        )

                except requests.exceptions.Timeout:
                    last_error = "Gemini timeout"
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return AiResponse(text="", success=False, error=last_error, provider="gemini")

                except Exception as e:
                    last_error = f"Gemini-anropet misslyckades: {e}"
                    if attempt < max_retries - 1:
                        time.sleep(0.5)
                        continue
                    return AiResponse(text="", success=False, error=last_error, provider="gemini")

            if not model_got_404:
                break

        return AiResponse(
            text="",
            success=False,
            error=f"Ingen modell fungerade. Provade: {', '.join(tried_models)}",
            provider="gemini",
        )

    def generate_structured(self, prompt: str, schema: dict) -> dict:
        """Generera strukturerad JSON från Gemini.

        Gemini kan använda response_mime_type för att tvinga JSON-format.
        """
        system_msg = (
            "Du svarar ENDAST med ett giltigt JSON-objekt. "
            "Ingen förklarande text före eller efter. "
            f"Svara med JSON som följer detta schema: {json.dumps(schema, ensure_ascii=False)}"
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ]

        response = self.generate(messages, max_tokens=4096, temperature=0.1)

        if not response.success:
            _logger.warning("Gemini generate_structured misslyckades: %s", response.error)
            return {}

        return self._parse_json_response(response.text, schema)

    def _parse_json_response(self, text: str, schema: dict) -> dict:
        """Försök parsea JSON från text, med fallback."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        _logger.warning("Kunde inte parsea JSON från Gemini-svar")
        return {}
