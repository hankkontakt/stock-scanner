"""
web/pages/admin_tabs/tab_pipeline.py
=====================================
Admin — Flik 2: Pipeline

Innehåll:
  - Starta scan (med tydliga beskrivningar av varje läge)
  - Körningshistorik (senaste körningstider och status)
  - Cache-hantering
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR


# ── Konstanter ────────────────────────────────────────────────────────────────

_SCAN_MODES = {
    "morning": {
        "label": "Morgon",
        "icon": "🌅",
        "desc": "Uppdaterar portföljpriser och skickar morgonbrevet.",
        "detail": "Körs automatiskt vardagar ~07:05 UTC. Tar ~5-10 min.",
        "color": "#f59e0b",
    },
    "evening": {
        "label": "Kväll",
        "icon": "🌆",
        "desc": "Hämtar stängningspriser och skickar kvällsrapporten med STARK-signaler.",
        "detail": "Körs automatiskt vardagar ~17:30 UTC. Tar ~10-15 min.",
        "color": "#6366f1",
    },
    "weekly": {
        "label": "Veckoscan",
        "icon": "📅",
        "desc": "Full genomgång av hela aktieuniverse med scoring, rotation och audit.",
        "detail": "Körs automatiskt varje måndag ~06:00 UTC. Tar ~20-40 min.",
        "color": "#10b981",
    },
    "smallcap": {
        "label": "Småbolag",
        "icon": "🔬",
        "desc": "Scan av nordiska och globala småbolag (separat universe).",
        "detail": "Körs automatiskt varje tisdag ~06:30 UTC. Tar ~15-25 min.",
        "color": "#8b5cf6",
    },
    "targeted": {
        "label": "Specifika tickers",
        "icon": "🎯",
        "desc": "Hämtar om exakt de tickers du anger nedan, inget annat.",
        "detail": "Användbart för att åtgärda enstaka tickers utan att vänta på nästa schemalagda körning.",
        "color": "#3b82f6",
    },
    "refresh_missing": {
        "label": "Fyll saknad data",
        "icon": "🔄",
        "desc": "Letar upp tickers med saknad historik och hämtar dem.",
        "detail": "Kör detta om du ser många 'NaN' eller neutrala (50p) scores i datasetet.",
        "color": "#f97316",
    },
    "retry_rate_limited": {
        "label": "Kör om rate-limitade",
        "icon": "⏱️",
        "desc": "Försöker igen med tickers som ratebegränsades i senaste körning.",
        "detail": "Rate-limiting är vanligt mot Yahoo Finance. Kör detta dagen efter om data saknas.",
        "color": "#ef4444",
    },
}


# ── Hjälpfunktioner ────────────────────────────────────────────────────────────

def _trigger_scan(mode: str) -> bool:
    """Triggar en pipeline-scan via GitHub Actions workflow_dispatch."""
    try:
        from web.pages.admin import _get_github_token
        token = _get_github_token()
        if not token:
            return False
        import requests as _req
        url = "https://api.github.com/repos/hankkontakt/stock-scanner/actions/workflows/daily_scan.yml/dispatches"
        payload = {"ref": "main", "inputs": {"mode": mode, "tickers": ""}}
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        resp = _req.post(url, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201, 204)
    except Exception:
        return False


def _trigger_targeted(ticker_list: list[str]) -> bool:
    """Triggar targeted refresh för specifika tickers."""
    try:
        from web.pages.admin import _trigger_targeted_refresh
        return _trigger_targeted_refresh(ticker_list)
    except Exception:
        return False


def _load_scan_log() -> list:
    path = DATA_DIR / "scan_log.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _time_ago(ts_str: str) -> str:
    """Omvandla ISO-tidsstampel till 'X min sedan' / 'X timmar sedan'."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00").split("+")[0])
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:
            return f"{diff}s sedan"
        if diff < 3600:
            return f"{diff // 60} min sedan"
        if diff < 86400:
            return f"{diff // 3600}h sedan"
        return f"{diff // 86400}d sedan"
    except Exception:
        return ts_str[:16].replace("T", " ") if ts_str else "?"


# ── Huvud-render ───────────────────────────────────────────────────────────────

