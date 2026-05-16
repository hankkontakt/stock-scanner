"""
email_template.py
=================
Gemensam email-engine för alla MarketScan-rapporter.

Designprinciper:
  - En källa för all email-rendering
  - Professionell, ren design utan emoji-överbelastning
  - Inline CSS (krävs för Gmail/Outlook)
  - Maxbredd 640px
  - Definierad färgpalett
  - Fungerar i alla email-klienter

Färgpalett:
  Primär:    #1a1a2e (mörkblå header)
  Positiv:   #16a34a (grön)
  Negativ:   #dc2626 (röd)
  Varning:   #f59e0b (gul)
  Bakgrund:  #f8fafc (ljus)
  Text:      #1e293b (mörkgrå)
  Accent:    #2563eb (blå)
  Muted:     #64748b (dämpad)
"""

import html
import re
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional


# ── Färgpalett ──────────────────────────────────────────────────────────────
COLORS = {
    "primary":   "#1a1a2e",
    "accent":    "#2563eb",
    "positive":  "#16a34a",
    "negative":  "#dc2626",
    "warning":   "#f59e0b",
    "bg":        "#f8fafc",
    "bg_card":   "#ffffff",
    "text":      "#1e293b",
    "muted":     "#64748b",
    "border":    "#e2e8f0",
    "header_bg": "#1a1a2e",
    "header_fg": "#ffffff",
    "row_even":  "#f8fafc",
    "row_odd":   "#ffffff",
}


# ── Email-konfiguration ─────────────────────────────────────────────────────

def _get_email_config() -> tuple[str, str, str]:
    """Hämtar email-inställningar från config.py eller environment."""
    import os
    try:
        from core import config
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


# ── HTML-layout ─────────────────────────────────────────────────────────────

def _build_html_document(body_html: str, subject: str = "") -> str:
    """
    Bygger ett komplett HTML-email-dokument med header, body och footer.
    All CSS är inline för maximal kompatibilitet.
    """
    today = date.today().strftime("%Y-%m-%d")
    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background-color:{COLORS['bg']};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:{COLORS['text']}">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:{COLORS['bg']}">
<tr>
<td align="center" style="padding:20px 10px">

  <!-- HUVUDCONTAINER -->
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" style="max-width:640px;width:100%;background-color:{COLORS['bg_card']};border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08)">

    <!-- HEADER -->
    <tr>
      <td style="background-color:{COLORS['header_bg']};padding:24px 32px 20px">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="vertical-align:middle">
              <span style="font-size:20px;font-weight:700;color:{COLORS['header_fg']};letter-spacing:3px;text-transform:uppercase">MARKET<span style="color:#00d4aa">SCAN</span></span>
              <br>
              <span style="font-size:11px;color:#94a3b8;letter-spacing:2px;text-transform:uppercase">{today}</span>
            </td>
            <td style="vertical-align:middle;text-align:right">
              <span style="font-size:10px;color:#94a3b8;letter-spacing:1.5px;text-transform:uppercase;background:rgba(255,255,255,0.08);padding:4px 10px;border-radius:4px">Aktieanalys</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>

    <!-- BODY -->
    <tr>
      <td style="padding:28px 32px 20px">
        {body_html}
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td style="padding:16px 32px 24px;border-top:1px solid {COLORS['border']}">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="font-size:11px;color:{COLORS['muted']};line-height:1.5">
              Detta är en automatisk rapport från MarketScan. Informationen utgör inte finansiell rådgivning.
              <br>
              Investeringar innebär risk – gör alltid din egen analys innan beslut.
            </td>
          </tr>
          <tr>
            <td style="padding-top:8px;font-size:10px;color:#94a3b8">
              MarketScan &middot; Genererad {datetime.now().strftime("%Y-%m-%d %H:%M")}
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>

  <!-- VIEW IN BROWSER -->
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" style="max-width:640px;width:100%">
    <tr>
      <td style="padding:12px 0;text-align:center;font-size:11px;color:{COLORS['muted']}">
        Detta mail skickas från MarketScan. Hanteras via din konfiguration.
      </td>
    </tr>
  </table>

