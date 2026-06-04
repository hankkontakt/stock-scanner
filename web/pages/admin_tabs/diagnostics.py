"""
web/pages/admin_tabs/diagnostics.py
=====================================
Streamlit Admin-tab: Systemdiagnostik Dashboard

Visar:
  - Realtidsstatus for miljö, konfiguration, pipeline, ML, notifieringar
  - Diagnoshistorik (data/diagnose_history.jsonl)
  - Direktknappar för att köra diagnos, testmail, GitHub-kontroll
  - Grafisk tidslinje för tidigare diagnosresultat
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DIAGNOSE_HISTORY = ROOT / "data" / "diagnose_history.jsonl"

# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _load_history(max_entries: int = 50) -> list[dict]:
    """Läs diagnos-historikfilen."""
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
    """Kör diagnose.py subprocess och returnera (exitcode, output)."""
    cmd = [sys.executable, str(ROOT / "scripts" / "diagnose.py")] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
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


def _status_badge(ok: bool | None, warn: bool = False) -> str:
    """Returnera HTML-badge för status."""
    if ok is None:
        return '<span style="background:#888;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">OKÄND</span>'
    if warn:
        return '<span style="background:#f0a500;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">VARNING</span>'
    if ok:
        return '<span style="background:#28a745;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">OK</span>'
    return '<span style="background:#dc3545;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">FEL</span>'


# ── Huvudfunktion ──────────────────────────────────────────────────────────────

def render_diagnostics_tab() -> None:
    """Renderar diagnostik-dashboarden."""
    st.subheader("Systemdiagnostik")
    st.caption("Kör självdiagnos och kontrollera alla systemkomponenter")

    # ── Åtgärdsknappar ──────────────────────────────────────────────────────
    st.markdown("### Köralternativ")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("Snabbdiagnos", key="diag_quick", type="primary",
                     help="Kör snabb diagnos (hoppar nätverkstester)"):
            st.session_state["diag_running"] = "quick"

    with col2:
        if st.button("Full diagnos", key="diag_full",
                     help="Kör komplett diagnos inkl. API-tester"):
            st.session_state["diag_running"] = "full"

    with col3:
        if st.button("Testmail", key="diag_email",
                     help="Kör diagnos och skicka testmail"):
            st.session_state["diag_running"] = "email"

    with col4:
        if st.button("GitHub-status", key="diag_github",
                     help="Kontrollera GitHub Actions-status"):
            st.session_state["diag_running"] = "github"

    # Kör diagnos om begärt
    diag_mode = st.session_state.get("diag_running")
    if diag_mode:
        st.session_state.pop("diag_running", None)

        args_map = {
            "quick":  ["--quick", "--save", "--json"],
            "full":   ["--save", "--json"],
            "email":  ["--send-test-mail", "--save", "--json"],
            "github": ["--section", "github", "--json"],
        }
        args = args_map.get(diag_mode, ["--quick"])

        with st.spinner(f"Kör diagnos ({diag_mode})..."):
            t0 = time.perf_counter()
            rc, output = _run_diagnose(args)
            elapsed = time.perf_counter() - t0

        # Visa resultat
        icon = "✅" if rc == 0 else "❌"
        st.markdown(f"**{icon} Diagnos klar ({elapsed:.1f}s)**")
        with st.expander("Visa detaljerad output", expanded=(rc != 0)):
            st.code(output, language=None)

        if rc == 0:
            st.success("Diagnosen klarades utan kritiska fel!")
        else:
            st.error("Diagnosen hittade kritiska fel — se output ovan")

        st.rerun()

    # ── Historik ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Diagnoshistorik")

    history = _load_history()
    if not history:
        st.info(
            "Ingen diagnoshistorik ännu. "
            "Klicka 'Snabbdiagnos' ovan för att köra och spara första posten."
        )
    else:
        # Senaste körning
        latest = history[-1]
        # Nycklar i diagnose_history.jsonl: ts, ok (int), warn, error, healthy
        lat_time = (latest.get("ts") or latest.get("timestamp") or "?")[:16].replace("T", " ")
        lat_healthy = latest.get("healthy", True)
        lat_ok   = latest.get("ok", 0)    # antal OK-checks (int)
        lat_err  = latest.get("error", 0)
        lat_warn = latest.get("warn", 0)
        lat_ok_n = lat_ok

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Senaste körning", lat_time)
        with col2:
            st.metric("Status", "OK" if lat_healthy else "FEL",
                      delta=None,
                      delta_color="normal")
        with col3:
            st.metric("Fel", lat_err, delta=None)
        with col4:
            st.metric("Varningar", lat_warn, delta=None)

        # Tidslinje som tabell
        st.markdown("#### Körningshistorik")
        try:
            import pandas as pd
            rows = []
            for entry in reversed(history):
                raw_ts = entry.get("ts") or entry.get("timestamp") or ""
                ts    = raw_ts[:16].replace("T", " ")
                healthy = entry.get("healthy", True)
                errs  = entry.get("error", 0)
                warns = entry.get("warn", 0)
                ok_n  = entry.get("ok", 0)
                mode  = entry.get("mode", "")
                rows.append({
                    "Tidpunkt":   ts,
                    "Status":     "OK" if healthy else "FEL",
                    "OK":         ok_n,
                    "Varningar":  warns,
                    "Fel":        errs,
                    "Läge":       mode,
                })
            df = pd.DataFrame(rows)

            # Färgkoda Status-kolumnen
            def _color_status(val: str) -> str:
                if val == "OK":
                    return "background-color: #d4edda; color: #155724"
                if val == "FEL":
                    return "background-color: #f8d7da; color: #721c24"
                return ""

            st.dataframe(
                df.style.applymap(_color_status, subset=["Status"]),
                use_container_width=True,
                hide_index=True,
            )
        except ImportError:
            # Fallback om pandas saknas
            for entry in reversed(history[-10:]):
                ts  = entry.get("timestamp", "")[:16].replace("T", " ")
                ok  = entry.get("ok", None)
                icon = "✅" if ok else "❌"
                st.text(f"{icon} {ts} — {entry.get('errors', 0)} fel, {entry.get('warnings', 0)} varningar")

    # ── Systemstatus-overview ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Systemstatus (realtid)")

    if st.button("Uppdatera status", key="diag_refresh"):
        # Kör snabb diagnos i bakgrunden för att uppdatera
        with st.spinner("Hämtar systemstatus..."):
            rc, output = _run_diagnose(["--quick", "--json", "--save"])

    # Visa senaste historik-entry som status-grid
    if history:
        latest = history[-1]
        sections = latest.get("sections", {})

        if sections:
            st.markdown("Sektionsstatus från senaste diagnos:")
            _section_names = {
                "env":       "Miljö & Beroenden",
                "config":    "Konfiguration",
                "email":     "E-post SMTP",
                "github":    "GitHub Actions",
                "streamlit": "Streamlit Webbapp",
                "pipeline":  "Pipeline Data",
                "ml":        "ML-modeller",
                "notif":     "Notifieringar",
                "data":      "Databeroenden",
                "flags":     "Feature Flags",
            }

            cols = st.columns(5)
            for i, (section_key, section_data) in enumerate(sections.items()):
                col = cols[i % 5]
                with col:
                    section_name = _section_names.get(section_key, section_key)
                    ok_n   = section_data.get("ok", 0)
                    err_n  = section_data.get("errors", 0)
                    warn_n = section_data.get("warnings", 0)

                    if err_n > 0:
                        color = "🔴"
                        status = f"{err_n} FEL"
                    elif warn_n > 0:
                        color = "🟡"
                        status = f"{warn_n} VARNING"
                    else:
                        color = "🟢"
                        status = "OK"

                    st.markdown(f"**{color} {section_name}**  \n{status}")
        else:
            st.info("Kör en diagnos för att se sektionsdetaljer")
    else:
        st.info("Ingen historik — kör en diagnos för att se systemstatus")

    # ── Diagnoslogg viewer ───────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("Visa rå diagnos-loggfil (JSONL)", expanded=False):
        if DIAGNOSE_HISTORY.exists():
            try:
                content = DIAGNOSE_HISTORY.read_text(encoding="utf-8")
                lines = content.strip().splitlines()
                st.caption(f"{len(lines)} poster i {DIAGNOSE_HISTORY}")
                # Visa senaste 5 poster
                for line in reversed(lines[-5:]):
                    try:
                        parsed = json.loads(line)
                        st.json(parsed)
                    except Exception:
                        st.text(line[:200])
            except Exception as e:
                st.error(f"Kunde inte läsa loggfil: {e}")
        else:
            st.info(f"Loggfil saknas: {DIAGNOSE_HISTORY}")

    # ── Tips & dokumentation ─────────────────────────────────────────────────
    with st.expander("Felsökningsguide", expanded=False):
        st.markdown("""
**Hur man kör diagnos manuellt:**
```bash
# Snabb diagnos
python scripts/diagnose.py --quick

# Full diagnos med sparning
python scripts/diagnose.py --save

# Specifik sektion
python scripts/diagnose.py --section email
python scripts/diagnose.py --section github

# Skicka testmail
python scripts/diagnose.py --send-test-mail

# JSON-output
python scripts/diagnose.py --json > diagnose.json
```

**Diagnostikscript:**
```bash
# GitHub Actions-status
python scripts/check_github.py --limit 10

# E-postsystem
python scripts/check_email.py
python scripts/check_email.py --send --to test@example.com

# Webbapp HTTP-hälsa
python scripts/check_site.py
python scripts/check_site.py --benchmark 5  # Latens-test

# Master test-runner
python scripts/test_all.py              # Allt
python scripts/test_all.py --fast       # Bara pytest
python scripts/test_all.py --all-checks # Pytest + alla hälsokontroller
```

**Live API-tester (kräver nätverkstillgång):**
```bash
pytest tests/test_live_api.py -m live -v
```
        """)
