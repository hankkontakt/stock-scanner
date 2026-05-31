"""admin/overview.py – Overview tab for admin page."""
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR, load_watchlist, load_portfolio
from web.pages.admin import (
    _get_github_token, _trigger_gh_workflow,
    _save_watchlist_data, _save_holdings_df, _github_commit_file,
)

_AI_LOG_FILE = DATA_DIR / "ai_usage_log.json"
_ACTIVITY_LOG_FILE = DATA_DIR / "activity_log.json"


def _load_ai_usage_log() -> list:
    try:
        if _AI_LOG_FILE.exists():
            return json.loads(_AI_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _load_activity_log() -> list:
    try:
        if _ACTIVITY_LOG_FILE.exists():
            return json.loads(_ACTIVITY_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def render(load_scan_log_fn):
    st.subheader("📊 Översikt")
    from core.email_template import load_subscribers

    c1, c2, c3, c4 = st.columns(4)
    try:
        scan_log = load_scan_log_fn()
        last = scan_log[-1] if scan_log else {}
        c1.metric("Senaste scan", last.get("scan_type", "—"), last.get("status", "—"))
    except Exception:
        c1.metric("Senaste scan", "Okänd", "—")
    c2.metric("Bevakningar", len(load_watchlist()))
    try:
        portfolio = load_portfolio()
        c3.metric("Portföljinnehav", len(portfolio) if not portfolio.empty else 0)
    except Exception:
        c3.metric("Portföljinnehav", "?")
    c4.metric("Prenumeranter", len(load_subscribers()))

    st.markdown("---")
    st.markdown("**🌐 GitHub-synkstatus**")
    _render_github_sync_status()

    st.markdown("---")
    st.markdown("**👥 Aktivitet**")
    activity = _load_activity_log()
    if activity:
        st.dataframe(pd.DataFrame(activity[-20:]), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen aktivitet loggad ännu.")

    st.markdown("---")
    st.markdown("**🤖 AI-användning**")
    ai_usage = _load_ai_usage_log()
    if ai_usage:
        df_ai = pd.DataFrame(ai_usage)
        date_col = next((c for c in df_ai.columns if "date" in c or "time" in c), None)
        if date_col:
            st.dataframe(df_ai.tail(20), use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_ai.tail(20), use_container_width=True, hide_index=True)
        st.caption(f"Totalt {len(ai_usage)} AI-anrop loggade")
    else:
        st.info("Ingen AI-användning loggad ännu.")


def _render_github_sync_status():
    token = _get_github_token()
    owner = "hankkontakt"
    repo = "stock-scanner"

    key_files = [
        ("data/scan_log.json", DATA_DIR / "scan_log.json"),
        ("data/watchlist.json", DATA_DIR / "watchlist.json"),
        ("data/holdings.csv", DATA_DIR / "holdings.csv"),
        ("data/email_subscribers.json", DATA_DIR / "email_subscribers.json"),
        ("data/custom_universe.json", DATA_DIR / "custom_universe.json"),
        ("data/blacklist.json", DATA_DIR / "blacklist.json"),
    ]

    if not token:
        st.warning("Ingen GitHub-token — kan inte kontrollera synkstatus")
        return

    rows = []
    for github_path, local_path in key_files:
        local_exists = local_path.exists()
        local_mtime = (
            datetime.fromtimestamp(local_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            if local_exists else "—"
        )
        gh_committed = "—"
        try:
            import requests as _req
            r = _req.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                params={"path": github_path, "per_page": 1},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=5,
            )
            if r.status_code == 200 and r.json():
                gh_committed = r.json()[0]["commit"]["committer"]["date"][:10]
        except Exception:
            gh_committed = "?"
        rows.append({
            "Fil": github_path,
            "Lokal": "OK" if local_exists else "SAKNAS",
            "Senast andrad (lokal)": local_mtime,
            "Senast commitad (GitHub)": gh_committed,
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
