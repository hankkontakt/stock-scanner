"""
scripts/ai_debug.py
====================
AI-briefing: ett kommando som berättar hela nuläget för systemet.

DETTA ÄR DET FÖRSTA SCRIPT JAG (Claude) KÖR NÄR JAG BÖRJAR EN NY SESSION.
Samlar information från alla tillgängliga källor och presenterar en
strukturerad "briefing" utan att behöva köra systemet lokalt.

Källor:
  - data/health/health_YYYY-MM-DD.json     (CI commitar varje dag)
  - data/ci_reports/latest_failure.json    (fetch_ci_logs.py)
  - data/diagnose_history.jsonl            (diagnose.py --save)
  - data/metrics/                          (pipeline-körningsmätningar)
  - data/scan_log.json                     (pipeline-historik)
  - data/fetch_errors.json                 (datahämtningsfel)
  - data/streamlit_errors.jsonl            (Streamlit-fel från appen)
  - GitHub API                             (om GITHUB_TOKEN konfigurerat)
  - HTTP-koll                              (om STREAMLIT_URL konfigurerat)

Användning:
  python scripts/ai_debug.py              # Full briefing (30s)
  python scripts/ai_debug.py --quick      # Bara lokala filer (3s)
  python scripts/ai_debug.py --github     # Inkludera GitHub Actions-status
  python scripts/ai_debug.py --json       # JSON-output för programmatisk användning
  python scripts/ai_debug.py --since 24h  # Filtrera fel från senaste 24h
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

DATA_DIR    = ROOT / "data"
CI_REPORTS  = DATA_DIR / "ci_reports"
HEALTH_DIR  = DATA_DIR / "health"
METRICS_DIR = DATA_DIR / "metrics"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO",  "")
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "")


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ago(hours: float) -> datetime:
    return _now_utc() - timedelta(hours=hours)


def _read_json(path: Path) -> dict | list | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_jsonl(path: Path, last_n: int = 20) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return entries[-last_n:]


def _section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def _ok(label: str, detail: str = "") -> None:
    print(f"  [OK ] {label:<40} {detail}")


def _warn(label: str, detail: str = "") -> None:
    print(f"  [!! ] {label:<40} {detail}")


def _err(label: str, detail: str = "") -> None:
    print(f"  [XX ] {label:<40} {detail}")


def _skip(label: str, detail: str = "") -> None:
    print(f"  [-- ] {label:<40} {detail}")


def _time_ago(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = int((_now_utc() - dt).total_seconds())
        if diff < 60:
            return f"{diff}s sedan"
        if diff < 3600:
            return f"{diff // 60}min sedan"
        if diff < 86400:
            return f"{diff // 3600}h sedan"
        return f"{diff // 86400}d sedan"
    except Exception:
        return iso_str[:16] if iso_str else "?"


# ── Informationskällor ────────────────────────────────────────────────────────

def section_pipeline_health(report: dict) -> None:
    """Läs data/health/ och data/scan_log.json."""
    _section("1. Pipeline & System-hälsa")

    # Senaste health-fil
    health_files = sorted(HEALTH_DIR.glob("health_*.json"), reverse=True)
    if health_files:
        health = _read_json(health_files[0])
        if health:
            status = health.get("status", "?")
            ok_fn  = _ok if status == "healthy" else _warn
            ok_fn("System-status", f"{status} ({health_files[0].name})")

            # Data-färskhet
            freshness = health.get("data_freshness", {})
            age_h     = freshness.get("age_hours", 999)
            scan_file = freshness.get("file", "?")
            stale     = freshness.get("stale", True)
            if stale or age_h > 24:
                _err("Scan-data", f"{age_h:.1f}h gammal — {scan_file}")
            elif age_h > 12:
                _warn("Scan-data", f"{age_h:.1f}h gammal — {scan_file}")
            else:
                _ok("Scan-data", f"{age_h:.1f}h gammal — {scan_file}")

            # Senaste pipeline-körning
            last_run = health.get("last_pipeline_run", {})
            if last_run:
                mode      = last_run.get("mode", "?")
                run_status = last_run.get("status", "?")
                duration  = last_run.get("duration", 0)
                ts        = last_run.get("timestamp", "")
                icon_fn   = _ok if run_status == "OK" else _err
                icon_fn("Senaste pipeline", f"{mode} | {run_status} | {duration:.0f}s | {_time_ago(ts)}")

            # ML-modeller
            model_st = health.get("model_status", {})
            days_trained = model_st.get("days_since_training", 999)
            if days_trained > 30:
                _warn("ML-modell", f"{days_trained} dagar sedan träning")
            else:
                _ok("ML-modell", f"Tränad {days_trained} dagar sedan")

            # Degraded components
            degraded = health.get("degraded_components", [])
            if degraded:
                _err("Degraderade komponenter", ", ".join(degraded))

            # Recent errors från health
            recent_errors = health.get("recent_errors", [])
            if recent_errors:
                _warn("Senaste fel (health)", f"{len(recent_errors)} st")
                for e in recent_errors[:3]:
                    print(f"        {str(e)[:80]}")
        else:
            _warn("Health-fil", f"Kunde inte parsa {health_files[0]}")
    else:
        _warn("Health-fil", "Ingen health_*.json hittad i data/health/")

    # scan_log.json
    scan_log = _read_json(DATA_DIR / "scan_log.json")
    if scan_log and isinstance(scan_log, list):
        recent = sorted(scan_log, key=lambda x: x.get("timestamp", ""), reverse=True)[:3]
        print("\n  Senaste scan-körningar (scan_log.json):")
        for entry in recent:
            ts    = entry.get("timestamp", "")
            # Stödjer scan_type eller mode
            mode  = entry.get("scan_type", entry.get("mode", "?"))
            ok_c  = entry.get("status", entry.get("ok", "OK")) in ("OK", True, "success")
            icon  = "[OK ]" if ok_c else "[XX ]"
            det   = entry.get("details", {}) or {}
            elapsed = det.get("elapsed_seconds", "")
            elapsed_str = f" ({elapsed:.0f}s)" if elapsed else ""
            n_tickers = det.get("n_tickers", entry.get("n_tickers", "?"))
            print(f"    {icon} {_time_ago(ts):<15} {mode:<15} {elapsed_str}")
    elif isinstance(scan_log, dict):
        for e in list(scan_log.values())[-3:]:
            ts = e.get("timestamp", e.get("ts", ""))
            print(f"    [??] {ts[:16]}")

    report["pipeline_health"] = {
        "status": (health or {}).get("status", "unknown") if health_files else "no_file",
        "scan_age_h": age_h if health_files and health else None,
    }


def section_ci_failures(report: dict, since_hours: float = 48) -> None:
    """Läs data/ci_reports/ för senaste CI-fel."""
    _section("2. Senaste CI-fel")

    if not CI_REPORTS.exists():
        _skip("CI-rapporter", "data/ci_reports/ saknas — kör fetch_ci_logs.py --save")
        report["ci_failures"] = []
        return

    # Senaste failure-fil
    latest = CI_REPORTS / "latest_failure.json"
    if latest.exists():
        failure = _read_json(latest)
        if failure:
            run_id  = failure.get("run_id", "?")
            wf      = failure.get("workflow", "?")
            started = failure.get("started", "")
            url     = failure.get("url", "")
            failed_jobs = failure.get("failed_jobs", [])
            _err("Senaste misslyckade körning", f"{wf} (run {run_id})")
            print(f"       {_time_ago(started)} | {url}")
            if failed_jobs:
                print(f"       Misslyckade jobs: {', '.join(failed_jobs)}")
            anns = failure.get("annotations", [])
            if anns:
                print("\n  Annotationer (fil:rad):")
                for ann in anns[:10]:
                    f_name = ann.get("file", "?")
                    line   = ann.get("line", "?")
                    msg    = ann.get("message", "?")[:100]
                    print(f"    [XX ] {f_name}:{line} — {msg}")
            errors = failure.get("error_lines", [])
            if errors:
                print(f"\n  Felrader ({len(errors)} block):")
                for block in errors[:5]:
                    for line in block.splitlines()[:3]:
                        print(f"    {line[:100]}")
                    print()
        report["ci_failures"] = [failure]
    else:
        _skip("CI-rapporter",
              "Ingen latest_failure.json — kör: python scripts/fetch_ci_logs.py --save")
        report["ci_failures"] = []

    # Räkna alla rapporter
    all_reports = sorted(CI_REPORTS.glob("*.json"))
    real_reports = [p for p in all_reports if p.name not in ("latest_failure.json",)]
    if real_reports:
        print(f"\n  {len(real_reports)} historiska CI-rapporter i data/ci_reports/")
        for p in real_reports[-3:]:
            print(f"    {p.name}")


def section_streamlit_errors(report: dict) -> None:
    """Läs data/streamlit_errors.jsonl för Streamlit-fel."""
    _section("3. Streamlit-fel (från appen)")

    errors_file = DATA_DIR / "streamlit_errors.jsonl"
    if not errors_file.exists():
        _skip("streamlit_errors.jsonl",
              "Filen finns ej — felet-logging inte aktiverad i appen ännu")
        report["streamlit_errors"] = []
        return

    entries = _read_jsonl(errors_file, last_n=20)
    if not entries:
        _ok("Streamlit-fel", "Inga fel loggade")
        report["streamlit_errors"] = []
        return

    # Filtrera på senaste 48h
    recent = []
    for e in entries:
        ts = e.get("ts", e.get("timestamp", ""))
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if (_now_utc() - dt).total_seconds() < 48 * 3600:
                recent.append(e)
        except Exception:
            recent.append(e)

    if not recent:
        _ok("Streamlit-fel", "Inga fel senaste 48h")
    else:
        _err("Streamlit-fel senaste 48h", f"{len(recent)} st")
        for e in recent[-5:]:
            ts    = e.get("ts", e.get("timestamp", ""))[:16]
            page  = e.get("page", "?")
            error = str(e.get("error", "?"))[:100]
            print(f"    [{ts}] {page}: {error}")

    report["streamlit_errors"] = recent


def section_pipeline_metrics(report: dict) -> None:
    """Läs data/metrics/ för körningstider och felfrekvens."""
    _section("4. Pipeline-metrics (senaste 5 körningar)")

    if not METRICS_DIR.exists():
        _skip("Metrics", "data/metrics/ saknas")
        report["metrics"] = []
        return

    metric_files = sorted(METRICS_DIR.glob("metrics_*.json"), reverse=True)[:5]
    if not metric_files:
        _skip("Metrics", "Inga metrics-filer hittade")
        report["metrics"] = []
        return

    metrics_list = []
    for path in metric_files:
        m = _read_json(path)
        if m:
            metrics_list.append(m)

    if not metrics_list:
        report["metrics"] = []
        return

    # Metrics-filernas struktur: pipeline_duration_seconds, tickers_fetched_total etc.
    for i, (path, m) in enumerate(zip(metric_files, metrics_list)):
        ts      = (m.get("exported_at") or m.get("latest_scan_timestamp") or "")[:16].replace("T", " ")
        # pipeline_duration_seconds: {mode: [seconds]} eller []
        dur_raw = m.get("pipeline_duration_seconds", {})
        if isinstance(dur_raw, dict):
            all_durs = [v[-1] for v in dur_raw.values() if isinstance(v, list) and v]
            dur      = all_durs[0] if all_durs else 0
            mode     = list(dur_raw.keys())[0][:11] if dur_raw else "?"
        else:
            dur, mode = 0, "?"
        tickers     = m.get("tickers_fetched_total", "?")
        fail_pipeline = m.get("pipeline_failure_total", 0)
        # Om duration > 0 körde pipelines — betrakta som OK om inga explicita fel
        ran = dur > 0 or tickers not in ("?", 0, "0")
        icon = "[OK]" if (ran and fail_pipeline == 0) else ("[--]" if not ran else "[XX]")
        status_str = "OK" if (ran and fail_pipeline == 0) else ("-" if not ran else "FEL")
        print(f"  {icon} {ts:<22} {mode:<12} {status_str:<10} {dur:<8.0f} {tickers}")

    # Sammanfattning
    all_dur = []
    for m in metrics_list:
        dur_raw = m.get("pipeline_duration_seconds", {})
        if isinstance(dur_raw, dict):
            for v in dur_raw.values():
                if isinstance(v, list) and v:
                    all_dur.extend(v)
    if all_dur:
        _ok("Pipeline-körningstid", f"snitt {sum(all_dur)/len(all_dur):.0f}s, max {max(all_dur):.0f}s")

    report["metrics"] = [{"file": p.name} for p in metric_files]


def section_fetch_errors(report: dict, max_show: int = 10) -> None:
    """Läs data/fetch_errors.json för datahämtningsfel."""
    _section("5. Datahämtningsfel (fetch_errors.json)")

    fetch_err = _read_json(DATA_DIR / "fetch_errors.json")
    if fetch_err is None:
        _skip("fetch_errors.json", "Filen saknas")
        report["fetch_errors"] = []
        return

    # fetch_errors.json är en lista med batch-sammanfattningar per körning
    # Struktur: [{timestamp, total, n_ok, n_failed, n_rate_limited, failed_tickers, ...}, ...]
    errors = fetch_err if isinstance(fetch_err, list) else list(fetch_err.values())
    errors = [e for e in errors if isinstance(e, dict)]

    if not errors:
        _ok("Datahämtningsfel", "Inga fel registrerade")
        report["fetch_errors"] = []
        return

    # Sortera på senaste
    try:
        errors = sorted(errors, key=lambda x: x.get("timestamp", x.get("ts", "")), reverse=True)
    except Exception:
        pass

    latest = errors[0]
    ts_latest = latest.get("timestamp", "")[:16]
    n_failed  = latest.get("n_failed", 0)
    n_rl      = latest.get("n_rate_limited", 0)
    n_total   = latest.get("total", "?")

    if n_failed > 20:
        _err("Datahämtning (senaste batch)",
             f"{n_failed} FAILED + {n_rl} rate-limited av {n_total} ({ts_latest})")
    elif n_failed > 0 or n_rl > 0:
        _warn("Datahämtning (senaste batch)",
              f"{n_failed} FAILED + {n_rl} rate-limited av {n_total} ({ts_latest})")
    else:
        _ok("Datahämtning (senaste batch)", f"Alla {n_total} OK ({ts_latest})")

    # Sammanfattning över alla körningar
    total_failed  = sum(e.get("n_failed", 0) for e in errors)
    total_rl      = sum(e.get("n_rate_limited", 0) for e in errors)
    print(f"\n  Totalt {len(errors)} batch-körningar: {total_failed} FAILED, {total_rl} rate-limited")

    # Visa vanligaste misslyckade tickers
    ticker_fails: dict[str, int] = {}
    for e in errors:
        for ft in e.get("failed_tickers", []):
            t = ft.get("ticker", "?") if isinstance(ft, dict) else str(ft)
            ticker_fails[t] = ticker_fails.get(t, 0) + 1
    if ticker_fails:
        top = sorted(ticker_fails.items(), key=lambda x: -x[1])[:8]
        print("\n  Tickers som oftast misslyckas:")
        for ticker, count in top:
            print(f"    [{count:3d}x] {ticker}")

    report["fetch_errors_count"] = total_failed + total_rl
    report["fetch_errors_sample"] = [latest]


def section_diagnose_history(report: dict) -> None:
    """Läs data/diagnose_history.jsonl."""
    _section("6. Diagnos-historik")

    entries = _read_jsonl(DATA_DIR / "diagnose_history.jsonl", last_n=10)
    if not entries:
        _skip("diagnose_history.jsonl",
              "Ingen historik — kör: python scripts/diagnose.py --save")
        report["diagnose_history"] = []
        return

    latest = entries[-1]
    ts      = (latest.get("ts") or "")[:16].replace("T", " ")
    healthy = latest.get("healthy", True)
    ok_n    = latest.get("ok", 0)
    warn_n  = latest.get("warn", 0)
    err_n   = latest.get("error", 0)

    icon_fn = _ok if healthy else _err
    icon_fn("Senaste diagnos", f"{ts} | {ok_n} OK / {warn_n} WARN / {err_n} FEL")

    if not healthy:
        _warn("OBS", "Diagnosen rapporterade kritiska fel — kör diagnose.py --section för detaljer")

    print(f"\n  Diagnoshistorik ({len(entries)} körningar):")
    for e in reversed(entries[-5:]):
        e_ts   = (e.get("ts") or "")[:16].replace("T", " ")
        e_ok   = e.get("healthy", True)
        e_icon = "[OK]" if e_ok else "[XX]"
        print(f"    {e_icon} {e_ts} | OK:{e.get('ok',0)} WARN:{e.get('warn',0)} FEL:{e.get('error',0)}")

    report["diagnose_history"] = entries


def section_github_status(report: dict) -> None:
    """Fråga GitHub API om senaste workflow-status."""
    _section("7. GitHub Actions Status (live API)")

    if not GITHUB_TOKEN or not GITHUB_REPO:
        _skip("GitHub API", "GITHUB_TOKEN / GITHUB_REPO saknas i .env")
        report["github"] = {"skipped": True}
        return

    try:
        import requests
    except ImportError:
        _skip("GitHub API", "requests-biblioteket saknas")
        return

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    try:
        # Senaste 10 körningar
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
            headers=headers,
            params={"per_page": 10},
            timeout=10,
        )
        if r.status_code != 200:
            _err("GitHub API", f"HTTP {r.status_code}")
            return

        runs = r.json().get("workflow_runs", [])
        failures = [r for r in runs if r.get("conclusion") == "failure"]
        in_progress = [r for r in runs if r.get("status") in ("in_progress", "queued")]

        if in_progress:
            _warn("Pågående körningar", f"{len(in_progress)} körningar pågår just nu")
            for run in in_progress:
                print(f"    [>>] {run.get('name','?')} — {run.get('status','?')}")

        if failures:
            _err("Misslyckade körningar (senaste 10)", f"{len(failures)} st")
            for run in failures[:3]:
                name    = run.get("name", "?")
                run_id  = run.get("id")
                started = run.get("run_started_at", "")
                print(f"    [XX] {name} (run {run_id}) — {_time_ago(started)}")
                print(f"         https://github.com/{GITHUB_REPO}/actions/runs/{run_id}")
        else:
            _ok("GitHub Actions", f"Inga fel i senaste {len(runs)} körningar")

        # Visa senaste av varje workflow
        seen_workflows = set()
        print("\n  Senaste körning per workflow:")
        for run in runs:
            wf_name = run.get("name", "?")
            if wf_name not in seen_workflows:
                seen_workflows.add(wf_name)
                conc    = run.get("conclusion") or run.get("status", "?")
                started = run.get("run_started_at", "")
                icon    = "[OK]" if conc == "success" else ("[XX]" if conc == "failure" else "[>>]")
                print(f"    {icon} {wf_name:<35} {conc:<15} {_time_ago(started)}")

        report["github"] = {
            "failures": len(failures),
            "in_progress": len(in_progress),
            "total_checked": len(runs),
        }

    except Exception as e:
        _err("GitHub API", f"Oväntat fel: {e}")


def section_streamlit_http(report: dict) -> None:
    """Kolla om Streamlit Cloud svarar."""
    _section("8. Streamlit Cloud HTTP-hälsa")

    if not STREAMLIT_URL:
        _skip("STREAMLIT_URL", "Sätt STREAMLIT_URL i .env för att aktivera")
        report["streamlit_http"] = {"skipped": True}
        return

    try:
        import urllib.request
        t0 = time.perf_counter()
        with urllib.request.urlopen(
            urllib.request.Request(
                STREAMLIT_URL,
                headers={"User-Agent": "MarketScan-AIDebug/1.0"},
            ),
            timeout=15,
        ) as resp:
            body = resp.read(1024).decode("utf-8", errors="replace")
            ms = (time.perf_counter() - t0) * 1000
            status = resp.status

        icon_fn = _ok if ms < 3000 else _warn
        icon_fn("Streamlit HTTP", f"HTTP {status} | {ms:.0f}ms | {STREAMLIT_URL}")

        if "streamlit" in body.lower() or "_stcore" in body:
            _ok("Streamlit-app", "Streamlit-signatur detekterad i body")
        else:
            _warn("Streamlit-app", "Ingen Streamlit-signatur i svar")

        report["streamlit_http"] = {"ok": True, "status": status, "ms": ms}

    except Exception as e:
        _err("Streamlit HTTP", f"{e}")
        report["streamlit_http"] = {"ok": False, "error": str(e)}


def section_git_status(report: dict) -> None:
    """Visa git-status för att se om det finns ocommittade ändringar."""
    _section("9. Git-status")
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, cwd=ROOT, timeout=5,
        )
        commits = result.stdout.strip().splitlines()
        print("  Senaste 5 commits:")
        for c in commits:
            print(f"    {c}")

        # Branch och remote status
        branch_r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=ROOT, timeout=5,
        )
        branch = branch_r.stdout.strip()

        status_r = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, cwd=ROOT, timeout=5,
        )
        changes = status_r.stdout.strip().splitlines()
        if changes:
            _warn("Ocommittade ändringar", f"{len(changes)} filer")
            for c in changes[:5]:
                print(f"    {c}")
        else:
            _ok("Git-status", f"Ren (branch: {branch})")

        report["git"] = {"branch": branch, "uncommitted": len(changes)}

    except Exception as e:
        _warn("Git-status", f"Fel: {e}")


# ── Sammanfattning ─────────────────────────────────────────────────────────────

def print_summary(report: dict, total_s: float) -> None:
    _section("SAMMANFATTNING — Nuläge")

    issues = []

    # Pipeline
    ph = report.get("pipeline_health", {})
    if ph.get("status") not in ("healthy", None):
        issues.append(f"Pipeline: status={ph.get('status')}")
    age = ph.get("scan_age_h")
    if age and age > 24:
        issues.append(f"Gammal scan-data: {age:.1f}h")

    # CI
    ci = report.get("ci_failures", [])
    if ci:
        issues.append("CI-fel: senaste körning misslyckades")

    # Streamlit
    sl_err = report.get("streamlit_errors", [])
    if sl_err:
        issues.append(f"Streamlit-fel: {len(sl_err)} st senaste 48h")

    # GitHub
    gh = report.get("github", {})
    if gh.get("failures", 0) > 0:
        issues.append(f"GitHub Actions: {gh['failures']} misslyckade körningar")

    # Streamlit HTTP
    sh = report.get("streamlit_http", {})
    if sh.get("ok") is False:
        issues.append(f"Streamlit Cloud nere: {sh.get('error', '?')}")

    if not issues:
        print("  [OK ] Inget kritiskt hittades — systemet verkar friskt!")
    else:
        print(f"  [XX ] {len(issues)} problem hittade:")
        for issue in issues:
            print(f"    - {issue}")

    print(f"\n  Briefing-tid: {total_s:.1f}s")
    print(f"  Genererad: {_now_utc().strftime('%Y-%m-%d %H:%M UTC')}")

    print("\n  Nästa steg om det finns problem:")
    print("    python scripts/fetch_ci_logs.py --save     # Ladda ned CI-loggar")
    print("    python scripts/diagnose.py --section ml    # Djupdiagnos ML-modeller")
    print("    python scripts/check_github.py --jobs      # GitHub med job-detaljer")


# ── main() ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI-briefing: hela systemets nuläge i ett kommando",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--quick",  "-q", action="store_true",
                        help="Bara lokala filer (hoppar nätverkskontroller)")
    parser.add_argument("--github", "-g", action="store_true",
                        help="Inkludera live GitHub Actions-status")
    parser.add_argument("--json",         action="store_true",
                        help="Skriv ut JSON-rapport")
    parser.add_argument("--save",   "-s", action="store_true",
                        help="Spara rapport till data/ai_debug_latest.json")
    parser.add_argument("--since",        default="48h",
                        help="Visa fel från senaste N timmar (t.ex. 24h)")
    args = parser.parse_args()

    print("=" * 70)
    print("  MarketScan — AI Debug Briefing")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Repo: {ROOT}")
    print("=" * 70)

    t0     = time.perf_counter()
    report: dict = {}

    # Alltid körs (lokala filer)
    section_pipeline_health(report)
    section_ci_failures(report)
    section_streamlit_errors(report)
    section_pipeline_metrics(report)
    section_fetch_errors(report)
    section_diagnose_history(report)
    section_git_status(report)

    # Nätverkskontroller (om ej --quick)
    if not args.quick:
        if args.github or GITHUB_TOKEN:
            section_github_status(report)
        if STREAMLIT_URL:
            section_streamlit_http(report)

    total_s = time.perf_counter() - t0
    print_summary(report, total_s)

    # JSON output
    if args.json:
        print("\n" + json.dumps(report, ensure_ascii=False, indent=2, default=str))

    # Spara
    if args.save:
        out = DATA_DIR / "ai_debug_latest.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  [OK ] Rapport sparad: {out}")

    # Exitkod baserad på kritiska problem
    has_critical = (
        report.get("github", {}).get("failures", 0) > 0 or
        report.get("streamlit_http", {}).get("ok") is False or
        len(report.get("streamlit_errors", [])) > 5
    )
    return 1 if has_critical else 0


if __name__ == "__main__":
    sys.exit(main())
