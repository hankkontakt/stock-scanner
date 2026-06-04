"""
admin_page.py — Admin Streamlit-sida (ombyggd, 5 sektioner)

Arkitektur:
  5 st.tabs() med väldefinierade sektioner.
  Varje tabs rendering finns i separata moduler under admin_tabs/.

  🟢 System         ← dashboard, hälsa, GitHub Actions, diagnostik
  ▶️  Pipeline       ← kör skannar, körningshistorik, cache
  🌐 Universe       ← täckning, kandidater, strikes, blacklist, datakvalitet
  ⚙️  Inställningar   ← konfiguration, API-nycklar, användare, e-post
  📊 Metrics        ← körningstider, AI-tokens, score-distribution, fetch-fel

Delade datatjänstfunktioner finns i admin.py (oförändrade).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from web.utils import DATA_DIR, REPORT_DIR
from core import config
from web.pages.admin import (
    _get_github_token, _get_st_secret, _check_admin_access,
    _load_users_config, _save_users_config, _save_holdings_df,
    _save_watchlist_data, _search_ticker_yfinance, _trigger_gh_workflow,
    _trigger_targeted_refresh, _github_commit_file, USERS_CONFIG_FILE,
)


# ── CSS Design System ─────────────────────────────────────────────────────────

_ADMIN_CSS = """
<style>
/* Status-badges */
.status-ok    { background:#28a745; color:#fff; padding:3px 10px; border-radius:20px; font-size:0.85em; }
.status-warn  { background:#f0a500; color:#fff; padding:3px 10px; border-radius:20px; font-size:0.85em; }
.status-error { background:#dc3545; color:#fff; padding:3px 10px; border-radius:20px; font-size:0.85em; }

/* KPI-kort */
.kpi-card {
    background:#f8f9fa; border-left:4px solid #2563eb;
    padding:12px 16px; border-radius:6px; margin:4px 0;
}

/* Sektion-rubrik */
.section-header {
    font-size:1.15em; font-weight:700; color:#1e293b;
    border-bottom:2px solid #e2e8f0; padding-bottom:6px; margin-bottom:4px;
}
.section-desc {
    font-size:0.88em; color:#64748b; margin-top:2px; margin-bottom:16px;
}

/* Compact tables */
[data-testid="stDataFrame"] {
    font-size:0.85em;
}

/* Badges for metric cards */
kpi-badge {
    display:inline-block; padding:2px 8px; border-radius:12px;
    font-size:0.78em; font-weight:600;
}
</style>
"""


# ── Delad funktion (importeras av admin/*-modulerna) ─────────────────────────

def _load_scan_log() -> list:
    path = DATA_DIR / "scan_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []


# ── Admin-sida ────────────────────────────────────────────────────────────────

def page_admin():
    """Admin-sida — 5 sektioner, kräver lösenord."""
    if not _check_admin_access():
        if st.session_state.get("admin_authenticated", False):
            if st.button("Logga ut från admin", key="btn_admin_logout"):
                st.session_state["admin_authenticated"] = False
                st.rerun()
        return

    # Injicera CSS
    st.markdown(_ADMIN_CSS, unsafe_allow_html=True)

    st.title("Admin — Systemöversikt")

    # Importera de 5 tab-modulerna
    from web.pages.admin_tabs.tab_system import render as _system
    from web.pages.admin_tabs.tab_pipeline import render as _pipeline
    from web.pages.admin_tabs.tab_universe import render as _universe
    from web.pages.admin_tabs.tab_settings import render as _settings
    from web.pages.admin_tabs.tab_metrics import render as _metrics

    tab_system, tab_pipeline, tab_universe, tab_settings, tab_metrics = st.tabs([
        "System",
        "Pipeline",
        "Universe",
        "Inställningar",
        "Metrics",
    ])

    with tab_system:
        _system()
    with tab_pipeline:
        _pipeline()
    with tab_universe:
        _universe()
    with tab_settings:
        _settings()
    with tab_metrics:
        _metrics()
