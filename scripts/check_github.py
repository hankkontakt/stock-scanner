"""
scripts/check_github.py
========================
GitHub Actions workflow-statuskontroll i realtid.

Anvaendning:
  python scripts/check_github.py                    # Visa alla senaste workflow-koerningar
  python scripts/check_github.py --workflow daily_scan  # Filtrera ett specifikt workflow
  python scripts/check_github.py --watch            # Loopmode var 30s
  python scripts/check_github.py --json             # JSON-output
  python scripts/check_github.py --failures         # Visa bara misslyckade

Krav: GITHUB_TOKEN + GITHUB_REPO i .env
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Lagg till projekt-root i path
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

# ── Konfiguration ──────────────────────────────────────────────────────────────

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "")  # format: "owner/repo"

# Status-ikoner (ASCII-saekra)
_ICONS = {
    "completed_success":   "[OK ]",
    "completed_failure":   "[XX ]",
    "completed_cancelled": "[-- ]",
    "in_progress":         "[>> ]",
    "queued":              "[.. ]",
    "waiting":             "[.. ]",
    "unknown":             "[?? ]",
}

# Koeningsstatus-foerklaringar
_CONCLUSION_MAP = {
    "success":   "OK",
    "failure":   "MISSLYCKAD",
    "cancelled": "AVBRUTEN",
    "skipped":   "HOPPAD",
    "timed_out": "TIMEOUT",
    "action_required": "AATGAERD KRAEVS",
    None: "PAGAAR",
}


# ── Hjaeelpfunktioner ──────────────────────────────────────────────────────────

def _api_get(path: str, params: dict | None = None) -> dict | list | None:
    """GET mot GitHub API med autentisering."""
    if not HAS_REQUESTS:
        print("[XX ] requests ej installerat: pip install requests")
        return None
    if not GITHUB_TOKEN:
        print("[!! ] GITHUB_TOKEN saknas i .env")
        return None
    if not GITHUB_REPO:
        print("[!! ] GITHUB_REPO saknas i .env (format: owner/repo)")
        return None

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"https://api.github.com/repos/{GITHUB_REPO}/{path.lstrip('/')}"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        print(f"[XX ] GitHub API HTTP-fel: {e}")
        return None
    except requests.exceptions.ConnectionError:
        print("[XX ] Ingen nätverksanslutning till GitHub API")
        return None
    except requests.exceptions.Timeout:
        print("[XX ] GitHub API timeout (>15s)")
        return None
    except Exception as e:
        print(f"[XX ] GitHub API oväntat fel: {e}")
        return None


def _format_duration(seconds: int) -> str:
    """Formatera sekunder till HH:MM:SS."""
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _time_ago(iso_str: str | None) -> str:
    """Maenniskalaesbar tid sedan ISO-tidsstampel."""
    if not iso_str:
        return "okänd tid"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return f"{diff}s sedan"
        if diff < 3600:
            return f"{diff // 60}min sedan"
        if diff < 86400:
            return f"{diff // 3600}h sedan"
        return f"{diff // 86400}d sedan"
    except Exception:
        return iso_str[:10] if iso_str else "?"


def _get_icon(run: dict) -> str:
    status     = run.get("status", "unknown")
    conclusion = run.get("conclusion")
    if status == "completed":
        key = f"completed_{conclusion or 'unknown'}"
    else:
        key = status
    return _ICONS.get(key, _ICONS["unknown"])


# ── Haemtningsfunktioner ───────────────────────────────────────────────────────

def get_workflow_runs(
    workflow_name: str | None = None,
    limit: int = 20,
    branch: str | None = None,
    only_failures: bool = False,
) -> list[dict]:
    """Haemta senaste workflow-koerningar."""
    params: dict[str, Any] = {"per_page": min(limit, 100)}
    if branch:
        params["branch"] = branch

    if workflow_name:
        # Normalisera workflow-namn (lagg till .yml om saknas)
        wf = workflow_name if workflow_name.endswith(".yml") else f"{workflow_name}.yml"
        data = _api_get(f"actions/workflows/{wf}/runs", params)
        runs = (data or {}).get("workflow_runs", [])
    else:
        data = _api_get("actions/runs", params)
        runs = (data or {}).get("workflow_runs", [])

    if only_failures:
        runs = [r for r in runs if r.get("conclusion") == "failure"]

    return runs[:limit]


def get_workflow_list() -> list[dict]:
    """Lista alla registrerade workflows."""
    data = _api_get("actions/workflows")
    return (data or {}).get("workflows", [])


def get_run_jobs(run_id: int) -> list[dict]:
    """Haemta jobs foer en specifik workflow-koerning."""
    data = _api_get(f"actions/runs/{run_id}/jobs")
    return (data or {}).get("jobs", [])


def get_repo_info() -> dict:
    """Haemta basinformation om repot."""
    return _api_get("") or {}


# ── Utskrift ───────────────────────────────────────────────────────────────────

def print_run(run: dict, show_jobs: bool = False) -> None:
    """Skriv ut en workflow-koerning."""
    icon       = _get_icon(run)
    name       = run.get("name", "?")[:35]
    status     = run.get("status", "?")
    conclusion = _CONCLUSION_MAP.get(run.get("conclusion"), run.get("conclusion") or "PAGAAR")
    branch     = run.get("head_branch", "?")
    commit_msg = (run.get("head_commit") or {}).get("message", "")
    commit_msg = commit_msg.split("\n")[0][:50]
    created_at = run.get("created_at")
    run_id     = run.get("id")

    # Beraekna koerningstid om tillgaenglig
    duration_str = ""
    if run.get("run_started_at") and run.get("updated_at") and status == "completed":
        try:
            start = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
            end   = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
            secs  = int((end - start).total_seconds())
            duration_str = f" ({_format_duration(secs)})"
        except Exception:
            pass

    print(f"  {icon} {name:<35} {conclusion:<18} {_time_ago(created_at)}{duration_str}")
    print(f"       Branch: {branch} | Commit: {commit_msg}")
    if run_id:
        print(f"       URL: https://github.com/{GITHUB_REPO}/actions/runs/{run_id}")

    if show_jobs:
        jobs = get_run_jobs(run_id)
        for job in jobs:
            j_icon = "[OK ]" if job.get("conclusion") == "success" else (
                     "[XX ]" if job.get("conclusion") == "failure" else "[>> ]")
            j_name = job.get("name", "?")[:40]
            j_conc = job.get("conclusion") or job.get("status", "?")
            print(f"         {j_icon} {j_name} -> {j_conc}")


def print_report(
    workflow_name: str | None = None,
    limit: int = 10,
    show_jobs: bool = False,
    only_failures: bool = False,
    branch: str | None = None,
) -> dict:
    """Huvud-rapportfunktion — returnerar sammanfattning."""
    print("=" * 70)
    print(f"  GitHub Actions Status — {GITHUB_REPO}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    if not GITHUB_TOKEN or not GITHUB_REPO:
        print()
        print("[XX ] Konfigurationsfel:")
        if not GITHUB_TOKEN:
            print("      GITHUB_TOKEN saknas i .env")
        if not GITHUB_REPO:
            print("      GITHUB_REPO saknas i .env (t.ex. 'owner/repo')")
        print()
        return {"ok": False, "error": "missing_config"}

    # Repo-info
    repo = get_repo_info()
    if repo:
        stars     = repo.get("stargazers_count", 0)
        open_issues = repo.get("open_issues_count", 0)
        default_branch = repo.get("default_branch", "main")
        print(f"\n  Repo: {GITHUB_REPO} | Stars: {stars} | "
              f"Issues: {open_issues} | Standardbranch: {default_branch}")

    # Workflow-lista
    if not workflow_name:
        print("\n-- Registrerade Workflows -----------------------------------------------")
        wf_list = get_workflow_list()
        for wf in wf_list:
            state = "[OK ]" if wf.get("state") == "active" else "[-- ]"
            print(f"  {state} {wf.get('name', '?'):<40} ({wf.get('path', '?')})")

    # Koerningar
    title = f"Senaste {limit} koerningar"
    if workflow_name:
        title += f" [{workflow_name}]"
    if only_failures:
        title += " (bara misslyckade)"
    print(f"\n-- {title} -----------------------------------------------")

    runs = get_workflow_runs(
        workflow_name=workflow_name,
        limit=limit,
        branch=branch,
        only_failures=only_failures,
    )

    if not runs:
        print("  [-- ] Inga koerningar hittades")
        return {"ok": True, "runs": 0, "failures": 0, "in_progress": 0}

    ok_count       = 0
    fail_count     = 0
    progress_count = 0
    for run in runs:
        print()
        print_run(run, show_jobs=show_jobs)
        conc = run.get("conclusion")
        stat = run.get("status")
        if conc == "success":
            ok_count += 1
        elif conc == "failure":
            fail_count += 1
        elif stat in ("in_progress", "queued", "waiting"):
            progress_count += 1

    # Sammanfattning
    print()
    print("=" * 70)
    print(f"  SUMMERING: {ok_count} OK  {fail_count} FEL  {progress_count} PAGAAR  "
          f"(av {len(runs)} visade)")
    print("=" * 70)

    return {
        "ok":         fail_count == 0,
        "runs":       len(runs),
        "ok_count":   ok_count,
        "failures":   fail_count,
        "in_progress": progress_count,
    }


# ── Watch-mode ─────────────────────────────────────────────────────────────────

def watch_mode(interval: int = 30, **kwargs) -> None:
    """Uppdatera workflow-status var N sekunder (Ctrl+C foer att avsluta)."""
    print(f"[>> ] Watch-mode aktiv — uppdaterar var {interval}s (Ctrl+C foer stopp)")
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            print_report(**kwargs)
            print(f"\n  [Naesta uppdatering om {interval}s — Ctrl+C foer stopp]")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[-- ] Watch-mode avslutat")


# ── main() ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kontrollera GitHub Actions workflow-status",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--workflow", "-w", help="Filtrera ett specifikt workflow (t.ex. daily_scan)")
    parser.add_argument("--limit",    "-n", type=int, default=10, help="Max antal koerningar att visa (default 10)")
    parser.add_argument("--branch",   "-b", help="Filtrera pa branch (t.ex. main)")
    parser.add_argument("--failures", "-f", action="store_true", help="Visa bara misslyckade koerningar")
    parser.add_argument("--jobs",     "-j", action="store_true", help="Visa jobs foer varje koerning")
    parser.add_argument("--watch",    "-W", action="store_true", help="Loop-mode, uppdatera var 30s")
    parser.add_argument("--interval", "-i", type=int, default=30, help="Uppdateringsintervall i sekunder (--watch)")
    parser.add_argument("--json",           action="store_true", help="Skriv ut JSON-rapport")
    args = parser.parse_args()

    kwargs = dict(
        workflow_name  = args.workflow,
        limit          = args.limit,
        branch         = args.branch,
        only_failures  = args.failures,
        show_jobs      = args.jobs,
    )

    if args.watch:
        watch_mode(interval=args.interval, **kwargs)
        return 0

    result = print_report(**kwargs)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
