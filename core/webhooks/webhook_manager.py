"""
core/webhooks/webhook_manager.py
================================
Webhook Manager for MarketScan.
Hanterar registrering, leverans och loggning av webhooks.

Events:
  - scan.completed: ny scan klar
  - alert.triggered: ny alert
  - portfolio.change: portfoljandring
  - price.target: prislarm
  - ai.analysis: ny AI-analys

Delivery:
  - POST till webhook URL med HMAC-SHA256 signatur
  - Retry: 3 ganger med exponential backoff (5s, 30s, 300s)
  - Timeout: 10 sekunder per leverans
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import requests

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
WEBHOOKS_FILE = DATA_DIR / "webhooks.json"
WEBHOOK_LOG = DATA_DIR / "webhook_log.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

VALID_EVENTS = {
    "scan.completed",
    "alert.triggered",
    "portfolio.change",
    "price.target",
    "ai.analysis",
}


def _load_data(path: Path) -> list:
    """Ladda JSON-data fran fil. Returnerar tom lista vid fel."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_data(path: Path, data: list) -> bool:
    """Spara JSON-data till fil."""
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


class WebhookManager:
    """Hanterar webhook-registrering, trigging och leverans."""

    def __init__(self):
        self.webhooks = _load_data(WEBHOOKS_FILE)

    # ── Registrering ─────────────────────────────────────────────────────────────

    def register_webhook(self, url: str, events: list[str],
                         secret: str = "") -> Optional[str]:
        """Registrera en ny webhook.

        Args:
            url: Webhook-URL att leverera till.
            events: Lista av event att prenumerera pa.
            secret: Hemlig nyckel for HMAC-signering (genereras om tom).

        Returns:
            Webhook-ID om lyckades, None annars.
        """
        if not url.startswith("https://"):
            return None

        invalid = [e for e in events if e not in VALID_EVENTS]
        if invalid:
            return None

        webhook_id = str(uuid.uuid4())[:8]
        secret = secret or uuid.uuid4().hex

        webhook = {
            "id": webhook_id,
            "url": url,
            "events": events,
            "secret": secret,
            "active": True,
            "created": datetime.now().isoformat(),
            "last_triggered": None,
            "delivery_count": 0,
            "failure_count": 0,
        }

        self.webhooks.append(webhook)
        _save_data(WEBHOOKS_FILE, self.webhooks)
        return webhook_id

    def unregister_webhook(self, webhook_id: str) -> bool:
        """Ta bort en webhook.

        Args:
            webhook_id: Webhook-ID att ta bort.

        Returns:
            True om borttagen, False om ej hittad.
        """
        before = len(self.webhooks)
        self.webhooks = [w for w in self.webhooks if w["id"] != webhook_id]
        if len(self.webhooks) < before:
            _save_data(WEBHOOKS_FILE, self.webhooks)
            return True
        return False

    def get_webhook(self, webhook_id: str) -> Optional[dict]:
        """Hämta en specifik webhook."""
        for w in self.webhooks:
            if w["id"] == webhook_id:
                return w
        return None

    def list_webhooks(self) -> list[dict]:
        """Lista alla registrerade webhooks (exklusive hemligheter)."""
        safe = []
        for w in self.webhooks:
            safe.append({k: v for k, v in w.items() if k != "secret"})
        return safe

    # ── Trigger ──────────────────────────────────────────────────────────────────

    def trigger_event(self, event: str, payload: dict) -> list[dict]:
        """Trigga alla prenumeranter pa ett event.

        Args:
            event: Event-namn (t.ex. "scan.completed").
            payload: Data att skicka.

        Returns:
            Lista av leveransresultat.
        """
        if event not in VALID_EVENTS:
            return []

        subscribers = [
            w for w in self.webhooks
            if w.get("active", False) and event in w.get("events", [])
        ]

        results = []
        for webhook in subscribers:
            result = self.deliver_webhook(webhook, event, payload)
            results.append(result)

            # Uppdatera rakneverk
            webhook["last_triggered"] = datetime.now().isoformat()
            webhook["delivery_count"] = webhook.get("delivery_count", 0) + 1
            if not result.get("success", False):
                webhook["failure_count"] = webhook.get("failure_count", 0) + 1

        _save_data(WEBHOOKS_FILE, self.webhooks)
        return results

    # ── Delivery ─────────────────────────────────────────────────────────────────

    def deliver_webhook(self, webhook: dict, event: str,
                        payload: dict) -> dict:
        """Leverera en webhook med retry-logik.

        Args:
            webhook: Webhook-konfiguration.
            event: Event-namn.
            payload: Data att skicka.

        Returns:
            Dict med leveransresultat.
        """
        delivery_id = str(uuid.uuid4())[:12]
        url = webhook["url"]
        secret = webhook.get("secret", "")

        body = json.dumps({
            "event": event,
            "delivery_id": delivery_id,
            "timestamp": datetime.now().isoformat(),
            "payload": payload,
        }, ensure_ascii=False)

        # HMAC-SHA256 signatur
        signature = hmac.new(
            secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": event,
            "X-Webhook-Delivery": delivery_id,
            "User-Agent": "MarketScan-Webhook/1.0",
        }

        # Retry: 3 ganger med exponential backoff
        retry_delays = [5, 30, 300]
        last_error = ""
        status_code = 0

        for attempt, delay in enumerate(retry_delays + [0]):  # +0 for 4th attempt
            try:
                resp = requests.post(
                    url,
                    data=body,
                    headers=headers,
                    timeout=10,
                )
                status_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    self._log_delivery(delivery_id, webhook["id"], event, True,
                                       status_code, "")
                    return {
                        "delivery_id": delivery_id,
                        "success": True,
                        "status_code": status_code,
                        "attempts": attempt + 1,
                    }
                last_error = f"HTTP {resp.status_code}"
            except requests.Timeout:
                last_error = "timeout"
            except requests.ConnectionError:
                last_error = "connection_error"
            except Exception as e:
                last_error = str(e)

            if attempt < len(retry_delays) - 1:
                time.sleep(delay)
            else:
                break

        self._log_delivery(delivery_id, webhook["id"], event, False,
                           status_code, last_error)
        return {
            "delivery_id": delivery_id,
            "success": False,
            "status_code": status_code,
            "error": last_error,
            "attempts": 4,
        }

    # ── Delivery Log ─────────────────────────────────────────────────────────────

    def _log_delivery(self, delivery_id: str, webhook_id: str, event: str,
                      success: bool, status_code: int, error: str):
        """Logga en leverans."""
        log_entry = {
            "delivery_id": delivery_id,
            "webhook_id": webhook_id,
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "status_code": status_code,
            "error": error,
        }
        logs = _load_data(WEBHOOK_LOG)
        logs.append(log_entry)
        # Behåll max 1000 loggar
        if len(logs) > 1000:
            logs = logs[-1000:]
        _save_data(WEBHOOK_LOG, logs)

    def get_delivery_log(self, webhook_id: str = "") -> list[dict]:
        """Hamta leveranshistorik.

        Args:
            webhook_id: Filtrera pa webhook-ID (tom = alla).

        Returns:
            Lista av leveransloggar.
        """
        logs = _load_data(WEBHOOK_LOG)
        if webhook_id:
            logs = [l for l in logs if l.get("webhook_id") == webhook_id]
        return logs[-100:]

    # ── Webhook Statistics ───────────────────────────────────────────────────────

    def get_webhook_stats(self) -> dict:
        """Returnera statistik over alla webhooks."""
        total = len(self.webhooks)
        active = sum(1 for w in self.webhooks if w.get("active", False))
        total_deliveries = sum(w.get("delivery_count", 0) for w in self.webhooks)
        total_failures = sum(w.get("failure_count", 0) for w in self.webhooks)

        return {
            "total_webhooks": total,
            "active_webhooks": active,
            "total_deliveries": total_deliveries,
            "total_failures": total_failures,
            "delivery_success_rate": (
                round((total_deliveries - total_failures) / total_deliveries * 100, 1)
                if total_deliveries > 0 else 100.0
            ),
        }
