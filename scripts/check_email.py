"""
scripts/check_email.py
=======================
SMTP-hälsokontroll och testmail-utskick.

Användning:
  python scripts/check_email.py              # Kontrollera SMTP-konfiguration
  python scripts/check_email.py --send       # Skicka ett testmail
  python scripts/check_email.py --to addr    # Skicka till specifik adress
  python scripts/check_email.py --verbose    # Detaljerad output
  python scripts/check_email.py --json       # JSON-output

Krav: EMAIL_SENDER, EMAIL_PASSWORD (+ valfritt EMAIL_TO) i .env
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import socket
import ssl
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Lagg till projekt-root i path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ── Konfiguration ──────────────────────────────────────────────────────────────

SMTP_HOST     = os.getenv("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
EMAIL_SENDER  = os.getenv("EMAIL_SENDER",  "")
EMAIL_PASSWORD= os.getenv("EMAIL_PASSWORD","")
EMAIL_TO      = os.getenv("EMAIL_TO",      "")


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _check_dns(host: str) -> tuple[bool, str]:
    """Kontrollera att SMTP-server kan nås via DNS."""
    try:
        ip = socket.gethostbyname(host)
        return True, ip
    except socket.gaierror as e:
        return False, str(e)


def _check_port(host: str, port: int, timeout: float = 5.0) -> tuple[bool, float]:
    """Kontrollera att TCP-anslutning till SMTP-port fungerar."""
    try:
        t0 = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout):
            ms = (time.perf_counter() - t0) * 1000
            return True, ms
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return False, -1.0


def _smtp_starttls_check(host: str, port: int, timeout: float = 10.0) -> tuple[bool, str]:
    """Kontrollera att STARTTLS-handshake lyckas (utan autentisering)."""
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            return True, "STARTTLS OK"
    except smtplib.SMTPException as e:
        return False, f"SMTP-fel: {e}"
    except ssl.SSLError as e:
        return False, f"SSL-fel: {e}"
    except Exception as e:
        return False, f"Anslutningsfel: {e}"


def _smtp_auth_check(host: str, port: int, sender: str, password: str,
                     timeout: float = 10.0) -> tuple[bool, str]:
    """Verifiera inloggning mot SMTP-server (utan att skicka mail)."""
    if not sender or not password:
        return False, "EMAIL_SENDER / EMAIL_PASSWORD saknas"
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(sender, password)
            return True, "Autentisering OK"
    except smtplib.SMTPAuthenticationError:
        return False, "Fel lösenord eller App-lösenord krävs (Gmail)"
    except smtplib.SMTPException as e:
        return False, f"SMTP-fel: {e}"
    except Exception as e:
        return False, f"Fel: {e}"


def _build_testmail(sender: str, recipient: str) -> str:
    """Bygg ett HTML-testmail."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[MarketScan] Testmail — {now}"
    msg["From"]    = sender
    msg["To"]      = recipient

    text_body = (
        f"MarketScan testmail\n"
        f"Skickat: {now}\n\n"
        f"E-postsystemet fungerar korrekt.\n"
        f"Konfiguration: {sender} -> {SMTP_HOST}:{SMTP_PORT}"
    )
    html_body = f"""
    <html><body>
    <h2 style="color:#2c5f2e;">MarketScan — Testmail</h2>
    <p><b>Skickat:</b> {now}</p>
    <p style="color:green;">E-postsystemet fungerar korrekt.</p>
    <hr>
    <small>Konfiguration: {sender} &rarr; {SMTP_HOST}:{SMTP_PORT}</small>
    </body></html>
    """
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html",  "utf-8"))
    return msg.as_string()


def send_test_email(sender: str, password: str, recipient: str,
                    host: str = SMTP_HOST, port: int = SMTP_PORT,
                    verbose: bool = False) -> tuple[bool, str]:
    """Skicka ett testmail. Returnerar (ok, meddelande)."""
    if not sender or not password:
        return False, "EMAIL_SENDER / EMAIL_PASSWORD saknas"
    if not recipient:
        return False, "Mottagaradress saknas (sätt --to eller EMAIL_TO)"
    try:
        raw = _build_testmail(sender, recipient)
        with smtplib.SMTP(host, port, timeout=15) as server:
            if verbose:
                server.set_debuglevel(1)
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(sender, password)
            server.sendmail(sender, recipient, raw.encode("utf-8"))
        return True, f"Testmail skickat till {recipient}"
    except smtplib.SMTPAuthenticationError:
        return False, "Autentiseringsfel — kontrollera App-lösenord (Gmail kräver App-lösenord)"
    except smtplib.SMTPRecipientsRefused:
        return False, f"Mottagare vägrad: {recipient}"
    except smtplib.SMTPException as e:
        return False, f"SMTP-fel: {e}"
    except Exception as e:
        return False, f"Oväntat fel: {e}"


# ── Huvudrapport ───────────────────────────────────────────────────────────────

