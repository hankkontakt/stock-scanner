"""
core/providers/deepseek_provider.py - DeepSeek API Provider.
Anropar DeepSeek API med exponential backoff retry och structured output.
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
_token_sanitize = re.compile(r"(sk-[a-zA-Z0-9]{10,}|AIza[a-zA-Z0-9_-]{20,})")


class DeepSeekProvider(BaseProvider):
    """Provider för DeepSeek API (deepseek-chat, deepseek-reasoner)."""

    PROVIDER_CONFIG = {
        "cost_per_1m_input": 0.27,
        "cost_per_1m_output": 1.10,
    }
    DEFAULT_MODEL = "deepseek-chat"
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, api_key: str = "", model: str = "", config: dict = None):
        super().__init__(api_key, model, config)
        if not self.api_key:
            self.api_key = _get_secret("DEEPSEEK_API_KEY", "")
        if not self.model:
            self.model = self.DEFAULT_MODEL

    def generate(self, messages: list,
                 max_tokens: int = 2048,
                 temperature: float = 0.3,
                 **kwargs) -> AiResponse:
        """Anropa DeepSeek API med meddelanden och exponential backoff retry."""
        if not self.api_key:
            return AiResponse(
                text="",
                success=False,
                error="DeepSeek API-nyckel saknas",
                provider="deepseek",
            )

        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Om första meddelandet har role="system", använd top-level system
        if messages and messages[0].get("role") == "system":
            system_content = messages[0]["content"]
            payload["messages"] = messages[1:]
            payload["messages"].insert(0, {"role": "user", "content": system_content})

        max_retries = 3
        last_error = ""
        input_tokens = 0
        output_tokens = 0

        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    self.BASE_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=kwargs.get("timeout", 60),
                )

                if resp.status_code == 200:
                    data = resp.json()
                    choice = data["choices"][0]
                    content = choice["message"]["content"]
                    usage = data.get("usage", {})
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)

                    return AiResponse(
                        text=content,
                        usage=TokenUsage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=input_tokens + output_tokens,
                        ),
                        model=data.get("model", self.model),
                        provider="deepseek",
                    )

                if resp.status_code in (401, 403):
                    try:
                        body = resp.json().get("error", {}).get("message", resp.text[:200])
                    except Exception:
                        body = resp.text[:200]
                    body = _token_sanitize.sub("***", body)
                    return AiResponse(
                        text="",
                        success=False,
                        error=f"DeepSeek nekade åtkomst ({resp.status_code}): {body}",
                        provider="deepseek",
                    )

                if resp.status_code == 429:
                    delay = 5.0 * (2 ** attempt)
                    _logger.warning("DeepSeek rate-limit (429) - väntar %.0fs (försök %d/%d)",
                                    delay, attempt + 1, max_retries)
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue
                    return AiResponse(
                        text="",
                        success=False,
                        error=f"DeepSeek rate-limited efter {max_retries} försök",
                        provider="deepseek",
                    )

                if 500 <= resp.status_code < 600:
                    delay = 2.0 * (2 ** attempt)
                    _logger.warning("DeepSeek server error (%d) - väntar %.0fs", resp.status_code, delay)
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                        continue
                    return AiResponse(
                        text="",
                        success=False,
                        error=f"DeepSeek svarade {resp.status_code} efter {max_retries} försök",
                        provider="deepseek",
                    )

                # Övriga fel
                try:
                    body = resp.text[:200]
                except Exception:
                    body = ""
                last_error = f"DeepSeek svarade {resp.status_code}: {body}"
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return AiResponse(text="", success=False, error=last_error, provider="deepseek")

            except requests.exceptions.Timeout:
                delay = 1.0 * (2 ** attempt)
                _logger.warning("DeepSeek timeout - väntar %.0fs", delay)
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                return AiResponse(
                    text="",
                    success=False,
                    error=f"DeepSeek timeout efter {max_retries} försök",
                    provider="deepseek",
                )

            except requests.exceptions.ConnectionError:
                _logger.warning("DeepSeek anslutningsfel")
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                return AiResponse(
                    text="",
                    success=False,
                    error="DeepSeek anslutningsfel - kolla internet/endpoint",
                    provider="deepseek",
                )

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(0.5)
                    continue
                return AiResponse(text="", success=False, error=last_error, provider="deepseek")

        return AiResponse(text="", success=False, error=last_error or "Okänt fel", provider="deepseek")

    def generate_structured(self, prompt: str, schema: dict) -> dict:
        """Generera strukturerad JSON från DeepSeek.

        Använder system-prompt för att instruera JSON-format och
        försöker parsa svaret som JSON med fallback till regex.
        """
        import json as _json

        system_msg = {
            "role": "system",
            "content": (
                "Du svarar ENDAST med ett giltigt JSON-objekt. "
                "Ingen förklarande text före eller efter. "
                f"Svara med JSON enligt detta schema: {_json.dumps(schema, ensure_ascii=False)}"
            )
        }
        messages = [system_msg, {"role": "user", "content": prompt}]

        response = self.generate(messages, max_tokens=4096, temperature=0.1)

        if not response.success:
            _logger.warning("generate_structured misslyckades: %s", response.error)
            return {}

        return self._parse_json_response(response.text, schema)

    def _parse_json_response(self, text: str, schema: dict) -> dict:
        """Försök parsea JSON från text, med fallback."""
        # Först försök rakt JSON-parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Försök hitta JSON-block inom ```json ... ```
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Försök hitta { ... } med regex
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        _logger.warning("Kunde inte parsea JSON från DeepSeek-svar")
        return {}
