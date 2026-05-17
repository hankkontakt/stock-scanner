"""
email_template.py
=================
Gemensam email-engine för alla MarketScan-rapporter.

Använder mistune (3.x) för markdown→HTML-konvertering istället för
handskriven parser, vilket ger:
  - Professionellare rendering (Github Flavored Markdown)
  - Mindre kod (~150 färre rader)
  - Färre buggar (emoji-separatorer, tabellkanter, etc.)

Design:
  - Inline CSS (krävs för Gmail/Outlook)
  - Responsiv (fungerar på mobil via media queries + flexibel bredd)
  - Unsubscribe-länk (minskar spam-risk)
  - Plain-text fallback som trunkeras vid mening (inte mitt i ord)
"""

import html
import json
import re
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import mistune

_SUBSCRIBERS_PATH = Path(__file__).resolve().parent.parent / "data" / "email_subscribers.json"

# Alla prenumerationstyper med human-readable etiketter
SUBSCRIPTION_TYPES: dict[str, str] = {
    "morning_report":   "🌅 Daglig morgonrapport",
    "evening_report":   "🌆 Kvällsuppdatering",
    "weekly_summary":   "📊 Veckossammanfattning (fredag)",
    "smallcap_report":  "🏦 Småbolagsrapport",
    "stark_alerts":     "⚡ STARK-signaler (omedelbart)",
    "portfolio_alerts": "💼 Portföljlarm (stop-loss/take-profit)",
    "failure_alerts":   "🚨 Tekniska fel i pipeline",
}


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


# ── Prenumeranthantering ─────────────────────────────────────────────────────

def load_subscribers() -> list[dict]:
    """Laddar prenumeranter från data/email_subscribers.json."""
    try:
        data = json.loads(_SUBSCRIBERS_PATH.read_text(encoding="utf-8"))
        return data.get("subscribers", [])
    except Exception:
        return []


