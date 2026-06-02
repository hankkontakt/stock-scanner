"""
core/webhooks/slack.py
======================
Slack Webhook Integration for MarketScan.
Skickar meddelanden, rapporter och digest till Slack via Incoming Webhooks.

Anvander Slack Block Kit for strukturerade meddelanden.
"""

import json
from datetime import datetime
from typing import Optional

import requests


class SlackWebhook:
    """Skicka meddelanden till Slack via webhook."""

    def __init__(self, url: str, channel: str = ""):
        """
        Args:
            url: Slack Incoming Webhook URL.
            channel: Slack-kanal (t.ex. "#alerts"). Kan vara tom om webhooken
                     redan har en standardkanal.
        """
        self.url = url
        self.channel = channel

    def _post(self, blocks: list, text: str = "") -> bool:
        """Posta ett Slack-meddelande med Block Kit.

        Args:
            blocks: Lista av Slack Block Kit-block.
            text: Fallback-text for notiser.

        Returns:
            True om lyckades, False annars.
        """
        payload = {
            "text": text or "MarketScan notification",
            "blocks": blocks,
            "mrkdwn": True,
        }
        if self.channel:
            payload["channel"] = self.channel

        try:
            resp = requests.post(
                self.url,
                json=payload,
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def send_alert(self, message: str, severity: str = "info") -> bool:
        """Skicka en alert till Slack.

        Args:
            message: Alert-meddelande.
            severity: "info", "warning", "critical".

        Returns:
            True om lyckades.
        """
        colors = {
            "info": "#4c9be8",
            "warning": "#f5a623",
            "critical": "#f0616d",
        }
        color = colors.get(severity, "#4c9be8")
        emoji = {"info": ":information_source:", "warning": ":warning:", "critical": ":red_circle:"}

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji.get(severity, '')} MarketScan Alert",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f":clock1: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Severity: *{severity}*",
                    }
                ],
            },
        ]

        return self._post(blocks, text=f"Alert: {message[:100]}")

    def send_report(self, summary_text: str, attachment_url: str = "") -> bool:
        """Skicka en rapport till Slack.

        Args:
            summary_text: Sammanfattningstext.
            attachment_url: URL till bifogad rapport (valfritt).

        Returns:
            True om lyckades.
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":bar_chart: MarketScan Report",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary_text},
            },
        ]

        if attachment_url:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":link: <{attachment_url}|Download full report>",
                },
            })

        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f":clock1: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            }],
        })

        return self._post(blocks, text=f"Report: {summary_text[:100]}")

    def send_digest(self, alerts: list[dict]) -> bool:
        """Skicka en sammanfattning (digest) till Slack.

        Args:
            alerts: Lista av alert-dicts med ticker, message, severity, type.

        Returns:
            True om lyckades.
        """
        if not alerts:
            return self._post([
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "No alerts to report. :white_check_mark:"},
                }
            ], "Digest: No alerts")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":bell: MarketScan Digest ({len(alerts)} alerts)",
                },
            },
            {"type": "divider"},
        ]

        # Gruppera efter severity
        for alert in alerts[:20]:  # Max 20 alerts per digest
            severity = alert.get("severity", "info")
            emoji = {"info": ":large_blue_circle:", "warning": ":yellow_circle:", "critical": ":red_circle:"}

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{emoji.get(severity, ':large_blue_circle:')} "
                        f"*{alert.get('ticker', 'N/A')}* - "
                        f"{alert.get('message', '')}\n"
                        f"Type: `{alert.get('type', 'unknown')}`"
                    ),
                },
            })

        if len(alerts) > 20:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"...and {len(alerts) - 20} more alerts.",
                },
            })

        return self._post(blocks, text=f"Digest: {len(alerts)} alerts")