def render():
    # ── A: Kör scan ──────────────────────────────────────────────────────────
    st.markdown("""
    <div style="margin-bottom:4px">
      <span style="font-size:1.15em;font-weight:700;">Starta pipeline-körning</span><br>
      <span style="opacity:0.55;font-size:0.88em;">
        Alla lägen körs via GitHub Actions — du behöver inte vara inloggad i GitHub.
        Resultat visas i körningshistoriken nedan inom några minuter.
      </span>
    </div>
    """, unsafe_allow_html=True)

    # Knappar i rutnät 2×4
    mode_keys = list(_SCAN_MODES.keys())
    cols_row1 = st.columns(4)
    cols_row2 = st.columns(4)
    all_cols = cols_row1 + cols_row2

    targeted_tickers = ""
    show_targeted_input = st.session_state.get("show_targeted_input", False)

    for i, (mode, info) in enumerate(_SCAN_MODES.items()):
        if i >= len(all_cols):
            break
        with all_cols[i]:
            if st.button(
                f"{info['icon']} {info['label']}",
                key=f"scan_btn_{mode}",
                use_container_width=True,
                help=info["desc"],
            ):
                if mode == "targeted":
                    st.session_state["show_targeted_input"] = True
                    st.session_state["pending_mode"] = mode
                    st.rerun()
                else:
                    st.session_state["pending_mode"] = mode
                    st.session_state["show_targeted_input"] = False
            st.caption(f"_{info['detail']}_")

    # Targeted ticker-input (visas när targeted valts)
    if st.session_state.get("show_targeted_input"):
        st.markdown("---")
        targeted_tickers = st.text_input(
            "🎯 Ange tickers (kommaseparerade)",
            placeholder="t.ex. VOLV-B.ST, ERIC-B.ST, AAPL",
            help="Separera med komma. Max 50 tickers per körning.",
            key="targeted_ticker_input",
        ).strip()
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Starta targeted", type="primary", key="btn_targeted_go"):
                ticker_list = [t.strip().upper() for t in targeted_tickers.split(",") if t.strip()]
                if not ticker_list:
                    st.warning("Ange minst en ticker.")
                elif len(ticker_list) > 50:
                    st.warning("Max 50 tickers per körning.")
                else:
                    with st.spinner(f"Startar targeted refresh för {len(ticker_list)} tickers..."):
                        ok = _trigger_targeted(ticker_list)
                    if ok:
                        st.success(f"✅ Targeted refresh startad för: {', '.join(ticker_list[:5])}{'...' if len(ticker_list) > 5 else ''}")
                        st.session_state["show_targeted_input"] = False
                        st.session_state.pop("pending_mode", None)
                    else:
                        st.error("Kunde inte starta workflow. Kontrollera att GITHUB_TOKEN är konfigurerat i Streamlit Secrets.")
        with c2:
            if st.button("Avbryt", key="btn_targeted_cancel"):
                st.session_state["show_targeted_input"] = False
                st.session_state.pop("pending_mode", None)
                st.rerun()

    # Hantera icke-targeted lägen
    pending = st.session_state.get("pending_mode")
    if pending and pending != "targeted" and not st.session_state.get("show_targeted_input"):
        info = _SCAN_MODES.get(pending, {})
        st.markdown("---")
        st.info(f"**{info.get('icon','')} {info.get('label',pending)}** — {info.get('desc','')}")
        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button(f"Bekräfta: Starta {info.get('label', pending)}", type="primary", key="btn_confirm_scan"):
                with st.spinner(f"Startar {info.get('label', pending)}..."):
                    ok = _trigger_scan(pending)
                if ok:
                    st.success(f"✅ **{info.get('label', pending)}** startad! Se GitHub Actions för status.")
                else:
                    st.error("Kunde inte starta workflow. Kontrollera GITHUB_TOKEN i Streamlit Secrets.")
                st.session_state.pop("pending_mode", None)
                st.rerun()
        with c2:
            if st.button("Avbryt", key="btn_confirm_cancel"):
                st.session_state.pop("pending_mode", None)
                st.rerun()

    # ── B: Körningshistorik ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <span style="font-size:1.1em;font-weight:700;">Körningshistorik</span>
    <span style="opacity:0.55;font-size:0.85em;margin-left:8px;">— senaste pipeline-körningar</span>
    """, unsafe_allow_html=True)

    scan_log = _load_scan_log()
    if not scan_log:
        st.info("Ingen körningshistorik ännu. Systemet loggar automatiskt efter varje körning.")
    else:
        # Filter
        col_f1, col_f2 = st.columns([2, 2])
        with col_f1:
            filter_type = st.selectbox(
                "Filtrera på typ",
                ["Alla", "morning", "evening", "weekly", "smallcap", "portfolio_refresh",
                 "refresh_missing", "retry_rate_limited"],
                key="pipeline_log_filter",
            )
        with col_f2:
            filter_status = st.selectbox("Filtrera på status", ["Alla", "OK", "ERROR"], key="pipeline_status_filter")

        filtered = list(reversed(scan_log))  # Nyaste först
        if filter_type != "Alla":
            filtered = [e for e in filtered if e.get("scan_type") == filter_type]
        if filter_status != "Alla":
            filtered = [e for e in filtered if e.get("status") == filter_status]

        rows = []
        for entry in filtered[:40]:
            ts     = entry.get("timestamp", "")
            typ    = entry.get("scan_type", "?")
            status = entry.get("status", "?")
            d      = entry.get("details", {}) or {}
            elapsed = d.get("elapsed_seconds", "")
            n_tickers = d.get("n_scored", d.get("n_tickers", d.get("n_holdings", "")))
            status_emoji = "✅" if status == "OK" else "❌" if status == "ERROR" else "⚠️"
            rows.append({
                " ":         status_emoji,
                "Tidpunkt":  _time_ago(ts),
                "Datum":     ts[:16].replace("T", " ") if ts else "?",
                "Typ":       _SCAN_MODES.get(typ, {}).get("label", typ),
                "Varaktighet": f"{elapsed:.0f}s" if isinstance(elapsed, (int, float)) and elapsed else "—",
                "Tickers":   str(n_tickers) if n_tickers != "" else "—",
            })

        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"Visar {len(rows)} av {len(scan_log)} körningar")
        else:
            st.info("Inga körningar matchar filtret.")

        # Senaste fel (om något)
        errors = [e for e in scan_log if e.get("status") == "ERROR"]
        if errors:
            with st.expander(f"⚠️ {len(errors)} felade körningar — klicka för detaljer", expanded=False):
                for err in reversed(errors[-5:]):
                    ts  = err.get("timestamp", "")[:16].replace("T", " ")
                    typ = err.get("scan_type", "?")
                    msg = err.get("error", err.get("details", {}).get("error", "Okänt fel"))
                    st.markdown(f"**{ts}** · {typ}")
                    st.code(str(msg)[:300], language=None)

    # ── C: Cache-hantering ────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("🗄️ Cache-hantering — rensa gamla datafiler", expanded=False):
        st.caption(
            "Cache sparar hämtad aktiedata lokalt för att undvika onödiga API-anrop mot Yahoo Finance. "
            "Om cachen är mycket gammal kan du tvinga fram ny data genom att rensa den."
        )

        cache_dir = DATA_DIR / "cache"
        ai_cache_dir = DATA_DIR / "ai_cache"

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("**Data-cache** (aktiekurser, fundamenta)")
            if cache_dir.exists():
                files = list(cache_dir.glob("*.pkl"))
                if files:
                    total_mb = sum(f.stat().st_size for f in files) / 1_048_576
                    oldest_h = max((time.time() - f.stat().st_mtime) / 3600 for f in files)
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Filer", len(files))
                    c2.metric("Storlek", f"{total_mb:.1f} MB")
                    c3.metric("Äldsta", f"{oldest_h:.0f}h" if oldest_h < 720 else f"{oldest_h/24:.0f}d")
                    if oldest_h > 720:
                        st.warning(f"Äldsta fil är {oldest_h/24:.0f} dagar — fundamenta borde uppdateras snart.")
                    age_choice = st.selectbox(
                        "Rensa filer äldre än",
                        {"Äldre än 48h": 48, "Äldre än 7 dagar": 168, "Äldre än 30 dagar": 720, "All cache": 0},
                        key="cache_age_select",
                    )
                    age_hours = {"Äldre än 48h": 48, "Äldre än 7 dagar": 168, "Äldre än 30 dagar": 720, "All cache": 0}
                    if st.button("Rensa data-cache", key="btn_clear_data_cache"):
                        cutoff = time.time() - age_hours.get(age_choice, 0) * 3600
                        removed = sum(1 for f in files if f.stat().st_mtime < cutoff and not f.unlink())
                        st.success(f"Rensade {removed} filer.")
                        st.rerun()
                else:
                    st.info("Data-cachen är tom.")
            else:
                st.info("Cache-katalogen saknas.")

        with col_c2:
            st.markdown("**AI-cache** (AI-analyssvar)")
            if ai_cache_dir.exists():
                ai_files = list(ai_cache_dir.glob("*.md"))
                st.metric("AI-cache-filer", len(ai_files))
                st.caption("AI-svar cachas 24h för att spara API-kostnader.")
                if ai_files and st.button("Rensa AI-cache", key="btn_clear_ai_cache"):
                    try:
                        from core.ai_analysis import clear_cache as _clr
                        removed = _clr()
                        st.success(f"Rensade {removed} AI-cache-filer.")
                    except Exception as e:
                        for f in ai_files:
                            try:
                                f.unlink()
                            except Exception:
                                pass
                        st.success(f"Rensade {len(ai_files)} filer.")
                    st.rerun()
            else:
                st.info("AI-cachen är tom.")

    # ── D: (reserverad för framtida pipeline-diagnostik) ──────────────────────
