"""admin/overview.py - Overview tab for admin page."""
import json
import os
import time
from datetime import date, datetime, timedelta
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


# ═══════════════════════════════════════════════════════════════════════════
# GITHUB ACTIONS MONITOR
# ═══════════════════════════════════════════════════════════════════════════

class GitHubActionsMonitor:
    """
    Monitor för GitHub Actions-körningar.
    Cachar i 60 sekunder för att undvika API rate limits.
    """

    OWNER = "hankkontakt"
    REPO  = "stock-scanner"

    def __init__(self):
        self._cache: dict = {}
        self._cache_ts: float = 0
        self._cache_ttl = 60  # sekunder

    def get_recent_runs(self, workflow: str = "daily_scan.yml", n: int = 20) -> list[dict]:
        """Hämta senaste N körningar för ett workflow."""
        cache_key = f"runs_{workflow}_{n}"
        now = time.time()
        if cache_key in self._cache and now - self._cache_ts < self._cache_ttl:
            return self._cache[cache_key]

        token = _get_github_token()
        if not token:
            return []

        try:
            import requests as _req
            url = f"https://api.github.com/repos/{self.OWNER}/{self.REPO}/actions/workflows/{workflow}/runs"
            r = _req.get(
                url,
                params={"per_page": n},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=6,
            )
            if r.status_code != 200:
                return []
            runs = r.json().get("workflow_runs", [])
            result = []
            for run in runs:
                result.append({
                    "id": run.get("id"),
                    "status": run.get("conclusion") or run.get("status") or "?",
                    "workflow": run.get("name", ""),
                    "branch": run.get("head_branch", ""),
                    "commit": (run.get("head_commit") or {}).get("message", "")[:60] if run.get("head_commit") else "",
                    "created_at": (run.get("created_at") or "")[:16].replace("T", " "),
                    "duration_min": round((run.get("updated_at", run.get("created_at", ""))[:19] > run.get("created_at", "")[:19]) or 0),
                    "html_url": run.get("html_url", ""),
                    "actor": (run.get("actor") or {}).get("login", ""),
                })
            self._cache[cache_key] = result
            self._cache_ts = now
            return result
        except Exception:
            return []

    def get_run_details(self, run_id: int) -> dict | None:
        """Hämta detaljer för en specifik körning."""
        cache_key = f"run_detail_{run_id}"
        now = time.time()
        if cache_key in self._cache and now - self._cache_ts < self._cache_ttl:
            return self._cache[cache_key]

        token = _get_github_token()
        if not token:
            return None

        try:
            import requests as _req
            url = f"https://api.github.com/repos/{self.OWNER}/{self.REPO}/actions/runs/{run_id}"
            r = _req.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=6,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            self._cache[cache_key] = data
            self._cache_ts = now
            return data
        except Exception:
            return None

    def get_run_logs(self, run_id: int, step_name: str | None = None) -> str:
        """Hämta loggar för en körning (eller specifikt steg)."""
        token = _get_github_token()
        if not token:
            return ""

        try:
            import requests as _req
            # Hämta jobs för körningen
            url = f"https://api.github.com/repos/{self.OWNER}/{self.REPO}/actions/runs/{run_id}/jobs"
            r = _req.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                timeout=6,
            )
            if r.status_code != 200:
                return f"Kunde inte hämta jobb: HTTP {r.status_code}"
            jobs = r.json().get("jobs", [])
            for job in jobs:
                for step in job.get("steps", []):
                    if step_name is None or step_name.lower() in step.get("name", "").lower():
                        # Hämta loggar för detta steg
                        logs_url = step.get("logs_url")
                        if logs_url:
                            log_r = _req.get(
                                logs_url,
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=10,
                            )
                            if log_r.status_code == 200:
                                return log_r.text[-5000:]  # Senaste 5000 tecken
                        return f"Steg: {step.get('name')} — status: {step.get('conclusion', '?')}"
            return "Inga loggar hittades"
        except Exception as e:
            return f"Fel: {e}"

    def cache_workflow_runs(self):
        """Forcera uppdatering av cache."""
        self._cache = {}
        self._cache_ts = 0
        self.get_recent_runs()


