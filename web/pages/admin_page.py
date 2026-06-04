"""admin_page.py - Admin Streamlit-sida (tab-navigering).
Varje tabs rendering finns i separata moduler under admin/.

Delade datatjänstfunktioner finns i admin.py (oförändrade).
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR, REPORT_DIR, load_watchlist, load_portfolio
from core import config
from web.pages.admin import (
    _get_github_token, _get_st_secret, _check_admin_access,
    _load_users_config, _save_users_config, _save_holdings_df,
    _save_watchlist_data, _search_ticker_yfinance, _trigger_gh_workflow,
    _trigger_targeted_refresh, _github_commit_file, USERS_CONFIG_FILE,
)


# ══════════════════════════════════════════════════════════════════════════════
# DELAD FUNKTION (importeras av admin/*-modulerna)
# ══════════════════════════════════════════════════════════════════════════════

def _load_scan_log() -> list:
    path = DATA_DIR / "scan_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN-SIDA
# ══════════════════════════════════════════════════════════════════════════════

def page_admin():
    """Admin-sida — kräver lösenord."""
    if not _check_admin_access():
        if st.session_state.get("admin_authenticated", False):
            if st.button("Logga ut från admin", key="btn_admin_logout"):
                st.session_state["admin_authenticated"] = False
                st.rerun()
        return

    st.title("Admin — Hantera portfölj, bevakning & scannar")

    # Import av alla tab-moduler
    from web.pages.admin_tabs.overview import render as _overview
    from web.pages.admin_tabs.watchlist import render as _watchlist
    from web.pages.admin_tabs.holdings import render as _holdings
    from web.pages.admin_tabs.scans import render as _scans
    from web.pages.admin_tabs.import_tab import render as _import_tab
    from web.pages.admin_tabs.health import render as _health
    from web.pages.admin_tabs.email_tab import render as _email
    from web.pages.admin_tabs.users import render as _users
    from web.pages.admin_tabs.config_tab import render as _config
    from web.pages.admin_tabs.cache_tab import render_cache, render_ai_log, render_alarms
    from web.pages.admin_tabs.debug_tab import render as _debug
    from web.pages.admin_tabs.data_quality import render as _data_quality
    from web.pages.admin_tabs.universe_discovery import render as _universe_discovery
    from web.pages.admin_tabs.strikes_health import render as _strikes_health
    try:
        from web.pages.admin_tabs.metrics import render as _metrics
        _has_metrics = True
    except ImportError:
        _has_metrics = False

    try:
        from web.pages.admin_tabs.diagnostics import render_diagnostics_tab as _diagnostics
        _has_diagnostics = True
    except ImportError:
        _has_diagnostics = False

    _tab_names = [
        "Översikt",
        "Bevakningslista",
        "Portfölj",
        "Starta scan",
        "Avanza-import",
        "Universe Health",
        "Ticker-discovery",
        "Strikes & Blacklist",
        "Datakvalitet",
        "E-post",
        "Användare",
        "Konfiguration",
        "Cache",
        "AI-logg",
        "Larm",
        "Felsökning",
        "Metrics",       # E3: pipeline-metrics och observability
        "Diagnostik",    # STEG 2: självdiagnos-dashboard
    ]
    tabs = st.tabs(_tab_names)

    with tabs[0]:
        _overview(_load_scan_log)
    with tabs[1]:
        _watchlist()
    with tabs[2]:
        _holdings()
    with tabs[3]:
        _scans()
    with tabs[4]:
        _import_tab()
    with tabs[5]:
        _health()
    with tabs[6]:
        _universe_discovery()
    with tabs[7]:
        _strikes_health()
    with tabs[8]:
        _data_quality()
    with tabs[9]:
        _email()
    with tabs[10]:
        _users()
    with tabs[11]:
        _config()
    with tabs[12]:
        render_cache()
    with tabs[13]:
        render_ai_log()
    with tabs[14]:
        render_alarms()
    with tabs[15]:
        _debug(_load_scan_log)
    with tabs[16]:
        if _has_metrics:
            _metrics()
        else:
            st.info("core.metrics ej installerat.")
    with tabs[17]:
        if _has_diagnostics:
            _diagnostics()
        else:
            st.info("Diagnostik-modulen ej tillgänglig.")
