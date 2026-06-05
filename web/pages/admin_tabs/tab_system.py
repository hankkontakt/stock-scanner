"""
web/pages/admin_tabs/tab_system.py
=====================================
Admin — Flik 1: System

Sektioner:
  - Statusbanner (övergripande systemstatus)
  - KPI-kort (senaste scan, dataålder, ML-modell, aktiva fel)
  - GitHub Actions (live via API)
  - API-nycklar & komponenter (env-tabell)
  - Diagnostikverktyg (Snabb/Full/GitHub-diagnos)
  - Fellog (senaste pipeline-fel med förklaringar)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from web.utils import DATA_DIR, REPORT_DIR

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DIAGNOSE_HISTORY = ROOT / "data" / "diagnose_history.jsonl"


# ── Statusbanner ──────────────────────────────────────────────────────────────

def _render_status_banner(scan_log: list):
    """Visar övergripande systemstatus: grönt/gult/rött baserat på senaste data."""
    has_error = any(e.get("status") == "ERROR" for e in scan_log[-5:] if scan_log)
    has_warn = any(
        e.get("status") not in ("OK", "ERROR") for e in scan_log[-3:] if scan_log
    )
    has_data = bool(scan_log)

    if has_error:
        badge = "🔴"
        status_text = "KRITISKA FEL"
        desc = "Senaste pipeline-körningarna har fel. Kontrollera felloggen nedan."
    elif has_warn:
        badge = "🟡"
        status_text = "VARNINGAR"
        desc = "Vissa pipeline-körningar har varningar eller är ofullständiga."
    elif has_data:
        badge = "🟢"
        status_text = "ALLT OK"
        desc = "Systemet fungerar normalt."
    else:
        badge = "⚪"
        status_text = "INGEN DATA"
        desc = "Inga pipeline-körningar har loggats ännu."

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:12px;padding:16px;'
        f'background:rgba(255,255,255,0.05);border-radius:8px;margin-bottom:16px;'
        f'border:1px solid rgba(255,255,255,0.10);">'
        f'<span style="font-size:2em;">{badge}</span>'
        f'<div><span style="font-size:1.2em;font-weight:700;">{status_text}</span><br>'
        f'<span style="opacity:0.6;font-size:0.9em;">{desc}</span></div></div>',
        unsafe_allow_html=True,
    )

    if scan_log:
        last = scan_log[-1]
        ts = last.get("timestamp", "")[:19].replace("T", " ")
        st.caption(f"Senast kontrollerat: {ts}")


# ── KPI-kort ──────────────────────────────────────────────────────────────────

def _render_kpi_cards(scan_log: list):
    """4 kolumner med nyckelindikatorer."""
    try:
        import pandas as pd
    except ImportError:
        pd = None

    c1, c2, c3, c4 = st.columns(4)

    # Inline-stil för alla KPI-kort (CSS-klasser är opålitliga i Streamlit)
    _K = (
        "background:rgba(255,255,255,0.06);"
        "border-left:3px solid rgba(99,153,255,0.50);"
        "padding:12px 16px;border-radius:8px;margin:4px 0;"
    )
    _LBL = "font-size:0.8em;opacity:0.55;"
    _VAL = "font-size:1.2em;font-weight:700;"
    _SUB = "font-size:0.82em;opacity:0.55;"

    # Senaste scan
    if scan_log:
        last = scan_log[-1]
        last_type = last.get("scan_type", "--")
        last_status = last.get("status", "?")
        last_ts = last.get("timestamp", "")[:16].replace("T", " ")
        icon = "OK" if last_status == "OK" else "FEL" if last_status == "ERROR" else "?"
        c1.markdown(
            f'<div style="{_K}"><span style="{_LBL}">Senaste scan</span><br>'
            f'<span style="{_VAL}">{last_type}</span><br>'
            f'<span style="{_SUB}">{icon} {last_ts}</span></div>',
            unsafe_allow_html=True,
        )
    else:
        c1.markdown(
            f'<div style="{_K}"><span style="{_LBL}">Senaste scan</span><br>'
            f'<span style="{_VAL}">—</span><br>'
            f'<span style="{_SUB}">Ingen data</span></div>',
            unsafe_allow_html=True,
        )

    # Data-ålder
    try:
        parquet_files = sorted(REPORT_DIR.glob("scored_universe_*.parquet"))
        if parquet_files:
            mtime = parquet_files[-1].stat().st_mtime
            age_h = (time.time() - mtime) / 3600
            age_str = f"{age_h:.1f}h"
            age_color = "#4ade80" if age_h < 24 else "#fbbf24" if age_h < 48 else "#f87171"
        else:
            age_str = "—"
            age_color = "#888"
    except Exception:
        age_str = "—"
        age_color = "#888"
    c2.markdown(
        f'<div style="{_K}"><span style="{_LBL}">Data-ålder</span><br>'
        f'<span style="{_VAL}color:{age_color};">{age_str}</span><br>'
        f'<span style="{_SUB}">Senaste scan-resultat</span></div>',
        unsafe_allow_html=True,
    )

    # ML-modell
    ml_path = ROOT / "models" / "ml_universe_metrics.json"
    ml_age = "—"
    try:
        if ml_path.exists():
            metrics = json.loads(ml_path.read_text(encoding="utf-8"))
            trained = metrics.get("trained_date", metrics.get("timestamp", ""))
            if trained:
                try:
                    trained_dt = datetime.fromisoformat(trained[:19])
                    days = (datetime.now() - trained_dt).days
                    ml_age = f"{days}d sedan"
                except Exception:
                    ml_age = trained[:10]
    except Exception:
        pass
    c3.markdown(
        f'<div style="{_K}"><span style="{_LBL}">ML-modell</span><br>'
        f'<span style="{_VAL}">{ml_age}</span><br>'
        f'<span style="{_SUB}">Tränad</span></div>',
        unsafe_allow_html=True,
    )

    # Aktiva fel
    n_errors = sum(1 for e in scan_log if e.get("status") == "ERROR") if scan_log else 0
    err_color = "#f87171" if n_errors > 0 else "#4ade80"
    c4.markdown(
        f'<div style="{_K}"><span style="{_LBL}">Aktiva fel</span><br>'
        f'<span style="{_VAL}color:{err_color};">{n_errors}</span><br>'
        f'<span style="{_SUB}">I pipeline-loggen</span></div>',
        unsafe_allow_html=True,
    )


# ── GitHub Actions ────────────────────────────────────────────────────────────

def _render_github_actions():
    """Live-status från GitHub Actions API."""
    from web.pages.admin import _get_github_token
    token = _get_github_token()
    OWNER = "hankkontakt"
    REPO = "stock-scanner"

    if not token:
        st.caption("GitHub-token saknas — kan inte visa Actions-status.")
        st.markdown(f"[Öppna GitHub Actions](https://github.com/{OWNER}/{REPO}/actions)")
        return

    workflow_info = {
        "daily_scan.yml": "Automatisk scanner, körs vardagar 07:05 och 17:30 UTC",
        "tests.yml": "Testning vid varje push till main",
        "smallcap_scan.yml": "Småbolagsscan, körs tisdagar 06:30 UTC",
        "train_ml.yml": "ML-modell-träning",
        "news_alerts.yml": "Nyhetsbevakning, var 30:e minut vardagar",
        "keep_alive.yml": "Håller Streamlit Cloud varm",
    }

    import requests as _req

    for wf_name, wf_desc in workflow_info.items():
        with st.container(border=True):
            cols = st.columns([1, 4])
            with cols[0]:
                try:
                    r = _req.get(
                        f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{wf_name}/runs",
                        params={"per_page": 1},
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                        timeout=6,
                    )
                    if r.status_code == 200:
                        runs = r.json().get("workflow_runs", [])
                        if runs:
                            run = runs[0]
                            conclusion = run.get("conclusion") or run.get("status")
                            icon = {
                                "success": "✅", "failure": "❌", "cancelled": "⛔",
                                "in_progress": "⏳", "queued": "🕐", "skipped": "⏭️",
                            }.get(conclusion, "❓")
                            st.markdown(f"<span style='font-size:1.4em;'>{icon}</span>", unsafe_allow_html=True)
                        else:
                            st.markdown("—")
                    else:
                        st.markdown("—")
                except Exception:
                    st.markdown("⚠️")
            with cols[1]:
                st.markdown(f"**{wf_name}**")
                st.caption(wf_desc)
                # Visa senaste körningstid
                try:
                    r = _req.get(
                        f"https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{wf_name}/runs",
                        params={"per_page": 1},
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                        timeout=6,
                    )
                    if r.status_code == 200:
                        runs = r.json().get("workflow_runs", [])
                        if runs:
                            run = runs[0]
                            created = (run.get("created_at") or "")[:16].replace("T", " ")
                            dur = ""
                            if run.get("updated_at") and run.get("run_started_at"):
                                try:
                                    dur_s = (datetime.fromisoformat(run["updated_at"][:19]) -
                                             datetime.fromisoformat(run["run_started_at"][:19])).total_seconds()
                                    dur = f" · {dur_s:.0f}s"
                                except Exception:
                                    pass
                            st.caption(f"Senast: {created}{dur}")
                    st.markdown(f"[Se körning ↗](https://github.com/{OWNER}/{REPO}/actions)", unsafe_allow_html=False)
                except Exception:
                    pass


# ── API-nycklar & Komponenter ─────────────────────────────────────────────────

def _render_api_keys():
    """Visar status för alla API-nycklar i tabellform med förklaringar."""
    from web.pages.admin import _get_st_secret

    components = [
        ("DeepSeek API", "DEEPSEEK_API_KEY", "AI-analys av aktier i portfölj och kandidater"),
        ("Gemini API", "GEMINI_API_KEY", "AI-fallback (gratis, rate-limited till 15 req/min)"),
        ("Financial Modeling Prep", "FMP_API_KEY", "Resultatkalender och earnings data"),
        ("Finnhub", "FINNHUB_API_KEY", "Nyhetssentiment och marknadsdata"),
        ("GitHub Token", "GITHUB_TOKEN", "Synkronisering av data och pipeline-trigger"),
        ("E-post (avsändare)", "EMAIL_SENDER", "SMTP-avsändare för rapporter"),
        ("E-post (lösenord)", "EMAIL_PASSWORD", "SMTP-lösenord"),
    ]

    rows = []
    for label, key, desc in components:
        val = _get_st_secret(key)
        status = "Satt" if val and val.strip() else "Saknas"
        status_icon = "✅" if val and val.strip() else "❌"
        rows.append({"Komponent": f"{status_icon} {label}", "Status": status, "Användning": desc})

    import pandas as pd
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Diagnostik ────────────────────────────────────────────────────────────────

def _load_history(max_entries: int = 50) -> list[dict]:
    if not DIAGNOSE_HISTORY.exists():
        return []
    entries = []
    try:
        with open(DIAGNOSE_HISTORY, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        return []
    return entries[-max_entries:]


def _run_diagnose(args: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, str(ROOT / "scripts" / "diagnose.py")] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=str(ROOT),
            env={"PYTHONPATH": str(ROOT), **__import__("os").environ},
        )
        output = result.stdout or ""
        if result.stderr:
            output += "\n" + result.stderr
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "Timeout — diagnosen tog mer än 120 sekunder"
    except Exception as e:
        return 1, f"Fel vid körning: {e}"


def _render_diagnostics():
    """Diagnostikverktyg med knappar och historik."""
    st.markdown("#### Diagnostikverktyg")
    st.caption("Kontrollera systemkomponenter och felsök problem.")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Snabbdiagnos", type="primary", key="diag_quick",
                      help="Hoppar nätverkstester, kör på ~30 sek"):
            st.session_state["diag_running"] = "quick"
    with col2:
        if st.button("Full diagnos", key="diag_full",
                      help="Komplett diagnos inklusive API-tester, tar ~2 min"):
            st.session_state["diag_running"] = "full"
    with col3:
        if st.button("GitHub-status", key="diag_github",
                      help="Kontrollera GitHub Actions och senaste körningar"):
            st.session_state["diag_running"] = "github"

    diag_mode = st.session_state.get("diag_running")
    if diag_mode:
        st.session_state.pop("diag_running", None)
        args_map = {
            "quick":  ["--quick", "--save", "--json"],
            "full":   ["--save", "--json"],
            "github": ["--section", "github", "--json"],
        }
        args = args_map.get(diag_mode, ["--quick"])
        with st.spinner(f"Kör diagnos ({diag_mode})..."):
            t0 = time.perf_counter()
            rc, output = _run_diagnose(args)
            elapsed = time.perf_counter() - t0
        icon = "✅" if rc == 0 else "❌"
        with st.expander(f"{icon} Diagnos klar ({elapsed:.1f}s)", expanded=(rc != 0)):
            st.code(output, language=None)
        if rc == 0:
            st.success("Diagnosen klarades utan kritiska fel.")
        else:
            st.error("Diagnosen hittade kritiska fel — se output ovan.")
        st.rerun()

    # Historik
    history = _load_history()
    if history:
        st.markdown("---")
        st.markdown("#### Diagnoshistorik")
        latest = history[-1]
        lat_time = (latest.get("ts") or latest.get("timestamp") or "?")[:16].replace("T", " ")
        lat_healthy = latest.get("healthy", True)
        lat_err = latest.get("error", 0)
        lat_warn = latest.get("warn", 0)

        c1, c2, c3 = st.columns(3)
        c1.metric("Senaste körning", lat_time)
        c2.metric("Status", "OK" if lat_healthy else "FEL")
        c3.metric("Fel / Varningar", f"{lat_err} / {lat_warn}")

        try:
            import pandas as pd
            rows = []
            for entry in reversed(history[-10:]):
                ts = (entry.get("ts") or entry.get("timestamp") or "")[:16].replace("T", " ")
                healthy = entry.get("healthy", True)
                errs = entry.get("error", 0)
                warns = entry.get("warn", 0)
                rows.append({"Tidpunkt": ts, "Status": "OK" if healthy else "FEL",
                             "Fel": errs, "Varningar": warns})
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        except ImportError:
            for entry in reversed(history[-10:]):
                ts = (entry.get("timestamp") or "")[:16].replace("T", " ")
                st.text(f"{'✅' if entry.get('healthy', True) else '❌'} {ts}")


# ── Fellog ────────────────────────────────────────────────────────────────────

def _render_error_log(scan_log: list):
    """Senaste pipeline-fel med förklaringar."""
    errors = [e for e in scan_log if e.get("status") == "ERROR"] if scan_log else []
    if not errors:
        st.markdown("#### Fellogg")
        st.success("Inga fel i pipeline-loggen.")
        return

    st.markdown("#### Fellogg")
    st.caption("Senaste pipeline-felen — vad de betyder och hur du åtgärdar dem.")

    error_faq = {
        "ModuleNotFoundError": "Ett Python-bibliotek saknas. Lägg till i requirements.txt och pusha.",
        "Timeout": "Pipeline tog för lång tid (>30 min). Oftast på grund av Yahoo Finance rate-limiting.",
        "Rate limit": "Yahoo Finance begränsar antalet anrop. Systemet försöker automatiskt igen.",
        "ConnectionError": "Nätverksproblem mot Yahoo Finance eller annan API-tjänst. Tillfälligt fel.",
        "KeyError": "Förväntad datapunkt saknas i API-svar. Kan bero på API-ändringar.",
        "ValueError": "Datakonverteringsfel. Kontrollera att alla tickers är giltiga.",
    }

    for err in reversed(errors[-5:]):
        ts = err.get("timestamp", "")[:16].replace("T", " ")
        typ = err.get("scan_type", "?")
        msg = str(err.get("error", err.get("details", {}).get("error", "Okänt fel")))

        with st.container(border=True):
            st.markdown(f"**{ts}** — {typ}")
            st.code(msg[:300], language=None)
            # Hitta FAQ-forklaring
            explanation = None
            for keyword, faq in error_faq.items():
                if keyword.lower() in msg.lower():
                    explanation = faq
                    break
            if explanation:
                st.caption(f"💡 {explanation}")
            else:
                st.caption("💡 Kontrollera GitHub Actions-loggarna för mer detaljer.")


# ── Render ────────────────────────────────────────────────────────────────────

def render():
    # Läs scan_log för data
    path = DATA_DIR / "scan_log.json"
    scan_log = []
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                scan_log = data
    except Exception:
        pass

    # A: Statusbanner
    _render_status_banner(scan_log)

    # B: KPI-kort
    _render_kpi_cards(scan_log)

    # C: GitHub Actions
    st.markdown("---")
    st.markdown("#### GitHub Actions")
    st.caption("Senaste körningsstatus per workflow.")
    _render_github_actions()

    # D: API-nycklar & Komponenter
    st.markdown("---")
    st.markdown("#### API-nycklar")
    st.caption("Status för alla externa tjänster som systemet använder.")
    _render_api_keys()

    # E: Diagnostikverktyg
    st.markdown("---")
    _render_diagnostics()

    # F: Fellog
    st.markdown("---")
    _render_error_log(scan_log)
