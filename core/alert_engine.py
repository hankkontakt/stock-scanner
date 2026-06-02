"""
alert_engine.py — Central alert- dispatchmotor.

Hanterar ALLA kanaler (Telegram, Discord, SMS, Push, Email) centralt med:
  - Rate-limiting per kanal (max N alerts/timme, configurable)
  - Dedup (samma alerttyp + ticker max 1 gång/dag)
  - Prioritering (HIGH=alla kanaler, MEDIUM=email+vald, LOW=endast email)
  - Graceful degradation (kanal som failar påverkar inte andra)
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Standardkanaler (i prioritetsordning för MEDIUM)
DEFAULT_CHANNELS = ["telegram", "discord", "email", "push"]

# Sökväg för rate-limit/dedup-state
_ALERT_STATE_DIR = Path(__file__).resolve().parent.parent / "data"
_RATE_LIMIT_FILE = _ALERT_STATE_DIR / "alert_rate_limit.json"
_DEDUP_FILE = _ALERT_STATE_DIR / "alert_dedup.json"


class AlertEngine:
    """Central motor för multi-channel alert-utskick.

    Användning:
        engine = AlertEngine()
        engine.send_alert("prisalarm", {"ticker": "AAPL", "price": 150},
                          channels=["telegram", "email"], priority="HIGH")
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Args:
            config: Dict med kanalkonfiguration. Om None läses från env.
        """
        self._config = config or {}
        self._lock = threading.Lock()

        # Initiera kanaler (mjuka beroenden)
        self._channels: dict[str, Any] = {}
        self._init_channels()

        # Rate-limit state: {kanal: [(timestamp,), ...]}
        self._rate_history: dict[str, list[float]] = defaultdict(list)

        # Dedup state: {(alert_type, ticker, date): True}
        self._dedup_state: dict[tuple[str, str, str], bool] = {}

        # Ladda sparat state
        self._load_state()

        # Läs rate-limit-konfiguration
        self._rate_limits: dict[str, int] = {
            "telegram": int(self._get_config_val("TELEGRAM_RATE_LIMIT", "60")),
            "discord": int(self._get_config_val("DISCORD_RATE_LIMIT", "60")),
            "sms": int(self._get_config_val("SMS_RATE_LIMIT", "10")),
            "push": int(self._get_config_val("PUSH_RATE_LIMIT", "60")),
            "email": int(self._get_config_val("EMAIL_RATE_LIMIT", "30")),
        }

    def _init_channels(self) -> None:
        """Initiera alla kanaler (graceful om import/config saknas)."""
        try:
            from core.channels.telegram_channel import TelegramChannel
            tc = TelegramChannel(self._config)
            if tc.enabled:
                self._channels["telegram"] = tc
        except Exception as e:
            logger.debug("TelegramChannel kunde inte laddas: %s", e)

        try:
            from core.channels.discord_channel import DiscordChannel
            dc = DiscordChannel(self._config)
            if dc.enabled:
                self._channels["discord"] = dc
        except Exception as e:
            logger.debug("DiscordChannel kunde inte laddas: %s", e)

        try:
            from core.channels.sms_channel import SmsChannel
            sc = SmsChannel(self._config)
            if sc.enabled:
                self._channels["sms"] = sc
        except Exception as e:
            logger.debug("SmsChannel kunde inte laddas: %s", e)

        try:
            from core.channels.push_channel import PushChannel
            pc = PushChannel(self._config)
            if pc.enabled:
                self._channels["push"] = pc
        except Exception as e:
            logger.debug("PushChannel kunde inte laddas: %s", e)

    def _get_config_val(self, key: str, default: str = "") -> str:
        """Läs från core.config eller env."""
        val = self._config.get(key)
        if val:
            return str(val)
        try:
            from core import config as core_config
            return str(getattr(core_config, key, default) or default)
        except ImportError:
            import os
            return os.getenv(key, default)

    # ── Huvud-API ──────────────────────────────────────────────────────

    def send_alert(
        self,
        message_type: str,
        message_data: dict[str, Any],
        channels: Optional[list[str]] = None,
        priority: str = "MEDIUM",
    ) -> dict[str, bool]:
        """Skicka en alert via valda kanaler.

        Args:
            message_type: Typ av alert, t.ex. "prisalarm", "stark_signal",
                          "insider_kop", "daglig_rapport".
            message_data: Dict med data, måste innehålla "message" (str).
                          För aktie-relaterade: "ticker" (för dedup).
            channels: Lista av kanaler. None = DEFAULT_CHANNELS.
            priority: "HIGH" (alla kanaler omedelbart),
                      "MEDIUM" (email + första tillgängliga kanal),
                      "LOW" (endast email).

        Returns:
            Dict {kanalnamn: True/False} med status per kanal.
        """
        channels = channels or DEFAULT_CHANNELS
        message = str(message_data.get("message", ""))
        ticker = str(message_data.get("ticker", ""))
        title = str(message_data.get("title", ""))

        if not message:
            logger.warning("send_alert anropad utan message — hoppar över")
            return {}

        # Dedup-kontroll (samma typ + ticker max 1 gång/dag)
        today = date.today().isoformat()
        if ticker:
            dedup_key = (message_type, ticker.upper(), today)
            with self._lock:
                if dedup_key in self._dedup_state:
                    logger.info(
                        "Dedup: hoppar över %s/%s (redan skickad idag)",
                        message_type, ticker,
                    )
                    return {"_deduped": True}
                self._dedup_state[dedup_key] = True

        # Välj kanaler baserat på prioritet
        target_channels = self._resolve_channels(channels, priority)

        result: dict[str, bool] = {}
        for chan_name in target_channels:
            channel = self._channels.get(chan_name)
            if not channel:
                result[chan_name] = False
                continue

            # Rate-limit check
            if not self._check_rate_limit(chan_name):
                logger.warning("Rate limit nådd för %s — hoppar över", chan_name)
                result[chan_name] = False
                continue

            try:
                ok = channel.send_alert(
                    message=message,
                    message_type=message_type,
                    title=title,
                    **{k: v for k, v in message_data.items()
                       if k not in ("message", "ticker", "title")},
                )
                result[chan_name] = ok
                if ok:
                    self._record_send(chan_name)
            except Exception as e:
                logger.exception("Kanal %s kastade undantag: %s", chan_name, e)
                result[chan_name] = False

        # Spara state (dedup + rate-limit)
        self._save_state()

        return result

    def send_daily_report(
        self,
        report_md: str,
        channels: Optional[list[str]] = None,
    ) -> dict[str, bool]:
        """Skicka en daglig/veckorapport via valda kanaler.

        Args:
            report_md: Markdown-formaterad rapport.
            channels: Kanaler. None = telegram + email.

        Returns:
            Dict {kanalnamn: True/False}.
        """
        channels = channels or [c for c in ["telegram", "discord", "email"]
                                if c in self._channels]
        result: dict[str, bool] = {}

        message_data = {
            "message": report_md,
            "title": f"MarketScan Rapport — {date.today().isoformat()}",
        }

        for chan_name in channels:
            channel = self._channels.get(chan_name)
            if not channel:
                result[chan_name] = False
                continue

            if not self._check_rate_limit(chan_name):
                result[chan_name] = False
                continue

            try:
                # Vissa kanaler har egna report-metoder
                if hasattr(channel, "send_daily_report"):
                    ok = channel.send_daily_report(report_md)
                elif hasattr(channel, "send_report"):
                    ok = channel.send_report(report_md)
                else:
                    ok = channel.send_alert(
                        message=report_md[:4000],
                        message_type="report",
                    )
                result[chan_name] = ok
                if ok:
                    self._record_send(chan_name)
            except Exception as e:
                logger.exception("Rapport till %s misslyckades: %s", chan_name, e)
                result[chan_name] = False

        return result

    def send_digest(
        self,
        alerts: list[dict[str, Any]],
        channels: Optional[list[str]] = None,
    ) -> dict[str, bool]:
        """Skicka en daglig sammanfattning av missade/lågprioriterade alerts.

        Args:
            alerts: Lista av alert-dicts.
            channels: Kanaler. None = email (digests skickas bara som email).

        Returns:
            Dict {kanalnamn: True/False}.
        """
        from core.email_template import send_digest_email
        channels = channels or ["email"]
        result: dict[str, bool] = {}

        if "email" in channels:
            try:
                ok = send_digest_email(alerts)
                result["email"] = ok
            except Exception as e:
                logger.exception("Digest-email misslyckades: %s", e)
                result["email"] = False

        return result

    def send_test(self, channel_name: str) -> str:
        """Skicka ett testmeddelande till en specifik kanal.

        Args:
            channel_name: "telegram", "discord", "sms", "push", "email"

        Returns:
            Statussträng.
        """
        if channel_name == "email":
            # Testa email separat
            from core.email_template import send_email
            ok = send_email(
                subject="MarketScan Test",
                body_markdown="Detta är ett test från MarketScan.  \nEmail-kanalen fungerar!",
                from_name="MarketScan Test",
            )
            return "OK — testmail skickat" if ok else "FEL — kunde inte skicka"

        channel = self._channels.get(channel_name)
        if not channel:
            return f"INTE TILLGÄNGLIG — kanalen '{channel_name}' är inte konfigurerad"

        try:
            if hasattr(channel, "send_test"):
                return channel.send_test()
            return "OK — kanal tillgänglig"
        except Exception as e:
            logger.exception("Test för %s misslyckades: %s", channel_name, e)
            return f"FEL — {e}"

    def get_channel_status(self) -> dict[str, bool]:
        """Returnera status för alla kanaler.

        Returns:
            Dict {kanalnamn: True (aktiv)/False (inaktiv)}.
        """
        status = {}
        for name in DEFAULT_CHANNELS:
            ch = self._channels.get(name)
            status[name] = ch.enabled if ch else False
        # SMS är extra
        sms = self._channels.get("sms")
        status["sms"] = sms.enabled if sms else False
        return status

    def get_available_channels(self) -> list[str]:
        """Returnera lista med aktiverade kanaler."""
        return [name for name, ch in self._channels.items() if ch.enabled]

    # ── Intern logik ───────────────────────────────────────────────────

    def _resolve_channels(
        self,
        requested: list[str],
        priority: str,
    ) -> list[str]:
        """Välj kanaler baserat på prioritet."""
        priority = priority.upper()

        if priority == "HIGH":
            # Alla tillgängliga kanaler
            return [c for c in requested if c in self._channels]

        if priority == "LOW":
            # Endast email
            return ["email"] if "email" in self._channels else []

        # MEDIUM: email + första tillgängliga icke-emailkanal
        mediums = []
        if "email" in self._channels:
            mediums.append("email")
        for c in requested:
            if c in self._channels and c != "email":
                mediums.append(c)
                break
        return mediums

    def _check_rate_limit(self, channel: str) -> bool:
        """Kontrollera om kanalen har nått sin rate limit (max N/timme).

        Returns:
            True om meddelandet får skickas.
        """
        max_per_hour = self._rate_limits.get(channel, 60)
        if max_per_hour <= 0:
            return True  # ingen begränsning

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        with self._lock:
            history = self._rate_history.get(channel, [])
            # Rensa gamla poster
            history = [ts for ts in history if ts > one_hour_ago.timestamp()]
            self._rate_history[channel] = history

            if len(history) >= max_per_hour:
                return False
            return True

    def _record_send(self, channel: str) -> None:
        """Registrera att ett meddelande skickades via kanalen."""
        with self._lock:
            self._rate_history[channel].append(datetime.now().timestamp())

    def _load_state(self) -> None:
        """Ladda rate-limit och dedup-state från disk."""
        self._load_rate_limit_state()
        self._load_dedup_state()

    def _load_rate_limit_state(self) -> None:
        try:
            if _RATE_LIMIT_FILE.exists():
                data = json.loads(_RATE_LIMIT_FILE.read_text(encoding="utf-8"))
                today = date.today().isoformat()
                if data.get("date") == today:
                    for ch, timestamps in data.get("history", {}).items():
                        self._rate_history[ch] = timestamps
        except Exception:
            pass

    def _load_dedup_state(self) -> None:
        try:
            if _DEDUP_FILE.exists():
                data = json.loads(_DEDUP_FILE.read_text(encoding="utf-8"))
                today = date.today().isoformat()
                if data.get("date") == today:
                    for key_str in data.get("deduped", []):
                        parts = key_str.split("|")
                        if len(parts) == 3:
                            self._dedup_state[tuple(parts)] = True  # type: ignore[assignment]
        except Exception:
            pass

    def _save_state(self) -> None:
        """Spara rate-limit och dedup-state till disk."""
        self._save_rate_limit_state()
        self._save_dedup_state()

    def _save_rate_limit_state(self) -> None:
        try:
            today = date.today().isoformat()
            data = {
                "date": today,
                "history": {
                    ch: ts_list
                    for ch, ts_list in self._rate_history.items()
                },
            }
            _RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            _RATE_LIMIT_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _save_dedup_state(self) -> None:
        try:
            today = date.today().isoformat()
            data = {
                "date": today,
                "deduped": ["|".join(k) for k in self._dedup_state],
            }
            _DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DEDUP_FILE.write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception:
            pass
