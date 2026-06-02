"""
PushChannel — Push-notifikationer via ntfy.sh.

ntfy.sh är en gratis, öppen källkods-tjänst för push-notiser.
Kräver bara en topic-sträng — ingen API-nyckel.
POSTar JSON till https://ntfy.sh/{topic}.

Mjukt beroende: kräver `requests`. Om NTFY_TOPIC saknas
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


# ntfy.sh prioriteringar (1=minst, 5=max, 4=default high)
PRIORITY_MAP: dict[str, int] = {
    "low": 1,
    "default": 3,
    "high": 4,
    "urgent": 5,
}


class PushChannel:
    """Push-notifikationskanal via ntfy.sh."""

    BASE_URL = "https://ntfy.sh"

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Args:
            config: Dict med NTFY_TOPIC.
        """
        self._config = config or {}
        self._topic: str = ""
        self._enabled = False
        self._configure(config)

    def _configure(self, config: Optional[dict]) -> None:
        """Läs konfiguration och slå på om allt finns."""
        topic = (
            self._config.get("NTFY_TOPIC")
            or self._get_config_attr("NTFY_TOPIC")
            or ""
        )

        if not requests:
            logger.debug("PushChannel inaktiverad: requests saknas")
            return

        if not topic:
            logger.debug("PushChannel inaktiverad: NTFY_TOPIC saknas")
            return

        self._topic = topic.strip()
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
        return "push"

    # ── Kanal-gränssnitt ──────────────────────────────────────────────

    def send_alert(
        self,
        message: str,
        message_type: str = "text",
        priority: int = 4,
        title: Optional[str] = None,
        tags: Optional[list[str]] = None,
        click_url: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Skicka en push-notifikation.

        Args:
            message: Meddelandetext.
            message_type: Ignoreras.
            priority: 1-5 (ntfy.sh prio). 4=high, 5=urgent.
            title: Notifikationstitel (default: "MarketScan Alert").
            tags: Lista med taggar/emojis, t.ex. ["chart", "warning"].
                  ntfy.sh renderar vissa taggar som emojis.
            click_url: URL att öppna när användaren klickar på notisen.
            **kwargs: Ignoreras.

        Returns:
            True om notisen skickades.
        """
        if not self._enabled:
            return False

        payload: dict[str, Any] = {
            "topic": self._topic,
            "message": message,
        }

        # Titel
        payload["title"] = (title or "MarketScan Alert")[:256]

        # Prioritet (1-5)
        if isinstance(priority, str):
            priority = PRIORITY_MAP.get(priority.lower(), 4)
        payload["priority"] = max(1, min(5, int(priority)))

        # Tags
        if tags:
            payload["tags"] = tags

        # Click-URL
        if click_url:
            payload["click"] = click_url

        return self._send(payload)

    def send_test(self) -> str:
        """Skicka ett testmeddelande.

        Returns:
            Statussträng för UI-visning.
        """
        if not self._enabled:
            return "INTE KONFIGURERAD — saknar NTFY_TOPIC"

        ok = self.send_alert(
            message="Detta är ett test från MarketScan. Din push-kanal fungerar!",
            title="MarketScan Test",
            priority=3,
            tags=["white_check_mark"],
        )
        return "OK — test-push skickad" if ok else "FEL — kunde inte skicka"

    # ── Interna ────────────────────────────────────────────────────────

    def _send(self, payload: dict) -> bool:
        """Skicka JSON-payload till ntfy.sh."""
        try:
            url = f"{self.BASE_URL}/{self._topic}"
            # Använd POST till base-URL:en med topic i body = enklare auth
            resp = requests.post(
                self.BASE_URL,
                json=payload,
                timeout=10,
            )

            if not resp.ok:
                logger.warning(
                    "ntfy.sh error (status %s): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True

        except requests.exceptions.Timeout:
            logger.warning("ntfy.sh timeout")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.warning("ntfy.sh connection error: %s", e)
            return False
        except Exception as e:
            logger.exception("ntfy.sh send error: %s", e)
            return False
