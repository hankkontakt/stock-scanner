"""
SmsChannel — SMS via carrier email-to-SMS-gateways.

Använder den redan konfigurerade email-infrastrukturen (EMAIL_SENDER,
EMAIL_PASSWORD) för att skicka SMS via operatörernas email-till-SMS-gateways.

Stödjer AT&T, Verizon, T-Mobile, Sprint, Telia, Tele2, Telenor, 3, m.fl.

Mjukt beroende: kräver att EMAIL_SENDER + EMAIL_PASSWORD är konfigurerade.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Kända SMS-gateways: {land: {operator: domain}}
CARRIER_GATEWAYS: dict[str, dict[str, str]] = {
    "US": {
        "att": "txt.att.net",
        "verizon": "vtext.com",
        "tmobile": "tmomail.net",
        "sprint": "messaging.sprintpcs.com",
        "xfnity": "vtext.com",
        "cricket": "sms.cricketwireless.net",
        "google_fi": "msg.fi.google.com",
        "uscellular": "email.uscc.net",
    },
    "SE": {
        "telia": "sms.telia.com",
        "tele2": "sms.tele2.se",
        "telenor": "sms.telenor.se",
        "tre": "sms.tre.se",
        "hallon": "sms.telia.com",  # Hallon uses Telia network
        "vipper": "sms.telenor.se",  # Vimla/VIpper uses Telenor
    },
    "NO": {
        "telenor": "mms.telenor.no",
        "telia": "epost.telia.no",
        "ice": "mms.ice.no",
    },
    "DK": {
        "telenor": "sms.telenor.dk",
        "telia": "sms.telia.dk",
        "tdc": "mms.tdc.dk",
        "3": "mms.3.dk",
    },
    "FI": {
        "elisa": "sms.elisa.fi",
        "saunalahti": "sms.saunalahti.fi",
        "telia": "sms.tele.fi",
        "dna": "mms.dna.fi",
    },
}

# Sparar SMS-sändningslogg för rate-limiting
_SMS_LOG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "sms_log.json"


class SmsChannel:
    """SMS-kanal via email-to-SMS-gateways."""

    MAX_DAILY_SMS = 10
    MAX_SMS_LENGTH = 160

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Args:
            config: Dict med SMS_GATEWAYS (dict mapping phone->"number@domain"),
                    EMAIL_SENDER och EMAIL_PASSWORD.
        """
        self._config = config or {}
        self._gateways: dict[str, str] = {}
        self._sender: str = ""
        self._password: str = ""
        self._enabled = False
        self._configure(config)

    def _configure(self, config: Optional[dict]) -> None:
        """Läs konfiguration från core.config."""
        try:
            from core import config as core_config
            self._sender = (self._config.get("EMAIL_SENDER")
                            or getattr(core_config, "EMAIL_SENDER", "")
                            or os_getenv("EMAIL_SENDER", ""))
            self._password = (self._config.get("EMAIL_PASSWORD")
                              or getattr(core_config, "EMAIL_PASSWORD", "")
                              or os_getenv("EMAIL_PASSWORD", ""))
        except ImportError:
            import os
            self._sender = self._config.get("EMAIL_SENDER", os.getenv("EMAIL_SENDER", ""))
            self._password = self._config.get("EMAIL_PASSWORD", os.getenv("EMAIL_PASSWORD", ""))

        # Läs gateways
        raw_gateways = self._config.get(
            "SMS_GATEWAYS",
            self._get_config_json("SMS_GATEWAYS", {}),
        )
        if isinstance(raw_gateways, dict):
            self._gateways = {k.strip(): v.strip() for k, v in raw_gateways.items() if v}

        if not self._sender or not self._password:
            logger.debug("SmsChannel inaktiverad: EMAIL_SENDER eller EMAIL_PASSWORD saknas")
            return

        if not self._gateways:
            logger.debug("SmsChannel inaktiverad: inga SMS-gateways konfigurerade")
            return

        self._enabled = True

    @staticmethod
    def _get_config_json(key: str, default: Any = None) -> Any:
        """Läs en JSON-konfigurationsvariabel från core.config."""
        try:
            from core import config as core_config
            val = getattr(core_config, key, None)
            if val is None:
                return default
            if isinstance(val, (dict, list)):
                return val
            import json
            return json.loads(val) if isinstance(val, str) else default
        except Exception:
            return default

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def name(self) -> str:
        return "sms"

    # ── Kanal-gränssnitt ──────────────────────────────────────────────

    def send_alert(
        self,
        message: str,
        message_type: str = "text",
        **kwargs: Any,
    ) -> bool:
        """Skicka ett SMS-larm.

        Args:
            message: Kort meddelande (< 160 tecken för enkel-SMS).
            message_type: Ignoreras.
            **kwargs: Ignoreras.

        Returns:
            True om SMS skickades till MINST en gateway.
        """
        if not self._enabled:
            return False

        # Rate-limit check
        today = date.today().isoformat()
        sent_today = self._count_sent_today(today)
        if sent_today >= self.MAX_DAILY_SMS:
            logger.warning(
                "SMS rate limit: %d/%d redan skickade idag (%s)",
                sent_today, self.MAX_DAILY_SMS, today,
            )
            return False

        # Kort prefix
        prefix = "[MarketScan] "
        body = f"{prefix}{message.strip()[:self.MAX_SMS_LENGTH - len(prefix)]}"

        sent_any = False
        for label, gateway_addr in self._gateways.items():
            if self._send_sms(gateway_addr, body):
                sent_any = True
                self._log_send(today, label, gateway_addr, True)
            else:
                self._log_send(today, label, gateway_addr, False)

        return sent_any

    def send_test(self) -> str:
        """Skicka ett test-SMS.

        Returns:
            Statussträng för UI-visning.
        """
        if not self._enabled:
            return "INTE KONFIGURERAD — saknar SMS-gateways eller email-konfiguration"

        if not self._gateways:
            return "INTE KONFIGURERAD — inga SMS-gateways (SMS_GATEWAYS) hittades"

        labels = list(self._gateways.keys())
        sent = self.send_alert(f"Test från MarketScan ({datetime.now():%H:%M})")
        if sent:
            return f"OK — test-SMS skickat till {len(labels)} gateway(s): {', '.join(labels)}"
        return "FEL — kunde inte skicka SMS (kontrollera email-konfiguration)"

    # ── Gateway-registrering ───────────────────────────────────────────

    @staticmethod
    def guess_gateway(phone: str, country: str = "SE", operator: str = "") -> str:
        """Gissa SMS-gateway för ett telefonnummer.

        Args:
            phone: Telefonnummer (med eller utan landskod).
            country: Landskod "SE", "US", "NO", "DK", "FI".
            operator: Operatör (valfri). Om tom, returneras första.

        Returns:
            Email-adress för SMS-gateway, t.ex. "46701234567@sms.telia.com"
        """
        # Rensa nummer från allt utom siffror
        digits = re.sub(r"[^\d]", "", phone)
        # Om svenskt nummer utan landskod, lägg till 46
        if country == "SE" and not digits.startswith("46") and digits.startswith("0"):
            digits = "46" + digits[1:]

        gateways = CARRIER_GATEWAYS.get(country, {})
        if not gateways:
            return f"{digits}@sms.telia.com"  # fallback

        domain = ""
        if operator and operator.lower() in gateways:
            domain = gateways[operator.lower()]
        else:
            # Ta första gatewayen för landet
            domain = list(gateways.values())[0]

        return f"{digits}@{domain}"

    # ── Interna ────────────────────────────────────────────────────────

    def _send_sms(self, to_address: str, body: str) -> bool:
        """Skicka ett SMS via email-to-SMS-gateway."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = ""  # Tom subject = bättre SMS-rendering
            msg["From"] = self._sender
            msg["To"] = to_address

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self._sender, self._password)
                server.sendmail(self._sender, [to_address], msg.as_string())

            logger.info("SMS skickat till %s", to_address)
            return True

        except Exception as e:
            logger.warning("SMS misslyckades till %s: %s", to_address, e)
            return False

    def _count_sent_today(self, today: str) -> int:
        """Räkna hur många SMS som skickats idag."""
        try:
            if _SMS_LOG_FILE.exists():
                log = _read_json(_SMS_LOG_FILE, [])
                return sum(1 for entry in log if entry.get("date") == today)
        except Exception:
            pass
        return 0

    def _log_send(self, date_str: str, gateway_label: str, address: str, success: bool) -> None:
        """Logga ett SMS-sändningsförsök."""
        try:
            log = _read_json(_SMS_LOG_FILE, [])
            log = log[-499:]
            log.append({
                "date": date_str,
                "gateway": gateway_label,
                "address": address,
                "success": success,
                "timestamp": datetime.now().isoformat()[:19],
            })
            _write_json(_SMS_LOG_FILE, log)
        except Exception:
            pass


# ── Hjälpfunktioner (modulnivå, återanvändbara) ───────────────────────

def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            import json
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    try:
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# Använd os.getenv som fallback (behövs för modulnivå)
def os_getenv(key: str, default: str = "") -> str:
    import os
    return os.getenv(key, default)
