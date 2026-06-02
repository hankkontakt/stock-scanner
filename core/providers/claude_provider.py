"""
core/providers/claude_provider.py - Claude API Provider (Anthropic).
Anropar Anthropic API med stöd för prompt caching och structured output (tool use).
"""

import json
import logging
import re
from typing import Optional

import requests

from core.config import _get_secret
from .base import BaseProvider, AiResponse, TokenUsage

_logger = logging.getLogger(__name__)


class ClaudeProvider(BaseProvider):
    """Provider för Anthropic Claude API med prompt caching och tool use."""

    PROVIDER_CONFIG = {
        "cost_per_1m_input": 3.00,
        "cost_per_1m_output": 15.00,
    }
    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    # Cachad input är 90% billigare
    CACHED_INPUT_MULTIPLIER = 0.1

    def __init__(self, api_key: str = "", model: str = "", config: dict = None):
        super().__init__(api_key, model, config)
        if not self.api_key:
            self.api_key = _get_secret("CLAUDE_API_KEY", "")
        if not self.model:
            self.model = self.DEFAULT_MODEL

    def generate(self, messages: list,
                 max_tokens: int = 2048,
                 temperature: float = 0.3,
                 **kwargs) -> AiResponse:
        """Anropa Anthropic Claude API.

        Stödjer prompt caching via cache_control på system-prompt
        och/eller första användarmeddelandet.

        Args:
            messages: Lista med {"role": "user"/"assistant"/"system", "content": "..."}
            max_tokens: Max tokens i svaret
            temperature: Kreativitet (0.0-1.0)
            **kwargs: use_caching (bool), timeout (int)

        Returns:
            AiResponse med text, usage, modellinfo
        """
        if not self.api_key:
            return AiResponse(
                text="",
                success=False,
                error="CLAUDE_API_KEY saknas. Sätt i .env eller Streamlit Secrets.",
                provider="claude",
            )

        use_caching = kwargs.get("use_caching", True)

        # Separera system-prompt från messages (Anthropic API har separat system-parameter)
        system_content = ""
        api_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_content += msg.get("content", "") + "\n"
            else:
                api_messages.append({
                    "role": "assistant" if msg["role"] == "assistant" else "user",
                    "content": msg.get("content", ""),
                })

        # Bygg request body
        payload = {
            "model": kwargs.get("model", self.model),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }

        # System-prompt med valfri caching
        if system_content.strip():
            system_block = {"type": "text", "text": system_content.strip()}
            if use_caching:
                system_block["cache_control"] = {"type": "ephemeral"}
            payload["system"] = [system_block]

        # Prompt caching på första användarmeddelandet (störst besparing)
        if use_caching and api_messages and api_messages[0]["role"] == "user":
            first_content = api_messages[0]["content"]
            if isinstance(first_content, str):
                api_messages[0]["content"] = [
                    {"type": "text", "text": first_content,
                     "cache_control": {"type": "ephemeral"}}
                ]

        anthropic_version = kwargs.get("anthropic_version", self.API_VERSION)
        timeout = kwargs.get("timeout", 120)

        try:
            resp = requests.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": anthropic_version,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 200:
                data = resp.json()

                content_blocks = data.get("content", [])
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text += block.get("text", "")

                usage = data.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                return AiResponse(
                    text=text.strip(),
                    usage=TokenUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens + output_tokens,
                        cached_input_tokens=cache_creation + cache_read,
                    ),
                    model=data.get("model", self.model),
                    provider="claude",
                )

            elif resp.status_code == 400:
                try:
                    err = resp.json().get("error", {})
                    msg = err.get("message", resp.text[:300])
                except Exception:
                    msg = resp.text[:300]
                return AiResponse(
                    text="",
                    success=False,
                    error=f"Claude: bad request (400): {msg}",
                    provider="claude",
                )

            elif resp.status_code == 401:
                return AiResponse(
                    text="",
                    success=False,
                    error="Claude API-nyckel ogiltig (401)",
                    provider="claude",
                )

            elif resp.status_code == 429:
                return AiResponse(
                    text="",
                    success=False,
                    error="Claude rate-limited (429). Försök igen senare.",
                    provider="claude",
                )

            elif resp.status_code == 500:
                return AiResponse(
                    text="",
                    success=False,
                    error="Claude server error (500). Anthropic har problem.",
                    provider="claude",
                )

            else:
                try:
                    body = resp.text[:200]
                except Exception:
                    body = ""
                return AiResponse(
                    text="",
                    success=False,
                    error=f"Claude svarade {resp.status_code}: {body}",
                    provider="claude",
                )

        except requests.exceptions.Timeout:
            return AiResponse(
                text="",
                success=False,
                error="Claude API timeout (120s). Försök med kortare prompt.",
                provider="claude",
            )
        except requests.exceptions.ConnectionError:
            return AiResponse(
                text="",
                success=False,
                error="Claude API anslutningsfel. Kolla internet.",
                provider="claude",
            )
        except Exception as e:
            return AiResponse(
                text="",
                success=False,
                error=f"Claude-anrop misslyckades: {e}",
                provider="claude",
            )

    def generate_structured(self, prompt: str, schema: dict) -> dict:
        """Generera strukturerad JSON från Claude med tool use.

        Använder Anthropic tool use (function calling) för att garantera
        strukturerad JSON-output, vilket är mer pålitligt än att be
        modellen att generera JSON i texten.

        Args:
            prompt: Prompt-texten
            schema: JSON-schema för önskad output

        Returns:
            Dict med strukturerad data
        """
        # Tool definition för structured output
        tools = [{
            "name": "structured_response",
            "description": "Svara med strukturerad data enligt schemat",
            "input_schema": schema,
        }]

        messages = [
            {"role": "user", "content": prompt},
        ]

        # Anropa med tool use
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "messages": messages,
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "structured_response"},
        }

        try:
            resp = requests.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=120,
            )

            if resp.status_code == 200:
                data = resp.json()
                content_blocks = data.get("content", [])

                for block in content_blocks:
                    if block.get("type") == "tool_use" and block.get("name") == "structured_response":
                        return block.get("input", {})

                # Fallback: försök parsea text som JSON
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text += block.get("text", "")
                return self._parse_json_response(text, schema)

            _logger.warning("Claude structured output failed: %s", resp.status_code)
            return {}

        except Exception as e:
            _logger.error("Claude structured output error: %s", e)
            return {}

    def cost_estimate(self, tokens: TokenUsage) -> float:
        """Beräkna kostnad med hänsyn till prompt caching-rabatt."""
        cfg = self.PROVIDER_CONFIG

        # Cachad input är 90% billigare
        cached_input = tokens.cached_input_tokens
        normal_input = tokens.input_tokens - cached_input

        input_cost = (normal_input / 1_000_000) * cfg.get("cost_per_1m_input", 0)
        cached_cost = (cached_input / 1_000_000) * cfg.get("cost_per_1m_input", 0) * self.CACHED_INPUT_MULTIPLIER
        output_cost = (tokens.output_tokens / 1_000_000) * cfg.get("cost_per_1m_output", 0)

        return round(input_cost + cached_cost + output_cost, 6)

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

        _logger.warning("Kunde inte parsea JSON från Claude-svar")
        return {}
