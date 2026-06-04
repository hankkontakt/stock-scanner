"""
scripts/diagnose.py — MarketScan Självdiagnos
==============================================
Kör diagnos på ALLA systemkomponenter och rapporterar status.
Kan köras lokalt eller triggeras från GitHub Actions / Admin-sidan.

Täcker:
  1. Miljö & beroenden
  2. Konfiguration & API-nycklar
  3. E-postsystem (SMTP-anslutning + testmail)
  4. GitHub Actions & repo-hälsa
  5. Streamlit-appen (HTTP-hälsocheck)
  6. Pipeline-data (scanfiler, ålder, integritet)
  7. ML-modeller (laddning, checksummar)
  8. Notifieringskanaler (Telegram, Discord, ntfy)
  9. Databeroenden (yfinance, Finnhub)
 10. Sammandrag med rekommendationer

Användning:
  python scripts/diagnose.py                  # Fullständig diagnos
  python scripts/diagnose.py --quick           # Hoppa över nätverkstest
  python scripts/diagnose.py --section email   # Bara e-postdiagnos
  python scripts/diagnose.py --send-test-mail  # Skicka ett riktigt testmail
  python scripts/diagnose.py --json            # Maskinläsbar JSON-output

Miljövariabler:
  DIAGNOSE_STREAMLIT_URL  — URL till Streamlit-appen (default: läses från secrets)
  DIAGNOSE_SEND_MAIL      — Om satt skickas testmail (default: nej)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ══════════════════════════════════════════════════════════════════════════════
# Resultatstruktur
# ══════════════════════════════════════════════════════════════════════════════

class CheckResult:
    """Resultatet av ett enstaka diagnos-check."""
    OK    = "OK"
    WARN  = "WARN"
    ERROR = "ERROR"
    SKIP  = "SKIP"

    def __init__(self, name: str, status: str, message: str,
                 detail: str = "", fix: str = ""):
        self.name    = name
        self.status  = status
        self.message = message
        self.detail  = detail
        self.fix     = fix
        self.ts      = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
            "fix": self.fix,
            "ts": self.ts,
        }


class DiagnosticReport:
    """Sammlar alla check-resultat och skriver rapport."""

    ICONS = {CheckResult.OK: "✅", CheckResult.WARN: "⚠️ ",
             CheckResult.ERROR: "❌", CheckResult.SKIP: "⏭️ "}

    def __init__(self, title: str = "MarketScan Självdiagnos"):
        self.title   = title
        self.results: list[CheckResult] = []
        self.sections: dict[str, list[CheckResult]] = {}
        self._current_section = "Övrigt"

    def section(self, name: str):
        self._current_section = name
        if name not in self.sections:
            self.sections[name] = []

    def add(self, result: CheckResult):
        self.results.append(result)
        self.sections.setdefault(self._current_section, []).append(result)

    def ok(self, name: str, msg: str, detail: str = ""):
        self.add(CheckResult(name, CheckResult.OK, msg, detail))

    def warn(self, name: str, msg: str, detail: str = "", fix: str = ""):
        self.add(CheckResult(name, CheckResult.WARN, msg, detail, fix))

    def error(self, name: str, msg: str, detail: str = "", fix: str = ""):
        self.add(CheckResult(name, CheckResult.ERROR, msg, detail, fix))

    def skip(self, name: str, msg: str):
        self.add(CheckResult(name, CheckResult.SKIP, msg))

    @property
    def n_ok(self) -> int:    return sum(1 for r in self.results if r.status == CheckResult.OK)
    @property
    def n_warn(self) -> int:  return sum(1 for r in self.results if r.status == CheckResult.WARN)
    @property
    def n_error(self) -> int: return sum(1 for r in self.results if r.status == CheckResult.ERROR)
    @property
    def is_healthy(self) -> bool: return self.n_error == 0

    def print_report(self):
        width = 70
        print("=" * width)
        print(f"  {self.title}")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * width)
        for sec_name, checks in self.sections.items():
            if not checks:
                continue
            print(f"\n── {sec_name} {'─' * (width - len(sec_name) - 4)}")
            for r in checks:
                icon = self.ICONS.get(r.status, "?")
                line = f"  {icon} {r.name:<35} {r.message}"
                print(line[:width])
                if r.detail:
                    for dl in r.detail.split("\n"):
                        print(f"      {dl}")
                if r.fix and r.status in (CheckResult.WARN, CheckResult.ERROR):
                    print(f"      💡 Fix: {r.fix}")
        print("\n" + "=" * width)
        status_line = f"  TOTALT: {self.n_ok} OK  {self.n_warn} VARNINGAR  {self.n_error} FEL"
        print(status_line)
        overall = "🟢 SYSTEMET ÄR FRISKT" if self.is_healthy else (
            "🟡 VARNINGAR — kontrollera ovan" if self.n_error == 0 else
            "🔴 KRITISKA FEL — åtgärd krävs"
        )
        print(f"  {overall}")
        print("=" * width)

    def to_json(self) -> str:
        return json.dumps({
            "title": self.title,
            "ts": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "ok": self.n_ok,
                "warnings": self.n_warn,
                "errors": self.n_error,
                "healthy": self.is_healthy,
            },
            "sections": {
                sec: [r.to_dict() for r in checks]
                for sec, checks in self.sections.items()
            },
        }, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# Diagnos-sektioner
# ══════════════════════════════════════════════════════════════════════════════

def check_environment(report: DiagnosticReport):
    """Sektion 1: Miljö & Python-beroenden."""
    report.section("1. Miljö & Beroenden")

    # Python-version
    v = sys.version_info
    if v >= (3, 11):
        report.ok("Python-version", f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        report.warn("Python-version", f"Python {v.major}.{v.minor} (rekommenderas 3.11+)",
                    fix="Uppgradera till Python 3.11 eller nyare")

    # Kritiska beroenden
    critical_deps = [
        ("pandas",     "2.0"),
        ("streamlit",  "1.38"),
        ("yfinance",   "0.2"),
        ("requests",   "2.28"),
    ]
    for pkg, min_ver in critical_deps:
        try:
            import importlib
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "?")
            report.ok(f"Beroende: {pkg}", f"v{ver}")
        except ImportError:
            report.error(f"Beroende: {pkg}", f"SAKNAS",
                        fix=f"pip install {pkg}>={min_ver}")

    # Valfria beroenden
    optional_deps = ["hypothesis", "pyarrow", "xgboost", "filelock", "pip_audit"]
    for pkg in optional_deps:
        try:
            import importlib
            mod = importlib.import_module(pkg.replace("-", "_"))
            ver = getattr(mod, "__version__", "?")
            report.ok(f"Valfritt: {pkg}", f"v{ver}")
        except ImportError:
            report.warn(f"Valfritt: {pkg}", "Ej installerat",
                       fix=f"pip install {pkg}")


def check_configuration(report: DiagnosticReport):
    """Sektion 2: Konfiguration & API-nycklar."""
    report.section("2. Konfiguration & API-nycklar")

    # Viktiga filer
    required_files = [
        (ROOT / "data" / "universe.json",     "universe.json"),
        (ROOT / "data" / "scoring_config.json", "scoring_config.json"),
        (ROOT / "requirements.txt",            "requirements.txt"),
    ]
    for path, name in required_files:
        if path.exists():
            size = path.stat().st_size
            report.ok(f"Fil: {name}", f"Finns ({size:,} bytes)")
        else:
            report.warn(f"Fil: {name}", "Saknas",
                       fix=f"Skapa {name} (se dokumentationen)")

    # API-nycklar
    try:
        from core import config
        key_checks = [
            ("DEEPSEEK_API_KEY",  getattr(config, "DEEPSEEK_API_KEY",  ""), True),
            ("GEMINI_API_KEY",    getattr(config, "GEMINI_API_KEY",    ""), True),
            ("FINNHUB_API_KEY",   getattr(config, "FINNHUB_API_KEY",   ""), True),
            ("EMAIL_SENDER",      getattr(config, "EMAIL_SENDER",      ""), False),
            ("EMAIL_PASSWORD",    getattr(config, "EMAIL_PASSWORD",    ""), False),
            ("NTFY_TOPIC",        getattr(config, "NTFY_TOPIC",        ""), False),
        ]
        for key_name, val, is_critical in key_checks:
            if val:
                masked = val[:4] + "..." + val[-3:] if len(val) > 10 else "***"
                report.ok(f"Nyckel: {key_name}", f"Konfigurerad ({masked})")
            elif is_critical:
                report.error(f"Nyckel: {key_name}", "SAKNAS — AI-analys fungerar ej",
                            fix=f"Sätt {key_name} i .env eller Streamlit Secrets")
            else:
                report.warn(f"Nyckel: {key_name}", "Ej konfigurerad (valfri)",
                           fix=f"Sätt {key_name} för att aktivera funktionen")
    except ImportError as e:
        report.error("Config-import", f"Kunde inte importera config: {e}",
                    fix="Kontrollera PYTHONPATH och att core/ finns")


def check_email(report: DiagnosticReport, send_test: bool = False):
    """Sektion 3: E-postsystem."""
    report.section("3. E-postsystem")

    try:
        import smtplib
        from core import config
        sender   = getattr(config, "EMAIL_SENDER",   "")
        password = getattr(config, "EMAIL_PASSWORD", "")
        to       = getattr(config, "EMAIL_TO",       sender)

        if not sender or not password:
            report.warn("SMTP-konfiguration", "EMAIL_SENDER/PASSWORD ej konfigurerade",
                       fix="Sätt EMAIL_SENDER och EMAIL_PASSWORD i secrets")
            return

        # Test SMTP-anslutning (utan att skicka mail)
        t0 = time.time()
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as s:
                s.starttls()
                s.login(sender, password)
                elapsed = time.time() - t0
                report.ok("SMTP-anslutning", f"Gmail OK ({elapsed:.1f}s)")
        except smtplib.SMTPAuthenticationError:
            report.error("SMTP-autentisering", "Inloggning misslyckades",
                        detail="Gmail kräver App-lösenord om 2FA är aktiverat",
                        fix="Skapa ett app-specifikt lösenord i Google-kontot")
        except Exception as e:
            report.error("SMTP-anslutning", f"Anslutning misslyckades: {type(e).__name__}",
                        detail=str(e)[:120],
                        fix="Kontrollera brandväggsregler och att port 587 är öppen")

        # Valfritt: skicka ett riktigt testmail
        if send_test:
            try:
                from core.email_template import send_email
                ok = send_email(
                    subject="🔬 MarketScan Diagnostik — Testmail",
                    body_markdown=(
                        "# Diagnostiktest\n\nDetta mail skickades av `scripts/diagnose.py`.\n"
                        "Om du ser detta mail fungerar e-postsystemet korrekt."
                    ),
                )
                if ok:
                    report.ok("Testmail", f"Skickat till {to}")
                else:
                    report.error("Testmail", "Misslyckades (se email_template-loggen)")
            except Exception as e:
                report.error("Testmail", f"Undantag: {e}",
                            fix="Kontrollera send_email()-funktionen i email_template.py")
        else:
            report.skip("Testmail", "Hoppad (kör med --send-test-mail för att skicka)")

    except ImportError as e:
        report.error("E-post-import", f"Importfel: {e}")


def check_github(report: DiagnosticReport, quick: bool = False):
    """Sektion 4: GitHub & repo-hälsa."""
    report.section("4. GitHub & Repo")

    # Git-status
    try:
        import subprocess
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            report.warn("Git-status", "git kommando misslyckades",
                       detail=result.stderr[:80])
        else:
            n_changed = len([l for l in result.stdout.splitlines() if l.strip()])
            if n_changed == 0:
                report.ok("Git-status", "Inga uncommittade ändringar")
            else:
                report.warn("Git-status", f"{n_changed} uncommittade filer",
                           fix="git add -A && git commit -m 'manual commit'")

        # Senaste commit
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=ROOT, capture_output=True, text=True, timeout=5
        )
        if log.returncode == 0:
            report.ok("Senaste commit", log.stdout.strip()[:70])

        # Branch
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5
        )
        if branch.returncode == 0:
            b = branch.stdout.strip()
            if b == "main":
                report.ok("Aktiv branch", f"main ✓")
            else:
                report.warn("Aktiv branch", f"{b} (ej main)",
                           fix="git checkout main")
    except FileNotFoundError:
        report.warn("Git", "git ej tillgängligt i PATH",
                   fix="Installera git")
    except Exception as e:
        report.warn("Git", f"Kontroll misslyckades: {e}")

    # GitHub API-åtkomst (om ej quick)
    if quick:
        report.skip("GitHub API", "Hoppad (quick-läge)")
        return

    try:
        import requests
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            report.warn("GitHub API", "GITHUB_TOKEN saknas",
                       fix="Sätt GITHUB_TOKEN för att kontrollera workflow-status")
            return

        # Hämta senaste workflow-körningar
        repo_url = None
        try:
            remote = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=ROOT, capture_output=True, text=True, timeout=5
            )
            if remote.returncode == 0:
                url = remote.stdout.strip()
                # Extrahera owner/repo
                import re
                m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
                if m:
                    repo_url = m.group(1)
        except Exception:
            pass

        if not repo_url:
            report.warn("GitHub API", "Kunde inte bestämma repo-URL")
            return

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        t0 = time.time()
        resp = requests.get(
            f"https://api.github.com/repos/{repo_url}/actions/runs",
            params={"per_page": 5},
            headers=headers,
            timeout=10,
        )
        elapsed = time.time() - t0

        if resp.status_code == 200:
            runs = resp.json().get("workflow_runs", [])
            failed = [r for r in runs if r.get("conclusion") == "failure"]
            if failed:
                report.warn(
                    "Senaste Workflows",
                    f"{len(failed)}/{len(runs)} körningar MISSLYCKADES",
                    detail="\n".join(r.get("name", "?") + ": " + r.get("html_url", "?") for r in failed[:3]),
                    fix="Kontrollera GitHub Actions-loggen för detaljerade felmeddelanden"
                )
            else:
                report.ok("Senaste Workflows",
                         f"{len(runs)} körningar — alla OK ({elapsed:.1f}s)")
        elif resp.status_code == 401:
            report.error("GitHub API", "Obehörig (401)",
                        fix="Verifiera att GITHUB_TOKEN har 'actions:read'-behörighet")
        else:
            report.warn("GitHub API", f"HTTP {resp.status_code}",
                       detail=resp.text[:80])
    except Exception as e:
        report.warn("GitHub API", f"Kontroll misslyckades: {e}")


def check_streamlit(report: DiagnosticReport, quick: bool = False):
    """Sektion 5: Streamlit-appen."""
    report.section("5. Streamlit-app")

    if quick:
        report.skip("HTTP-hälsocheck", "Hoppad (quick-läge)")
        return

    # Hitta Streamlit-URL
    app_url = os.getenv("DIAGNOSE_STREAMLIT_URL", "")
    if not app_url:
        try:
            import streamlit as st
            app_url = os.getenv("APP_URL", "")
        except Exception:
            pass
    if not app_url:
        # Prova att läsa från .env
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("APP_URL="):
                    app_url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not app_url:
        report.warn("Streamlit URL", "APP_URL ej konfigurerad",
                   fix="Sätt APP_URL=https://din-app.streamlit.app i Streamlit Secrets")
        return

    try:
        import requests
        t0 = time.time()
        resp = requests.get(app_url, timeout=15, allow_redirects=True)
        elapsed = time.time() - t0
        if resp.status_code == 200:
            report.ok("Streamlit HTTP", f"HTTP 200 OK ({elapsed:.1f}s) — {app_url[:50]}")
        elif resp.status_code in (401, 403):
            report.warn("Streamlit HTTP", f"HTTP {resp.status_code} — Lösenordsskyddad (förväntad)",
                       detail=f"URL: {app_url}")
        else:
            report.warn("Streamlit HTTP", f"HTTP {resp.status_code}",
                       detail=f"URL: {app_url}",
                       fix="Kontrollera Streamlit Cloud dashboard för fel")
    except requests.exceptions.ConnectionError:
        report.error("Streamlit HTTP", "Anslutning misslyckades",
                    detail=f"URL: {app_url}",
                    fix="Kontrollera om appen är live på Streamlit Cloud")
    except requests.exceptions.Timeout:
        report.warn("Streamlit HTTP", "Timeout (>15s) — appen är troligen i viloläge",
                   detail=f"URL: {app_url}",
                   fix="keep_alive.yml bör hålla appen igång — kontrollera schema")
    except Exception as e:
        report.warn("Streamlit HTTP", f"Kontroll misslyckades: {e}")


def check_pipeline_data(report: DiagnosticReport):
    """Sektion 6: Pipeline-data och scanfiler."""
    report.section("6. Pipeline-data")

    reports_dir = ROOT / "reports"
    data_dir    = ROOT / "data"

    # Scanfiler
    parquet_files = sorted(reports_dir.glob("scored_universe_*.parquet"), reverse=True)
    csv_files     = sorted(reports_dir.glob("scored_universe_*.csv"), reverse=True)

    latest = parquet_files[0] if parquet_files else (csv_files[0] if csv_files else None)
    if latest:
        age_h = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds() / 3600
        size  = latest.stat().st_size
        if age_h < 36:
            report.ok("Senaste scan", f"{latest.name} ({age_h:.0f}h gammal, {size:,} bytes)")
        elif age_h < 72:
            report.warn("Senaste scan", f"{latest.name} är {age_h:.0f}h gammal",
                       fix="Utlös ett nytt scan via GitHub Actions → 'Run workflow'")
        else:
            report.error("Senaste scan", f"{latest.name} är {age_h/24:.0f} dagar gammal",
                        fix="Pipeline verkar ha slutat fungera — kontrollera GitHub Actions-loggen")
        report.ok("Antal scanfiler", f"{len(parquet_files)} parquet + {len(csv_files)} CSV")
    else:
        report.error("Scanfiler", "Inga scored_universe-filer hittade",
                    detail=f"Kontrollerade: {reports_dir}",
                    fix="Kör 'python -c from core.daily_pipeline import run_pipeline; run_pipeline(weekly)'")

    # Smallcap-scan
    sc_files = sorted(reports_dir.glob("smallcap_scored_*.parquet"), reverse=True)
    if sc_files:
        age_h = (datetime.now() - datetime.fromtimestamp(sc_files[0].stat().st_mtime)).total_seconds() / 3600
        if age_h < 168:  # < 7 dagar
            report.ok("Smallcap scan", f"{sc_files[0].name} ({age_h:.0f}h gammal)")
        else:
            report.warn("Smallcap scan", f"Äldre än 7 dagar ({age_h/24:.0f}d)",
                       fix="Kör smallcap-scan: run_pipeline('smallcap')")
    else:
        report.warn("Smallcap scan", "Inga smallcap-filer hittade")

    # Viktiga datafiler
    important_files = [
        (data_dir / "universe.json",    "universe.json"),
        (data_dir / "watchlist.json",   "watchlist.json"),
        (data_dir / "blacklist.json",   "blacklist.json"),
    ]
    for path, name in important_files:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    n = sum(len(v.get("tickers", [])) for v in data.values() if isinstance(v, dict))
                    report.ok(f"Datafil: {name}", f"OK ({n} poster)")
                elif isinstance(data, list):
                    report.ok(f"Datafil: {name}", f"OK ({len(data)} poster)")
                else:
                    report.ok(f"Datafil: {name}", "OK")
            except json.JSONDecodeError as e:
                report.error(f"Datafil: {name}", f"KORRUPT JSON: {e}",
                            fix=f"Återställ {name} från git: git checkout HEAD -- data/{name}")
        else:
            report.warn(f"Datafil: {name}", "Saknas (normal om ej konfigurerat)")


def check_ml_models(report: DiagnosticReport):
    """Sektion 7: ML-modeller."""
    report.section("7. ML-modeller")

    try:
        from core.ml_predictor import load_model, MODELS_DIR
    except ImportError as e:
        report.warn("ML-import", f"ml_predictor ej tillgänglig: {e}")
        return

    models_dir = Path(MODELS_DIR) if not isinstance(MODELS_DIR, Path) else MODELS_DIR
    if not models_dir.exists():
        report.warn("ML-katalog", f"{models_dir} saknas",
                   fix="Kör ML-träning via GitHub Actions → 'Train ML Models'")
        return

    pkl_files = list(models_dir.glob("*.pkl"))
    if not pkl_files:
        report.warn("ML-filer", "Inga .pkl-filer hittade",
                   fix="Kör ML-träning via GitHub Actions → 'Train ML Models'")
        return

    for pkl in pkl_files:
        sha_file = pkl.with_suffix(".pkl.sha256")
        if sha_file.exists():
            report.ok(f"SHA256: {pkl.name}", "Checksumfil finns")
        else:
            report.warn(f"SHA256: {pkl.name}", "Checksumfil saknas",
                       fix=f"Kör save_model() igen för att generera checksumfil")

    # Försök ladda modeller
    for universe in ["universe", "smallcap"]:
        try:
            t0 = time.time()
            model = load_model(universe)
            elapsed = time.time() - t0
            if model is not None:
                report.ok(f"ML-modell: {universe}", f"Laddad OK ({elapsed:.2f}s)")
            else:
                report.warn(f"ML-modell: {universe}", "Returnerade None (model saknas eller checksumfel)",
                           fix="Kör ML-träning via GitHub Actions → 'Train ML Models'")
        except Exception as e:
            report.error(f"ML-modell: {universe}", f"Laddning misslyckades: {e}",
                        fix="Kontrollera models/-katalogen och checksumfiler")


def check_notification_channels(report: DiagnosticReport, quick: bool = False):
    """Sektion 8: Notifieringskanaler."""
    report.section("8. Notifieringskanaler")

    if quick:
        report.skip("Kanaltest", "Hoppad (quick-läge)")
        return

    # Telegram
    try:
        from core import config
        bot_token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
        if bot_token:
            import requests
            resp = requests.get(
                f"https://api.telegram.org/bot{bot_token}/getMe",
                timeout=5
            )
            if resp.status_code == 200:
                bot_name = resp.json().get("result", {}).get("username", "?")
                report.ok("Telegram", f"Bot aktiv: @{bot_name}")
            else:
                report.error("Telegram", f"HTTP {resp.status_code} — token ogiltig",
                            fix="Kontrollera TELEGRAM_BOT_TOKEN")
        else:
            report.warn("Telegram", "Ej konfigurerat",
                       fix="Sätt TELEGRAM_BOT_TOKEN och TELEGRAM_CHAT_ID")
    except Exception as e:
        report.warn("Telegram", f"Kontroll misslyckades: {e}")

    # Discord
    try:
        from core import config
        webhook = getattr(config, "DISCORD_WEBHOOK_URL", "")
        if webhook:
            import requests
            resp = requests.get(webhook, timeout=5)
            if resp.status_code in (200, 404):  # 404 = webhook existerar men stöder ej GET
                report.ok("Discord", "Webhook konfigurerad")
            else:
                report.warn("Discord", f"HTTP {resp.status_code}",
                           fix="Kontrollera DISCORD_WEBHOOK_URL")
        else:
            report.warn("Discord", "Ej konfigurerat")
    except Exception as e:
        report.warn("Discord", f"Kontroll misslyckades: {e}")

    # ntfy.sh
    try:
        from core import config
        ntfy_topic = getattr(config, "NTFY_TOPIC", "")
        if ntfy_topic:
            import requests
            resp = requests.get(f"https://ntfy.sh/{ntfy_topic}/json", timeout=5)
            if resp.status_code in (200, 304):
                report.ok("ntfy.sh", f"Topic '{ntfy_topic}' är aktivt")
            else:
                report.warn("ntfy.sh", f"HTTP {resp.status_code}")
        else:
            report.warn("ntfy.sh", "Ej konfigurerat")
    except Exception as e:
        report.warn("ntfy.sh", f"Kontroll misslyckades: {e}")


def check_data_providers(report: DiagnosticReport, quick: bool = False):
    """Sektion 9: Datakällor (yfinance, Finnhub)."""
    report.section("9. Datakällor")

    if quick:
        report.skip("API-test", "Hoppad (quick-läge)")
        return

    # yfinance
    try:
        import yfinance as yf
        t0 = time.time()
        ticker = yf.Ticker("AAPL")
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        elapsed = time.time() - t0
        if price and price > 0:
            report.ok("yfinance", f"AAPL pris: ${price:.2f} ({elapsed:.1f}s)")
        else:
            report.warn("yfinance", "Pris saknas — rate-limited eller API-ändring",
                       fix="Vänta 30s och försök igen")
    except Exception as e:
        report.error("yfinance", f"Misslyckades: {e}",
                    fix="pip install -U yfinance")

    # Finnhub
    try:
        from core import config
        finnhub_key = getattr(config, "FINNHUB_API_KEY", "")
        if finnhub_key:
            import requests
            t0 = time.time()
            resp = requests.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": "AAPL", "token": finnhub_key},
                timeout=10,
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                price = resp.json().get("c", 0)
                report.ok("Finnhub", f"AAPL: ${price:.2f} ({elapsed:.1f}s)")
            elif resp.status_code == 429:
                report.warn("Finnhub", "Rate-limited (429)",
                           fix="Vänta 61 sekunder och försök igen")
            else:
                report.error("Finnhub", f"HTTP {resp.status_code}",
                            detail=resp.text[:80],
                            fix="Kontrollera FINNHUB_API_KEY")
        else:
            report.warn("Finnhub", "Ej konfigurerat",
                       fix="Sätt FINNHUB_API_KEY för Finnhub-sentiment och nyheter")
    except Exception as e:
        report.warn("Finnhub", f"Kontroll misslyckades: {e}")

    # DeepSeek
    try:
        from core import config
        ds_key = getattr(config, "DEEPSEEK_API_KEY", "")
        if ds_key:
            import requests
            t0 = time.time()
            resp = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {ds_key}",
                         "Content-Type": "application/json"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "user", "content": "Say OK"}],
                      "max_tokens": 5},
                timeout=15,
            )
            elapsed = time.time() - t0
            if resp.status_code == 200:
                report.ok("DeepSeek API", f"Svar OK ({elapsed:.1f}s)")
            elif resp.status_code == 402:
                report.error("DeepSeek API", "Saldo slut (402)",
                            fix="Fyll på saldot på platform.deepseek.com")
            else:
                report.error("DeepSeek API", f"HTTP {resp.status_code}",
                            detail=resp.text[:80])
        else:
            report.warn("DeepSeek API", "Ej konfigurerat")
    except Exception as e:
        report.warn("DeepSeek API", f"Kontroll misslyckades: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Huvud-entry-point
# ══════════════════════════════════════════════════════════════════════════════

def run_diagnostics(
    sections: Optional[list[str]] = None,
    quick: bool = False,
    send_test_mail: bool = False,
    output_json: bool = False,
) -> DiagnosticReport:
    """Kör alla (eller valda) diagnostik-sektioner och returnerar rapporten."""
    report = DiagnosticReport()

    all_sections = {
        "env":      lambda: check_environment(report),
        "config":   lambda: check_configuration(report),
        "email":    lambda: check_email(report, send_test=send_test_mail),
        "github":   lambda: check_github(report, quick=quick),
        "streamlit": lambda: check_streamlit(report, quick=quick),
        "data":     lambda: check_pipeline_data(report),
        "ml":       lambda: check_ml_models(report),
        "channels": lambda: check_notification_channels(report, quick=quick),
        "providers": lambda: check_data_providers(report, quick=quick),
    }

    to_run = sections if sections else list(all_sections.keys())
    for sec_key in to_run:
        if sec_key in all_sections:
            try:
                all_sections[sec_key]()
            except Exception as e:
                report.error(f"Sektion {sec_key}", f"Oväntad krasch: {e}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="MarketScan Självdiagnos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--quick",          action="store_true",
                        help="Hoppa över alla nätverkstest (snabb kontroll)")
    parser.add_argument("--send-test-mail", action="store_true",
                        help="Skicka ett riktigt testmail via SMTP")
    parser.add_argument("--json",           action="store_true",
                        help="Skriv ut maskinläsbar JSON istf mänsklig rapport")
    parser.add_argument("--section",        nargs="+",
                        choices=["env","config","email","github","streamlit",
                                 "data","ml","channels","providers"],
                        help="Kör bara valda sektioner")
    parser.add_argument("--save",           metavar="FILE",
                        help="Spara rapporten till en JSON-fil")
    args = parser.parse_args()

    report = run_diagnostics(
        sections=args.section,
        quick=args.quick,
        send_test_mail=args.send_test_mail,
        output_json=args.json,
    )

    if args.json:
        print(report.to_json())
    else:
        report.print_report()

    if args.save:
        Path(args.save).write_text(report.to_json(), encoding="utf-8")
        print(f"\n  💾 Rapport sparad till {args.save}")

    # Avsluta med exit code baserat på hälsa
    sys.exit(0 if report.is_healthy else 1)


if __name__ == "__main__":
    main()
