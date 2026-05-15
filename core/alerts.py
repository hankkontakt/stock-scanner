"""
alerts.py
=========
Skickar email-notifikationer via Gmail.

Setup (en gång):
  1. Gå till myaccount.google.com → Säkerhet → Tvåstegsverifiering (aktivera)
  2. Gå till myaccount.google.com → Säkerhet → App-lösenord
  3. Skapa ett app-lösenord för "Annan app" → kopiera 16-teckens lösenord
  4. Lägg till i config.py:
       EMAIL_SENDER   = "din@gmail.com"
       EMAIL_PASSWORD = "xxxx xxxx xxxx xxxx"   # App-lösenordet
       EMAIL_TO       = "din@gmail.com"          # Kan vara samma

För GitHub Actions – lägg till som Secrets:
  EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_TO

Email-typer:
  send_weekly_report(rapport_md)   – Veckans fullständiga rapport
  send_daily_update(portfolio_df)  – Daglig portföljuppdatering
  send_alert(subject, body)        – Akuta notiser (SÄLJ-signal etc.)
"""

import smtplib
import html
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from datetime             import date
from pathlib              import Path

import pandas as pd


# ── Importera config ──────────────────────────────────────────────────────────
def _get_email_config() -> tuple[str, str, str]:
    """Hämtar email-inställningar från config.py eller environment."""
    import os
    try:
        import config
        sender   = getattr(config, "EMAIL_SENDER",   None) or os.getenv("EMAIL_SENDER",   "")
        password = getattr(config, "EMAIL_PASSWORD", None) or os.getenv("EMAIL_PASSWORD", "")
        to       = getattr(config, "EMAIL_TO",       None) or os.getenv("EMAIL_TO",       sender)
        return sender, password, to
    except ImportError:
        return (os.getenv("EMAIL_SENDER", ""),
                os.getenv("EMAIL_PASSWORD", ""),
                os.getenv("EMAIL_TO", ""))


def email_configured() -> bool:
    """Returnerar True om email är konfigurerat."""
    sender, password, _ = _get_email_config()
    return bool(sender and password)


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _markdown_to_html(md: str) -> str:
    """Enkel markdown → HTML konvertering för email."""
    import re

    # Klipp AI-Datalager-sektionen – den är för filen, inte e-posten
    for marker in ["## 📦 AI-Datalager", "## 🤖 AI-analyspromptar"]:
        if marker in md:
            md = md[:md.index(marker)]

    lines = md.split("\n")
    out      = []
    in_table = False
    in_code  = False
    in_list  = False

    for line in lines:
        # Kodblockar
        if line.strip().startswith("```"):
            if in_list:
                out.append("</ul>")
                in_list = False
            if not in_code:
                out.append('<pre style="background:#f4f4f4;padding:12px;border-radius:6px;'
                           'font-size:12px;overflow-x:auto;white-space:pre-wrap;'
                           'word-break:break-all">')
                in_code = True
            else:
                out.append("</pre>")
                in_code = False
            continue

        if in_code:
            out.append(html.escape(line))
            continue

        # Bullet-listor (- item eller * item)
        if re.match(r"^[-*] ", line):
            if in_table:
                out.append("</table>")
                in_table = False
            if not in_list:
                out.append('<ul style="margin:4px 0 8px 20px;padding:0;font-size:14px">')
                in_list = True
            out.append(f'<li style="margin:2px 0;line-height:1.5">{_inline_md(line[2:])}</li>')
            continue
        elif in_list and line.strip() != "":
            out.append("</ul>")
            in_list = False
        elif in_list and line.strip() == "":
            out.append("</ul>")
            in_list = False

        # Tabeller
        if line.startswith("|"):
            if not in_table:
                out.append('<table style="border-collapse:collapse;width:100%;margin:8px 0;font-size:13px">')
                in_table = True
            if "---|" in line or ":---" in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            row_html = "".join(
                f'<td style="padding:5px 10px;border:0.5px solid #ddd">'
                f'{_inline_md(c)}</td>' for c in cells
            )
            out.append(f"<tr>{row_html}</tr>")
            continue
        elif in_table:
            out.append("</table>")
            in_table = False

        # Rubriker
        if line.startswith("### "):
            out.append(f'<h3 style="font-size:15px;margin:16px 0 6px;color:#1a1a1a">'
                       f'{_inline_md(line[4:])}</h3>')
        elif line.startswith("## "):
            out.append(f'<h2 style="font-size:17px;margin:20px 0 8px;border-bottom:1px solid #eee;'
                       f'padding-bottom:4px">{_inline_md(line[3:])}</h2>')
        elif line.startswith("# "):
            out.append(f'<h1 style="font-size:20px;margin:0 0 16px">{_inline_md(line[2:])}</h1>')
        elif line.strip() == "---":
            out.append('<hr style="border:none;border-top:1px solid #eee;margin:16px 0">')
        elif line.strip() == "":
            if not in_table:
                out.append("<br>")
        else:
            out.append(f'<p style="margin:4px 0;font-size:14px;line-height:1.6">'
                       f'{_inline_md(line)}</p>')

    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")

    return "\n".join(out)