def render_github_actions_monitor():
    """Visa GitHub Actions Monitor i admin-översikten."""
    st.markdown("### 🤖 GitHub Actions Monitor")
    monitor = GitHubActionsMonitor()

    token = _get_github_token()
    if not token:
        st.caption("⚠️ Ingen GitHub-token — kan inte hämta Actions-data")
        st.markdown(
            f"[Öppna GitHub Actions](https://github.com/{monitor.OWNER}/{monitor.REPO}/actions)",
            unsafe_allow_html=False,
        )
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        workflow_filter = st.selectbox(
            "Workflow", ["daily_scan.yml", "weekly_scan.yml", "smallcap_scan.yml", "alla"],
            key="gh_workflow_filter",
        )
    with col2:
        if st.button("🔄 Uppdatera", key="gh_refresh"):
            monitor.cache_workflow_runs()
            st.rerun()

    n_runs = st.slider("Antal körningar", 5, 50, 15, key="gh_n_runs")
    runs = monitor.get_recent_runs(workflow=workflow_filter, n=n_runs) if workflow_filter != "alla" else _get_all_runs_fallback(n_runs)

    if not runs:
        st.info("Inga körningar hittades.")
        return

    # Sammanfattning
    success = sum(1 for r in runs if r.get("status") == "success")
    failed = sum(1 for r in runs if r.get("status") == "failure")
    in_progress = sum(1 for r in runs if r.get("status") in ("in_progress", "queued", "pending"))

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("✅ Lyckade", success)
    sc2.metric("❌ Misslyckade", failed)
    sc3.metric("⏳ Pågående", in_progress)
    sc4.metric("Totalt", len(runs))

    # Tabell med körningar
    rows = []
    for run in runs:
        status = run.get("status", "?")
        status_icon = {
            "success": "✅", "failure": "❌", "cancelled": "⛔",
            "in_progress": "⏳", "queued": "🕐", "pending": "🕐",
            "skipped": "⏭️",
        }.get(status, "❓")
        rows.append({
            "Status": f"{status_icon} {status}",
            "Branch": run.get("branch", ""),
            "Commit": run.get("commit", "")[:40],
            "Start": run.get("created_at", ""),
            "Länk": run.get("html_url", ""),
        })

    df_runs = pd.DataFrame(rows)
    st.dataframe(
        df_runs.drop(columns=["Länk"]),
        use_container_width=True,
        hide_index=True,
    )

    # Visa detaljer för vald körning
    with st.expander("🔍 Visa detaljer för körning"):
        run_ids = [r.get("id", "?") for r in runs[:20]]
        selected_id = st.selectbox("Välj körning (ID)", run_ids, format_func=lambda x: f"Run #{x}")
        if selected_id and selected_id != "?":
            details = monitor.get_run_details(int(selected_id))
            if details:
                st.json({
                    "status": details.get("conclusion") or details.get("status"),
                    "branch": details.get("head_branch"),
                    "commit": (details.get("head_commit") or {}).get("message", ""),
                    "actor": (details.get("actor") or {}).get("login"),
                    "created": details.get("created_at"),
                    "duration": details.get("run_started_at"),
                })
            logs = monitor.get_run_logs(int(selected_id), step_name=None)
            if logs:
                st.code(logs[:3000], language="log")

    st.caption(
        f"[Öppna GitHub Actions ↗](https://github.com/{monitor.OWNER}/{monitor.REPO}/actions)"
    )


def _get_all_runs_fallback(n: int = 15) -> list[dict]:
    """Fallback: hämta alla workflows."""
    monitor = GitHubActionsMonitor()
    all_runs = []
    for wf in ["daily_scan.yml", "weekly_scan.yml", "smallcap_scan.yml"]:
        all_runs.extend(monitor.get_recent_runs(workflow=wf, n=n))
    all_runs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return all_runs[:n]


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

    st.markdown("---")
    _render_monitoring_sections()


