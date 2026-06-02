"""
DiscordChannel — Skicka meddelanden via Discord Webhooks.

Mjukt beroende: kräver `requests`. Om DISCORD_WEBHOOK_URL saknas
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


class DiscordChannel:
    """Discord Webhook-kanal för alert-utskick."""

    # Discord embed-färger (decimal)
    COLOR_RED = 0xDC2626
    COLOR_GREEN = 0x16A34A
    COLOR_YELLOW = 0xF59E0B
    COLOR_BLUE = 0x2563EB

    # Max tecken per meddelande (Discord limit)
    MAX_MSG_LENGTH = 2000

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Args:
            config: Dict med DISCORD_WEBHOOK_URL.
                    Om None läses från core.config.
        """
        self._config = config or {}
        self._webhook_url: str = ""
        self._enabled = False
        self._configure(config)

    def _configure(self, config: Optional[dict]) -> None:
        """Läs konfiguration och slå på om allt finns."""
        webhook_url = (
            self._config.get("DISCORD_WEBHOOK_URL")
            or self._get_config_attr("DISCORD_WEBHOOK_URL")
            or ""
        )

        if not requests:
            logger.debug("DiscordChannel inaktiverad: requests saknas")
            return

        if not webhook_url:
            logger.debug("DiscordChannel inaktiverad: DISCORD_WEBHOOK_URL saknas")
            return

        self._webhook_url = webhook_url.strip()
        self._enabled = True

    @staticmethod
    def _get_config_attr(key: str) -> str:
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
        return "discord"

    # ── Kanal-gränssnitt ──────────────────────────────────────────────

    def send_alert(
        self,
        message: str,
        message_type: str = "text",
        color: str = "red",
        fields: Optional[list[dict[str, str]]] = None,
        **kwargs: Any,
    ) -> bool:
        """Skicka en alert som en Discord-embed.

        Args:
            message: Huvudtext (används som description i embed).
            message_type: Ignoreras för Discord (använder alltid embeds).
            color: "red", "green", "yellow", "blue" eller en hex-färg.
            fields: Extra fält för embeden, t.ex. [{"name": "Pris", "value": "150 kr"}]
            **kwargs: Kan innehålla "title" för embed-titel.

        Returns:
            True om meddelandet skickades.
        """
        if not self._enabled:
            return False

        embed_color = self._resolve_color(color)
        title = kwargs.get("title", "MarketScan Alert")

        embed = {
            "title": title[:256],
            "description": message[:4096],
            "color": embed_color,
            "footer": {"text": "MarketScan — Automatisk notis"},
        }

        if fields:
            embed["fields"] = [
                {"name": str(f.get("name", ""))[:256],
                 "value": str(f.get("value", ""))[:1024],
                 "inline": f.get("inline", False)}
                for f in fields
            ]

        payload = {"embeds": [embed]}
        return self._send_json(payload)

    def send_report(self, report_md: str) -> bool:
        """Skicka en rapport, delad i 2000-teckenchunks.

        Args:
            report_md: Markdown-text.

        Returns:
            True om ALLA delar skickades.
        """
        if not self._enabled:
            return False

        success = True
        for chunk in self._chunk_text(report_md):
            payload = {"content": chunk[:self.MAX_MSG_LENGTH]}
            if not self._send_json(payload):
                success = False
        return success

    def send_test(self) -> str:
        """Skicka ett testmeddelande.

        Returns:
            Statussträng för UI-visning.
        """
        if not self._enabled:
            return "INTE KONFIGURERAD — saknar DISCORD_WEBHOOK_URL"

        ok = self._send_json({
            "embeds": [{
                "title": "Testmeddelande",
                "description": "Discord-kanalen fungerar!  \\nDetta är ett test från MarketScan.",
                "color": self.COLOR_GREEN,
                "footer": {"text": "MarketScan — Test"},
            }]
        })
        return "OK — testmeddelande skickat" if ok else "FEL — kunde inte skicka"

    # ── Interna ────────────────────────────────────────────────────────

    def _resolve_color(self, color: str) -> int:
        mapping = {
            "red": self.COLOR_RED,
            "green": self.COLOR_GREEN,
            "yellow": self.COLOR_YELLOW,
            "blue": self.COLOR_BLUE,
            "warning": self.COLOR_YELLOW,
            "critical": self.COLOR_RED,
            "info": self.COLOR_BLUE,
            "success": self.COLOR_GREEN,
        }
        if color.lower() in mapping:
            return mapping[color.lower()]
        # Försök tolka som hex
        try:
            return int(color.lstrip("#"), 16)
        except (ValueError, AttributeError):
            return self.COLOR_BLUE

    def _send_json(self, payload: dict) -> bool:
        """Skicka JSON-payload till Discord webhook."""
        if not self._enabled:
            return False

        try:
            resp = requests.post(
                self._webhook_url,
                json=payload,
                timeout=15,
            )
            # Discord returnerar 204 No Content vid success
            if resp.status_code not in (200, 204):
                logger.warning(
                    "Discord webhook error (status %s): %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return False
            return True

        except requests.exceptions.Timeout:
            logger.warning("Discord webhook timeout")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.warning("Discord connection error: %s", e)
            return False
        except Exception as e:
            logger.exception("Discord send error: %s", e)
            return False

    def _chunk_text(self, text: str, max_len: int = 0) -> list[str]:
        """Dela lång text i chunks vid lämpliga breakpoints."""
        max_len = max_len or self.MAX_MSG_LENGTH
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break

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