def save_subscribers(subscribers: list[dict]) -> bool:
    """Sparar prenumeranter till data/email_subscribers.json."""
    try:
        _SUBSCRIBERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SUBSCRIBERS_PATH.write_text(
            json.dumps({"subscribers": subscribers}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        print(f"  ❌ Kunde inte spara prenumeranter: {e}")
        return False


def get_emails_for_type(subscription_type: str) -> list[str]:
    """
    Returnerar lista av aktiva e-postadresser för en given prenumerationstyp.
    Faller tillbaka på EMAIL_TO från config/env om prenumerantlistan är tom.
    """
    subscribers = load_subscribers()
    emails = [
        s["email"]
        for s in subscribers
        if s.get("active", True) and s.get("subscriptions", {}).get(subscription_type, False)
    ]
    if emails:
        return emails
    # Fallback: använd EMAIL_TO från konfigurationen
    _, _, to = _get_email_config()
    return [r.strip() for r in to.split(",") if r.strip()]


# ── Mistune renderer för inline CSS ─────────────────────────────────────────

class _InlineCSSRenderer(mistune.HTMLRenderer):
    """
    En Mistune-renderer som lägger till inline CSS-styling på alla element.
    Detta krävs för att email-klienter (Gmail, Outlook) ska visa
    formateringen korrekt.
    """

    def _style(self, tag: str, extra: str = "") -> str:
        """Hämta inline-style för en given HTML-tagg."""
        styles = {
            "table": (
                "border-collapse:collapse;width:100%;margin:12px 0;"
                f"font-size:13px;border:1px solid {COLORS['border']};"
                "border-radius:6px;overflow:hidden"
            ),
            "th": (
                "padding:8px 12px;text-align:left;"
                "font-size:11px;font-weight:600;text-transform:uppercase;"
                f"letter-spacing:1px;color:{COLORS['muted']};"
                f"background:#f1f5f9;border-bottom:1px solid {COLORS['border']}"
            ),
            "td": (
                f"padding:7px 12px;border-bottom:1px solid {COLORS['border']};"
                "vertical-align:middle"
            ),
            "h1": (
                f"font-size:20px;font-weight:700;margin:0 0 16px;color:{COLORS['primary']}"
            ),
            "h2": (
                f"font-size:17px;font-weight:600;margin:24px 0 10px;"
                f"padding-bottom:6px;border-bottom:1px solid {COLORS['border']};"
                f"color:{COLORS['text']}"
            ),
            "h3": (
                f"font-size:15px;font-weight:600;margin:20px 0 8px;color:{COLORS['text']}"
            ),
            "p": (
                "margin:4px 0;font-size:14px;line-height:1.6"
            ),
            "a": (
                f"color:{COLORS['accent']};text-decoration:none;font-weight:500"
            ),
            "code": (
                "background:#f1f5f9;padding:1px 5px;border-radius:3px;"
                "font-size:13px;color:#1e293b"
            ),
            "pre": (
                "background:#f1f5f9;padding:14px 16px;border-radius:6px;"
                "font-size:13px;overflow-x:auto;white-space:pre-wrap;"
                "word-break:break-all;border:1px solid #e2e8f0;margin:12px 0"
            ),
            "blockquote": (
                f"margin:12px 0;padding:10px 16px;border-left:3px solid {COLORS['accent']};"
                "background:#f8fafc;border-radius:0 6px 6px 0;color:#475569"
            ),
            "ul": (
                "margin:8px 0;padding:0 0 0 20px"
            ),
            "li": (
                "margin:3px 0;line-height:1.5"
            ),
            "hr": (
                f"border:none;border-top:1px solid {COLORS['border']};margin:20px 0"
            ),
        }
        base = styles.get(tag, "")
        return f'style="{base}{extra}"' if base else ""

    # ── Block-element ─────────────────────────────────────────────────────
    def table(self, text: str) -> str:
        return f'<table {self._style("table")}>{text}</table>'

    def table_head(self, text: str) -> str:
        return f"<thead>{text}</thead>"

    def table_body(self, text: str) -> str:
        return f"<tbody>{text}</tbody>"

    def table_row(self, text: str) -> str:
        return f"<tr>{text}</tr>"

    def table_cell(self, text: str, **kwargs) -> str:
        tag = "th" if kwargs.get("head") else "td"
        return f"<{tag} {self._style(tag)}>{text}</{tag}>"

    def heading(self, text: str, level: int, **kwargs) -> str:
        tag = f"h{level}"
        return f"<{tag} {self._style(tag)}>{text}</{tag}>"

    def paragraph(self, text: str) -> str:
        return f"<p {self._style('p')}>{text}</p>"

    def link(self, text: str, url: str, title: Optional[str] = None) -> str:
        title_attr = f' title="{html.escape(title)}"' if title else ""
        return f'<a {self._style("a")} href="{html.escape(url)}"{title_attr}>{text}</a>'

    def codespan(self, text: str) -> str:
        return f"<code {self._style('code')}>{html.escape(text)}</code>"

    def block_code(self, text: str, info: Optional[str] = None) -> str:
        return f"<pre {self._style('pre')}>{html.escape(text)}</pre>"

    def block_quote(self, text: str) -> str:
        return f"<blockquote {self._style('blockquote')}>{text}</blockquote>"

    def list(self, text: str, ordered: bool = False, **kwargs) -> str:
        tag = "ol" if ordered else "ul"
        return f"<{tag} {self._style('ul')}>{text}</{tag}>"

    def list_item(self, text: str, **kwargs) -> str:
        return f"<li {self._style('li')}>{text}</li>"

    def thematic_break(self) -> str:
        return f"<hr {self._style('hr')}>"

    # ── Inline-element ───────────────────────────────────────────────────
    def inline_html(self, html_str: str) -> str:
        # Pass through raw HTML (used for score badges, pnl cells, etc.)
        return html_str

    def emphasis(self, text: str) -> str:
        return f"<em>{text}</em>"

    def strong(self, text: str) -> str:
        return f"<strong>{text}</strong>"


# Skapa en global instans av markdown-parsern
_markdown = mistune.Markdown(renderer=_InlineCSSRenderer())


def _markdown_to_html(md_text: str) -> str:
    """
    Konverterar markdown till HTML-body med inline CSS.
    Klipper bort sektioner som inte ska vara i email.
    """
    # Klipp bort interna sektioner (debug/analys-promptar etc.)
    skip_markers = [
        "## 📦 AI-Datalager",
        "## 🤖 AI-analyspromptar",
        "## 🤖 Klistra in i Claude Pro",
    ]
    for marker in skip_markers:
        if marker in md_text:
            md_text = md_text[:md_text.index(marker)]

    # Konvertera till HTML via mistune
    return _markdown(md_text)


# ── HTML-layout (responsiv) ─────────────────────────────────────────────────

def _build_html_document(body_html: str, subject: str = "", unsubscribe_url: str = "") -> str:
    """
    Bygger ett komplett HTML-email-dokument med header, body och footer.
    Responsiv design med media queries för mobil.
    """
    today = date.today().strftime("%Y-%m-%d")

    # Responsiv CSS för mobil-anpassning
    responsive_css = """
@media only screen and (max-width: 600px) {
  .email-container { width: 100% !important; max-width: 100% !important; }
  .email-header { padding: 16px 16px 14px !important; }
  .email-body   { padding: 16px 16px 12px !important; }
  .email-footer { padding: 12px 16px 20px !important; }
  .email-logo   { font-size: 16px !important; }
  .email-table { font-size: 12px !important; }
  .email-table th,
  .email-table td { padding: 5px 8px !important; }
}
"""

    unsubscribe_html = ""
    if unsubscribe_url:
        unsubscribe_html = (
            f'<a href="{html.escape(unsubscribe_url)}" '
            f'style="color:#94a3b8;text-decoration:underline">Avsluta prenumeration</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(subject)}</title>
<style>{responsive_css}</style>
</head>
<body style="margin:0;padding:0;background-color:{COLORS['bg']};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:{COLORS['text']}">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:{COLORS['bg']}">
<tr>
<td align="center" style="padding:20px 10px">

  <!-- HUVUDCONTAINER -->
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" class="email-container" style="max-width:640px;width:100%;background-color:{COLORS['bg_card']};border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08)">

    <!-- HEADER -->
    <tr>
      <td class="email-header" style="background-color:{COLORS['header_bg']};padding:24px 32px 20px">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="vertical-align:middle">
              <span class="email-logo" style="font-size:20px;font-weight:700;color:{COLORS['header_fg']};letter-spacing:3px;text-transform:uppercase">MARKET<span style="color:#00d4aa">SCAN</span></span>
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
      <td class="email-body" style="padding:28px 32px 20px">
        {body_html}
      </td>
    </tr>

    <!-- FOOTER -->
    <tr>
      <td class="email-footer" style="padding:16px 32px 24px;border-top:1px solid {COLORS['border']}">
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
          <tr>
            <td style="padding-top:12px;font-size:10px;color:#94a3b8">
              {unsubscribe_html if unsubscribe_html else "Detta mail skickas från MarketScan. Hanteras via din konfiguration."}
            </td>
          </tr>
        </table>
      </td>
    </tr>

  </table>

</td>
</tr>
</table>
</body>
</html>"""


# ── Bygg komponenter (behålls från original) ─────────────────────────────────

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
    title_safe = html.escape(title)
    subtitle_html = ""
    if subtitle:
        subtitle_html = f'<span style="font-size:12px;color:{COLORS["muted"]};margin-left:8px">{html.escape(subtitle)}</span>'
    inner = f'<span style="font-size:17px;font-weight:600;color:{COLORS["text"]}">{title_safe}</span>{subtitle_html}'
    return (
        f'<h2 style="font-size:17px;font-weight:600;margin:24px 0 10px;'
        f'padding-bottom:6px;border-bottom:1px solid {COLORS["border"]};'
        f'color:{COLORS["text"]}">'
        f'{inner}</h2>'
    )


# ── Plain-text fallback ──────────────────────────────────────────────────────

def _make_plain_text(md_text: str, max_chars: int = 100000) -> str:
    """
    Konverterar markdown till plain text och trunkerar vid mening.
    Trunkering sker alltid vid en mening (punkt + mellanrum), inte mitt i.
    """
    if not md_text:
        return "Se HTML-versionen."

    # Ta bort rubriker, tabell-tecken, emoji
    text = re.sub(r"^#+\s*", "", md_text, flags=re.MULTILINE)
    text = re.sub(r"[|:-]{3,}", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[-*]\s", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if len(text) <= max_chars:
        return text

    # Trunkera vid sista mening före max_chars
    truncated = text[:max_chars]
    # Hitta sista punkt + mellanrum före max_chars
    last_sentence_end = max(
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind("!\n"),
        truncated.rfind("?\n"),
    )
    if last_sentence_end > max_chars * 0.5:  # Minst 50% av texten
        return truncated[: last_sentence_end + 1] + "\n\n[...] Läs mer i HTML-versionen."

    # Om ingen mening hittas, trunkera vid mellanrum
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.5:
        return truncated[:last_space] + "\n\n[...] Läs mer i HTML-versionen."

    return truncated + "\n\n[...] Läs mer i HTML-versionen."


# ── Huvudfunktion: skicka email ─────────────────────────────────────────────

def send_email(
    subject: str,
    body_markdown: str = "",
    body_html_extra: str = "",
    from_name: str = "MarketScan",
    unsubscribe_url: str = "",
    subscription_type: str = "",
    recipients: Optional[list[str]] = None,
) -> bool:
    """
    Skickar ett formaterat email via Gmail SMTP.

    Args:
        subject: Ämnesrad
        body_markdown: Markdown som konverteras till HTML
        body_html_extra: Extra HTML som läggs till efter markdown (t.ex. alert-boxar)
        from_name: Avsändarnamn
        unsubscribe_url: URL för att avsluta prenumeration (valfritt)
        subscription_type: Prenumerationstyp (t.ex. "morning_report") för att slå upp mottagare
        recipients: Explicit lista av mottagare (överskriver subscription_type och EMAIL_TO)

    Returns:
        True om email skickades, annars False
    """
    sender, password, _ = _get_email_config()
    if not sender or not password:
        print("  ⚠ Email ej konfigurerat – hoppar över utskick")
        return False

    if recipients is not None:
        # Explicit lista skickad in
        pass
    elif subscription_type:
        recipients = get_emails_for_type(subscription_type)
    else:
        _, _, to = _get_email_config()
        recipients = [r.strip() for r in to.split(",") if r.strip()]

    if not recipients:
        print("  ⚠ Inga mottagare för utskicket")
        return False

    # Bygg HTML-body
    html_parts = []
    if body_markdown:
        html_parts.append(_markdown_to_html(body_markdown))
    if body_html_extra:
        html_parts.append(body_html_extra)

    body_html = "\n".join(html_parts)
    full_html = _build_html_document(body_html, subject, unsubscribe_url)

    # Plain-text fallback (trunkeras vid mening, inte mitt i)
    body_text = _make_plain_text(body_markdown) if body_markdown else "Se HTML-versionen."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{sender}>"
    msg["To"]      = ", ".join(recipients)
    
    # List-Unsubscribe header – minskar spam-risk och krävs av många email-klienter
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

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


def send_failure_alert(workflow: str, run_id: str = "", repo: str = "") -> bool:
    """Skickar varningsmail när en GitHub Actions-pipeline misslyckas."""
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    body = (
        f"# 🚨 Pipeline-fel: `{workflow}`\n\n"
        f"En automatisk körning av **{workflow}** misslyckades.\n\n"
        + (f"- **Run-länk:** {run_url}\n" if run_url else "")
        + (f"- **Run ID:** `{run_id}`\n" if run_id else "")
        + "\nKolla GitHub Actions-loggar för detaljer."
    )
    return send_email(
        subject=f"🚨 MarketScan: {workflow} misslyckades",
        body_markdown=body,
        from_name="MarketScan Alerts",
        subscription_type="failure_alerts",
    )