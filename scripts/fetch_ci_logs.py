"""
scripts/fetch_ci_logs.py
=========================
Laddar ned och parsar GitHub Actions-loggar direkt från API.

Som AI-agent kan jag inte logga in på GitHub och klicka runt.
Men med detta script kan jag hämta EXAKTA felmeddelanden från
misslyckade CI-körningar och spara dem som läsbar text.

Användning:
  python scripts/fetch_ci_logs.py                    # Senaste misslyckade körning
  python scripts/fetch_ci_logs.py --run-id 12345678  # Specifik körning
  python scripts/fetch_ci_logs.py --workflow daily_scan  # Senaste för ett workflow
  python scripts/fetch_ci_logs.py --all              # Alla senaste (OK + misslyckade)
  python scripts/fetch_ci_logs.py --save             # Spara till data/ci_reports/

Output sparas till: data/ci_reports/latest_failure.txt (och .json)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO",  "")
CI_REPORTS   = ROOT / "data" / "ci_reports"

# ── API-hjälp ──────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(path: str, params: dict | None = None) -> dict | list | None:
    if not HAS_REQUESTS:
        print("[XX ] pip install requests")
        return None
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[XX ] GITHUB_TOKEN / GITHUB_REPO saknas i .env")
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/{path.lstrip('/')}"
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[XX ] API-fel: {e}")
        return None


# ── Hämtfunktioner ─────────────────────────────────────────────────────────────

def get_latest_failed_run(workflow: str | None = None) -> dict | None:
    """Hitta senaste misslyckade workflow-körning."""
    params = {"per_page": 20, "status": "failure"}
    if workflow:
        wf = workflow if workflow.endswith(".yml") else f"{workflow}.yml"
        data = _get(f"actions/workflows/{wf}/runs", params)
    else:
        data = _get("actions/runs", params)
    runs = (data or {}).get("workflow_runs", [])
    return runs[0] if runs else None


def get_run_jobs(run_id: int) -> list[dict]:
    """Hämta jobs för en körning."""
    data = _get(f"actions/runs/{run_id}/jobs")
    return (data or {}).get("jobs", [])


def download_run_logs(run_id: int) -> str | None:
    """
    Ladda ned logg-zip för en körning och returnera innehållet som text.
    GitHub API: GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs
    Returnerar zip → vi extraherar och parsar.
    """
    if not HAS_REQUESTS or not GITHUB_TOKEN or not GITHUB_REPO:
        return None

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/logs"
    try:
        r = requests.get(url, headers=_headers(), timeout=60, allow_redirects=True)
        if r.status_code == 302:
            # GitHub redirectar till S3 — följ redirect
            r = requests.get(r.headers["Location"], timeout=60)

        if r.status_code != 200:
            return f"[XX ] HTTP {r.status_code} vid loggnedladdning"

        # Parsa zip-innehåll
        log_parts = []
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            for name in sorted(zf.namelist()):
                if name.endswith(".txt"):
                    content = zf.read(name).decode("utf-8", errors="replace")
                    log_parts.append(f"\n{'='*60}\n  LOG: {name}\n{'='*60}")
                    log_parts.append(content)
        return "\n".join(log_parts) if log_parts else "[-- ] Zip-fil var tom"

    except zipfile.BadZipFile:
        return "[XX ] Ogiltig zip-fil (GitHub API kan kräva utökade permissions)"
    except Exception as e:
        return f"[XX ] Loggnedladdning misslyckades: {e}"


def extract_error_lines(log_text: str, max_lines: int = 100) -> list[str]:
    """
    Filtrera ut relevanta felrader från ett CI-loggblock.
    Letar efter ERROR, FAILED, Traceback, Exception, assert.
    """
    if not log_text:
        return []

    error_keywords = [
        "error:", "Error:", "ERROR", "FAILED", "FAIL:",
        "Traceback", "Exception:", "AssertionError",
        "ImportError", "ModuleNotFoundError", "AttributeError",
        "KeyError:", "ValueError:", "TypeError:",
        "exit code 1", "exit 1", "returncode=1",
        "CRITICAL", "fatal:", "Fatal:",
    ]
    results = []
    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        if any(kw in line for kw in error_keywords):
            # Ta med 2 rader kontext
            start = max(0, i - 1)
            end   = min(len(lines), i + 3)
            block = "\n".join(lines[start:end])
            if block not in results:
                results.append(block)
        if len(results) >= max_lines:
            break
    return results


def get_job_log_annotations(run_id: int) -> list[dict]:
    """
    Hämta check-annotations för en körning (GitHub visar dessa som inline errors).
    Mer precis än rå-loggar — pekar direkt på fil:rad.
    """
    # Hämta check-runs för denna workflow-run
    data = _get(f"actions/runs/{run_id}/check-suite", {})
    check_suite_id = (data or {}).get("check_suite_id")
    if not check_suite_id:
        return []

    checks = _get(f"check-suites/{check_suite_id}/check-runs") or {}
    annotations = []
    for check in (checks or {}).get("check_runs", []):
        check_id = check.get("id")
        if check_id:
            ann_data = _get(f"check-runs/{check_id}/annotations") or []
            for ann in (ann_data if isinstance(ann_data, list) else []):
                annotations.append({
                    "check":    check.get("name", "?"),
                    "file":     ann.get("path", "?"),
                    "line":     ann.get("start_line"),
                    "level":    ann.get("annotation_level", "?"),
                    "message":  ann.get("message", "?"),
                    "title":    ann.get("title", ""),
                })
    return annotations


# ── Rapport ────────────────────────────────────────────────────────────────────

def build_failure_report(run: dict, include_logs: bool = True) -> dict:
    """Bygg en strukturerad felrapport för en körning."""
    run_id   = run["id"]
    wf_name  = run.get("name", "?")
    branch   = run.get("head_branch", "?")
    commit   = run.get("head_sha", "?")[:8]
    msg      = (run.get("head_commit") or {}).get("message", "").split("\n")[0][:80]
    started  = run.get("run_started_at", "")
    updated  = run.get("updated_at", "")
    url      = f"https://github.com/{GITHUB_REPO}/actions/runs/{run_id}"

    # Jobs
    jobs = get_run_jobs(run_id)
    failed_jobs = [j for j in jobs if j.get("conclusion") == "failure"]
    job_summary = []
    for j in jobs:
        steps_failed = [
            s["name"] for s in j.get("steps", [])
            if s.get("conclusion") == "failure"
        ]
        job_summary.append({
            "name":          j.get("name"),
            "conclusion":    j.get("conclusion"),
            "failed_steps":  steps_failed,
        })

    report = {
        "run_id":       run_id,
        "workflow":     wf_name,
        "branch":       branch,
        "commit":       commit,
        "commit_msg":   msg,
        "started":      started,
        "updated":      updated,
        "url":          url,
        "jobs":         job_summary,
        "failed_jobs":  [j["name"] for j in failed_jobs],
        "error_lines":  [],
        "annotations":  [],
    }

    # Annotations (fil:rad-pekning)
    try:
        report["annotations"] = get_job_log_annotations(run_id)
    except Exception:
        pass

    # Rå-loggar (om requested)
    if include_logs:
        log_text = download_run_logs(run_id)
        if log_text and not log_text.startswith("[XX ]"):
            report["error_lines"] = extract_error_lines(log_text)
            report["log_snippet"] = log_text[-5000:]  # Sista 5000 chars
        elif log_text:
            report["log_error"] = log_text

    return report


def print_report(report: dict) -> None:
    """Skriv ut felrapporten läsbart."""
    print("=" * 70)
    print(f"  CI-felrapport: {report['workflow']}")
    print(f"  Run ID: {report['run_id']}")
    print(f"  Branch: {report['branch']} @ {report['commit']}")
    print(f"  Commit: {report['commit_msg']}")
    print(f"  Startat: {report['started'][:16] if report['started'] else '?'}")
    print(f"  URL: {report['url']}")
    print("=" * 70)

    if report.get("failed_jobs"):
        print(f"\n  [XX ] Misslyckade jobs: {', '.join(report['failed_jobs'])}")

    if report.get("jobs"):
        print("\n-- Jobs ---------------------------------------------------------------")
        for j in report["jobs"]:
            icon = "[OK ]" if j["conclusion"] == "success" else "[XX ]"
            steps = f" (steg: {', '.join(j['failed_steps'][:3])})" if j.get("failed_steps") else ""
            print(f"  {icon} {j['name']}{steps}")

    if report.get("annotations"):
        print("\n-- Annotationer (fil:rad) ---------------------------------------------")
        for ann in report["annotations"][:20]:
            lvl  = ann.get("level", "?").upper()
            file = ann.get("file", "?")
            line = ann.get("line", "?")
            msg  = ann.get("message", "?")[:120]
            print(f"  [{lvl}] {file}:{line} — {msg}")

    if report.get("error_lines"):
        print("\n-- Felrader (filtrerade från loggar) ----------------------------------")
        for block in report["error_lines"][:30]:
            print()
            for line in block.splitlines():
                print(f"  {line}")
    elif report.get("log_error"):
        print(f"\n  [!! ] {report['log_error']}")
    else:
        print("\n  [-- ] Inga logg-felrader extraherade")

    print()
    print("=" * 70)


def save_report(report: dict) -> Path:
    """Spara rapporten till data/ci_reports/."""
    CI_REPORTS.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    wf  = report["workflow"].replace(" ", "_").replace("/", "_")[:30]

    json_path = CI_REPORTS / f"{ts}_{wf}_{report['run_id']}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Uppdatera "latest_failure.json" alltid
    latest_json = CI_REPORTS / "latest_failure.json"
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Spara text-version
    latest_txt = CI_REPORTS / "latest_failure.txt"
    import io as _io
    old_stdout = sys.stdout
    sys.stdout = buf = _io.StringIO()
    print_report(report)
    sys.stdout = old_stdout
    latest_txt.write_text(buf.getvalue(), encoding="utf-8")

    return json_path


# ── main() ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ladda ned och parsa GitHub Actions CI-loggar",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--run-id",   "-r", type=int,
                        help="Specifik run ID att hämta loggar för")
    parser.add_argument("--workflow", "-w",
                        help="Filtrera på workflow-namn (t.ex. daily_scan)")
    parser.add_argument("--all",      "-a", action="store_true",
                        help="Visa alla senaste körningar (inte bara misslyckade)")
    parser.add_argument("--no-logs",        action="store_true",
                        help="Hoppa över loggnedladdning (snabbare)")
    parser.add_argument("--save",     "-s", action="store_true",
                        help="Spara rapport till data/ci_reports/")
    parser.add_argument("--json",           action="store_true",
                        help="Skriv ut JSON-rapport")
    args = parser.parse_args()

    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("[XX ] GITHUB_TOKEN och GITHUB_REPO måste sättas i .env")
        print("       GITHUB_REPO=owner/repo")
        return 1

    # Hitta körning att analysera
    if args.run_id:
        data = _get(f"actions/runs/{args.run_id}")
        run  = data if isinstance(data, dict) and "id" in data else None
        if not run:
            print(f"[XX ] Körning {args.run_id} hittades inte")
            return 1
    else:
        params = {"per_page": 5}
        if not args.all:
            params["conclusion"] = "failure"
        if args.workflow:
            wf = args.workflow if args.workflow.endswith(".yml") else f"{args.workflow}.yml"
            data = _get(f"actions/workflows/{wf}/runs", params)
        else:
            data = _get("actions/runs", params)
        runs = (data or {}).get("workflow_runs", [])

        if args.all:
            # Visa alla
            print("=" * 70)
            print(f"  Senaste GitHub Actions-körningar — {GITHUB_REPO}")
            print("=" * 70)
            for r in runs:
                icon = "[OK ]" if r.get("conclusion") == "success" else "[XX ]"
                name = r.get("name", "?")[:35]
                conc = r.get("conclusion") or r.get("status", "?")
                msg  = (r.get("head_commit") or {}).get("message", "").split("\n")[0][:50]
                print(f"  {icon} {name:<35} {conc:<15} {r['id']}")
                print(f"       {msg}")
            return 0

        if not runs:
            print("[OK ] Inga misslyckade körningar hittades — systemet verkar friskt!")
            return 0
        run = runs[0]

    # Bygg felrapport
    print(f"\n  Analyserar körning {run['id']} — {run.get('name', '?')}...")
    print("  (Laddar ned loggar från GitHub API...)")
    report = build_failure_report(run, include_logs=not args.no_logs)

    # Utskrift
    if args.json:
        # Ta bort stora log_snippet för JSON-output
        r = {k: v for k, v in report.items() if k != "log_snippet"}
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    # Spara
    if args.save:
        path = save_report(report)
        print(f"  [OK ] Rapport sparad: {path}")
        print(f"  [OK ] Snabblänk: {CI_REPORTS / 'latest_failure.txt'}")

    return 0 if not report.get("failed_jobs") else 1


if __name__ == "__main__":
    sys.exit(main())