</td>
</tr>
</table>
</body>
</html>"""


# ── Markdown → HTML ─────────────────────────────────────────────────────────

def _inline_md(text: str) -> str:
    """Konverterar inline markdown (bold, code, italic, links) till HTML."""
    # Spara markdown-länkar före html.escape
    link_matches = []
    def _save_link(m):
        idx = len(link_matches)
        link_matches.append((m.group(1), m.group(2)))
        return f"\x00LINK{idx}\x00"
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _save_link, text)

    text = html.escape(text)

    # Återställ länkar
    for idx, (title, url) in enumerate(link_matches):
        title_safe = html.escape(title)
        url_safe   = html.escape(url)
        text = text.replace(
            f"\x00LINK{idx}\x00",
            f'<a href="{url_safe}" style="color:{COLORS["accent"]};text-decoration:none;font-weight:500">{title_safe}</a>'
        )

    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`",
                  r'<code style="background:#f1f5f9;padding:1px 5px;border-radius:3px;font-size:13px;color:#1e293b">\1</code>', text)
    text = re.sub(r"\*(.+?)\*",    r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_",    r"<em>\1</em>", text)
    return text


def _markdown_to_html(md: str) -> str:
    """
    Konverterar markdown till HTML-body (utan wrapper).
    Hanterar: rubriker, tabeller, listor, kodblock, citat, horisontella linjer.
    """
    # Klipp bort sektioner som inte ska vara i email
    for marker in ["## 📦 AI-Datalager", "## 🤖 AI-analyspromptar", "## 🤖 Klistra in i Claude Pro"]:
        if marker in md:
            md = md[:md.index(marker)]

    lines = md.split("\n")
    out      = []
    in_table = False
    in_code  = False
    in_list  = False
    in_blockquote = False

    for line in lines:
        # Kodblock
        if line.strip().startswith("```"):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            if not in_code:
                out.append('<pre style="background:#f1f5f9;padding:14px 16px;border-radius:6px;font-size:13px;overflow-x:auto;white-space:pre-wrap;word-break:break-all;border:1px solid #e2e8f0;margin:12px 0">')
                in_code = True
            else:
                out.append("</pre>")
                in_code = False
            continue

        if in_code:
            out.append(html.escape(line))
            continue

        # Blockquote
        if line.startswith("> "):
            if in_table:
                out.append("</table>")
                in_table = False
            if in_list:
                out.append("</ul>")
                in_list = False
            if not in_blockquote:
                out.append(f'<blockquote style="margin:12px 0;padding:10px 16px;border-left:3px solid {COLORS["accent"]};background:#f8fafc;border-radius:0 6px 6px 0;color:#475569">')
                in_blockquote = True
            out.append(f'<p style="margin:2px 0">{_inline_md(line[2:])}</p>')
            continue
        elif in_blockquote and line.strip() == "":
            out.append("</blockquote>")
            in_blockquote = False
            continue
        elif in_blockquote:
            out.append(f'<p style="margin:2px 0">{_inline_md(line)}</p>')
            continue

        # Listor
        if re.match(r"^[-*] ", line):
            if in_table:
                out.append("</table>")
                in_table = False
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            if not in_list:
                out.append('<ul style="margin:8px 0;padding:0 0 0 20px">')
                in_list = True
            out.append(f'<li style="margin:3px 0;line-height:1.5">{_inline_md(line[2:])}</li>')
            continue
        elif in_list and line.strip() == "":
            out.append("</ul>")
            in_list = False
        elif in_list:
            out.append("</ul>")
            in_list = False

        # Tabeller
        if line.startswith("|"):
            if in_blockquote:
                out.append("</blockquote>")
                in_blockquote = False
            if not in_table:
                out.append(f'<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:13px;border:1px solid {COLORS["border"]};border-radius:6px;overflow:hidden">')
                in_table = True
                # Header-rad
                cells = [c.strip() for c in line.strip("|").split("|")]
                out.append('<thead><tr>')
                for c in cells:
                    out.append(f'<th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:{COLORS["muted"]};background:#f1f5f9;border-bottom:1px solid {COLORS["border"]}">{_inline_md(c)}</th>')
                out.append('</tr></thead><tbody>')
                continue
            if "---|" in line or ":---" in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            out.append('<tr>')
            for c in cells:
                out.append(f'<td style="padding:7px 12px;border-bottom:1px solid {COLORS["border"]};vertical-align:middle">{_inline_md(c)}</td>')
            out.append('</tr>')
            continue
        elif in_table:
            out.append("</tbody></table>")
            in_table = False

        # Rubriker
        if line.startswith("### "):
            out.append(f'<h3 style="font-size:15px;font-weight:600;margin:20px 0 8px;color:{COLORS["text"]}">{_inline_md(line[4:])}</h3>')
        elif line.startswith("## "):
            out.append(f'<h2 style="font-size:17px;font-weight:600;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid {COLORS["border"]};color:{COLORS["text"]}">{_inline_md(line[3:])}</h2>')
        elif line.startswith("# "):
            out.append(f'<h1 style="font-size:20px;font-weight:700;margin:0 0 16px;color:{COLORS["primary"]}">{_inline_md(line[2:])}</h1>')
        elif line.strip() == "---":
            out.append(f'<hr style="border:none;border-top:1px solid {COLORS["border"]};margin:20px 0">')
        elif line.strip() == "":
            out.append('<br>')
        else:
            out.append(f'<p style="margin:4px 0;font-size:14px;line-height:1.6">{_inline_md(line)}</p>')

    # Stäng öppna taggar
    if in_table:
        out.append("</tbody></table>")
    if in_list:
        out.append("</ul>")
    if in_blockquote:
        out.append("</blockquote>")

    return "\n".join(out)


# ── Bygg komponenter ────────────────────────────────────────────────────────

def build_alert_box(message: str, level: str = "warning") -> str:
    """
    Bygger en alert-box.
    level: "critical" (röd), "warning" (gul), "info" (blå), "success" (grön)
    """
    colors = {
        "critical": {"bg": "#fef2f2", "border": "#dc2626", "text": "#991b1b", "icon": "!"},
        "warning":  {"bg": "#fffbeb", "border": "#f59e0b", "text": "#92400e", "icon": "!"},
        "info":     {"bg": "#eff6ff", "border": "#2563eb", "text": "#1e40af", "icon": "i"},
        "success":  {"bg": "#f0fdf4", "border": "#16a34a", "text": "#166534", "icon": "✓"},
    }
    c = colors.get(level, colors["info"])
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin:12px 0">
<tr>
<td style="background:{c['bg']};border-left:4px solid {c['border']};border-radius:0 6px 6px 0;padding:12px 16px">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td style="width:24px;vertical-align:top;font-size:16px;font-weight:700;color:{c['border']}">{c['icon']}</td>
      <td style="font-size:14px;color:{c['text']};line-height:1.5">{message}</td>
    </tr>
  </table>
</td>
</tr>
</table>"""