def run_check(send_test: bool = False,
              to_override: str | None = None,
              verbose: bool = False) -> dict:
    """Kör alla e-postkontroller och returnera rapport."""
    recipient = to_override or EMAIL_TO or EMAIL_SENDER  # fallback: skicka till sig själv

    results: list[dict] = []

    def _r(name: str, ok: bool | None, msg: str, fix: str = "") -> None:
        results.append({"name": name, "ok": ok, "msg": msg, "fix": fix})
        if ok is True:
            print(f"  [OK ] {name:<35} {msg}")
        elif ok is False:
            print(f"  [XX ] {name:<35} {msg}")
            if fix:
                print(f"        FIX: {fix}")
        else:
            print(f"  [-- ] {name:<35} {msg}")

    print("=" * 70)
    print(f"  E-postsystem Diagnostik — {SMTP_HOST}:{SMTP_PORT}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    # 1. Konfigurationskontroll
    print("-- Konfiguration --------------------------------------------------------")
    _r("SMTP-host",    bool(SMTP_HOST),     SMTP_HOST or "(ej satt)")
    _r("SMTP-port",    True,                str(SMTP_PORT))
    _r("EMAIL_SENDER", bool(EMAIL_SENDER),  EMAIL_SENDER or "(ej satt)",
       "Sätt EMAIL_SENDER i .env")
    pwd_ok = bool(EMAIL_PASSWORD)
    _r("EMAIL_PASSWORD", pwd_ok, "***" if pwd_ok else "(ej satt)",
       "Sätt EMAIL_PASSWORD (Gmail: App-lösenord från myaccount.google.com/apppasswords)")
    _r("EMAIL_TO",     bool(EMAIL_TO),      EMAIL_TO or "(ej satt — skickar till sender)",
       "Sätt EMAIL_TO i .env")

    # 2. Nätverkskontroll
    print()
    print("-- Nätverkskontroll -----------------------------------------------------")
    dns_ok, dns_ip = _check_dns(SMTP_HOST)
    _r("DNS-uppslag", dns_ok, f"{SMTP_HOST} -> {dns_ip}" if dns_ok else dns_ip,
       f"Kontrollera internetanslutning / hostname {SMTP_HOST}")

    if dns_ok:
        port_ok, ms = _check_port(SMTP_HOST, SMTP_PORT)
        _r("TCP-port", port_ok,
           f"Port {SMTP_PORT} öppen ({ms:.0f}ms)" if port_ok else f"Port {SMTP_PORT} stängd",
           f"Brandvägg blockerar port {SMTP_PORT}?")
    else:
        _r("TCP-port", None, "Hoppar över (DNS misslyckades)")

    # 3. SMTP-protokollkontroll
    print()
    print("-- SMTP-protokoll -------------------------------------------------------")
    tls_ok, tls_msg = _smtp_starttls_check(SMTP_HOST, SMTP_PORT)
    _r("STARTTLS", tls_ok, tls_msg)

    if tls_ok and EMAIL_SENDER and EMAIL_PASSWORD:
        auth_ok, auth_msg = _smtp_auth_check(SMTP_HOST, SMTP_PORT, EMAIL_SENDER, EMAIL_PASSWORD)
        _r("SMTP-autentisering", auth_ok, auth_msg,
           "Gmail: Aktivera 2FA och skapa App-lösenord på myaccount.google.com/apppasswords")
    else:
        _r("SMTP-autentisering", None,
           "Hoppar över (saknar sender/password eller STARTTLS misslyckades)")

    # 4. Testmail
    if send_test:
        print()
        print("-- Testmail -------------------------------------------------------------")
        if not recipient:
            _r("Skicka testmail", False, "Ingen mottagare konfigurerad",
               "Sätt EMAIL_TO i .env eller använd --to addr@example.com")
        else:
            print(f"  Skickar testmail till {recipient}...")
            t0 = time.perf_counter()
            ok, msg = send_test_email(
                EMAIL_SENDER, EMAIL_PASSWORD, recipient,
                host=SMTP_HOST, port=SMTP_PORT, verbose=verbose
            )
            elapsed = (time.perf_counter() - t0) * 1000
            _r("Skicka testmail", ok,
               f"{msg} ({elapsed:.0f}ms)" if ok else msg,
               "Kontrollera autentisering och mottagaradress")

    # Sammanfattning
    ok_n   = sum(1 for r in results if r["ok"] is True)
    fail_n = sum(1 for r in results if r["ok"] is False)
    skip_n = sum(1 for r in results if r["ok"] is None)

    print()
    print("=" * 70)
    status = "OK" if fail_n == 0 else "FEL"
    print(f"  SUMMERING [{status}]: {ok_n} OK  {fail_n} FEL  {skip_n} HOPPADE")
    print("=" * 70)

    return {
        "ok":      fail_n == 0,
        "ok_n":    ok_n,
        "fail_n":  fail_n,
        "skip_n":  skip_n,
        "details": results,
        "config":  {
            "smtp_host": SMTP_HOST,
            "smtp_port": SMTP_PORT,
            "sender":    EMAIL_SENDER,
            "recipient": recipient,
        },
    }


# ── main() ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnostisera e-postsystem och skicka testmail",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--send",    "-s", action="store_true",
                        help="Skicka ett testmail")
    parser.add_argument("--to",      "-t", metavar="ADDR",
                        help="Mottagaradress (override EMAIL_TO)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Visa SMTP-debug-output")
    parser.add_argument("--json",          action="store_true",
                        help="Skriv ut JSON-rapport")
    args = parser.parse_args()

    result = run_check(
        send_test    = args.send,
        to_override  = args.to,
        verbose      = args.verbose,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