def _inline_md(text: str) -> str:
    """Konverterar inline markdown (bold, code, italic, links) till HTML."""
    import re
    # Konvertera markdown-länkar INNAN html.escape (URL-tecknen måste vara intakta)
    link_matches = []
    def _save_link(m):
        idx = len(link_matches)
        link_matches.append((m.group(1), m.group(2)))
        return f"\x00LINK{idx}\x00"
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _save_link, text)

    text = html.escape(text)

    # Återställ sparade länkar
    for idx, (title, url) in enumerate(link_matches):
        title_safe = html.escape(title)
        url_safe   = html.escape(url)
        text = text.replace(
            f"\x00LINK{idx}\x00",
            f'<a href="{url_safe}" style="color:#0066cc;text-decoration:none">{title_safe}</a>'
        )

    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`",
                  r'<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px;'
                  r'font-size:12px">\1</code>', text)
    text = re.sub(r"\*(.+?)\*",    r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_",    r"<em>\1</em>", text)
    return text


def _send_email(subject: str, body_html: str, body_text: str = None):
    """Skickar ett email via Gmail SMTP."""
    sender, password, to = _get_email_config()

    if not sender or not password:
        print("  ⚠ Email ej konfigurerat – hoppar över utskick")
        print("    Lägg till EMAIL_SENDER och EMAIL_PASSWORD i config.py")
        return False

    recipients = [r.strip() for r in to.split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"MarketScan <{sender}>"
    msg["To"]      = ", ".join(recipients)

    # HTML-del med styling
    html_body = f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                        max-width:680px;margin:0 auto;padding:20px;color:#1a1a1a">
      <div style="background:#f8f8f8;border-radius:8px;padding:20px;margin-bottom:20px">
        <span style="font-size:12px;color:#666;letter-spacing:2px;text-transform:uppercase">
          MARKETSCAN · {date.today().strftime('%Y-%m-%d')}
        </span>
      </div>
      {body_html}
      <div style="margin-top:32px;padding-top:16px;border-top:1px solid #eee;
                  font-size:11px;color:#999">
        Automatisk rapport från ditt aktieanalyss system. Inte finansiell rådgivning.
      </div>
    </body></html>
    """

    msg.attach(MIMEText(body_text or "Se HTML-versionen.", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        print(f"  ✉ Email skickat till {', '.join(recipients)}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ Email-autentisering misslyckades")
        print("     Kontrollera EMAIL_SENDER och EMAIL_PASSWORD i config.py")
        print("     Använd ett Gmail App-lösenord, inte ditt vanliga lösenord")
        return False
    except Exception as e:
        print(f"  ❌ Email-fel: {e}")
        return False


# ══════════════════════════════════════════════════════════════
# EMAIL-TYPER
# ══════════════════════════════════════════════════════════════

def send_weekly_report(report_md: str, n_scanned: int = 0, n_top: int = 0) -> bool:
    """
    Skickar veckans fullständiga rapport.
    Konverterar markdown → HTML automatiskt.
    """
    subject   = f"📊 MarketScan Veckorapport – {date.today().strftime('%Y-%m-%d')}"
    body_html = _markdown_to_html(report_md)
    body_text = f"MarketScan veckorapport {date.today()}\n\n{report_md[:500]}...\n"
    return _send_email(subject, body_html, body_text)


def send_daily_update(
    portfolio_df:  "pd.DataFrame",
    alerts:        list = None,
    omxs30_change: float = None,
    spy_change:    float = None,
) -> bool:
    """
    Skickar daglig portföljuppdatering.
    Kompakt format – bara det viktigaste.
    """
    lines_html = []
    lines_text = []

    # Marknadsöversikt
    if omxs30_change is not None or spy_change is not None:
        lines_html.append('<h2>Marknaden idag</h2>')
        mkt_parts = []
        if omxs30_change is not None:
            sign = "+" if omxs30_change >= 0 else ""
            color = "#27a84f" if omxs30_change >= 0 else "#e53e3e"
            mkt_parts.append(f'<span>OMXS30: <strong style="color:{color}">{sign}{omxs30_change:.1f}%</strong></span>')
            lines_text.append(f"OMXS30: {sign}{omxs30_change:.1f}%")
        if spy_change is not None:
            sign = "+" if spy_change >= 0 else ""
            color = "#27a84f" if spy_change >= 0 else "#e53e3e"
            mkt_parts.append(f'<span>SPY: <strong style="color:{color}">{sign}{spy_change:.1f}%</strong></span>')
            lines_text.append(f"SPY: {sign}{spy_change:.1f}%")
        lines_html.append('<div style="display:flex;gap:24px;margin:8px 0">' + " &nbsp;·&nbsp; ".join(mkt_parts) + '</div>')

    # Akuta alerts
    if alerts:
        lines_html.append('<h2 style="color:#e53e3e">⚠ Åtgärd krävs</h2>')
        lines_text.append("\n=== ÅTGÄRD KRÄVS ===")
        for alert in alerts:
            lines_html.append(
                f'<div style="background:#fff5f5;border-left:3px solid #e53e3e;'
                f'padding:10px 14px;margin:6px 0;border-radius:0 6px 6px 0">'
                f'<strong>{alert["ticker"]}</strong>: {alert["message"]}'
                f'<span style="margin-left:8px;background:#e53e3e;color:white;'
                f'padding:2px 8px;border-radius:4px;font-size:12px">{alert["action"]}</span></div>'
            )
            lines_text.append(f"  {alert['ticker']}: {alert['message']} → {alert['action']}")

    # Portfölj-tabell
    if portfolio_df is not None and not portfolio_df.empty:
        lines_html.append("<h2>Din portfölj</h2>")
        lines_text.append("\n=== PORTFÖLJ ===")
        lines_html.append(
            '<table style="border-collapse:collapse;width:100%;font-size:13px">'
            '<tr style="background:#f4f4f4">'
            '<th style="padding:7px 10px;text-align:left">Ticker</th>'
            '<th style="padding:7px 10px;text-align:right">Pris</th>'
            '<th style="padding:7px 10px;text-align:right">P&L</th>'
            '<th style="padding:7px 10px;text-align:center">Signal</th>'
            '</tr>'
        )
        for _, row in portfolio_df.iterrows():
            pnl_pct = row.get("pnl_pct_today", 0) or 0
            pnl_col = "#27a84f" if pnl_pct >= 0 else "#e53e3e"
            sign    = "+" if pnl_pct >= 0 else ""
            rec     = str(row.get("recommendation", "—"))
            rec_col = "#e53e3e" if "SÄLJ" in rec else "#27a84f" if "KÖP" in rec else "#666"

            lines_html.append(
                f'<tr style="border-top:0.5px solid #eee">'
                f'<td style="padding:6px 10px"><strong>{row["ticker"]}</strong><br>'
                f'<span style="font-size:11px;color:#888">{str(row.get("name",""))[:20]}</span></td>'
                f'<td style="padding:6px 10px;text-align:right">{row.get("current_price","—")}</td>'
                f'<td style="padding:6px 10px;text-align:right;color:{pnl_col}">{sign}{pnl_pct:.1f}%</td>'
                f'<td style="padding:6px 10px;text-align:center;color:{rec_col};font-size:12px"><strong>{rec}</strong></td>'
                f'</tr>'
            )
            lines_text.append(f"  {row['ticker']}: {sign}{pnl_pct:.1f}% – {rec}")

        lines_html.append("</table>")

    subject = f"{'🚨 ALERT – ' if alerts else '📈 '}MarketScan daglig – {date.today().strftime('%d %b')}"
    return _send_email(subject, "\n".join(lines_html), "\n".join(lines_text))


def send_alert(ticker: str, message: str, action: str) -> bool:
    """Skickar en akut notis för en enskild aktie."""
    subject = f"🚨 MarketScan Alert: {ticker} – {action}"
    body_html = f"""
    <h2 style="color:#e53e3e">{ticker}: {action}</h2>
    <p style="font-size:16px">{message}</p>
    <p style="color:#666;font-size:13px">Datum: {date.today()}</p>
    """
    return _send_email(subject, body_html, f"{ticker}: {message} ({action})")
