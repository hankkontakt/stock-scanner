"""
alerts.py
=========
Skickar email-notifikationer via gemensam email-engine.

Email-typer (delegeras till email_template):
  send_weekly_report(rapport_md)   - Veckans fullstandiga rapport
  send_daily_update(portfolio_df)  - Daglig portfoljuppdatering
  send_alert(subject, body)        - Akuta notiser (SALJ-signal etc.)

Bevarar bakatkompatibilitet: _get_email_config(), email_configured(),
_markdown_to_html() finns fortfarande men delegerar till email_template.
"""

from datetime import date
from typing import Optional

import pandas as pd

from core import email_template

# Unicode-konstanter (maste vara variabler, inte escapes i f-strings for Python 3.11)
EN_DASH = "\u2013"
RIGHT_ARROW = "\u2192"
EM_DASH = "\u2014"


# ── Bevarade for bakatkompatibilitet ─────────────────────────────────────────

def _get_email_config() -> tuple[str, str, str]:
    """Delegerar till email_template."""
    return email_template._get_email_config()


def email_configured() -> bool:
    """Delegerar till email_template."""
    return email_template.email_configured()


def _markdown_to_html(md: str) -> str:
    """Delegerar till email_template."""
    return email_template._markdown_to_html(md)


# ── Email-typer (delegeras till email_template) ─────────────────────────────

def send_weekly_report(report_md: str, n_scanned: int = 0, n_top: int = 0) -> bool:
    """
    Skickar veckans fullstandiga rapport via gemensam email-engine.
    """
    subject = f"MarketScan Veckorapport {EN_DASH} {date.today().strftime('%Y-%m-%d')}"
    return email_template.send_email(
        subject=subject,
        body_markdown=report_md,
        from_name="MarketScan",
    )


def send_daily_update(
    portfolio_df:  "pd.DataFrame",
    alerts:        Optional[list] = None,
    omxs30_change: Optional[float] = None,
    spy_change:    Optional[float] = None,
) -> bool:
    """
    Skickar daglig portfoljuppdatering via gemensam email-engine.
    Bygger en HTML-body med marknad, alerts och portfolj.
    """
    import html as html_mod

    html_parts = []

    # Marknadsoversikt
    if omxs30_change is not None or spy_change is not None:
        mkt_parts = []
        if omxs30_change is not None:
            color = email_template.COLORS["positive"] if omxs30_change >= 0 else email_template.COLORS["negative"]
            sign = "+" if omxs30_change >= 0 else ""
            mkt_parts.append(f'<span>OMXS30: <strong style="color:{color}">{sign}{omxs30_change:.1f}%</strong></span>')
        if spy_change is not None:
            color = email_template.COLORS["positive"] if spy_change >= 0 else email_template.COLORS["negative"]
            sign = "+" if spy_change >= 0 else ""
            mkt_parts.append(f'<span>SPY: <strong style="color:{color}">{sign}{spy_change:.1f}%</strong></span>')
        html_parts.append(email_template.build_section_header("Marknaden idag"))
        html_parts.append(f'<div style="margin:8px 0 16px">{", ".join(mkt_parts)}</div>')

    # Akuta alerts
    if alerts:
        for alert in alerts:
            ticker = html_mod.escape(str(alert.get("ticker", "")))
            msg = html_mod.escape(str(alert.get("message", "")))
            action = html_mod.escape(str(alert.get("action", "")))
            html_parts.append(email_template.build_alert_box(
                f"<strong>{ticker}</strong>: {msg} {RIGHT_ARROW} <strong>{action}</strong>",
                level="critical"
            ))

    # Portfolj-tabell
    if portfolio_df is not None and not portfolio_df.empty:
        rows = []
        for _, row in portfolio_df.iterrows():
            pnl_pct = row.get("pnl_pct_today", 0) or 0
            pnl_html = email_template.build_pnl_cell(pnl_pct)
            ticker = html_mod.escape(str(row.get("ticker", "")))
            name = html_mod.escape(str(row.get("name", ""))[:20])
            price = str(row.get("current_price", EM_DASH))
            rec = html_mod.escape(str(row.get("recommendation", EM_DASH)))
            rows.append(
                f'<tr style="border-bottom:1px solid {email_template.COLORS["border"]}">'
                f'<td style="padding:6px 10px"><strong>{ticker}</strong><br>'
                f'<span style="font-size:11px;color:{email_template.COLORS["muted"]}">{name}</span></td>'
                f'<td style="padding:6px 10px;text-align:right">{price}</td>'
                f'<td style="padding:6px 10px;text-align:right">{pnl_html}</td>'
                f'<td style="padding:6px 10px;text-align:center;font-size:12px"><strong>{rec}</strong></td>'
                f'</tr>'
            )

        html_parts.append(email_template.build_section_header("Din portfolj"))
        html_parts.append(
            f'<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:13px;'
            f'border:1px solid {email_template.COLORS["border"]};border-radius:6px;overflow:hidden">'
            f'<thead><tr>'
            f'<th style="padding:7px 10px;text-align:left;font-size:11px;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:1px;color:{email_template.COLORS["muted"]};'
            f'background:#f1f5f9">Ticker</th>'
            f'<th style="padding:7px 10px;text-align:right;font-size:11px;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:1px;color:{email_template.COLORS["muted"]};'
            f'background:#f1f5f9">Pris</th>'
            f'<th style="padding:7px 10px;text-align:right;font-size:11px;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:1px;color:{email_template.COLORS["muted"]};'
            f'background:#f1f5f9">P&L</th>'
            f'<th style="padding:7px 10px;text-align:center;font-size:11px;font-weight:600;'
            f'text-transform:uppercase;letter-spacing:1px;color:{email_template.COLORS["muted"]};'
            f'background:#f1f5f9">Signal</th>'
            f'</tr></thead><tbody>'
            + "\n".join(rows) +
            f'</tbody></table>'
        )

    has_alerts = bool(alerts)
    prefix = f"ALERT {EN_DASH} " if has_alerts else ""
    subject = f"{prefix}MarketScan daglig {EN_DASH} {date.today().strftime('%d %b')}"
    return email_template.send_email(
        subject=subject,
        body_html_extra="\n".join(html_parts),
        from_name="MarketScan",
    )


def send_alert(ticker: str, message: str, action: str) -> bool:
    """Skickar en akut notis for en enskild aktie."""
    subject = f"MarketScan Alert: {ticker} {EN_DASH} {action}"
    body_html = email_template.build_alert_box(
        f"<strong>{ticker}</strong>: {message} {RIGHT_ARROW} <strong>{action}</strong>",
        level="critical"
    )
    body_html += f'<p style="color:#64748b;font-size:13px;margin-top:16px">Datum: {date.today()}</p>'
    return email_template.send_email(
        subject=subject,
        body_html_extra=body_html,
        from_name="MarketScan Alert",
    )