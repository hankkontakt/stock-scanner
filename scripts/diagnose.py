"""
scripts/diagnose.py - MarketScan Komplett Systemdiagnos
=======================================================
Kör diagnos på ALLA systemkomponenter och rapporterar status.
Kan köras lokalt, från GitHub Actions, eller via Admin-sidan.

TACKER:
  1.  Miljo & beroenden
  2.  Konfiguration & API-nycklar
  3.  E-postsystem (SMTP-anslutning + testmail)
  4.  GitHub Actions & repo-halsa
  5.  Streamlit-appen (HTTP-halsocheck, svarstid)
  6.  Pipeline-data (scanfiler, alder, integritet)
  7.  ML-modeller (laddning, checksummar, SHA-256)
  8.  Notifieringskanaler (Telegram, Discord, ntfy)
  9.  Databeroenden (yfinance, Finnhub live-test)
  10. Feature flags & metrics-system
  11. Sammandrag med rekommendationer

ANVANDNING:
  python scripts/diagnose.py               # Fullstandig diagnos
  python scripts/diagnose.py --quick       # Hoppa over natverkstest
  python scripts/diagnose.py --section email  # Bara e-postdiagnos
  python scripts/diagnose.py --send-test-mail # Skicka riktigt testmail
  python scripts/diagnose.py --json        # Maskinlasbar JSON-output
  python scripts/diagnose.py --save        # Spara JSON till data/diagnose_history.jsonl
  python scripts/diagnose.py --github      # Visa GitHub Actions-status
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Detect Windows terminal encoding - use ASCII fallback if needed
_USE_UNICODE = sys.stdout.encoding and sys.stdout.encoding.lower() in (
    "utf-8", "utf-8-sig", "utf8"
)

def _icon(kind: str) -> str:
    """Return status icon (ASCII fallback for Windows cp1252)."""
    if _USE_UNICODE:
        return {"OK": "OK ", "WARN": "!! ", "ERROR": "XX ", "SKIP": "-- "}.get(kind, "?  ")
    return {"OK": "OK ", "WARN": "!! ", "ERROR": "XX ", "SKIP": "-- "}.get(kind, "?  ")

# ========================================================================================
# Resultatstruktur
# ========================================================================================

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
            "name":    self.name,
            "status":  self.status,
            "message": self.message,
            "detail":  self.detail,
            "fix":     self.fix,
            "ts":      self.ts,
        }


class DiagnosticReport:
    """Samlar alla check-resultat och skriver rapport."""

    def __init__(self, title: str = "MarketScan Sjalvdiagnos"):
        self.title   = title
        self.results: list[CheckResult] = []
        self.sections: dict[str, list[CheckResult]] = {}
        self._current_section = "Ovrigt"

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
    def n_ok(self)    -> int: return sum(1 for r in self.results if r.status == CheckResult.OK)
    @property
    def n_warn(self)  -> int: return sum(1 for r in self.results if r.status == CheckResult.WARN)
    @property
    def n_error(self) -> int: return sum(1 for r in self.results if r.status == CheckResult.ERROR)
    @property
    def is_healthy(self) -> bool: return self.n_error == 0

    def print_report(self):
        width = 72
        sep = "=" * width
        print(sep)
        print(f"  {self.title}")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(sep)
        for sec_name, checks in self.sections.items():
            if not checks:
                continue
            dash = "-" * max(0, width - len(sec_name) - 6)
            print(f"\n-- {sec_name} {dash}")
            for r in checks:
                icon = _icon(r.status)
                line = f"  [{icon}] {r.name:<34} {r.message}"
                print(line[:width + 10])
                if r.detail:
                    for dl in r.detail.split("\n"):
                        if dl.strip():
                            print(f"         {dl[:width - 9]}")
                if r.fix and r.status in (CheckResult.WARN, CheckResult.ERROR):
                    print(f"     FIX: {r.fix[:width - 9]}")
        print("\n" + sep)
        status_line = (
            f"  TOTALT: {self.n_ok} OK  "
            f"{self.n_warn} VARNINGAR  "
            f"{self.n_error} FEL"
        )
        print(status_line)
        if self.n_error == 0 and self.n_warn == 0:
            print("  SYSTEMET AR FRISKT")
        elif self.n_error == 0:
            print("  VARNINGAR - kontrollera ovan")
        else:
            print("  KRITISKA FEL - atgard kravs")
        print(sep)

    def to_json(self) -> str:
        return json.dumps({
            "title":   self.title,
            "ts":      datetime.now(timezone.utc).isoformat(),
            "summary": {
                "ok":      self.n_ok,
                "warnings": self.n_warn,
                "errors":   self.n_error,
                "healthy":  self.is_healthy,
            },
            "sections": {
                sec: [r.to_dict() for r in checks]
                for sec, checks in self.sections.items()
            },
        }, ensure_ascii=False, indent=2)

    def save_history(self, path: Optional[Path] = None):
        """Lagg till en rad i data/diagnose_history.jsonl."""
        if path is None:
            path = ROOT / "data" / "diagnose_history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ok": self.n_ok,
            "warn": self.n_warn,
            "error": self.n_error,
            "healthy": self.is_healthy,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ========================================================================================
# Diagnos-sektioner
# ========================================================================================

def check_environment(report: DiagnosticReport):
    """Sektion 1: Miljo & Python-beroenden."""
    report.section("1. Miljo & Beroenden")

    v = sys.version_info
    if v >= (3, 11):
        report.ok("Python-version", f"Python {v.major}.{v.minor}.{v.micro}")
    elif v >= (3, 9):
        report.warn("Python-version", f"Python {v.major}.{v.minor} (rekommenderas 3.11+)",
                    fix="Uppgradera till Python 3.11")
    else:
        report.error("Python-version", f"Python {v.major}.{v.minor} - for gammal",
                    fix="Uppgradera till Python 3.11+")

    critical_deps = [
        "pandas", "streamlit", "yfinance", "requests", "numpy",
        "plotly", "scipy",
    ]
    optional_deps = [
        "pyarrow", "xgboost", "scikit-learn", "hypothesis",
        "bcrypt", "pydantic_settings",
    ]
    for pkg in critical_deps:
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "?")
            report.ok(f"Dep: {pkg}", f"v{ver}")
        except ImportError:
            report.error(f"Dep: {pkg}", "SAKNAS",
                        fix=f"pip install {pkg}")
    for pkg in optional_deps:
        try:
            mod = importlib.import_module(pkg.replace("-", "_"))
            ver = getattr(mod, "__version__", "?")
            report.ok(f"Opt: {pkg}", f"v{ver}")
        except ImportError:
            report.warn(f"Opt: {pkg}", "Ej installerat",
                       fix=f"pip install {pkg}")


def check_configuration(report: DiagnosticReport):
    """Sektion 2: Konfiguration & API-nycklar."""
    report.section("2. Konfiguration & API-nycklar")

    required_files = [
        (ROOT / "data" / "universe.json",       "universe.json"),
        (ROOT / "data" / "scoring_config.json",  "scoring_config.json"),
        (ROOT / "requirements.txt",              "requirements.txt"),
        (ROOT / "data" / "feature_flags.json",   "feature_flags.json"),
    ]
    for path, name in required_files:
        if path.exists():
            size = path.stat().st_size
            report.ok(f"Fil: {name}", f"Finns ({size:,} bytes)")
        else:
            report.warn(f"Fil: {name}", "Saknas",
                       fix=f"Skapa {name}")

    try:
        from core import config
        key_checks = [
            ("DEEPSEEK_API_KEY",  getattr(config, "DEEPSEEK_API_KEY",  ""), True,  "AI-analys (primär)"),
            ("GEMINI_API_KEY",    getattr(config, "GEMINI_API_KEY",    ""), False, "AI-analys (fallback)"),
            ("FINNHUB_API_KEY",   getattr(config, "FINNHUB_API_KEY",   ""), False, "Sentimentdata"),
            ("EMAIL_SENDER",      getattr(config, "EMAIL_SENDER",      ""), False, "E-postsystem"),
            ("EMAIL_PASSWORD",    getattr(config, "EMAIL_PASSWORD",    ""), False, "E-postsystem"),
            ("EMAIL_TO",          getattr(config, "EMAIL_TO",          ""), False, "E-postsystem"),
            ("GITHUB_TOKEN",      os.environ.get("GITHUB_TOKEN", ""),        False, "GitHub API"),
            ("NTFY_TOPIC",        os.environ.get("NTFY_TOPIC", ""),          False, "Push-notiser"),
            ("TELEGRAM_BOT_TOKEN",os.environ.get("TELEGRAM_BOT_TOKEN", ""), False, "Telegram"),
        ]
        for key_name, val, is_critical, usage in key_checks:
            if val:
                masked = val[:4] + "..." + val[-3:] if len(val) > 10 else "***"
                report.ok(f"Key: {key_name}", f"Konfigurerad ({masked}) — {usage}")
            elif is_critical:
                report.error(f"Key: {key_name}", f"SAKNAS — {usage} fungerar ej",
                            fix=f"Satt {key_name} i .env eller Streamlit Secrets")
            else:
                report.warn(f"Key: {key_name}", f"Ej konfigurerad — {usage} inaktivt",
                           fix=f"Satt {key_name} for att aktivera")
    except ImportError as e:
        report.error("Config-import", f"Kunde inte importera core.config: {e}",
                    fix="Kontrollera PYTHONPATH=. och att core/ finns")


def check_email(report: DiagnosticReport, send_test: bool = False):
    """Sektion 3: E-postsystem."""
    report.section("3. E-postsystem")
    try:
        import smtplib
        from core import config
        sender   = getattr(config, "EMAIL_SENDER",   "")
        password = getattr(config, "EMAIL_PASSWORD", "")
        to_addr  = getattr(config, "EMAIL_TO",       sender)

        if not sender or not password:
            report.warn("SMTP-konfiguration", "EMAIL_SENDER/PASSWORD ej konfigurerade",
                       fix="Satt EMAIL_SENDER och EMAIL_PASSWORD i .env")
            return

        t0 = time.time()
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as s:
                s.starttls()
                s.login(sender, password)
                elapsed = time.time() - t0
                report.ok("SMTP Gmail", f"Inloggad OK ({elapsed:.1f}s) — {sender[:20]}...")
        except smtplib.SMTPAuthenticationError:
            report.error("SMTP-autentisering", "Fel losenord eller 2FA kravs",
                        fix="Skapa ett App Password pa: myaccount.google.com/apppasswords")
        except Exception as e:
            report.error("SMTP-anslutning", str(e)[:80],
                        fix="Kontrollera natverksatkomst och brandvagg pa port 587")
            return

        # Testa e-postmall
        try:
            from core.email_template import build_section_header
            html = build_section_header("Test")
            if html and len(html) > 10:
                report.ok("E-postmall", f"build_section_header() returnerar {len(html)} bytes")
            else:
                report.warn("E-postmall", "Returnerade tomt/kort svar")
        except Exception as e:
            report.warn("E-postmall", f"core.email_template: {e}")

        # Skicka testmail
        if send_test and to_addr:
            try:
                from core.email_template import send_email
                ok = send_email(
                    subject="[MarketScan Diagnos] SMTP-test",
                    body_markdown="# Test\n\nDenna e-post skickades automatiskt av `scripts/diagnose.py`.\n\nAllt fungerar!",
                    recipients=[to_addr],
                )
                if ok:
                    report.ok("Testmail", f"Skickat till {to_addr}")
                else:
                    report.error("Testmail", "send_email() returnerade False")
            except Exception as e:
                report.error("Testmail", str(e)[:80])
        elif send_test:
            report.warn("Testmail", "EMAIL_TO ej konfigurerat")

        # Kontrollera prenumerantlistan
        try:
            from core.email_template import load_subscribers
            subs = load_subscribers()
            active = [s for s in subs if s.get("active", True)]
            report.ok("Prenumeranter", f"{len(active)} aktiva prenumeranter")
        except Exception as e:
            report.warn("Prenumeranter", f"Kunde inte lasa: {e}")

    except Exception as e:
        report.error("E-post (ovantat fel)", str(e)[:80])


def check_github(report: DiagnosticReport, quick: bool = False):
    """Sektion 4: GitHub Actions & repo-halsa."""
    report.section("4. GitHub Actions")

    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=ROOT,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
            # Hämta branch
            branch_r = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5, cwd=ROOT,
            )
            branch = branch_r.stdout.strip() or "?"
            report.ok("Git-repo", f"Branch={branch}, HEAD={commit}")
        else:
            report.warn("Git-repo", "Kunde inte kora git-kommando")
    except Exception as e:
        report.warn("Git-repo", str(e)[:60])

    # Kontrollera .github/workflows/
    workflows_dir = ROOT / ".github" / "workflows"
    if workflows_dir.exists():
        workflows = list(workflows_dir.glob("*.yml"))
        report.ok("Workflows", f"{len(workflows)} workflow-filer hittades: " +
                  ", ".join(w.stem for w in workflows))
    else:
        report.error("Workflows", ".github/workflows/ saknas")

    if quick:
        report.skip("GitHub API", "Hoppar over (--quick)")
        return

    # GitHub API — kontrollera senaste workflow-körningar
    token = os.environ.get("GITHUB_TOKEN", "")
    owner = os.environ.get("GITHUB_OWNER", "")
    repo  = os.environ.get("GITHUB_REPO",  "")

    if not token:
        # Försök läsa från core.config
        try:
            from core import config
            token = getattr(config, "GITHUB_TOKEN", "")
            owner = getattr(config, "GITHUB_OWNER", "")
            repo  = getattr(config, "GITHUB_REPO",  "")
        except Exception:
            pass

    if not (token and owner and repo):
        report.warn("GitHub API", "GITHUB_TOKEN/OWNER/REPO ej konfigurerade",
                   fix="Satt i .env for att se workflow-status")
        return

    try:
        import requests
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?per_page=5"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            runs = data.get("workflow_runs", [])
            if runs:
                latest = runs[0]
                status   = latest.get("status", "?")
                conclude = latest.get("conclusion", "?")
                name     = latest.get("name", "?")[:30]
                created  = latest.get("created_at", "")[:16]
                line = f"{name} | {status}/{conclude} | {created}"
                if conclude in ("success", None) and status in ("completed", "in_progress"):
                    report.ok("GitHub API (senaste run)", line)
                elif conclude == "failure":
                    report.error("GitHub API (senaste run)", f"FAILED: {line}",
                                fix="Kolla GitHub Actions-loggen")
                else:
                    report.warn("GitHub API (senaste run)", line)
                # Sammanfatta senaste 5 runs
                fails = [r for r in runs if r.get("conclusion") == "failure"]
                if fails:
                    report.warn("GitHub (misslyckade runs)",
                                f"{len(fails)} av {len(runs)} senaste runs misslyckades")
            else:
                report.warn("GitHub API", "Inga runs hittade")
        elif resp.status_code == 401:
            report.error("GitHub API", "401 Unauthorized — ogiltig token")
        elif resp.status_code == 404:
            report.error("GitHub API", f"404 — repo {owner}/{repo} hittades ej")
        else:
            report.warn("GitHub API", f"HTTP {resp.status_code}")
    except Exception as e:
        report.warn("GitHub API", str(e)[:80])


def check_streamlit(report: DiagnosticReport, quick: bool = False):
    """Sektion 5: Streamlit-appen."""
    report.section("5. Streamlit-app")

    if quick:
        report.skip("HTTP-halsocheck", "Hoppar over (--quick)")
        return

    # Hämta app-URL
    app_url = os.environ.get("DIAGNOSE_STREAMLIT_URL", "")
    if not app_url:
        try:
            from core import config
            app_url = getattr(config, "APP_URL", "") or os.environ.get("APP_URL", "")
        except Exception:
            pass
    if not app_url:
        app_url = "https://stock-scanner-hank.streamlit.app"

    try:
        import requests
        t0 = time.time()
        resp = requests.get(app_url, timeout=30, allow_redirects=True)
        elapsed = (time.time() - t0) * 1000

        status = resp.status_code
        if status in (200, 302, 301):
            speed = "snabb" if elapsed < 2000 else "latt" if elapsed < 8000 else "LANG"
            report.ok("HTTP-status", f"{status} OK — {elapsed:.0f}ms ({speed}) — {app_url[:50]}")

            # Kolla om sidan innehaller MarketScan-relaterat innehall
            if "MarketScan" in resp.text or "marketscan" in resp.text.lower():
                report.ok("Innehall", "Sidan innehaller 'MarketScan'")
            elif "<html" in resp.text.lower():
                report.warn("Innehall", "HTML-svar men 'MarketScan' hittades ej i body")
            else:
                report.warn("Innehall", f"Overraskande svar ({len(resp.text)} bytes)")
        elif status == 503:
            report.warn("HTTP-status", "503 Service Unavailable — appen startar kanske upp",
                       fix="Vanta 30s och prova igen")
        else:
            report.error("HTTP-status", f"HTTP {status} — {app_url[:50]}",
                        fix="Kolla Streamlit Cloud -> Manage app")

        # Svarstid-varning
        if elapsed > 10000:
            report.warn("Svarstid", f"{elapsed:.0f}ms — over 10 sekunder!",
                       fix="Appen kan vara overbelastad eller startande")

    except Exception as e:
        err = str(e)
        if "timeout" in err.lower():
            report.error("HTTP-timeout", f"Appen svarade inte pa 30s — {app_url[:50]}",
                        fix="Kolla Streamlit Cloud-status pa share.streamlit.io")
        else:
            report.error("HTTP-fel", err[:80])


def check_pipeline_data(report: DiagnosticReport):
    """Sektion 6: Pipeline-data & scanresultat."""
    report.section("6. Pipeline-data")

    data_dir   = ROOT / "data"
    report_dir = ROOT / "reports"

    # Scan-filer
    parquet_files = sorted(report_dir.glob("scored_universe_*.parquet"), reverse=True)
    csv_files     = sorted(report_dir.glob("scored_universe_*.csv"),     reverse=True)
    all_scan_files = parquet_files or csv_files

    if all_scan_files:
        latest = all_scan_files[0]
        age_h = (time.time() - latest.stat().st_mtime) / 3600
        age_str = f"{age_h:.1f}h sedan"
        if age_h < 36:
            report.ok("Senaste scan", f"{latest.name} ({age_str})")
        elif age_h < 72:
            report.warn("Senaste scan", f"{latest.name} ({age_str})",
                       fix="Kör morning/weekly pipeline manuellt eller vänta på schema")
        else:
            report.error("Senaste scan", f"DATA AR {age_h/24:.1f} DAGAR GAMMAL",
                        fix="Pipeline har inte körts! Kör: python -c \"from core.daily_pipeline import run_pipeline; run_pipeline('morning')\"")
        report.ok("Antal scanfiler", f"{len(parquet_files)} parquet + {len(csv_files)} csv")

        # Läs senaste scan och rapportera innehåll
        try:
            import pandas as pd
            if parquet_files:
                df = pd.read_parquet(parquet_files[0])
            else:
                df = pd.read_csv(csv_files[0], low_memory=False)
            n = len(df)
            n_stark = (df.get("entry_signal", pd.Series()) == "STARK").sum() if "entry_signal" in df.columns else "?"
            avg_score = df["score_total"].mean() if "score_total" in df.columns else 0
            report.ok("Scan-innehall", f"{n} tickers | {n_stark} STARK | snitt {avg_score:.1f} poang")
        except Exception as e:
            report.warn("Scan-las", f"Kunde inte lasa: {e}")
    else:
        report.error("Scan-filer", "Inga scored_universe-filer hittades",
                    fix="Kör pipeline: python -c \"from core.daily_pipeline import run_pipeline; run_pipeline('morning')\"")

    # Smallcap-filer
    sc_files = sorted(report_dir.glob("smallcap_scored_*.parquet"), reverse=True) or \
               sorted(report_dir.glob("smallcap_scored_*.csv"), reverse=True)
    if sc_files:
        age_h = (time.time() - sc_files[0].stat().st_mtime) / 3600
        report.ok("Smallcap-scan", f"{sc_files[0].name} ({age_h:.1f}h)")
    else:
        report.warn("Smallcap-scan", "Inga smallcap-scanfiler",
                   fix="Kör smallcap-pipeline")

    # Viktiga datafiler
    json_checks = [
        (data_dir / "universe.json",       "universe.json",      100),
        (data_dir / "watchlist.json",       "watchlist.json",     0),
        (data_dir / "blacklist.json",       "blacklist.json",     0),
        (data_dir / "scan_log.json",        "scan_log.json",      0),
        (data_dir / "feature_flags.json",   "feature_flags.json", 10),
    ]
    for path, name, min_size in json_checks:
        if not path.exists():
            if min_size > 0:
                report.warn(f"JSON: {name}", "Saknas")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            size = path.stat().st_size
            if isinstance(data, list):
                report.ok(f"JSON: {name}", f"OK ({len(data)} entries, {size:,} bytes)")
            elif isinstance(data, dict):
                report.ok(f"JSON: {name}", f"OK ({len(data)} nycklar, {size:,} bytes)")
            else:
                report.ok(f"JSON: {name}", f"OK ({size:,} bytes)")
        except Exception as e:
            report.error(f"JSON: {name}", f"KORRUPT JSON: {e}",
                        fix=f"Kontrollera {path} och reparera manuellt")

    # Pipeline-logg (senaste körningar)
    scan_log_path = data_dir / "scan_log.json"
    if scan_log_path.exists():
        try:
            log = json.loads(scan_log_path.read_text(encoding="utf-8"))
            if log:
                latest = log[-1]
                ts   = latest.get("timestamp", "?")[:16]
                mode = latest.get("scan_type", "?")
                stat = latest.get("status", "?")
                if stat == "OK":
                    report.ok("Pipeline-logg", f"Senaste: {mode} @ {ts} — OK")
                else:
                    report.warn("Pipeline-logg", f"Senaste: {mode} @ {ts} — {stat}",
                               fix="Kolla Admin -> Felsökning")
        except Exception:
            pass


def check_ml_models(report: DiagnosticReport):
    """Sektion 7: ML-modeller."""
    report.section("7. ML-modeller")

    models_dir = ROOT / "models"
    if not models_dir.exists():
        report.warn("ML models-mapp", "models/ saknas",
                   fix="Kör train_ml workflow på GitHub Actions")
        return

    expected = ["ml_universe.pkl", "ml_smallcap.pkl"]
    for model_name in expected:
        model_path = models_dir / model_name
        if not model_path.exists():
            report.warn(f"ML: {model_name}", "Saknas",
                       fix="Kör train_ml workflow")
            continue

        age_days = (time.time() - model_path.stat().st_mtime) / 86400
        size_kb = model_path.stat().st_size / 1024
        age_str = f"{age_days:.0f} dagar gammal"

        # Kontrollera SHA-256 checksum
        hash_path = models_dir / f"{model_name}.sha256"
        if hash_path.exists():
            try:
                import hashlib
                sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
                stored = hash_path.read_text().strip()
                if sha == stored:
                    report.ok(f"ML: {model_name}", f"SHA-256 OK | {age_str} | {size_kb:.0f} KB")
                else:
                    report.error(f"ML: {model_name}", "SHA-256 MISMATCH — modellen är förändrad!",
                                fix="Ladda ner original från GitHub eller träna om")
            except Exception as e:
                report.warn(f"ML hash: {model_name}", str(e)[:60])
        else:
            report.warn(f"ML: {model_name}", f"Ingen SHA-256-checksumfil | {age_str} | {size_kb:.0f} KB",
                       fix="Kör train_ml workflow för att skapa ny checksum")

        # Försök ladda modellen
        try:
            from core.ml_predictor import load_model
            universe = model_name.replace("ml_", "").replace(".pkl", "")
            m = load_model(universe)
            if m is not None:
                report.ok(f"ML laddning: {universe}", "load_model() OK")
            else:
                report.warn(f"ML laddning: {universe}", "load_model() returnerade None")
        except Exception as e:
            report.warn(f"ML laddning: {model_name}", str(e)[:60])

        if age_days > 30:
            report.warn(f"ML alder: {model_name}", f"Modellen ar {age_days:.0f} dagar gammal",
                       fix="Trena om via GitHub Actions -> train_ml workflow")


def check_notifications(report: DiagnosticReport, quick: bool = False):
    """Sektion 8: Notifieringskanaler."""
    report.section("8. Notifieringskanaler")

    if quick:
        report.skip("Notifier-test", "Hoppar over (--quick)")
        return

    try:
        import requests

        # Telegram
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        tg_chat  = os.environ.get("TELEGRAM_CHAT_ID",   "")
        if tg_token:
            try:
                r = requests.get(f"https://api.telegram.org/bot{tg_token}/getMe", timeout=10)
                if r.status_code == 200:
                    bot_name = r.json().get("result", {}).get("username", "?")
                    report.ok("Telegram", f"Bot aktiv: @{bot_name}")
                else:
                    report.error("Telegram", f"HTTP {r.status_code} — ogiltig token",
                                fix="Kontrollera TELEGRAM_BOT_TOKEN")
            except Exception as e:
                report.warn("Telegram", str(e)[:60])
        else:
            report.warn("Telegram", "Ej konfigurerat",
                       fix="Sätt TELEGRAM_BOT_TOKEN och TELEGRAM_CHAT_ID")

        # Discord webhook
        dc_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if dc_url:
            try:
                r = requests.get(dc_url, timeout=10)
                if r.status_code in (200, 405):
                    report.ok("Discord", "Webhook-URL svarar")
                else:
                    report.warn("Discord", f"HTTP {r.status_code}")
            except Exception as e:
                report.warn("Discord", str(e)[:60])
        else:
            report.warn("Discord", "Ej konfigurerat",
                       fix="Sätt DISCORD_WEBHOOK_URL")

        # ntfy.sh
        ntfy_topic = os.environ.get("NTFY_TOPIC", "")
        if ntfy_topic:
            try:
                r = requests.get(f"https://ntfy.sh/{ntfy_topic}/json?poll=1", timeout=10)
                if r.status_code in (200, 304):
                    report.ok("ntfy.sh", f"Topic '{ntfy_topic}' aktiv")
                else:
                    report.warn("ntfy.sh", f"HTTP {r.status_code}")
            except Exception as e:
                report.warn("ntfy.sh", str(e)[:60])
        else:
            report.warn("ntfy.sh", "Ej konfigurerat",
                       fix="Sätt NTFY_TOPIC")

    except ImportError:
        report.error("requests", "requests-biblioteket saknas",
                    fix="pip install requests")


def check_data_providers(report: DiagnosticReport, quick: bool = False):
    """Sektion 9: Databeroenden (yfinance, Finnhub)."""
    report.section("9. Databeroenden")

    if quick:
        report.skip("API-test", "Hoppar over (--quick)")
        return

    # yfinance live-test
    try:
        import yfinance as yf
        t0 = time.time()
        ticker = yf.Ticker("AAPL")
        hist = ticker.history(period="5d", auto_adjust=True)
        elapsed = (time.time() - t0) * 1000
        if not hist.empty:
            price = hist["Close"].iloc[-1]
            report.ok("yfinance (AAPL)", f"${price:.2f} — {elapsed:.0f}ms")
        else:
            report.warn("yfinance (AAPL)", f"Tom historik ({elapsed:.0f}ms)")
    except Exception as e:
        report.error("yfinance", str(e)[:80],
                    fix="Kontrollera internettillgang och yfinance-version")

    # Finnhub
    try:
        from core import config
        fh_key = getattr(config, "FINNHUB_API_KEY", "")
        if fh_key:
            import requests
            t0 = time.time()
            r = requests.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": "AAPL", "token": fh_key},
                timeout=10,
            )
            elapsed = (time.time() - t0) * 1000
            if r.status_code == 200:
                price = r.json().get("c", "?")
                report.ok("Finnhub (AAPL)", f"${price} — {elapsed:.0f}ms")
            elif r.status_code == 401:
                report.error("Finnhub", "Ogiltig API-nyckel",
                            fix="Kontrollera FINNHUB_API_KEY pa finnhub.io")
            elif r.status_code == 429:
                report.warn("Finnhub", "Rate-limited — for manga anrop")
            else:
                report.warn("Finnhub", f"HTTP {r.status_code}")
        else:
            report.warn("Finnhub", "Ej konfigurerat — sentimentdata otillganglig")
    except Exception as e:
        report.warn("Finnhub", str(e)[:60])


def check_feature_flags(report: DiagnosticReport):
    """Sektion 10: Feature flags & metrics."""
    report.section("10. Feature Flags & Metrics")

    try:
        from core.feature_flags import get_all_flags, _FLAGS_FILE
        flags = get_all_flags()
        enabled  = [k for k, v in flags.items() if v]
        disabled = [k for k, v in flags.items() if not v]
        report.ok("Feature flags", f"{len(enabled)} aktiva, {len(disabled)} inaktiva | {_FLAGS_FILE}")
        for k, v in flags.items():
            status = "ON " if v else "off"
            report.ok(f"Flag: {k}", status) if v else report.warn(f"Flag: {k}", status)
    except Exception as e:
        report.warn("Feature flags", str(e)[:60])

    # Metrics-system
    try:
        from core.metrics import list_metrics, get_metric_summary
        metrics = list_metrics()
        if metrics:
            report.ok("Metrics-system", f"{len(metrics)} metrics registrerade")
            # Visa senaste pipeline-körning
            if "pipeline_run" in metrics:
                s = get_metric_summary("pipeline_run", last_n=5)
                if s:
                    report.ok("Pipeline-körningar", f"{s.get('count', 0)} körningar loggade | senast: {s.get('last_ts', '?')[:16]}")
        else:
            report.warn("Metrics-system", "Inga metrics registrerade annu",
                       fix="Kör pipeline for att starta logga metrics")
    except Exception as e:
        report.warn("Metrics-system", str(e)[:60])


# ========================================================================================
# Huvudfunktion
# ========================================================================================

SECTION_MAP = {
    "env":      check_environment,
    "config":   check_configuration,
    "email":    check_email,
    "github":   check_github,
    "streamlit":check_streamlit,
    "pipeline": check_pipeline_data,
    "ml":       check_ml_models,
    "notif":    check_notifications,
    "data":     check_data_providers,
    "flags":    check_feature_flags,
}


def run_diagnostics(
    sections: Optional[list[str]] = None,
    quick: bool = False,
    send_test_mail: bool = False,
) -> DiagnosticReport:
    """Kör alla (eller valda) diagnoser och returnerar rapporten."""
    report = DiagnosticReport()

    run_sections = sections or list(SECTION_MAP.keys())

    for key in run_sections:
        fn = SECTION_MAP.get(key)
        if fn is None:
            print(f"Okand sektion: {key}. Giltiga: {list(SECTION_MAP.keys())}")
            continue
        try:
            if key == "email":
                fn(report, send_test=send_test_mail)
            elif key in ("github", "streamlit", "notif", "data"):
                fn(report, quick=quick)
            else:
                fn(report)
        except Exception as e:
            report.error(f"Sektion {key}", f"Kraschade: {e}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="MarketScan systemdiagnos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exempel:
  python scripts/diagnose.py                  Fullstandig diagnos
  python scripts/diagnose.py --quick          Hoppa over natverkstest
  python scripts/diagnose.py --section email  Bara e-postdiagnos
  python scripts/diagnose.py --send-test-mail Skicka testmail
  python scripts/diagnose.py --json           JSON-output
  python scripts/diagnose.py --save           Spara till diagnose_history.jsonl
  python scripts/diagnose.py --github         Visa GitHub workflow-status
        """,
    )
    parser.add_argument("--quick",          action="store_true", help="Hoppa over natverkstest")
    parser.add_argument("--send-test-mail", action="store_true", help="Skicka testmail")
    parser.add_argument("--json",           action="store_true", help="JSON-output")
    parser.add_argument("--save",           action="store_true", help="Spara historik")
    parser.add_argument("--github",         action="store_true", help="Fokusera pa GitHub")
    parser.add_argument("--section", "-s",  action="append",     help=f"Specifik sektion: {list(SECTION_MAP.keys())}")
    args = parser.parse_args()

    sections = args.section
    if args.github:
        sections = ["github"]

    report = run_diagnostics(
        sections=sections,
        quick=args.quick,
        send_test_mail=args.send_test_mail,
    )

    if args.json:
        print(report.to_json())
    else:
        report.print_report()

    if args.save:
        report.save_history()
        print(f"\nHistorik sparad till: {ROOT / 'data' / 'diagnose_history.jsonl'}")

    sys.exit(0 if report.is_healthy else 1)


if __name__ == "__main__":
    main()
