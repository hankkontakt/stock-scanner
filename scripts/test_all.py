"""
scripts/test_all.py
====================
Pytest + lint-runner för AI-felsökning.

Körs av mig (Claude Code) via Bash-verktyget när jag vill verifiera
att kod fungerar INNAN jag pushar — utan att behöva veta alla pytest-flaggor.

Tester körs också automatiskt i CI via .github/workflows/tests.yml på varje push.
Det här scriptet är för snabb lokal verifiering under utveckling.

Användning:
  python scripts/test_all.py              # pytest + ruff lint
  python scripts/test_all.py --pytest     # bara pytest
  python scripts/test_all.py --lint       # bara ruff
  python scripts/test_all.py --verbose    # detaljerad pytest-output
  python scripts/test_all.py --file path  # testa en specifik fil/mapp
  python scripts/test_all.py --json       # JSON-sammanfattning till stdout
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _run(cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
    """Kör subprocess, returnera (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"},
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout efter {timeout}s"
    except FileNotFoundError as e:
        return 1, "", f"Kommando ej hittat: {e}"


def run_pytest(path: str = "tests/", verbose: bool = False) -> dict:
    """Kör pytest med täckningsrapport."""
    print(f"\n{'='*60}")
    print(f"  Pytest — {path}")
    print(f"{'='*60}")

    cmd = [sys.executable, "-m", "pytest", path,
           "--tb=short",
           "-v" if verbose else "-q",
           "--cov=core",
           "--cov=portfolio",
           "--cov-report=term-missing:skip-covered",
           "--cov-report=json:.coverage.json",
           "-m", "not integration and not live",
           "--timeout=120",
           ]

    print(f"  Kommando: pytest {path} {'--verbose' if verbose else '-q'}")
    print()

    t0 = time.perf_counter()
    rc, stdout, stderr = _run(cmd, timeout=300)
    elapsed = time.perf_counter() - t0

    # Visa output direkt
    if stdout:
        print(stdout[-4000:] if len(stdout) > 4000 else stdout)
    if stderr and rc != 0:
        print(stderr[-1000:] if len(stderr) > 1000 else stderr)

    # Läs coverage
    cov_pct = None
    cov_json = ROOT / ".coverage.json"
    if cov_json.exists():
        try:
            with open(cov_json, encoding="utf-8") as f:
                cov_data = json.load(f)
            cov_pct = round(cov_data.get("totals", {}).get("percent_covered", 0), 1)
        except Exception:
            pass

    ok = (rc == 0)
    print()
    icon = "[OK ]" if ok else "[XX ]"
    print(f"  {icon} Pytest: exitkod {rc} | tid {elapsed:.1f}s" +
          (f" | täckning {cov_pct}%" if cov_pct else ""))

    return {"ok": ok, "returncode": rc, "duration_s": round(elapsed, 1),
            "coverage_pct": cov_pct}


def run_lint() -> dict:
    """Kör ruff lint på all Python-kod."""
    print(f"\n{'='*60}")
    print("  Ruff Lint")
    print(f"{'='*60}")

    cmd = [sys.executable, "-m", "ruff", "check",
           "core/", "tests/", "portfolio/", "web/", "scripts/",
           "--select=E,F,W", "--ignore=E501",
           "--output-format=concise"]

    t0 = time.perf_counter()
    rc, stdout, stderr = _run(cmd, timeout=60)
    elapsed = time.perf_counter() - t0

    if stdout.strip():
        print(stdout[:3000])

    ok = (rc == 0)
    issues = stdout.count("\n") if stdout else 0
    icon = "[OK ]" if ok else "[!! ]"
    print(f"  {icon} Ruff: {'inga problem' if ok else f'{issues} problem'} | {elapsed:.1f}s")

    return {"ok": ok, "returncode": rc, "issue_count": issues,
            "duration_s": round(elapsed, 1)}


def print_summary(results: dict[str, dict], total_s: float) -> bool:
    """Skriv ut slutsammanfattning, returnera True om allt OK."""
    print(f"\n{'='*60}")
    print("  SAMMANFATTNING")
    print(f"{'='*60}")

    all_ok = True
    for name, r in results.items():
        ok = r.get("ok", False)
        dur = r.get("duration_s", 0)
        if ok:
            print(f"  [OK ] {name:<30} ({dur:.1f}s)")
        else:
            print(f"  [XX ] {name:<30} ({dur:.1f}s)")
            all_ok = False

    if "pytest" in results and results["pytest"].get("coverage_pct") is not None:
        cov = results["pytest"]["coverage_pct"]
        icon = "[OK ]" if cov >= 50 else "[!! ]"
        print(f"\n  {icon} Testtäckning: {cov}%")

    print(f"\n  Total tid: {total_s:.1f}s")
    if all_ok:
        print("  [OK ] Klart — inga problem hittades")
    else:
        print("  [XX ] Problem hittades — se detaljer ovan")
    print(f"{'='*60}")
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pytest + lint-runner (för AI-felsökning under utveckling)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--pytest", "-p", action="store_true",
                        help="Bara pytest (ingen lint)")
    parser.add_argument("--lint",   "-l", action="store_true",
                        help="Bara ruff lint (inga tester)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Detaljerad pytest-output")
    parser.add_argument("--file",   "-f", default="tests/",
                        help="Testa specifik fil eller mapp (default: tests/)")
    parser.add_argument("--json",         action="store_true",
                        help="Skriv ut JSON-sammanfattning")
    args = parser.parse_args()

    print(f"{'='*60}")
    print("  MarketScan — Test Runner")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  (Tester körs också automatiskt via CI på push)")
    print(f"{'='*60}")

    t0 = time.perf_counter()
    results: dict[str, dict] = {}

    run_both = not args.pytest and not args.lint

    if args.pytest or run_both:
        results["pytest"] = run_pytest(path=args.file, verbose=args.verbose)

    if args.lint or run_both:
        results["ruff"] = run_lint()

    total_s = time.perf_counter() - t0
    all_ok = print_summary(results, total_s)

    if args.json:
        summary = {
            "timestamp": datetime.now().isoformat(),
            "ok": all_ok,
            "duration_s": round(total_s, 1),
            "results": results,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
