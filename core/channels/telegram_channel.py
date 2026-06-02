"""
TelegramChannel — Skicka meddelanden via Telegram Bot API.

Mjukt beroende: kräver `requests`. Om TELEGRAM_BOT_TOKEN saknas
i konfigurationen hoppar kanalen över sig själv.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


class TelegramChannel:
    """Telegram Bot-kanal för alert-utskick."""

    # Max tecken per meddelande (Telegram Bot API-gräns)
    MAX_MSG_LENGTH = 4096

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Args:
            config: Dict med TELEGRAM_BOT_TOKEN och TELEGRAM_CHAT_ID.
                    Om None läses från core.config.
        """
        self._config = config or {}
        self._bot_token: str = ""
        self._chat_id: str = ""
        self._enabled = False
        self._configure(config)

    def _configure(self, config: Optional[dict]) -> None:
        """Läs konfiguration och slå på om allt finns."""
        token = (
            self._config.get("TELEGRAM_BOT_TOKEN")
            or self._get_config_attr("TELEGRAM_BOT_TOKEN")
            or ""
        )
        chat_id = (
            self._config.get("TELEGRAM_CHAT_ID")
            or self._get_config_attr("TELEGRAM_CHAT_ID")
            or ""
        )

        if not requests:
            logger.debug("TelegramChannel inaktiverad: requests saknas")
            return

        if not token or not chat_id:
            logger.debug("TelegramChannel inaktiverad: TELEGRAM_BOT_TOKEN eller TELEGRAM_CHAT_ID saknas")
            return

        self._bot_token = token.strip()
        self._chat_id = chat_id.strip()
        self._enabled = True

    @staticmethod
    def _get_config_attr(key: str) -> str:
        """Läs från core.config, returnera tom sträng om det misslyckas."""
        try:
            from core import config
            return str(getattr(config, key, "") or "")
        except ImportError:
            return ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def name(self) -> str:
        return "telegram"

    # ── Kanal-gränssnitt ──────────────────────────────────────────────

    def send_alert(
        self,
        message: str,
        message_type: str = "text",
        image_url: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Skicka ett alert-meddelande till Telegram.

        Args:
            message: Textmeddelande (markdown/HTML stöds).
            message_type: "text", "markdown" eller "html".
            image_url: Valfri bild-URL (chart screenshot etc).
            **kwargs: Ignoreras.

        Returns:
            True om meddelandet skickades.
        """
        if not self._enabled:
            return False

        # Format message with emojis for alerts
        formatted = self._format_alert(message)
        return self._send(formatted, parse_mode=message_type, image_url=image_url)

    def send_daily_report(self, report_md: str) -> bool:
        """Skicka en lång rapport, delad i chunks vid behov.

        Args:
            report_md: Markdown-formaterad rapport.

        Returns:
            True om ALLA chunks skickades.
        """
        if not self._enabled:
            return False

        success = True
        for chunk in self._chunk_text(report_md):
            if not self._send(chunk, parse_mode="markdown"):
                success = False
        return success

    def send_test(self) -> str:
        """Skicka ett testmeddelande för att verifiera kanalen.

        Returns:
            Statussträng för UI-visning.
        """
        if not self._enabled:
            return "INTE KONFIGURERAD — saknar TELEGRAM_BOT_TOKEN eller TELEGRAM_CHAT_ID"

        ok = self._send(
            "✅ *Telegramkanalen fungerar!*\n\n"
            "Detta är ett testmeddelande från MarketScan.\n"
            f"Din chat_id är: `{self._chat_id}`",
            parse_mode="markdown",
        )
        return "OK — testmeddelande skickat" if ok else "FEL — kunde inte skicka"

    # ── Interna ────────────────────────────────────────────────────────

    def _format_alert(self, message: str) -> str:
        """Lägg till emojis och struktur för alert-meddelanden."""
        message = message.strip()
        if not any(message.startswith(c) for c in ["⚠", "🚨", "✅", "📊", "🔔", "💼", "📈", "📉", "⚡", "🟢", "🔴"]):
            message = f"🚨 *MarketScan Alert*\n\n{message}"
        return message

    def _send(
        self,
        text: str,
        parse_mode: str = "markdown",
        image_url: Optional[str] = None,
    ) -> bool:
        """Lägre nivå: skicka ett enskilt meddelande via Telegram Bot API."""
        if not self._enabled:
            return False

        # Parse mode mapping
        parse_map = {
            "text": None,
            "markdown": "MarkdownV2",
            "html": "HTML",
            "": None,
        }
        api_parse = parse_map.get(parse_mode, None)

        try:
            if image_url:
                # Send photo with caption
                resp = requests.post(
                    f"https://api.telegram.org/bot{self._bot_token}/sendPhoto",
                    json={
                        "chat_id": self._chat_id,
                        "photo": image_url,
                        "caption": text[:1024],
                        "parse_mode": api_parse,
                    },
                    timeout=15,
                )
            else:
                resp = requests.post(
                    f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                    json={
                        "chat_id": self._chat_id,
                        "text": text,
                        "parse_mode": api_parse,
                        "disable_web_page_preview": False,
                    },
                    timeout=15,
                )

            if not resp.ok:
                logger.warning(
                    "Telegram API error (status %s): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True

        except requests.exceptions.Timeout:
            logger.warning("Telegram API timeout")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.warning("Telegram connection error: %s", e)
            return False
        except Exception as e:
            logger.exception("Telegram send error: %s", e)
            return False

    def _chunk_text(self, text: str, max_len: int = 0) -> list[str]:
        """Dela lång text i chunks vid lämpliga breakpoints.

        Försöker dela vid dubbelradbrytning först, sen enkel radbrytning.
        """
        max_len = max_len or self.MAX_MSG_LENGTH
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

            # Försök hitta en bra breakpoint
            split_at = text.rfind("\n\n", 0, max_len)
            if split_at == -1 or split_at < max_len // 2:
                split_at = text.rfind("\n", 0, max_len)
            if split_at == -1 or split_at < max_len // 2:
                split_at = text.rfind(" ", 0, max_len)
            if split_at == -1 or split_at < max_len // 2:
                split_at = max_len

            chunks.append(text[:split_at].strip())
            text = text[split_at:].strip()

        return chunks
