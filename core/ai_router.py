"""
core/ai_router.py
=================
A3-split: AI-provider-router för MarketScan.

Centraliserat lager för provider-val, fallback-kedjor och token-tracking.
Extraherat från core/ai_analysis.py som ett led i att bryta upp monoliten.

Användning:
    from core.ai_router import call_ai, get_active_provider
    result = call_ai(messages, system_prompt="...", provider="auto")
    provider = get_active_provider()

Providers prioriteras:
1. Explicit provider-argument
2. AI_PROVIDER-miljövariabel (auto/deepseek/gemini/claude)
3. Fallback-kedja: deepseek → gemini → claude
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_active_provider(provider: str = "auto") -> str:
    """Returnerar den aktiva providerens namn baserat på konfiguration.

    Args:
        provider: "auto", "deepseek", "gemini", "claude", eller "" (= auto)

    Returns:
        str: "deepseek", "gemini", eller "claude"
    """
    if not provider or provider == "auto":
        provider = os.environ.get("AI_PROVIDER", "auto")

    if provider == "auto":
        # Auto-prioritering: deepseek (bäst/billigast) → gemini (gratis) → claude
        from core import config
        if config._get_secret("DEEPSEEK_API_KEY"):
            return "deepseek"
        if config._get_secret("GEMINI_API_KEY"):
            return "gemini"
        if config._get_secret("CLAUDE_API_KEY") or config._get_secret("ANTHROPIC_API_KEY"):
            return "claude"
        return "deepseek"  # Fallback: försök ändå (misslyckas med nyckel-fel)

    return provider.lower()


def call_ai(
    messages: list,
    system_prompt: str = "",
    provider: str = "auto",
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout: int = 60,
    max_retries: int = 3,
) -> tuple[str, dict]:
    """Anropa AI med automatisk provider-val och fallback.

    Args:
        messages: Lista med {"role": "user/assistant", "content": "..."} dicts
        system_prompt: System-prompt (läggs till som första meddelande om angiven)
        provider: "auto", "deepseek", "gemini", "claude"
        model: Specifik modell att använda (tom = provider-default)
        temperature: Kreativitetsnivå (0.0-1.0)
        max_tokens: Max tokens i svaret
        timeout: Timeout i sekunder
        max_retries: Antal återförsök vid tillfälliga fel

    Returns:
        Tuple[str, dict]: (svar-text, token-statistik)
        Returnerar ("", {}) vid fel.
    """
    active = get_active_provider(provider)

    # Bygg fullständiga messages med system prompt
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    # Försök med vald provider
    result, tokens = _try_provider(
        active, full_messages, model, temperature, max_tokens, timeout, max_retries
    )

    if result:
        return result, tokens

    # Fallback: prova andra providers
    fallback_order = [p for p in ["deepseek", "gemini", "claude"] if p != active]
    for fallback in fallback_order:
        logger.warning("AI: %s misslyckades — försöker med fallback %s", active, fallback)
        result, tokens = _try_provider(
            fallback, full_messages, "", temperature, max_tokens, timeout, 1
        )
        if result:
            return result, tokens

    logger.error("AI: Alla providers misslyckades (deepseek, gemini, claude)")
    return "", {}


def _try_provider(
    provider: str,
    messages: list,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    max_retries: int,
) -> tuple[str, dict]:
    """Försöker anropa en specifik provider. Returnerar ("", {}) vid fel."""
    try:
        if provider == "deepseek":
            from core.providers.deepseek_provider import DeepSeekProvider
            from core import config
            api_key = config._get_secret("DEEPSEEK_API_KEY")
            if not api_key:
                return "", {}
            prov = DeepSeekProvider(api_key=api_key, model=model or "deepseek-chat")
            response = prov.generate(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            return response.content, {
                "provider": "deepseek",
                "model": response.model,
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }

        elif provider == "gemini":
            from core.providers.gemini_provider import GeminiProvider
            from core import config
            api_key = config._get_secret("GEMINI_API_KEY")
            if not api_key:
                return "", {}
            prov = GeminiProvider(api_key=api_key, model=model or "gemini-2.0-flash")
            response = prov.generate(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            return response.content, {
                "provider": "gemini",
                "model": response.model,
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }

        elif provider == "claude":
            from core.providers.claude_provider import ClaudeProvider
            from core import config
            api_key = config._get_secret("CLAUDE_API_KEY") or config._get_secret("ANTHROPIC_API_KEY")
            if not api_key:
                return "", {}
            prov = ClaudeProvider(api_key=api_key, model=model or "claude-3-5-haiku-20241022")
            response = prov.generate(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            return response.content, {
                "provider": "claude",
                "model": response.model,
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }

    except Exception as e:
        logger.debug("_try_provider(%s) fel: %s", provider, e)

    return "", {}


def get_providers_status() -> dict:
    """Returnerar status för alla tillgängliga providers (för diagnostik)."""
    from core import config
    return {
        "deepseek": bool(config._get_secret("DEEPSEEK_API_KEY")),
        "gemini": bool(config._get_secret("GEMINI_API_KEY")),
        "claude": bool(
            config._get_secret("CLAUDE_API_KEY") or config._get_secret("ANTHROPIC_API_KEY")
        ),
        "active": get_active_provider(),
    }
