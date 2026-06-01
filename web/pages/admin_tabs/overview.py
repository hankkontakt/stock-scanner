"""admin/overview.py - Overview tab for admin page."""
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
        c1.metric("Senaste scan", last.get("scan_type", "--"), last.get("status", "--"))
    except Exception:
        c1.metric("Senaste scan", "Okänd", "--")
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
    st.markdown("**⚙️ GitHub Actions**")
    _render_actions_status()

    st.markdown("---")
    st.markdown("**📊 Fetch-fellogg**")
    _render_fetch_errors()

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
        st.warning("Ingen GitHub-token -- kan inte kontrollera synkstatus")
        return

    rows = []
    for github_path, local_path in key_files:
        local_exists = local_path.exists()
        local_mtime = (
            datetime.fromtimestamp(local_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            if local_exists else "--"
        )
        gh_committed = "--"
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


def _render_actions_status():
    """Visar senaste GitHub Actions-körningar och länk till Actions-sidan."""
    owner = "hankkontakt"
    repo  = "stock-scanner"
    token = _get_github_token()

    st.markdown(
        f"[Öppna GitHub Actions ↗](https://github.com/{owner}/{repo}/actions)",
        unsafe_allow_html=False,
    )

    if not token:
        st.caption("Ingen GitHub-token — kan inte hämta körningshistorik.")
        return

    try:
        import requests as _req
        r = _req.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs",
            params={"per_page": 8},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=6,
        )
        if r.status_code != 200:
            st.caption(f"Kunde inte hämta Actions-data (HTTP {r.status_code}).")
            return
        runs = r.json().get("workflow_runs", [])
        if not runs:
            st.caption("Inga körningar hittades.")
            return
        rows_a = []
        for run in runs:
            status_icon = {
                "success":    "✅",
                "failure":    "❌",
                "cancelled":  "⛔",
                "in_progress":"⏳",
                "queued":     "🕐",
            }.get(run.get("conclusion") or run.get("status"), "❓")
            rows_a.append({
                "Status": status_icon + " " + (run.get("conclusion") or run.get("status") or "?"),
                "Workflow": run.get("name", ""),
                "Branch": run.get("head_branch", ""),
                "Startat": (run.get("created_at") or "")[:16].replace("T", " "),
                "Länk": run.get("html_url", ""),
            })
        df_runs = pd.DataFrame(rows_a)
        st.dataframe(
            df_runs.drop(columns=["Länk"]),
            use_container_width=True,
            hide_index=True,
        )
    except Exception as e:
        st.caption(f"Fel vid hämtning av Actions: {e}")


def _render_fetch_errors():
    """Visar fetch_errors.json — tickers som misslyckades i senaste skannen."""
    errors_path = DATA_DIR / "fetch_errors.json"
    if not errors_path.exists():
        st.caption("Ingen fellogg ännu (skapas efter första skannen).")
        return
    try:
        history = json.loads(errors_path.read_text(encoding="utf-8"))
        if not history:
            st.caption("Fellogg är tom.")
            return
        last = history[-1]
        ts   = last.get("timestamp", "?")
        n_ok = last.get("n_ok", 0)
        n_fail = last.get("n_failed", 0)
        n_del  = last.get("n_delisted", 0)
        col1, col2, col3 = st.columns(3)
        col1.metric("Hämtade OK", n_ok)
        col2.metric("Misslyckades", n_fail, delta=None)
        col3.metric("Delistade", n_del)
        st.caption(f"Senaste scan: {ts}")

        failed = last.get("failed_tickers", [])
        if failed:
            with st.expander(f"Visa {len(failed)} misslyckade tickers"):
                st.dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)

        delisted = last.get("delisted_tickers", [])
        if delisted:
            with st.expander(f"Visa {len(delisted)} delistade tickers"):
                st.write(", ".join(delisted))
    except Exception as e:
        st.caption(f"Kunde inte läsa fellogg: {e}")