def _render_monitoring_sections():
    """Visa monitoring-sektioner: health, staleness, cache analytics."""
    st.markdown("**🏥 System Health**")
    try:
        from core.monitoring.health import system_health_check
        health = system_health_check()

        status_icon = "🟢" if health.get("status") == "healthy" else "🟡" if health.get("status") == "degraded" else "🔴"
        st.markdown(f"**Status:** {status_icon} {health.get('status', 'unknown').upper()}")

        if health.get("degraded_components"):
            st.warning(f"Degraderade komponenter: {', '.join(health['degraded_components'])}")

        c1, c2, c3 = st.columns(3)
        c1.metric("Disk (data)", f"{health.get('disk_usage', {}).get('total_mb', '?')} MB",
                  f"{health.get('disk_usage', {}).get('free_gb', '?')} GB ledigt")
        c2.metric("Cache-filer", health.get('cache_stats', {}).get('total_files', '?'))
        c3.metric("Portfölj", health.get('portfolio_status', {}).get('n_holdings', '?'))

        with st.expander("🔍 Detaljerad hälsokoll"):
            st.json(health)
    except Exception as e:
        st.caption(f"Kunde inte hämta hälsokoll: {e}")

    st.markdown("**📦 Data Freshness**")
    try:
        from core.monitoring.staleness import DataStalenessMonitor
        dsm = DataStalenessMonitor()
        score = dsm.get_freshness_score()
        color = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"
        st.markdown(f"**Freshness Score:** {color} {score}/100")

        stale = dsm.get_stale_items(threshold_hours=48)
        if stale:
            st.warning(f"{len(stale)} föråldrade datafiler")
            with st.expander(f"Visa {len(stale)} föråldrade filer"):
                st.dataframe(pd.DataFrame(stale), use_container_width=True, hide_index=True)
        else:
            st.success("All data är färsk (< 48h)")

        suggestions = dsm.auto_refresh_suggestions()
        if suggestions:
            with st.expander("💡 Auto-refresh-förslag"):
                for s in suggestions:
                    st.write(f"- {s}")
    except Exception as e:
        st.caption(f"Kunde inte hämta data freshness: {e}")

    st.markdown("**🗄️ Cache Analytics**")
    try:
        from core.cache_utils import CacheAnalytics
        ca = CacheAnalytics()
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Cache-storlek", f"{ca.get_cache_size()} MB")
        cc2.metric("Antal filer", ca.get_cache_count())
        hit_rate = ca.get_hit_rate()
        cc3.metric("Hit rate", f"{hit_rate*100:.1f}%" if hit_rate >= 0 else "N/A")

        by_type = ca.get_cache_by_type()
        if by_type:
            st.caption("Fördelning: " + ", ".join(f"{k}={v}" for k, v in by_type.items()))

        with st.expander("🔍 Största cache-filer"):
            largest = ca.get_largest_cache(5)
            if largest:
                st.dataframe(pd.DataFrame(largest), use_container_width=True, hide_index=True)
    except Exception as e:
        st.caption(f"Kunde inte hämta cache-analys: {e}")

    st.markdown("**⏱️ Pipeline Performance**")
    try:
        from core.daily_pipeline import get_performance_summary, get_slowest_stages
        perf = get_performance_summary()
        if not perf.empty:
            st.dataframe(perf, use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen prestandadata ännu (kör pipeline först)")
    except Exception as e:
        st.caption(f"Kunde inte hämta prestandadata: {e}")

    st.markdown("**💾 Resource Monitor**")
    try:
        from core.monitoring.resources import track_disk_usage, get_data_growth_rate, estimate_monthly_growth
        disk = track_disk_usage()
        growth = get_data_growth_rate()
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Data", f"{disk.get('data_mb', 0)} MB")
        rc2.metric("Reports", f"{disk.get('reports_mb', 0)} MB")
        rc3.metric("Daglig tillväxt", f"{growth.get('daily_growth_mb', 0)} MB/dag")

        monthly = estimate_monthly_growth(3)
        if monthly.get("estimates"):
            st.caption(f"Prognos om 3 mån: {monthly['estimates'][-1].get('estimated_mb', 0)} MB")
    except Exception as e:
        st.caption(f"Kunde inte hämta resursdata: {e}")


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
