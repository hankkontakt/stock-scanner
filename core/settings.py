"""
core/settings.py
================
Centraliserad konfiguration med Pydantic Settings v2.
Läser från .env-fil och miljövariabler med validering och defaults.

E7-implementation: Pydantic BaseSettings som ett lager ovanpå config.py.
Mjuk dependency — faller tillbaka till os.environ om pydantic-settings saknas.

Användning:
    from core.settings import get_settings
    s = get_settings()
    key = s.deepseek_api_key
    if s.is_configured:
        ...
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PYDANTIC_AVAILABLE = False
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field, field_validator
    _PYDANTIC_AVAILABLE = True
except ImportError:
    pass

_ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    """Läser en env-variabel med fallback till tom sträng."""
    return os.environ.get(key, default) or default


# ── Pydantic Settings (om tillgängligt) ─────────────────────────────────────

if _PYDANTIC_AVAILABLE:
    class MarketScanSettings(BaseSettings):
        """Centraliserade MarketScan-inställningar med validering.

        Läses från .env-fil och miljövariabler.
        Alla fält har defaults → systemet fungerar utan konfiguration.
        """
        model_config = SettingsConfigDict(
            env_file=str(_ROOT / ".env"),
            env_file_encoding="utf-8",
            extra="ignore",
            case_sensitive=False,
        )

        # ── AI-nycklar ───────────────────────────────────────────────────────
        deepseek_api_key: str = Field(default="", description="DeepSeek API-nyckel")
        gemini_api_key: str = Field(default="", description="Google Gemini API-nyckel")
        claude_api_key: str = Field(default="", description="Anthropic Claude API-nyckel")
        finnhub_api_key: str = Field(default="", description="Finnhub API-nyckel (sentiment)")
        fmp_api_key: str = Field(default="", description="Financial Modeling Prep API-nyckel")

        # ── E-post / notifieringar ───────────────────────────────────────────
        email_sender: str = Field(default="", description="SMTP avsändare (Gmail etc.)")
        email_password: str = Field(default="", description="SMTP lösenord eller app-lösenord")
        email_to: str = Field(default="", description="Mottagare (kommaseparerade)")
        ntfy_topic: str = Field(default="", description="ntfy.sh topic för push-notiser")
        telegram_bot_token: str = Field(default="", description="Telegram Bot Token")
        telegram_chat_id: str = Field(default="", description="Telegram Chat ID")
        discord_webhook: str = Field(default="", description="Discord webhook URL")

        # ── GitHub ──────────────────────────────────────────────────────────
        github_token: str = Field(default="", description="GitHub Personal Access Token")
        github_owner: str = Field(default="", description="GitHub repo ägare")
        github_repo: str = Field(default="", description="GitHub repo-namn")

        # ── Pipeline-konfiguration ───────────────────────────────────────────
        ai_provider: str = Field(default="auto", description="AI-provider: auto/deepseek/gemini/claude")
        rotation_dry_run: bool = Field(default=True, description="Dry run för rotation (ingen handel)")

        # ── Sökvägar ─────────────────────────────────────────────────────────
        data_dir: str = Field(default="data", description="Datamapp (relativ till projektroten)")
        reports_dir: str = Field(default="reports", description="Rapportmapp")

        @property
        def is_configured(self) -> bool:
            """Returnerar True om minst en AI-nyckel är konfigurerad."""
            return bool(self.deepseek_api_key or self.gemini_api_key)

        @property
        def has_email(self) -> bool:
            """Returnerar True om e-postinställningar är konfigurerade."""
            return bool(self.email_sender and self.email_password and self.email_to)

        def masked(self) -> dict:
            """Returnerar inställningar med maskerade nycklar (för diagnostik)."""
            result = {}
            for field_name, field in self.model_fields.items():
                val = getattr(self, field_name)
                if isinstance(val, str) and len(val) > 8 and "key" in field_name.lower():
                    result[field_name] = val[:4] + "..." + val[-4:]
                elif isinstance(val, str) and "password" in field_name.lower():
                    result[field_name] = "***" if val else ""
                else:
                    result[field_name] = val
            return result


else:
    # ── Fallback utan pydantic-settings ──────────────────────────────────────
    class MarketScanSettings:  # type: ignore[no-redef]
        """Fallback-implementering baserad på os.environ."""

        def __init__(self):
            self.deepseek_api_key = _env("DEEPSEEK_API_KEY")
            self.gemini_api_key = _env("GEMINI_API_KEY")
            self.claude_api_key = _env("CLAUDE_API_KEY")
            self.finnhub_api_key = _env("FINNHUB_API_KEY")
            self.fmp_api_key = _env("FMP_API_KEY")
            self.email_sender = _env("EMAIL_SENDER")
            self.email_password = _env("EMAIL_PASSWORD")
            self.email_to = _env("EMAIL_TO")
            self.ntfy_topic = _env("NTFY_TOPIC")
            self.telegram_bot_token = _env("TELEGRAM_BOT_TOKEN")
            self.telegram_chat_id = _env("TELEGRAM_CHAT_ID")
            self.discord_webhook = _env("DISCORD_WEBHOOK_URL")
            self.github_token = _env("GITHUB_TOKEN")
            self.github_owner = _env("GITHUB_OWNER")
            self.github_repo = _env("GITHUB_REPO")
            self.ai_provider = _env("AI_PROVIDER", "auto")
            self.rotation_dry_run = _env("ROTATION_DRY_RUN", "true").lower() == "true"
            self.data_dir = _env("DATA_DIR", "data")
            self.reports_dir = _env("REPORTS_DIR", "reports")

        @property
        def is_configured(self) -> bool:
            return bool(self.deepseek_api_key or self.gemini_api_key)

        @property
        def has_email(self) -> bool:
            return bool(self.email_sender and self.email_password and self.email_to)

        def masked(self) -> dict:
            result = {}
            for attr in vars(self):
                val = getattr(self, attr)
                if isinstance(val, str) and len(val) > 8 and "key" in attr:
                    result[attr] = val[:4] + "..." + val[-4:]
                elif isinstance(val, str) and "password" in attr:
                    result[attr] = "***" if val else ""
                else:
                    result[attr] = val
            return result


# ── Singleton ────────────────────────────────────────────────────────────────

_settings_instance: MarketScanSettings | None = None


def get_settings() -> MarketScanSettings:
    """Returnerar den centrala settings-instansen (singleton, lazy-init)."""
    global _settings_instance
    if _settings_instance is None:
        try:
            _settings_instance = MarketScanSettings()
        except Exception as e:
            logger.warning("settings.get_settings() misslyckades med Pydantic, faller tillbaka: %s", e)
            # Explicit fallback om pydantic-validering kastar
            _settings_instance = MarketScanSettings.__new__(MarketScanSettings)
            MarketScanSettings.__init__(_settings_instance)  # type: ignore
    return _settings_instance


def reload_settings() -> MarketScanSettings:
    """Tvingar en omladdning av settings (t.ex. efter .env-ändring)."""
    global _settings_instance
    _settings_instance = None
    return get_settings()
