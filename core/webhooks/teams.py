"""
core/webhooks/teams.py
======================
Microsoft Teams Webhook Integration for MarketScan.
Skickar meddelanden, alerts och digest till Teams via Incoming Webhooks.

Anvander Adaptive Cards for strukturerade meddelanden.
"""

import json
from datetime import datetime
from typing import Optional

import requests


class TeamsWebhook:
    """Skicka meddelanden till Microsoft Teams via webhook."""

    def __init__(self, url: str):
        """
        Args:
            url: Teams Incoming Webhook URL.
        """
        self.url = url

    def _post(self, payload: dict) -> bool:
        """Posta ett meddelande till Teams.

        Args:
            payload: Teams-meddelande (JSON).

        Returns:
            True om lyckades, False annars.
        """
        try:
            resp = requests.post(
                self.url,
                json=payload,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def send_card(self, title: str, message: str, color: str = "0078D4",
                  facts: list[dict] = None) -> bool:
        """Skicka ett Adaptive Card till Teams.

        Args:
            title: Kortets titel.
            message: Huvudmeddelande.
            color: Accentfarg (hex without #).
            facts: Lista av {"name": ..., "value": ...} for faktasektion.

        Returns:
            True om lyckades.
        """
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "title": title,
            "text": message,
            "sections": [],
        }

        if facts:
            card["sections"].append({
                "facts": [{"name": f["name"], "value": f["value"]} for f in facts],
            })

        # Lagg till timestamp
        card["sections"].append({
            "text": f"*MarketScan* | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        })

        return self._post(card)

    def send_alert(self, message: str, severity: str = "info") -> bool:
        """Skicka en alert till Teams.

        Args:
            message: Alert-meddelande.
            severity: "info", "warning", "critical".

        Returns:
            True om lyckades.
        """
        colors = {
            "info": "0078D4",      # Blå
            "warning": "FF8C00",   # Orange
            "critical": "E81123",  # Röd
        }
        labels = {
            "info": "Info",
            "warning": "Warning",
            "critical": "Critical",
        }

        return self.send_card(
            title=f"[{labels.get(severity, 'Info')}] MarketScan Alert",
            message=message,
            color=colors.get(severity, "0078D4"),
        )

    def send_digest(self, alerts: list[dict]) -> bool:
        """Skicka en digest med flera alerts som ett multi-section card.

        Args:
            alerts: Lista av alert-dicts med ticker, message, severity, type.

        Returns:
            True om lyckades.
        """
        if not alerts:
            return self.send_card(
                title="MarketScan Digest",
                message="No alerts to report.",
                color="0078D4",
            )

        sections = []
        for alert in alerts[:25]:  # Max 25 alerts per digest
            severity = alert.get("severity", "info")
            colors = {"info": "blue", "warning": "orange", "critical": "red"}

            sections.append({
                "title": f"{alert.get('ticker', 'N/A')} - {alert.get('type', 'unknown')}",
                "text": alert.get("message", ""),
                "markdown": True,
            })

        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "0078D4",
            "title": f"MarketScan Digest ({len(alerts)} alerts)",
            "text": f"Sammanfattning av {len(alerts)} larm.",
            "sections": sections + [{
                "text": f"*MarketScan* | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            }],
        }

        return self._post(card)

    def send_report(self, title: str, summary_text: str,
                    attachment_url: str = "") -> bool:
        """Skicka en rapport till Teams.

        Args:
            title: Rapporttitel.
            summary_text: Sammanfattningstext.
            attachment_url: URL till full rapport (valfritt).

        Returns:
            True om lyckades.
        """
        text = summary_text
        if attachment_url:
            text += f"\n\n[Download full report]({attachment_url})"

        return self.send_card(
            title=f":chart_with_upwards_trend: {title}",
            message=text,
            color="0078D4",
        )
