"""
scripts/test_all.py
====================
Master test-runner — kör alla tester och diagnostikverktyg i ett enda kommando.

Användning:
  python scripts/test_all.py              # Kör allt (pytest + hälsokontroller)
  python scripts/test_all.py --fast       # Bara pytest (hoppa över nätverkstester)
  python scripts/test_all.py --pytest     # Bara pytest
  python scripts/test_all.py --health     # Bara hälsokontroller (diagnose)
  python scripts/test_all.py --github     # Inkludera GitHub-kontroll
  python scripts/test_all.py --email      # Inkludera SMTP-kontroll
  python scripts/test_all.py --site       # Inkludera webbkontroll
  python scripts/test_all.py --verbose    # Detaljerad pytest-output
  python scripts/test_all.py --json       # JSON-sammanfattning
  python scripts/test_all.py --ci         # CI-läge (strängt, exitcode 1 vid fel)

Visar:
  - Pytest-resultat med täckningsrapport
  - Miljö- och konfigurationshälsa
  - GitHub Actions-status (om GITHUB_TOKEN finns)
  - E-postsystem (om EMAIL_* konfigurerat)
  - Webbapp-hälsa (om STREAMLIT_URL konfigurerat)
  - Samlad slutrapport med exitcode
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Lägg till projekt-root i path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _run_command(cmd: list[str], cwd: Path | None = None,
                 timeout: int = 300,
                 capture: bool = True) -> tuple[int, str, str]:
    """Kör subprocess och returnera (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd or ROOT,
            capture_output=capture,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"},
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout efter {timeout}s"
    except FileNotFoundError as e:
        return 1, "", f"Kommando ej hittat: {e}"
    except Exception as e:
        return 1, "", f"Fel: {e}"


def _section(title: str) -> None:
    print()
    print(f"{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _result_line(name: str, ok: bool, detail: str = "", duration_s: float = 0.0) -> None:
    icon = "[OK ]" if ok else "[XX ]"
    dur  = f" ({duration_s:.1f}s)" if duration_s > 0 else ""
    print(f"  {icon} {name:<40} {detail}{dur}")


# ── Pytest-koerning ────────────────────────────────────────────────────────────

def run_pytest(verbose: bool = False, ci_mode: bool = False,
               test_path: str = "tests/") -> dict:
    """Kör pytest med täckningsrapport."""
    _section("Pytest — Enhetstester")

    cmd = [sys.executable, "-m", "pytest", test_path]

    # Standard-flags
    cmd += [
        "--tb=short",          # Kort traceback
        "-q",                  # Tyst läge (om ej verbose)
    ]

    if verbose:
        cmd += ["-v", "--tb=long"]
    else:
        cmd += ["-q"]

    # Täckning
    cmd += [
        "--cov=core",
        "--cov=portfolio",
        "--cov-report=term-missing:skip-covered",
        "--cov-report=json:.coverage.json",
    ]

    # CI: strängare timeout
    if ci_mode:
        cmd += ["--timeout=60"]

    # Hoppa över integrationstest och live-tester i normalt läge
    # (live = kräver riktiga nätverksanrop; integration = äldre mock-baserade)
    cmd += ["-m", "not integration and not live"]

    print(f"  Kör: {' '.join(cmd[2:])}")
    print()

    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(cmd, capture=False)
    elapsed = time.perf_counter() - t0

    # Läs coverage JSON om den finns
    cov_pct = None
    cov_json = ROOT / ".coverage.json"
    if cov_json.exists():
        try:
            with open(cov_json, encoding="utf-8") as f:
                cov_data = json.load(f)
            totals  = cov_data.get("totals", {})
            cov_pct = round(totals.get("percent_covered", 0), 1)
        except Exception:
            pass

    ok = (rc == 0)
    print()
    _result_line("Pytest", ok,
                 f"Exitkod {rc}" + (f" | Täckning: {cov_pct}%" if cov_pct else ""),
                 elapsed)

    return {
        "ok":          ok,
        "returncode":  rc,
        "duration_s":  round(elapsed, 1),
        "coverage_pct": cov_pct,
    }


def run_pytest_integration(verbose: bool = False) -> dict:
    """Kör integrationstest separat (kräver riktiga API-nycklar)."""
    _section("Pytest — Integrationstest (riktiga API-anrop)")

    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_integration.py",
        "-v" if verbose else "-q",
        "--tb=short",
        "-m", "integration",
    ]

    print(f"  Kör: {' '.join(cmd[2:])}")

    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(cmd, capture=False)
    elapsed = time.perf_counter() - t0

    ok = (rc == 0)
    _result_line("Integrationstest", ok, f"Exitkod {rc}", elapsed)

    return {"ok": ok, "returncode": rc, "duration_s": round(elapsed, 1)}


# ── Hälsokontroller ────────────────────────────────────────────────────────────

def run_diagnose(quick: bool = True) -> dict:
    """Kör scripts/diagnose.py."""
    _section("Systemdiagnos (diagnose.py)")
    cmd = [sys.executable, "scripts/diagnose.py", "--save"]
    if quick:
        cmd.append("--quick")

    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(cmd, capture=False)
    elapsed = time.perf_counter() - t0

    ok = (rc == 0)
    _result_line("Diagnose", ok, f"Exitkod {rc}", elapsed)
    return {"ok": ok, "returncode": rc, "duration_s": round(elapsed, 1)}


def run_check_github() -> dict:
    """Kör scripts/check_github.py."""
    _section("GitHub Actions Status (check_github.py)")
    if not os.getenv("GITHUB_TOKEN") or not os.getenv("GITHUB_REPO"):
        print("  [-- ] GITHUB_TOKEN / GITHUB_REPO saknas — hoppar över")
        return {"ok": True, "skipped": True}

    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(
        [sys.executable, "scripts/check_github.py", "--limit", "5"],
        capture=False,
    )
    elapsed = time.perf_counter() - t0
    ok = (rc == 0)
    _result_line("GitHub Actions", ok, f"Exitkod {rc}", elapsed)
    return {"ok": ok, "returncode": rc, "duration_s": round(elapsed, 1)}


def run_check_email() -> dict:
    """Kör scripts/check_email.py (utan testmail)."""
    _section("E-postsystem (check_email.py)")
    if not os.getenv("EMAIL_SENDER"):
        print("  [-- ] EMAIL_SENDER saknas — hoppar över")
        return {"ok": True, "skipped": True}

    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(
        [sys.executable, "scripts/check_email.py"],
        capture=False,
    )
    elapsed = time.perf_counter() - t0
    ok = (rc == 0)
    _result_line("E-post SMTP", ok, f"Exitkod {rc}", elapsed)
    return {"ok": ok, "returncode": rc, "duration_s": round(elapsed, 1)}


def run_check_site() -> dict:
    """Kör scripts/check_site.py."""
    _section("Webbapp Hälsa (check_site.py)")
    if not os.getenv("STREAMLIT_URL"):
        print("  [-- ] STREAMLIT_URL saknas — testar localhost:8501")

    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(
        [sys.executable, "scripts/check_site.py"],
        capture=False,
    )
    elapsed = time.perf_counter() - t0
    ok = (rc == 0)
    _result_line("Streamlit webbapp", ok, f"Exitkod {rc}", elapsed)
    return {"ok": ok, "returncode": rc, "duration_s": round(elapsed, 1)}


def run_ruff() -> dict:
    """Kör ruff lint på all Python-kod."""
    _section("Ruff Linter")
    cmd = [
        sys.executable, "-m", "ruff", "check",
        "core/", "tests/", "portfolio/", "web/", "scripts/",
        "--select=E,F,W",
        "--ignore=E501",
    ]
    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(cmd, capture=True)
    elapsed = time.perf_counter() - t0

    if stdout.strip():
        print(stdout[:2000])  # Max 2000 chars
    if stderr.strip():
        print(stderr[:500])

    ok = (rc == 0)
    count = stdout.count("\n") if stdout else 0
    _result_line("Ruff lint", ok,
                 "Inga problem" if ok else f"{count} problem hittade",
                 elapsed)
    return {"ok": ok, "returncode": rc, "issue_count": count, "duration_s": round(elapsed, 1)}


def run_mypy() -> dict:
    """Kör mypy typkontroll på core/."""
    _section("Mypy Typkontroll")
    cmd = [sys.executable, "-m", "mypy", "core/", "--ignore-missing-imports", "--no-error-summary"]
    t0 = time.perf_counter()
    rc, stdout, stderr = _run_command(cmd, capture=True)
    elapsed = time.perf_counter() - t0

    if stdout.strip():
        print(stdout[:2000])

    ok = (rc == 0)
    errors = stdout.count(": error:") if stdout else 0
    _result_line("Mypy", ok,
                 "Inga typproblem" if ok else f"{errors} typfel",
                 elapsed)
    return {"ok": ok, "returncode": rc, "error_count": errors, "duration_s": round(elapsed, 1)}


# ── Slutrapport ────────────────────────────────────────────────────────────────

def print_summary(results: dict[str, dict], total_s: float) -> bool:
    """Skriv ut samlad slutrapport. Returnerar True om allt är OK."""
    _section("SAMLAD SLUTRAPPORT")

    all_ok  = True
    skipped = 0

    for name, r in results.items():
        if r.get("skipped"):
            print(f"  [-- ] {name:<40} (hoppad)")
            skipped += 1
        elif r.get("ok"):
            dur = f" ({r.get('duration_s', 0):.1f}s)" if r.get("duration_s") else ""
            print(f"  [OK ] {name:<40}{dur}")
        else:
            dur = f" ({r.get('duration_s', 0):.1f}s)" if r.get("duration_s") else ""
            print(f"  [XX ] {name:<40}{dur}")
            all_ok = False

    # Pytest-specifik info
    if "pytest" in results and results["pytest"].get("coverage_pct") is not None:
        cov = results["pytest"]["coverage_pct"]
        icon = "[OK ]" if cov >= 50 else "[!! ]" if cov >= 35 else "[XX ]"
        print(f"\n  {icon} Testtäckning: {cov}%")

    ok_count   = sum(1 for r in results.values() if r.get("ok") and not r.get("skipped"))
    fail_count = sum(1 for r in results.values() if not r.get("ok") and not r.get("skipped"))

    print()
    print(f"  Totalt: {ok_count} OK  {fail_count} FEL  {skipped} HOPPADE")
    print(f"  Koerningstid: {total_s:.1f}s")
    print()

    if all_ok:
        print("  [OK ] ALLA KONTROLLER KLARADE")
    else:
        print("  [XX ] KRITISKA FEL — se detaljer ovan")

    print("=" * 70)
    return all_ok


# ── main() ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Master test-runner — kör alla tester och diagnostikverktyg",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--fast",        action="store_true",
                        help="Bara pytest (hoppa över nätverkskontroller)")
    parser.add_argument("--pytest",      action="store_true",
                        help="Bara pytest-tester")
    parser.add_argument("--health",      action="store_true",
                        help="Bara hälsokontroller (ej pytest)")
    parser.add_argument("--integration", action="store_true",
                        help="Inkludera integrationstest (kräver API-nycklar)")
    parser.add_argument("--github",      action="store_true",
                        help="Inkludera GitHub Actions-kontroll")
    parser.add_argument("--email",       action="store_true",
                        help="Inkludera e-postsystemkontroll")
    parser.add_argument("--site",        action="store_true",
                        help="Inkludera webbappkontroll")
    parser.add_argument("--lint",        action="store_true",
                        help="Inkludera ruff-lint")
    parser.add_argument("--mypy",        action="store_true",
                        help="Inkludera mypy typkontroll")
    parser.add_argument("--all-checks",  action="store_true",
                        help="Kör ALLA kontroller (inkl. nätverkstester)")
    parser.add_argument("--verbose",     action="store_true",
                        help="Detaljerad pytest-output")
    parser.add_argument("--ci",          action="store_true",
                        help="CI-läge (strängare; exitcode 1 vid valfritt fel)")
    parser.add_argument("--json",        action="store_true",
                        help="Skriv ut JSON-sammanfattning i slutet")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  MarketScan — Master Test Runner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    total_start = time.perf_counter()
    results: dict[str, dict] = {}

    # Bestäm vad som ska köras
    run_all_net = args.all_checks
    run_pytest_flag  = args.pytest or (not args.health and not run_all_net) or run_all_net
    run_health_flag  = args.health or run_all_net
    run_github_flag  = args.github or run_all_net
    run_email_flag   = args.email or run_all_net
    run_site_flag    = args.site or run_all_net
    run_lint_flag    = args.lint or run_all_net
    run_mypy_flag    = args.mypy or run_all_net

    # Fast-mode override
    if args.fast:
        run_pytest_flag = True
        run_health_flag = False
        run_github_flag = False
        run_email_flag  = False
        run_site_flag   = False

    # Kör i ordning
    if run_pytest_flag:
        results["pytest"] = run_pytest(verbose=args.verbose, ci_mode=args.ci)

    if args.integration:
        results["integration"] = run_pytest_integration(verbose=args.verbose)

    if run_lint_flag:
        results["ruff"] = run_ruff()

    if run_mypy_flag:
        results["mypy"] = run_mypy()

    if run_health_flag:
        results["diagnose"] = run_diagnose(quick=not run_all_net)

    if run_github_flag:
        results["github"] = run_check_github()

    if run_email_flag:
        results["email"] = run_check_email()

    if run_site_flag:
        results["site"] = run_check_site()

    total_s = time.perf_counter() - total_start
    all_ok = print_summary(results, total_s)

    if args.json:
        summary = {
            "timestamp":  datetime.now().isoformat(),
            "ok":         all_ok,
            "duration_s": round(total_s, 1),
            "results":    results,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # Spara till fil
        out_path = ROOT / "data" / "test_results_latest.json"
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"  [OK ] Resultat sparat: {out_path}")
        except Exception as e:
            print(f"  [!! ] Kunde inte spara resultat: {e}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