def build_pnl_cell(value_pct: Optional[float], bold: bool = True) -> str:
    """Bygger en P&L-cell med färg baserat på värde."""
    if value_pct is None:
        return f'<span style="color:{COLORS["muted"]}">—</span>'
    sign = "+" if value_pct >= 0 else ""
    color = COLORS["positive"] if value_pct >= 0 else COLORS["negative"]
    weight = "700" if bold else "400"
    return f'<span style="color:{color};font-weight:{weight}">{sign}{value_pct:.1f}%</span>'


def build_score_badge(score: Optional[float]) -> str:
    """Bygger en score-badge."""
    if score is None:
        return f'<span style="color:{COLORS["muted"]}">—</span>'
    color = COLORS["positive"] if score >= 70 else COLORS["warning"] if score >= 50 else COLORS["negative"]
    return f'<span style="color:{color};font-weight:600">{score:.0f}</span>'


def build_section_header(title: str, subtitle: str = "") -> str:
    """Bygger en sektionsrubrik."""
    parts = [f'<span style="font-size:17px;font-weight:600;color:{COLORS["text"]}">{html.escape(title)}</span>']
    if subtitle:
        parts.append(f'<span style="font-size:12px;color:{COLORS["muted"]};margin-left:8px">{html.escape(subtitle)}</span>')
    return f'<h2 style="font-size:17px;font-weight:600;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid {COLORS["border"]};color:{COLORS["text"]}">{"".join(parts)}</h2>'


# ── Huvudfunktion: skicka email ─────────────────────────────────────────────

def send_email(
    subject: str,
    body_markdown: str = "",
    body_html_extra: str = "",
    from_name: str = "MarketScan",
) -> bool:
    """
    Skickar ett formaterat email via Gmail SMTP.

    Args:
        subject: Ämnesrad
        body_markdown: Markdown som konverteras till HTML
        body_html_extra: Extra HTML som läggs till efter markdown (t.ex. alert-boxar)
        from_name: Avsändarnamn

    Returns:
        True om email skickades, annars False
    """
    sender, password, to = _get_email_config()
    if not sender or not password:
        print("  ⚠ Email ej konfigurerat – hoppar över utskick")
        return False

    recipients = [r.strip() for r in to.split(",") if r.strip()]

    # Bygg HTML-body
    html_parts = []
    if body_markdown:
        html_parts.append(_markdown_to_html(body_markdown))
    if body_html_extra:
        html_parts.append(body_html_extra)

    body_html = "\n".join(html_parts)
    full_html = _build_html_document(body_html, subject)

    # Plain-text fallback
    body_text = body_markdown[:1000] if body_markdown else "Se HTML-versionen."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{sender}>"
    msg["To"]      = ", ".join(recipients)

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        print(f"  ✉ Email skickat till {', '.join(recipients)}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ Email-autentisering misslyckades")
        print("     Kontrollera EMAIL_SENDER och EMAIL_PASSWORD i config.py")
        return False
    except Exception as e:
        print(f"  ❌ Email-fel: {e}")
        return False