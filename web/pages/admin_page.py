"""web/pages/admin_page.py - Admin Streamlit-sida (rendering).
Delade datatjanstfunktioner finns i admin.py.
"""

import json
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from web.utils import (
    DATA_DIR, REPORT_DIR, load_watchlist, load_portfolio, _get_provider,
    kpi_row,
)
from core import config
from web.pages.admin import (
    _get_github_token, _get_st_secret, _check_admin_access,
    _load_users_config, _save_users_config, _save_holdings_df,
    _save_watchlist_data, _search_ticker_yfinance, _trigger_gh_workflow,
    _trigger_targeted_refresh, _github_commit_file, USERS_CONFIG_FILE,
    validate_ticker,
)

# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER FÖR NYA FLIKAR
# ══════════════════════════════════════════════════════════════════════════════

def _load_scan_log() -> list:
    path = DATA_DIR / "scan_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []


def _load_ai_usage_log() -> list:
    path = DATA_DIR / "ai_usage_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []


def _load_activity_log() -> list:
    path = DATA_DIR / "activity_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []


def _load_email_delivery_log() -> list:
    path = DATA_DIR / "email_delivery_log.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except Exception:
        return []


def _render_github_sync_status():
    """Show which key data files are committed to GitHub vs local-only."""
    token = _get_github_token()
    owner = os.getenv("GITHUB_OWNER") or "hankkontakt"
    repo  = os.getenv("GITHUB_REPO")  or "stock-scanner"

    key_files = [
        ("data/scan_log.json",              DATA_DIR / "scan_log.json"),
        ("data/watchlist.json",             DATA_DIR / "watchlist.json"),
        ("data/holdings.csv",               DATA_DIR / "holdings.csv"),
        ("data/email_subscribers.json",     DATA_DIR / "email_subscribers.json"),
        ("data/custom_universe.json",       DATA_DIR / "custom_universe.json"),
        ("data/blacklist.json",             DATA_DIR / "blacklist.json"),
    ]

    if not token:
        st.warning("⚠️ Ingen GitHub-token — kan inte kontrollera synkstatus")
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
            "Fil":                       github_path,
            "Lokal":                     "✅" if local_exists else "❌",
            "Senast ändrad (lokal)":     local_mtime,
            "Senast commitad (GitHub)":  gh_committed,
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_overview_tab():
    st.subheader("📊 Systemoversikt")

    # Row 1: 4 KPI metrics
    col1, col2, col3, col4 = st.columns(4)

    scan_log = _load_scan_log()
    last_scan = scan_log[-1] if scan_log else {}
    last_scan_time = last_scan.get("timestamp", "Aldrig")[:16] if last_scan else "Aldrig"
    last_scan_mode = last_scan.get("mode", "—")

    users = _load_users_config()
    active_users = sum(1 for u in users if u.get("active", True))

    try:
        from core.email_template import load_subscribers
        subs = load_subscribers()
        active_subs = sum(1 for s in subs if s.get("active", True))
    except Exception:
        active_subs = 0

    ai_log = _load_ai_usage_log()
    today_str = date.today().isoformat()
    ai_today = sum(1 for e in ai_log if e.get("date", "").startswith(today_str))

    with col1:
        st.metric("🕐 Senaste scan", last_scan_time, last_scan_mode)
    with col2:
        st.metric("👥 Aktiva användare", active_users)
    with col3:
        st.metric("📧 E-postprenumeranter", active_subs)
    with col4:
        st.metric("🤖 AI-anrop idag", ai_today)

    st.markdown("---")

    # Row 2: API-nyckelstatus
    st.markdown("**🔑 API-nyckelstatus**")
    api_cols = st.columns(5)
    keys = [
        ("GitHub",   bool(_get_st_secret("GITHUB_TOKEN"))),
        ("Finnhub",  bool(_get_st_secret("FINNHUB_API_KEY"))),
        ("DeepSeek", bool(_get_st_secret("DEEPSEEK_API_KEY"))),
        ("Gemini",   bool(_get_st_secret("GEMINI_API_KEY"))),
        ("E-post",   bool(_get_st_secret("EMAIL_SENDER"))),
    ]
    for col, (name, ok) in zip(api_cols, keys):
        col.markdown(f"{'✅' if ok else '❌'} **{name}**")

    st.markdown("---")

    # Row 3: Senaste skanningar
    st.markdown("**📋 Senaste körningar**")
    if scan_log:
        df_log = pd.DataFrame(scan_log[-10:][::-1])
        show_cols = [c for c in ["timestamp", "mode", "status", "duration_sec", "n_holdings", "n_stoploss"] if c in df_log.columns]
        st.dataframe(df_log[show_cols] if show_cols else df_log, use_container_width=True, hide_index=True)
    else:
        st.info("Inga körningar loggade ännu")

    # Row 4: Scan-prestanda (Item 7)
    if scan_log and len(scan_log) > 2:
        try:
            import plotly.graph_objects as go
            st.markdown("**📈 Scan-prestanda (senaste 30 körningar)**")
            df_perf = pd.DataFrame(scan_log[-30:])
            if "duration_sec" in df_perf.columns and "timestamp" in df_perf.columns:
                df_perf["ts"] = pd.to_datetime(df_perf["timestamp"], errors="coerce")
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_perf["ts"], y=df_perf["duration_sec"],
                    mode="lines+markers", name="Körtid (sek)",
                    line=dict(color="#4c9be8"),
                ))
                fig.update_layout(
                    height=200, margin=dict(l=0, r=0, t=20, b=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(gridcolor="#252b3b"),
                    yaxis=dict(gridcolor="#252b3b", title="sekunder"),
                    font=dict(color="#8892a4"),
                )
                st.plotly_chart(fig, use_container_width=True)

                if len(df_perf) >= 5:
                    avg_recent = df_perf["duration_sec"].tail(5).mean()
                    avg_baseline = df_perf["duration_sec"].mean()
                    if avg_recent > avg_baseline * 1.5:
                        st.warning(
                            f"⚠️ Scan-körtid har ökat: senaste 5 körningar avg {avg_recent:.0f}s "
                            f"vs historiskt {avg_baseline:.0f}s"
                        )
        except ImportError:
            pass  # plotly ej installerat

    # Row 5: GitHub sync status
    st.markdown("---")
    st.markdown("**🔄 GitHub-synkstatus**")
    _render_github_sync_status()

    # Row 6: Senaste aktivitet (Item 4b)
    st.markdown("---")
    st.markdown("**👤 Senaste aktivitet**")
    activity_log = _load_activity_log()
    if activity_log:
        df_act = pd.DataFrame(activity_log[-20:][::-1])
        st.dataframe(df_act, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen aktivitet loggad ännu")



def _render_ai_log_tab():
    st.subheader("🤖 AI-användning")

    ai_log = _load_ai_usage_log()
    if not ai_log:
        st.info("Ingen AI-användning loggad ännu. Loggen skapas automatiskt vid nästa AI-anrop.")
        return

    df = pd.DataFrame(ai_log)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    col1, col2, col3, col4 = st.columns(4)
    today = pd.Timestamp.now().date()
    week_ago = today - pd.Timedelta(days=7)

    cached_col = df.get("cached", pd.Series([False] * len(df), index=df.index)).fillna(False)
    df_real = df[~cached_col]

    with col1:
        st.metric("Totalt anrop", len(df))
    with col2:
        st.metric("Idag", len(df[df["date"].dt.date == today]))
    with col3:
        cache_rate = (cached_col.sum() / len(df) * 100) if len(df) > 0 else 0
        st.metric("Cache-träffar", f"{cache_rate:.0f}%")
    with col4:
        if "est_cost_usd" in df.columns:
            cost_7d = df_real[df_real["date"].dt.date >= week_ago]["est_cost_usd"].sum()
        else:
            cost_7d = 0.0
        st.metric("Uppsk. kostnad (7d)", f"${cost_7d:.4f}")

    st.markdown("---")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Anrop per provider**")
        if "provider" in df.columns:
            st.dataframe(df.groupby("provider").size().reset_index(name="Antal"),
                         use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**Mest analyserade tickers**")
        if "ticker" in df.columns:
            top_tickers = df[df["ticker"] != ""]["ticker"].value_counts().head(10).reset_index()
            top_tickers.columns = ["Ticker", "Antal"]
            st.dataframe(top_tickers, use_container_width=True, hide_index=True)

    st.markdown("**Senaste anrop**")
    show = df.sort_values("date", ascending=False).head(50)
    show_cols = [c for c in ["date", "provider", "function", "ticker", "cached", "est_cost_usd"] if c in show.columns]
    st.dataframe(show[show_cols], use_container_width=True, hide_index=True)


def _render_config_tab():
    st.subheader("⚙️ Scoringkonfiguration")
    st.info(
        "Ändringar sparas till data/scoring_config.json och används av nästa pipeline-körning "
        "(override av defaultvärden i config.py)."
    )

    config_path = DATA_DIR / "scoring_config.json"
    try:
        override = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    except Exception:
        override = {}

    from core.config import FACTOR_WEIGHTS, SMALLCAP_CONFIG
    current_weights = override.get("factor_weights", dict(FACTOR_WEIGHTS))

    st.markdown("### 📊 Stora scannen — Faktorsikter")
    st.markdown("Summerar till 1.0. Ändra fördelningen mellan faktorerna.")

    factor_labels = {
        "value":     "Värdering (P/E, P/B, EV/EBITDA)",
        "quality":   "Kvalitet (ROE, ROA, marginaler)",
        "momentum":  "Momentum (12m avkastning, trend)",
        "growth":    "Tillväxt (omsättning, vinst YoY)",
        "sentiment": "Sentiment (insider, nyheter)",
        "risk":      "Risk (volatilitet, D/E)",
        "dividend":  "Utdelning (yield, payout ratio)",
        "size":      "Storlek (market cap)",
    }

    new_weights = {}
    factor_items = list(current_weights.items())
    cols_per_row = 2
    for i in range(0, len(factor_items), cols_per_row):
        row_cols = st.columns(cols_per_row)
        for j, (factor, default_w) in enumerate(factor_items[i:i + cols_per_row]):
            label = factor_labels.get(factor, factor)
            new_weights[factor] = row_cols[j].slider(
                label, min_value=0.0, max_value=0.40,
                value=float(current_weights.get(factor, default_w)),
                step=0.01, key=f"weight_{factor}",
            )

    total = sum(new_weights.values())
    color = "green" if abs(total - 1.0) < 0.01 else "red"
    st.markdown(f"**Total: :{color}[{total:.2f}]** (måste vara 1.00)")

    st.markdown("---")
    st.markdown("### 🏦 Småbolag — Filtertröskelvar")

    sc_cfg = override.get("smallcap_config", {})
    sc_defaults = dict(SMALLCAP_CONFIG)

    col1, col2 = st.columns(2)
    with col1:
        new_min_turnover = st.number_input(
            "Min daglig omsättning (SEK)",
            value=int(sc_cfg.get("min_daily_turnover_sek", sc_defaults.get("min_daily_turnover_sek", 150000))),
            step=10000, min_value=0, key="sc_min_turnover",
        )
        new_min_mcap = st.number_input(
            "Min börsvärde (SEK)",
            value=int(sc_cfg.get("min_market_cap_sek", sc_defaults.get("min_market_cap_sek", 20000000))),
            step=1000000, min_value=0, key="sc_min_mcap",
        )
        new_max_mcap = st.number_input(
            "Max börsvärde (SEK)",
            value=int(sc_cfg.get("max_market_cap_sek", sc_defaults.get("max_market_cap_sek", 10000000000))),
            step=100000000, min_value=0, key="sc_max_mcap",
        )
    with col2:
        new_max_de = st.number_input(
            "Max skuldsättning D/E (%)",
            value=int(sc_cfg.get("max_debt_to_equity", sc_defaults.get("max_debt_to_equity", 300))),
            step=10, min_value=0, key="sc_max_de",
        )
        new_min_cr = st.number_input(
            "Min current ratio",
            value=float(sc_cfg.get("min_current_ratio", sc_defaults.get("min_current_ratio", 0.5))),
            step=0.1, min_value=0.0, key="sc_min_cr",
        )
        new_max_piotroski_skip = st.number_input(
            "Max Piotroski F-Score för eliminering",
            value=int(sc_cfg.get("max_piotroski_skip", sc_defaults.get("max_piotroski_skip", 2))),
            step=1, min_value=0, max_value=4, key="sc_piotroski",
        )

    if st.button(
        "💾 Spara konfiguration", key="btn_save_config", type="primary",
        disabled=(abs(total - 1.0) >= 0.01),
    ):
        new_override = {
            "factor_weights": new_weights,
            "smallcap_config": {
                "min_daily_turnover_sek": new_min_turnover,
                "min_market_cap_sek":     new_min_mcap,
                "max_market_cap_sek":     new_max_mcap,
                "max_debt_to_equity":     new_max_de,
                "min_current_ratio":      new_min_cr,
                "max_piotroski_skip":     new_max_piotroski_skip,
            },
        }
        config_path.write_text(json.dumps(new_override, indent=2, ensure_ascii=False), encoding="utf-8")
        token = _get_github_token()
        if token:
            _github_commit_file(
                "data/scoring_config.json",
                json.dumps(new_override, indent=2, ensure_ascii=False),
                token,
            )
        st.success("✅ Konfiguration sparad och commitad till GitHub!")
        st.rerun()

    if config_path.exists():
        if st.button("🔄 Återställ till standardvärden", key="btn_reset_config"):
            config_path.unlink()
            st.success("Standardvärden återställda")
            st.rerun()


def _render_cache_tab():
    st.subheader("🗄️ Cache-hantering")

    cache_dir    = DATA_DIR / "cache"
    ai_cache_dir = DATA_DIR / "ai_cache"

    def _cache_stats(d: Path) -> dict:
        if not d.exists():
            return {"count": 0, "size_mb": 0, "oldest": None, "newest": None}
        files = list(d.glob("*"))
        if not files:
            return {"count": 0, "size_mb": 0, "oldest": None, "newest": None}
        mtimes = [f.stat().st_mtime for f in files]
        sizes  = [f.stat().st_size  for f in files]
        return {
            "count":    len(files),
            "size_mb":  round(sum(sizes) / 1024 / 1024, 1),
            "oldest":   datetime.fromtimestamp(min(mtimes)).strftime("%Y-%m-%d"),
            "newest":   datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d"),
        }

    price_stats = _cache_stats(cache_dir)
    ai_stats    = _cache_stats(ai_cache_dir)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Priscache-filer",    price_stats["count"])
    col2.metric("Priscache-storlek",  f"{price_stats['size_mb']} MB")
    col3.metric("AI-cache-filer",     ai_stats["count"])
    col4.metric("AI-cache-storlek",   f"{ai_stats['size_mb']} MB")

    st.markdown("---")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**🗑️ Rensa priscache**")
        days_old = st.slider("Rensa filer äldre än (dagar)", 1, 90, 30, key="cache_days_slider")
        if st.button(f"🗑️ Rensa priscache > {days_old} dagar", key="btn_clear_price_cache"):
            if cache_dir.exists():
                cutoff = time.time() - days_old * 86400
                removed = 0
                for f in cache_dir.glob("*"):
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink()
                            removed += 1
                    except Exception:
                        pass
                st.success(f"✅ Raderade {removed} cache-filer")
                st.rerun()

        st.markdown("**🗑️ Rensa cache för specifik ticker**")
        clear_ticker = st.text_input("Ticker (t.ex. VOLV-B.ST)", key="cache_clear_ticker").upper().strip()
        if st.button("🗑️ Rensa", key="btn_clear_ticker_cache") and clear_ticker:
            if cache_dir.exists():
                safe = clear_ticker.replace(".", "_").replace("-", "_").replace("/", "_")
                removed = 0
                for pattern in [f"{safe}*", f"*{safe}*"]:
                    for f in cache_dir.glob(pattern):
                        try:
                            f.unlink()
                            removed += 1
                        except Exception:
                            pass
                st.success(f"✅ Raderade {removed} cache-filer för {clear_ticker}")

    with col_b:
        st.markdown("**🗑️ Rensa AI-cache**")
        ai_days = st.slider("Rensa AI-cache äldre än (dagar)", 1, 30, 7, key="ai_cache_days_slider")
        if st.button(f"🗑️ Rensa AI-cache > {ai_days} dagar", key="btn_clear_ai_cache"):
            if ai_cache_dir.exists():
                cutoff = time.time() - ai_days * 86400
                removed = 0
                for f in ai_cache_dir.glob("*"):
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink()
                            removed += 1
                    except Exception:
                        pass
                st.success(f"✅ Raderade {removed} AI-cache-filer")
                st.rerun()

        st.markdown("**⚠️ Rensa ALL cache**")
        if st.button("🔴 Rensa ALL priscache (alla filer)", key="btn_clear_all_cache"):
            if cache_dir.exists():
                removed = 0
                for f in cache_dir.glob("*"):
                    try:
                        f.unlink()
                        removed += 1
                    except Exception:
                        pass
                st.success(f"✅ All priscache rensad ({removed} filer)")
                st.rerun()

        st.markdown("**🤖 Rensa ALL AI-cache**")
        if st.button("🔴 Rensa ALL AI-cache (alla analyser)", key="btn_clear_all_ai_cache"):
            try:
                from core.ai_analysis import clear_cache as _clear_ai_cache
                msg = _clear_ai_cache()
                st.success(msg)
                st.rerun()
            except Exception as e:
                st.error(f"Fel: {e}")


def _render_alarms_tab():
    st.subheader("🚨 Aktiva larm (alla användare)")

    all_alarms = []
    users_dir = DATA_DIR / "users"

    def _load_alarms_from_dir(d: Path, username: str) -> list:
        alarm_files = ["alarms.json", "price_alarms.json", "news_alarms.json", "stop_loss.json"]
        result = []
        for fname in alarm_files:
            p = d / fname
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                item["_username"] = username
                                item["_file"] = fname
                                result.append(item)
                    elif isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, list):
                                for item in v:
                                    if isinstance(item, dict):
                                        item["_username"] = username
                                        item["_file"] = fname
                                        result.append(item)
                except Exception:
                    pass
        return result

    all_alarms.extend(_load_alarms_from_dir(DATA_DIR, "admin"))
    if users_dir.exists():
        for user_dir in users_dir.iterdir():
            if user_dir.is_dir():
                all_alarms.extend(_load_alarms_from_dir(user_dir, user_dir.name))

    if all_alarms:
        df_alarms = pd.DataFrame(all_alarms)
        st.dataframe(df_alarms, use_container_width=True, hide_index=True)
        st.caption(f"Totalt {len(all_alarms)} aktiva larmregler")
    else:
        st.info("Inga aktiva larm hittades")

    st.markdown("---")
    st.markdown("**📄 Paper Trading — Aktiva positioner med stop-loss**")
    paper_path = DATA_DIR / "paper_trades.json"
    if paper_path.exists():
        try:
            trades = json.loads(paper_path.read_text(encoding="utf-8"))
            active = [t for t in trades if t.get("status") in ("OPEN", "open", None)]
            if active:
                df_pt = pd.DataFrame(active)
                show_cols = [c for c in ["ticker", "entry_price", "stop_loss", "take_profit", "entry_date", "status"] if c in df_pt.columns]
                st.dataframe(df_pt[show_cols] if show_cols else df_pt, use_container_width=True, hide_index=True)
            else:
                st.info("Inga öppna paper trading-positioner")
        except Exception as e:
            st.warning(f"Kunde inte läsa paper_trades.json: {e}")
    else:
        st.info("Ingen paper trading-fil hittades")


# ══════════════════════════════════════════════════════════════════════════════
# FELSÖKNINGSFLIK
# ══════════════════════════════════════════════════════════════════════════════

def _render_debug_tab():
    """Diagnostik-flik under Admin – pipeline-status, felhistorik, data coverage."""
    st.subheader("🔍 Systemdiagnostik")
    st.caption("Här ser du status på pipeline-körningar, felhistorik och datakvalitet.")

    scan_log = _load_scan_log()
    blacklist_path = DATA_DIR / "blacklist.json"
    strike_path = DATA_DIR / "strike_list.json"

    # ── 1. Pipeline-statuskort ────────────────────────────────────────────────
    st.markdown("### 📊 Pipeline-status")

    if scan_log:
        last = scan_log[-1]
        last_status = last.get("status", "?")
        icon = "✅" if last_status == "OK" else "❌" if last_status == "ERROR" else "⚠️"
        last_type = last.get("scan_type", "?")
        last_time = last.get("timestamp", "?")[:16].replace("T", " ")
        last_detail = last.get("details", {})
        last_elapsed = last_detail.get("elapsed_seconds", "—")
        last_n = last_detail.get("n_scored", last_detail.get("n_tickers", "—"))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Senaste körning", f"{icon} {last_type}", last_time)
        c2.metric("Status", last_status)
        c3.metric("Tickers", str(last_n))
        c4.metric("Körtid", f"{last_elapsed}s" if isinstance(last_elapsed, (int, float)) else "—")

        # Felhistorik (senaste 10)
        errors = [e for e in reversed(scan_log) if e.get("status") == "ERROR"][:10]
        if errors:
            st.markdown("#### ❌ Senaste pipeline-fel")
            rows = []
            for e in errors:
                ts = e.get("timestamp", "?")[:16].replace("T", " ")
                typ = e.get("scan_type", "?")
                err = e.get("error", "")
                remedy = e.get("remediation", "")
                # Korta ner fel till 120 tecken
                short_err = err[:120] + "..." if len(err) > 120 else err
                rows.append({"Tid": ts, "Typ": typ, "Fel": short_err, "Åtgärd": remedy})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Senaste 5 OK-körningar
        ok_runs = [e for e in reversed(scan_log) if e.get("status") == "OK"][:5]
        if ok_runs:
            st.markdown("#### ✅ Senaste OK-körningar")
            rows = []
            for e in ok_runs:
                d = e.get("details", {})
                rows.append({
                    "Tid": e.get("timestamp", "?")[:16].replace("T", " "),
                    "Typ": e.get("scan_type", "?"),
                    "Tickers": d.get("n_scored", d.get("n_tickers", "—")),
                    "Portfölj": d.get("n_holdings", "—"),
                    "Körtid": f"{d.get('elapsed_seconds', '—')}s",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen pipeline-logg hittades ännu. Första körningen skapar den automatiskt.")

    # ── 2. Blacklist ──────────────────────────────────────────────────────────
    st.markdown("---")
    col_bl, col_st = st.columns(2)
    with col_bl:
        st.markdown("### 🚫 Blacklist")
        try:
            bl = json.loads(blacklist_path.read_text(encoding="utf-8")) if blacklist_path.exists() else {}
            if bl:
                bl_rows = []
                for ticker, info in bl.items():
                    bl_rows.append({
                        "Ticker": ticker,
                        "Anledning": info.get("reason", "?"),
                        "Datum": info.get("date", "?"),
                    })
                st.dataframe(pd.DataFrame(bl_rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(bl)} tickers blacklistade")
            else:
                st.info("Blacklist är tom.")
        except Exception as e:
            st.warning(f"Kunde inte läsa blacklist: {e}")

    with col_st:
        st.markdown("### ⚠️ Strikes (varningar)")
        try:
            sl = json.loads(strike_path.read_text(encoding="utf-8")) if strike_path.exists() else {}
            if sl:
                sl_rows = []
                for ticker, info in sl.items():
                    sl_rows.append({
                        "Ticker": ticker,
                        "Strikes": info.get("count", 0),
                        "Senast": info.get("date", "?"),
                    })
                st.dataframe(pd.DataFrame(sl_rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(sl)} tickers med strikes")
            else:
                st.info("Strike-listan är tom — inga tickers på väg mot blacklist.")
        except Exception as e:
            st.warning(f"Kunde inte läsa strike_list: {e}")

    # ── 3. Cache-ålder ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🗄️ Cache-status")
    _render_cache_age()

    # ── 4. API-nycklar ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🔑 API-nycklar")
    _check_api_key("DEEPSEEK_API_KEY", "DeepSeek", core_required=True)
    _check_api_key("GEMINI_API_KEY", "Gemini (fallback)")
    _check_api_key("FMP_API_KEY", "FMP (earnings)")
    _check_api_key("FINNHUB_API_KEY", "Finnhub (sentiment)")
    _check_api_key("EMAIL_SENDER", "E-post (avsändare)")
    _check_api_key("EMAIL_PASSWORD", "E-post (lösenord)")
    _check_api_key("EMAIL_TO", "E-post (mottagare)")
    _check_api_key("GITHUB_TOKEN", "GitHub (synk)")

    # ── 4. Data coverage ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 Datatäckning (senaste scored_universe)")
    _render_data_coverage()

    # ── 6. Vanliga fel och lösningar ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("### ❓ Vanliga fel & felsökning")
    with st.expander("❌ Pipeline misslyckades med 'ModuleNotFoundError'"):
        st.markdown("""
**Orsak:** En dependency saknas i `requirements.txt` eller pip-installationen misslyckades.

**Lösning:** Kolla GitHub Actions-loggen — vilket modul saknas? Lägg till i `requirements.txt` och pusha.
Om det är `curl_cffi` eller `mistune` — kör `pip install -r requirements.txt` lokalt först för att verifiera att pip hittar paketet.
        """)
    with st.expander("❌ Pipeline timeout (30 min)"):
        st.markdown("""
**Orsak:** yfinance hänger på en eller flera tickers. Kör `targeted`-läge eller `refresh_missing` för att
reparera specifika tickers utan att göra en full scan.

**Lösning:** Identifiera problemtickers via GitHub Actions-loggen. Användワークフロー `workflow_dispatch` → `targeted` för att bara uppdatera dem.
        """)
    with st.expander("❌ 'ValueError: If using all scalar values'"):
        st.markdown("""
**Orsak:** `dict` → `DataFrame` med skalärvärden. Använd `pd.concat(list, axis=1)` istället för `pd.DataFrame(dict)`.

**Var:** Se `web/streamlit_app.py:1817` för guard.
        """)
    with st.expander("❌ Streamlit Cloud kraschar efter deploy"):
        st.markdown("""
**Orsak:** Oftast en import som inte finns i Streamlit Cloud-miljön, eller en fil som inte commitats.

**Lösning:** Kolla Streamlit Cloud → Manage app → Logs. Vanligaste:
- `ModuleNotFoundError` — saknat paket i `requirements.txt`
- `FileNotFoundError` — fil som inte commitats (kolla `.gitignore`)
- `st.secrets` saknas — lägg till i Streamlit Cloud → Settings → Secrets
        """)
    with st.expander("❌ 'KeyError: ev_to_ebitda' eller 'KeyError: price_to_sales'"):
        st.markdown("""
**Orsak:** `calc_value_score()` förutsätter att vissa kolumner finns i datan. Detta är normalt — pipelinen
tillhandahåller alltid full data via yfinance. Om felet uppstår är det troligen i en testmiljö eller
om `fetch_universe_data` returnerade ofullständig data för just den tickern.

**Lösning:** Kör `targeted`-läge för den tickern, eller kolla om tickern är delisted.
        """)
    with st.expander("❌ Streamlit Cloud sleepar — data försvinner"):
        st.markdown("""
**Orsak:** Streamlit Cloud lägger appen i sleep efter ~30 minuters inaktivitet (gratis-plan).
Filsystemet är ephemeral — ändringar som inte commitats till GitHub försvinner.

**Lösning:** Keep-alive-workflowet (`keep_alive.yml`) pingar appen var 20:e minut för att förhindra sleep.
Se `.github/workflows/keep_alive.yml`.
För data som måste sparas: använd GitHub-commit från Streamlit (via `_github_commit_file()`).
        """)


def _render_cache_age():
    """Visa cache-filernas ålder och antal."""
    cache_dir = DATA_DIR / "cache"
    if not cache_dir.exists():
        st.info("Cache-katalogen finns inte ännu — första pipeline-körningen skapar den.")
        return

    files = list(cache_dir.glob("*.pkl"))
    if not files:
        st.info("Cache-katalogen är tom.")
        return

    now = datetime.now()
    ages = []
    for f in files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        age_h = (now - mtime).total_seconds() / 3600
        ages.append(age_h)

    oldest = max(ages) if ages else 0
    newest = min(ages) if ages else 0
    avg_age = sum(ages) / len(ages) if ages else 0

    total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cache-filer", str(len(files)))
    c2.metric("Totalt storlek", f"{total_size:.0f} MB")
    c3.metric("Äldsta", f"{oldest:.0f}h" if oldest < 720 else f"{oldest/24:.0f}d")
    c4.metric("Nyaste", f"{newest:.0f}h" if newest < 24 else f"{newest/24:.0f}d")
    c5.metric("Medelålder", f"{avg_age:.0f}h" if avg_age < 24 else f"{avg_age/24:.0f}d")

    # Flagga om åldern är oroväckande
    if oldest > 720:  # > 30 dagar = static fundamentals som inte uppdaterats
        st.warning(f"⚠️ Äldsta cache-fil är {oldest/24:.0f} dagar — statiska fundamenta borde refreshas snart.")
    if oldest > 1440:  # > 60 dagar
        st.error(f"🚨 Äldsta cache-fil är {oldest/24:.0f} dagar — data kan vara inaktuell!")


def _check_api_key(key_name: str, label: str, core_required: bool = False):
    """Visa grön/röd indikator för en API-nyckel."""
    try:
        from web.pages.admin import _get_st_secret
        val = _get_st_secret(key_name)
    except Exception:
        val = ""
    has = bool(val and val.strip())
    status = "✅ Tillgänglig" if has else ("❌ SAKNAS (krävs!)" if core_required else "⚠️ Saknas (valfri)")
    st.markdown(f"- {status} — **{label}** (`{key_name}`)")


def _render_data_coverage():
    """Visa datatäckning per faktor från senaste scored_universe."""
    import glob
    parquet_files = sorted(REPORT_DIR.glob("scored_universe_*.parquet"))
    csv_files = sorted(REPORT_DIR.glob("scored_universe_*.csv"))

    latest = None
    if parquet_files:
        try:
            latest = pd.read_parquet(parquet_files[-1])
        except Exception:
            pass
    if latest is None and csv_files:
        try:
            latest = pd.read_csv(csv_files[-1], low_memory=False)
        except Exception:
            pass

    if latest is None or latest.empty:
        st.info("Ingen scored_universe-fill hittades — kör en pipeline först.")
        return

    st.caption(f"Baserad på senaste filen ({len(latest)} tickers)")

    # Kolumner som borde finnas
    vital_cols = {
        "score_value": "Value",
        "score_quality": "Quality",
        "score_momentum": "Momentum",
        "score_growth": "Growth",
        "score_risk": "Risk",
        "score_size": "Size",
        "score_dividend": "Dividend",
        "score_sentiment": "Sentiment",
        "score_total": "Total Score",
        "entry_signal": "Entry Signal",
    }
    raw_cols = {
        "pe_trailing": "P/E",
        "roe": "ROE",
        "return_12m": "Return 12m",
        "revenue_growth": "Revenue Growth",
        "debt_to_equity": "D/E",
        "volatility": "Volatility",
        "market_cap": "Market Cap",
        "dividend_yield": "Div Yield",
        "free_cash_flow": "FCF",
    }

    rows = []
    for col, label in {**vital_cols, **raw_cols}.items():
        if col in latest.columns:
            pct = latest[col].notna().mean() * 100
            missing = latest[col].isna().sum()
        else:
            pct = 0.0
            missing = len(latest)
        rows.append({"Faktor/Mått": label, "Kolumn": col, "Täckning": f"{pct:.0f}%",
                     "Saknas": str(missing)})

    df_cov = pd.DataFrame(rows)

    # Färgkoda täckning
    def _color_pct(val):
        try:
            p = float(val.strip("%"))
            if p >= 95:
                return "color: #16a34a"
            if p >= 70:
                return "color: #f59e0b"
            return "color: #dc2626; font-weight: bold"
        except Exception:
            return ""

    styled = df_cov.style.applymap(_color_pct, subset=["Täckning"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption("Röd = <70%, Gul = 70-95%, Grön = >95%")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN-SIDA
# ══════════════════════════════════════════════════════════════════════════════

def page_admin():
    """Admin-sida – kräver lösenord."""

    if not _check_admin_access():
        if st.session_state.get("admin_authenticated", False):
            if st.button("🚪 Logga ut från admin", key="btn_admin_logout"):
                st.session_state["admin_authenticated"] = False
                st.rerun()
        return

    st.title("🔧 Admin – Hantera portfölj, bevakning & scannar")

    (tab_overview, tab_wl, tab_hold, tab_scan, tab_import,
     tab_health, tab_email, tab_users,
     tab_config, tab_cache, tab_ai_log, tab_alarms, tab_debug) = st.tabs([
        "📊 Översikt", "⭐ Bevakningslista", "💼 Portfölj", "🚀 Starta scan",
        "📥 Avanza-import", "🩺 Universe Health", "📧 E-post", "👥 Användare",
        "⚙️ Konfiguration", "🗄️ Cache", "🤖 AI-logg", "🚨 Larm",
        "🔍 Felsökning",
    ])

    # ── Flik 0: Översikt ─────────────────────────────────────────────────────
    with tab_overview:
        _render_overview_tab()

    # ── Flik 1: Bevakningslista ────────────────────────────────────────────────
    with tab_wl:
        st.subheader("⭐ Bevakningslista")

        items = load_watchlist()

        if items:
            wl_df = pd.DataFrame(items)
            st.dataframe(wl_df, use_container_width=True, hide_index=True)

            remove_ticker = st.selectbox(
                "Ta bort ticker", [""] + [i["ticker"] for i in items],
                key="wl_remove"
            )
            if remove_ticker and st.button("🗑️ Ta bort", key="btn_wl_remove"):
                items = [i for i in items if i["ticker"] != remove_ticker]
                _save_watchlist_data(items)
                st.success(f"`{remove_ticker}` borttagen från bevakningslistan!")
                st.rerun()
        else:
            st.info("Bevakningslistan är tom.")

        st.markdown("---")
        st.markdown("### Lägg till ny ticker")

        search_q = st.text_input("Sök aktie (ticker eller namn)", key="wl_search",
                                 placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
        if search_q:
            hits = _search_ticker_yfinance(search_q)
            if hits:
                options = {f"{h['ticker']} — {h['name'][:40]}": h for h in hits}
                selected = st.selectbox("Välj från sökresultat", list(options.keys()),
                                        key="wl_hit")
                if selected:
                    h = options[selected]
                    col1, col2 = st.columns([2, 1])
                    if col1.button("✅ Lägg till i bevakningslistan", key="btn_wl_add"):
                        new_ticker = h["ticker"]
                        exists = any(i["ticker"] == new_ticker for i in items)
                        if not exists:
                            items.append({
                                "ticker": new_ticker,
                                "name": h["name"],
                                "added": str(date.today()),
                            })
                            _save_watchlist_data(items)
                            st.success(f"`{new_ticker}` tillagd i bevakningslistan!")
                            st.rerun()
                        else:
                            st.info(f"`{new_ticker}` finns redan i bevakningslistan.")
            else:
                st.caption("Inga sökresultat. Prova med annat sökord.")

        with st.expander("Eller lägg till manuellt (ticker)"):
            manual_ticker = st.text_input("Ticker (t.ex. AAPL)", key="wl_manual",
                                          max_chars=15,
                                          placeholder="Ticker-symbol").upper().strip()
            manual_name = st.text_input("Namn (valfritt)", key="wl_manual_name")
            if st.button("➕ Lägg till", key="btn_wl_manual"):
                if manual_ticker:
                    ok, err = validate_ticker(manual_ticker)
                    if not ok:
                        st.error(f"❌ Ogiltig ticker: {err}")
                    else:
                        exists = any(i["ticker"] == manual_ticker for i in items)
                        if not exists:
                            items.append({
                                "ticker": manual_ticker,
                                "name": manual_name or manual_ticker,
                                "added": str(date.today()),
                            })
                            _save_watchlist_data(items)
                            st.success(f"`{manual_ticker}` tillagd!")
                            st.rerun()
                        else:
                            st.info(f"`{manual_ticker}` finns redan.")
                else:
                    st.warning("Ange en ticker.")

    # ── Flik 2: Portfölj ──────────────────────────────────────────────────
    with tab_hold:
        st.subheader("💼 Portfölj (holdings.csv)")

        holdings = load_portfolio()

        col_del_left, col_del_right = st.columns([3, 1])
        with col_del_left:
            if not holdings.empty:
                remove_h = st.selectbox(
                    "Välj innehav att ta bort",
                    [""] + holdings["ticker"].tolist(),
                    key="hold_remove"
                )
            else:
                remove_h = ""
        with col_del_right:
            if remove_h and st.button("🗑️ Ta bort", key="btn_hold_remove",
                                      use_container_width=True):
                holdings = load_portfolio()
                if remove_h in holdings["ticker"].values:
                    holdings = holdings[holdings["ticker"] != remove_h]
                    ok = _save_holdings_df(holdings)
                    if ok:
                        st.cache_data.clear()
                        st.success(f"`{remove_h}` borttagen från portföljen!")
                        st.rerun()
                    else:
                        st.error("Kunde inte spara. Kontrollera filrättigheter.")
                else:
                    st.info(f"`{remove_h}` finns inte i portföljen.")

        if not holdings.empty:
            st.dataframe(holdings, use_container_width=True, hide_index=True)
        else:
            st.info("Portföljen är tom. Lägg till innehav nedan.")

        st.markdown("---")
        st.markdown("### Lägg till / uppdatera innehav")

        search_h = st.text_input("Sök aktie (ticker eller namn) – valfritt", key="hold_search",
                                 placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
        suggested_ticker = ""
        if search_h:
            hits, search_err = _search_ticker_yfinance(search_h), None
            if isinstance(hits, tuple):
                hits, search_err = hits
            if hits:
                options = {f"{h['ticker']} — {h['name'][:40]}": h for h in hits}
                selected = st.selectbox("Välj från sökresultat", [""] + list(options.keys()),
                                        key="hold_hit")
                if selected:
                    suggested_ticker = options[selected]["ticker"]
            else:
                if search_err:
                    st.warning(f"Sökning misslyckades: {search_err} — ange ticker manuellt nedan.")
                else:
                    st.caption("Inga träffar. Prova att skriva bolagsnamnet på engelska, eller ange tickern direkt (t.ex. INVE-B.ST).")

        if suggested_ticker:
            st.session_state["hold_ticker_input"] = suggested_ticker

        col1, col2, col3 = st.columns(3)
        with col1:
            ticker = st.text_input(
                "Ticker *",
                key="hold_ticker_input",
                placeholder="AAPL"
            ).upper().strip()
        with col2:
            shares = st.number_input("Antal aktier", min_value=0.0, max_value=10_000_000.0,
                                     step=1.0, format="%.2f", key="hold_shares")
        with col3:
            cost = st.number_input("Inköpspris (SEK)", min_value=0.0, max_value=10_000_000.0,
                                   step=1.0, format="%.2f", key="hold_cost")

        saved = st.button("💾 Spara i portföljen", key="btn_hold_save",
                          use_container_width=True, type="primary")

        if saved:
            ticker = st.session_state.get("hold_ticker_input", "").upper().strip()
            shares = st.session_state.get("hold_shares", 0)
            cost = st.session_state.get("hold_cost", 0)

            if not ticker:
                st.warning("Ange en ticker.")
            elif shares <= 0:
                st.warning("Ange antal aktier (> 0).")
            elif cost <= 0:
                st.warning("Ange inköpspris (> 0).")
            else:
                holdings = load_portfolio()
                if ticker in holdings["ticker"].values:
                    holdings.loc[holdings["ticker"] == ticker, "shares"] = shares
                    holdings.loc[holdings["ticker"] == ticker, "cost_basis"] = cost
                    msg = f"`{ticker}` uppdaterad i portföljen!"
                else:
                    new_row = pd.DataFrame([{"ticker": ticker, "shares": shares,
                                              "cost_basis": cost}])
                    holdings = pd.concat([holdings, new_row], ignore_index=True)
                    msg = f"`{ticker}` tillagd i portföljen!"
                ok = _save_holdings_df(holdings)
                if ok:
                    st.cache_data.clear()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error("Kunde inte spara portföljen. Se felmeddelandet ovan.")

    # ── Flik 3: GitHub Actions – starta scannar ─────────────────────────────
    with tab_scan:
        st.subheader("🚀 Starta scanning via GitHub Actions")
        st.caption("Triggar en scanning i GitHub. Scannern körs i molnet (även när din dator är avstängd).")

        _secrets_token = ""
        try:
            if hasattr(st, "secrets"):
                _secrets_token = st.secrets.get("GITHUB_TOKEN", "")
        except Exception:
            _secrets_token = ""
        gh_token = os.getenv("GITHUB_TOKEN") or _secrets_token
        gh_owner = os.getenv("GITHUB_OWNER") or "hankkontakt"
        gh_repo  = os.getenv("GITHUB_REPO")  or "stock-scanner"

        if not gh_token:
            gh_token = st.text_input(
                "GitHub token (krävs för att starta scannar)",
                type="password",
                key="gh_token_input",
                placeholder="ghp_...",
            )
        else:
            st.success("✅ GitHub token läst från miljövariabel/Secrets")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**🌅 Morgonbrief (vardagar)**")
            if st.button("▶️ Starta morgonbrief", key="btn_morning",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Morgonbrief",
                                     inputs={"mode": "morning"})
                st.toast("Morgonbrief startad! ⏳", icon="🌅")

            st.markdown("**🌆 Kvällsbrev (vardagar)**")
            if st.button("▶️ Starta kvällsbrev", key="btn_evening",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Kvällsbrev",
                                     inputs={"mode": "evening"})
                st.toast("Kvällsbrev startad! ⏳", icon="🌆")

        with col_b:
            st.markdown("**📊 Veckoscan (lördagar)**")
            if st.button("▶️ Starta veckoscan", key="btn_weekly",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Veckoscan",
                                     inputs={"mode": "weekly"})
                st.toast("Veckoscan startad! ⏳", icon="📊")

            st.markdown("**🏆 Småbolagsscan (måndagar)**")
            if st.button("▶️ Starta småbolagsscan", key="btn_smallcap",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "daily_scan.yml", "Småbolagsscan",
                                     inputs={"mode": "smallcap"})
                st.toast("Småbolagsscan startad! ⏳", icon="🏆")

        st.markdown("---")
        st.info(
            "Scan-resultaten visas här när GitHub Actions har kört klart och "
            "committat tillbaka CSV-filerna (tar 2–10 min beroende på scannern). "
            "Uppdatera sidan för att se nya resultat."
        )

    # ── Flik 4: Avanza-import ──────────────────────────────────────────────
    with tab_import:
        st.subheader("📥 Importera portfölj från Avanza CSV")
        st.caption("Exportera din portfölj från Avanza som CSV och ladda upp här.")

        from data_management import avanza_import

        uploaded = st.file_uploader("Välj Avanza CSV-fil", type=["csv"],
                                    key="avanza_csv")
        if uploaded is not None:
            try:
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name
                try:
                    df_avanza = avanza_import.parse_avanza_csv(tmp_path)
                finally:
                    os.unlink(tmp_path)

                if df_avanza.empty:
                    st.error(
                        "Kunde inte läsa filen. Kontrollera att det är en "
                        "Avanza-export (kolumner: namn, antal, inköpspris)."
                    )
                else:
                    st.success(f"Läste {len(df_avanza)} rader från Avanza-filen.")
                    st.caption("Granska och bekräfta importen nedan.")

                    rows = []
                    for _, r in df_avanza.iterrows():
                        rows.append({
                            "name": r.get("name", ""),
                            "shares": r.get("shares", 0),
                            "cost_basis": r.get("cost_basis", 0),
                        })

                    import_data = []
                    for i, row in enumerate(rows):
                        hits = _search_ticker_yfinance(row["name"])
                        suggested = hits[0]["ticker"] if hits else ""
                        with st.container(border=True):
                            cc1, cc2, cc3, cc4, cc5 = st.columns([3, 1, 1, 2, 2])
                            with cc1:
                                st.markdown(f"**{row['name']}**")
                            with cc2:
                                st.markdown(f"Antal: {row['shares']}")
                            with cc3:
                                st.markdown(f"Pris: {row['cost_basis']}")
                            with cc4:
                                ticker_val = st.text_input(
                                    "Ticker", value=suggested,
                                    key=f"import_ticker_{i}",
                                    label_visibility="collapsed",
                                ).upper().strip()
                            with cc5:
                                import_me = st.checkbox("Importera", value=True,
                                                        key=f"import_ok_{i}")
                            import_data.append({
                                "row": row,
                                "ticker": ticker_val,
                                "import": import_me,
                            })

                    if st.button("✅ Bekräfta import", type="primary",
                                 use_container_width=True):
                        holdings = load_portfolio()
                        n_add = 0
                        n_upd = 0
                        for item in import_data:
                            if not item["import"] or not item["ticker"]:
                                continue
                            t = item["ticker"]
                            s = float(item["row"]["shares"])
                            c = item["row"]["cost_basis"]
                            if t in holdings["ticker"].values:
                                holdings.loc[holdings["ticker"] == t, "shares"] = s
                                holdings.loc[holdings["ticker"] == t, "cost_basis"] = c
                                n_upd += 1
                            else:
                                new_row = pd.DataFrame([{
                                    "ticker": t, "shares": s, "cost_basis": c
                                }])
                                holdings = pd.concat([holdings, new_row], ignore_index=True)
                                n_add += 1
                        _save_holdings_df(holdings)
                        st.success(f"Import klar! {n_add} tillagda, {n_upd} uppdaterade.")
                        st.rerun()
            except Exception as e:
                    st.error(f"Fel vid läsning av fil: {e}")

    # ── Flik 5: Universe Health ────────────────────────────────────────────
    with tab_health:
        st.subheader("🩺 Universe Health – underhåll av aktieuniversum")
        st.caption(
            "Upptäck avnoterade/ogiltiga tickers, hantera svartlista "
            "och hitta nya intressanta aktier med AI-hjälp."
        )

        try:
            from core.universe_health import (
                detect_invalid_tickers, suggest_replacements,
                find_new_stocks, run_health_check,
                load_blacklist, add_to_blacklist, remove_from_blacklist,
            )
        except ImportError as e:
            st.error(f"Kunde inte ladda universe_health-modulen: {e}")
            return

        blacklist = load_blacklist()
        st.markdown(f"**Svartlista:** {len(blacklist)} tickers")

        with st.expander("📋 Visa svartlista", expanded=False):
            if blacklist:
                st.dataframe(pd.DataFrame(blacklist), use_container_width=True, hide_index=True)

                remove_bl = st.selectbox(
                    "Ta bort från svartlistan",
                    [""] + [i.get("ticker", "") for i in blacklist],
                    key="bl_remove",
                )
                if remove_bl and st.button("🗑️ Ta bort", key="btn_bl_remove"):
                    if remove_from_blacklist(remove_bl):
                        st.success(f"`{remove_bl}` borttagen från svartlistan!")
                        st.rerun()
            else:
                st.info("Svartlistan är tom.")

        with st.expander("➕ Lägg till i svartlistan manuellt", expanded=False):
            col_bl_t, col_bl_r = st.columns([2, 3])
            with col_bl_t:
                bl_ticker = st.text_input("Ticker", key="bl_add_ticker",
                                          max_chars=15,
                                          placeholder="AAPL").upper().strip()
            with col_bl_r:
                bl_reason = st.text_input("Anledning", key="bl_add_reason",
                                          placeholder="t.ex. avnoterad")
            if st.button("➕ Lägg till i svartlistan", key="btn_bl_add"):
                if bl_ticker:
                    if add_to_blacklist(bl_ticker, bl_reason or "manuell"):
                        st.success(f"`{bl_ticker}` tillagd i svartlistan!")
                        st.rerun()
                    else:
                        st.info(f"`{bl_ticker}` finns redan i svartlistan.")
                else:
                    st.warning("Ange en ticker.")

        st.markdown("---")

        st.markdown("### 🔍 Kör hälsokontroll")
        st.caption("Kontrollerar alla tickers i senaste scandatan mot yfinance.")

        health_provider = st.selectbox(
            "AI-provider för nya aktieförslag",
            ["auto", "deepseek", "gemini"],
            format_func=lambda k: {
                "auto": f"Auto ({config.AI_PROVIDER})",
                "deepseek": "DeepSeek (komplex, kostar)",
                "gemini": "Gemini (enkel, gratis)",
            }.get(k, k),
            key="health_provider",
        )

        if st.button("🩺 Kör hälsokontroll", key="btn_health_check",
                     type="primary", use_container_width=True):
            with st.spinner("Kör hälsokontroll (kan ta några minuter)..."):
                try:
                    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                    if not reports:
                        st.warning("Ingen scandata hittad. Kör en scan först.")
                    else:
                        df_health = pd.read_csv(reports[0], low_memory=False)
                        df_health.columns = df_health.columns.str.strip()

                        result = run_health_check(df=df_health, provider=health_provider)
                        st.success("✅ Hälsokontroll klar!")

                        col_h1, col_h2, col_h3 = st.columns(3)
                        with col_h1:
                            st.metric("Ogiltiga tickers", len(result.get("invalid_tickers", [])))
                        with col_h2:
                            st.metric("Svartlistade", result.get("blacklist_count", 0))
                        with col_h3:
                            st.metric("Nya AI-förslag", len(result.get("new_stocks", [])))

                        invalid = result.get("invalid_tickers", [])
                        if invalid:
                            st.markdown("---")
                            st.error(f"⚠️ Hittade {len(invalid)} ogiltiga/avnoterade tickers!")
                            inv_df = pd.DataFrame(invalid)
                            st.dataframe(inv_df, use_container_width=True, hide_index=True)

                            st.markdown("### 💡 Ersättningsförslag")
                            suggestions = result.get("suggestions", {})
                            for bad_ticker, replacements in suggestions.items():
                                with st.expander(f"`{bad_ticker}` → ersättningsförslag", expanded=True):
                                    if replacements:
                                        rep_df = pd.DataFrame(replacements)
                                        st.dataframe(rep_df, use_container_width=True, hide_index=True)
                                        if st.button(f"➕ Lägg till `{replacements[0]['ticker']}` i bevakningslistan",
                                                     key=f"health_add_{bad_ticker}"):
                                            items = load_watchlist()
                                            if not any(i["ticker"] == replacements[0]["ticker"] for i in items):
                                                items.append({
                                                    "ticker": replacements[0]["ticker"],
                                                    "name": replacements[0].get("name", ""),
                                                    "added": str(date.today()),
                                                })
                                                _save_watchlist_data(items)
                                                st.success(f"{replacements[0]['ticker']} tillagd i bevakningslistan!")
                                                st.rerun()
                                            else:
                                                st.info("Finns redan i bevakningslistan.")
                                    else:
                                        st.caption("Inga ersättningsförslag tillgängliga.")
                        else:
                            st.success("✅ Alla tickers verkar vara giltiga!")

                        new_stocks = result.get("new_stocks", [])
                        if new_stocks:
                            st.markdown("---")
                            st.subheader("🚀 AI-förslag: nya intressanta aktier")
                            st.caption("AI-genererade förslag på aktier att titta närmare på.")
                            for s in new_stocks:
                                ticker_s = s.get("ticker", "?")
                                name_s = s.get("name", "")
                                reason_s = s.get("reason", "")
                                with st.container(border=True):
                                    col_s1, col_s2 = st.columns([3, 1])
                                    with col_s1:
                                        st.markdown(f"**{ticker_s}** – {name_s}")
                                        if reason_s:
                                            st.caption(reason_s)
                                    with col_s2:
                                        if st.button("➕ Lägg till", key=f"health_new_{ticker_s}"):
                                            items = load_watchlist()
                                            if not any(i["ticker"] == ticker_s for i in items):
                                                items.append({
                                                    "ticker": ticker_s,
                                                    "name": name_s or ticker_s,
                                                    "added": str(date.today()),
                                                })
                                                _save_watchlist_data(items)
                                                st.success(f"{ticker_s} tillagd i bevakningslistan!")
                                                st.rerun()
                                            else:
                                                st.info("Finns redan i bevakningslistan.")

                except Exception as e:
                    st.error(f"❌ Hälsokontroll misslyckades: {e}")

        st.markdown("---")
        st.markdown("### ⚡ Snabbkontroll")
        st.caption("Kontrollera om specifika tickers är ogiltiga (utan AI-förslag).")
        if st.button("🔍 Kör snabbkontroll", key="btn_health_quick",
                     use_container_width=True):
            with st.spinner("Kontrollerar tickers..."):
                try:
                    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                    if reports:
                        df_quick = pd.read_csv(reports[0], low_memory=False)
                        df_quick.columns = df_quick.columns.str.strip()
                        invalid = detect_invalid_tickers(df_quick)
                        if invalid:
                            st.error(f"⚠️ Hittade {len(invalid)} ogiltiga tickers")
                            st.dataframe(pd.DataFrame(invalid), use_container_width=True, hide_index=True)
                        else:
                            st.success("✅ Alla tickers verkar giltiga!")
                except Exception as e:
                    st.error(f"❌ {e}")

    # ── Flik 6: E-post-prenumeranter ──────────────────────────────────────────
    with tab_email:
        st.subheader("📧 E-post-prenumeranter")
        st.caption(
            "Hantera vilka som får rapporter och vilka typer de prenumererar på. "
            "Listan sparas i repot via GitHub API – inga ändringar i Secrets krävs."
        )

        try:
            from core.email_template import (
                load_subscribers, save_subscribers, SUBSCRIPTION_TYPES,
                email_configured, send_email as _send_test_email,
            )
        except ImportError as e:
            st.error(f"Kunde inte ladda email_template: {e}")
            return

        if not email_configured():
            st.warning(
                "⚠️ Email är inte konfigurerat. "
                "Sätt `EMAIL_SENDER` och `EMAIL_PASSWORD` i Streamlit Secrets eller config.py."
            )

        subs = load_subscribers()

        if subs:
            sub_rows = []
            for s in subs:
                row = {
                    "E-post": s.get("email", ""),
                    "Namn": s.get("name", ""),
                    "Aktiv": "✅" if s.get("active", True) else "❌",
                    "Tillagd": s.get("added", ""),
                }
                for key, label in SUBSCRIPTION_TYPES.items():
                    row[label] = "✓" if s.get("subscriptions", {}).get(key, False) else ""
                sub_rows.append(row)
            st.dataframe(pd.DataFrame(sub_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Inga prenumeranter ännu. Lägg till den första nedan.")

        st.markdown("---")

        with st.expander("➕ Lägg till ny prenumerant", expanded=len(subs) == 0):
            with st.form("form_add_subscriber", clear_on_submit=True):
                col_e, col_n = st.columns([3, 2])
                with col_e:
                    new_email = st.text_input("E-postadress *", placeholder="namn@example.com")
                with col_n:
                    new_name = st.text_input("Namn (valfritt)", placeholder="Henrik")

                st.markdown("**Prenumerationstyper:**")
                sub_cols = st.columns(2)
                new_subs: dict[str, bool] = {}
                for i, (key, label) in enumerate(SUBSCRIPTION_TYPES.items()):
                    with sub_cols[i % 2]:
                        new_subs[key] = st.checkbox(label, value=(key in ("morning_report", "failure_alerts")),
                                                    key=f"new_sub_{key}")

                submitted_add = st.form_submit_button("➕ Lägg till", type="primary")
                if submitted_add:
                    new_email = new_email.strip().lower()
                    if not new_email or "@" not in new_email:
                        st.error("Ange en giltig e-postadress.")
                    elif any(s["email"] == new_email for s in subs):
                        st.warning(f"`{new_email}` finns redan.")
                    else:
                        subs.append({
                            "email": new_email,
                            "name": new_name.strip(),
                            "active": True,
                            "added": str(date.today()),
                            "subscriptions": new_subs,
                        })
                        save_subscribers(subs)
                        token = _get_github_token()
                        if token:
                            content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                            ok = _github_commit_file("data/email_subscribers.json", content, token)
                            if ok:
                                st.success(f"✅ `{new_email}` tillagd och synkad till GitHub!")
                            else:
                                st.success(f"✅ `{new_email}` tillagd lokalt (GitHub-sync misslyckades).")
                        else:
                            st.success(f"✅ `{new_email}` tillagd lokalt.")
                        st.rerun()

        if subs:
            st.markdown("---")
            st.markdown("### Hantera befintliga prenumeranter")

            email_options = [s["email"] for s in subs]
            sel_email = st.selectbox("Välj prenumerant att hantera", email_options, key="sub_select")
            sel_sub = next((s for s in subs if s["email"] == sel_email), None)

            if sel_sub:
                col_act, col_del, col_test = st.columns(3)

                with col_act:
                    is_active = sel_sub.get("active", True)
                    btn_label = "⏸ Inaktivera" if is_active else "▶️ Aktivera"
                    if st.button(btn_label, key="btn_sub_toggle"):
                        sel_sub["active"] = not is_active
                        save_subscribers(subs)
                        token = _get_github_token()
                        if token:
                            content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                            _github_commit_file("data/email_subscribers.json", content, token)
                        st.rerun()

                with col_del:
                    if st.button("🗑️ Ta bort", key="btn_sub_delete"):
                        subs = [s for s in subs if s["email"] != sel_email]
                        save_subscribers(subs)
                        token = _get_github_token()
                        if token:
                            content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                            _github_commit_file("data/email_subscribers.json", content, token)
                        st.success(f"`{sel_email}` borttagen!")
                        st.rerun()

                with col_test:
                    if st.button("📤 Skicka testmail", key="btn_sub_test"):
                        if email_configured():
                            ok = _send_test_email(
                                subject="📧 MarketScan – testmail",
                                body_markdown=(
                                    "# Testmail\n\nDetta är ett testmail från MarketScan admin-panelen.\n\n"
                                    "Om du ser detta mail fungerar e-postkonfigurationen korrekt!"
                                ),
                                from_name="MarketScan",
                                recipients=[sel_email],
                            )
                            if ok:
                                st.success(f"✅ Testmail skickat till `{sel_email}`!")
                            else:
                                st.error("❌ Misslyckades. Kontrollera EMAIL_SENDER/EMAIL_PASSWORD.")
                        else:
                            st.error("Email är inte konfigurerat.")

                with st.expander(f"Redigera prenumerationer för {sel_email}", expanded=False):
                    with st.form(f"form_edit_{sel_email.replace('@','_').replace('.','_')}"):
                        st.markdown("**Välj prenumerationstyper:**")
                        edit_cols = st.columns(2)
                        edit_subs: dict[str, bool] = {}
                        for i, (key, label) in enumerate(SUBSCRIPTION_TYPES.items()):
                            with edit_cols[i % 2]:
                                current = sel_sub.get("subscriptions", {}).get(key, False)
                                edit_subs[key] = st.checkbox(label, value=current, key=f"edit_{key}_{sel_email}")
                        if st.form_submit_button("💾 Spara ändringar"):
                            sel_sub["subscriptions"] = edit_subs
                            save_subscribers(subs)
                            token = _get_github_token()
                            if token:
                                content = json.dumps({"subscribers": subs}, indent=2, ensure_ascii=False)
                                _github_commit_file("data/email_subscribers.json", content, token)
                            st.success("✅ Prenumerationer uppdaterade!")
                            st.rerun()

        st.markdown("---")
        st.markdown("### 📊 Statistik")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            st.metric("Totalt prenumeranter", len(subs))
        with col_s2:
            st.metric("Aktiva", sum(1 for s in subs if s.get("active", True)))
        with col_s3:
            st.metric("Email konfigurerat", "✅ Ja" if email_configured() else "❌ Nej")

        # ── Leveranshistorik (Item 8b) ──────────────────────────────────────
        st.markdown("---")
        st.markdown("**📬 Leveranshistorik**")
        delivery_log = _load_email_delivery_log()
        if delivery_log:
            df_del = pd.DataFrame(delivery_log[-50:][::-1])
            st.dataframe(df_del, use_container_width=True, hide_index=True)
            total_del = len(delivery_log)
            successes = sum(1 for e in delivery_log if e.get("success"))
            st.caption(f"Totalt: {total_del} utskick | ✅ {successes} lyckade | ❌ {total_del - successes} misslyckade")
        else:
            st.info("Ingen leveranshistorik ännu — loggas automatiskt vid nästa utskick")

    # ── Flik 7: Användare ─────────────────────────────────────────────────────
    with tab_users:
        st.subheader("👥 Användare")
        st.caption(
            "Lägg till och hantera inloggningsuppgifter för andra användare. "
            "Varje användare får sin egen portfölj, bevakningslista och paper trading. "
            "Admin-kontot hanteras separat via Streamlit Secrets."
        )

        try:
            import streamlit_authenticator as stauth
            _stauth_ok = True
        except ImportError:
            st.error("❌ `streamlit-authenticator` saknas. Kör: `pip install streamlit-authenticator`")
            _stauth_ok = False

        if _stauth_ok:
            users = _load_users_config()
            active_users = [u for u in users if u.get("active", True)]
            inactive_users = [u for u in users if not u.get("active", True)]

            # ── Nuvarande användare ──────────────────────────────────────────
            st.markdown(f"**{len(active_users)} aktiva användare** (utöver admin)")
            if active_users:
                user_rows = [
                    {
                        "Användarnamn": u["username"],
                        "Namn":         u.get("name", ""),
                        "E-post":       u.get("email", ""),
                        "Tillagd":      u.get("added", ""),
                        "Aktiv":        "✅",
                    }
                    for u in active_users
                ]
                st.dataframe(pd.DataFrame(user_rows), use_container_width=True, hide_index=True)
            else:
                st.info("Inga extra användare tillagda ännu.")

            # ── Lägg till ny användare ───────────────────────────────────────
            st.markdown("---")
            st.markdown("### ➕ Lägg till ny användare")
            with st.form("form_add_user", clear_on_submit=True):
                col_u, col_n = st.columns(2)
                with col_u:
                    new_uname = st.text_input(
                        "Användarnamn *",
                        placeholder="t.ex. hans",
                        help="Gemener, inga mellanslag. Används vid inloggning.",
                    )
                with col_n:
                    new_name = st.text_input("Visningsnamn", placeholder="t.ex. Hans")

                col_e, col_p = st.columns(2)
                with col_e:
                    new_email = st.text_input("E-post (valfritt)", placeholder="hans@example.com")
                with col_p:
                    new_pw = st.text_input(
                        "Lösenord *",
                        type="password",
                        placeholder="Minst 6 tecken",
                        help="Lagras krypterat (bcrypt). Du ser det aldrig igen.",
                    )

                submitted_add = st.form_submit_button("➕ Skapa användare", type="primary")
                if submitted_add:
                    uname_clean = new_uname.strip().lower().replace(" ", "_")
                    existing_names = [u["username"] for u in users]
                    if not uname_clean:
                        st.error("Ange ett användarnamn.")
                    elif uname_clean == "admin":
                        st.error("Användarnamnet 'admin' är reserverat.")
                    elif uname_clean in existing_names:
                        st.error(f"Användarnamnet `{uname_clean}` används redan.")
                    elif len(new_pw) < 6:
                        st.error("Lösenordet måste vara minst 6 tecken.")
                    else:
                        hashed_pw = stauth.Hasher.hash(new_pw)
                        users.append({
                            "username": uname_clean,
                            "name":     new_name.strip() or uname_clean.capitalize(),
                            "email":    new_email.strip().lower(),
                            "password": hashed_pw,
                            "active":   True,
                            "added":    str(date.today()),
                        })
                        _save_users_config(users)
                        st.success(
                            f"✅ Användaren **{uname_clean}** skapad! "
                            f"De kan nu logga in med det valda lösenordet."
                        )
                        st.rerun()

            # ── Hantera befintliga användare ─────────────────────────────────
            if users:
                st.markdown("---")
                st.markdown("### Hantera befintliga användare")
                manage_options = [u["username"] for u in users]
                sel_uname = st.selectbox("Välj användare", manage_options, key="user_manage_sel")
                sel_user = next((u for u in users if u["username"] == sel_uname), None)

                if sel_user:
                    is_active = sel_user.get("active", True)
                    col_tog, col_del, col_pw = st.columns(3)

                    with col_tog:
                        btn_lbl = "⏸ Inaktivera" if is_active else "▶️ Aktivera"
                        if st.button(btn_lbl, key="btn_user_toggle", use_container_width=True):
                            sel_user["active"] = not is_active
                            _save_users_config(users)
                            st.success(f"{'Inaktiverad' if not sel_user['active'] else 'Aktiverad'}: {sel_uname}")
                            st.rerun()

                    with col_del:
                        if st.button("🗑️ Ta bort", key="btn_user_delete", use_container_width=True):
                            users = [u for u in users if u["username"] != sel_uname]
                            _save_users_config(users)
                            st.success(f"✅ `{sel_uname}` borttagen.")
                            st.rerun()

                    with col_pw:
                        if st.button("🔑 Byt lösenord", key="btn_user_pw", use_container_width=True):
                            st.session_state["user_pw_change_target"] = sel_uname

                    if st.session_state.get("user_pw_change_target") == sel_uname:
                        with st.form(f"form_pw_{sel_uname}"):
                            new_pw2 = st.text_input("Nytt lösenord", type="password", key=f"pw2_{sel_uname}")
                            if st.form_submit_button("💾 Spara nytt lösenord"):
                                if len(new_pw2) < 6:
                                    st.error("Lösenordet måste vara minst 6 tecken.")
                                else:
                                    sel_user["password"] = stauth.Hasher.hash(new_pw2)
                                    _save_users_config(users)
                                    st.session_state.pop("user_pw_change_target", None)
                                    st.success(f"✅ Lösenord uppdaterat för `{sel_uname}`.")
                                    st.rerun()

            if inactive_users:
                with st.expander(f"Inaktiva användare ({len(inactive_users)})", expanded=False):
                    st.dataframe(
                        pd.DataFrame([
                            {"Användarnamn": u["username"], "Namn": u.get("name", ""),
                             "E-post": u.get("email", ""), "Tillagd": u.get("added", "")}
                            for u in inactive_users
                        ]),
                        use_container_width=True, hide_index=True,
                    )

            # ── Portföljöversikt per användare (Item 3) ──────────────────────
            st.markdown("---")
            st.markdown("**💼 Portföljöversikt per användare**")

            all_usernames = ["admin"] + [u["username"] for u in users if u.get("username") != "admin"]
            for uname in all_usernames:
                user_dir = DATA_DIR if uname == "admin" else DATA_DIR / f"users/{uname}"
                holdings_path  = user_dir / "holdings.csv"
                watchlist_path = user_dir / "watchlist.json"

                has_holdings  = holdings_path.exists()
                has_watchlist = watchlist_path.exists()

                label = f"**{uname}**"
                if has_holdings:
                    try:
                        h = pd.read_csv(holdings_path)
                        label += f" — {len(h)} innehav"
                    except Exception:
                        pass
                else:
                    label += " — inga innehav"

                with st.expander(label, expanded=False):
                    col_h, col_w = st.columns(2)
                    with col_h:
                        st.markdown("**💼 Innehav**")
                        if has_holdings:
                            try:
                                h = pd.read_csv(holdings_path)
                                st.dataframe(h, use_container_width=True, hide_index=True)
                                _btn_r, _btn_c = st.columns(2)
                                with _btn_r:
                                    if st.button(f"🔄 Refresh data", key=f"refresh_user_{uname}",
                                                 use_container_width=True):
                                        tickers = h["ticker"].dropna().tolist()
                                        if _trigger_targeted_refresh(tickers):
                                            st.toast(f"Startar refresh för {uname}s {len(tickers)} innehav", icon="🔄")
                                with _btn_c:
                                    _ck = f"confirm_clear_h_{uname}"
                                    if not st.session_state.get(_ck):
                                        if st.button("🗑️ Rensa innehav", key=f"clear_h_{uname}",
                                                     use_container_width=True):
                                            st.session_state[_ck] = True
                                            st.rerun()
                                    else:
                                        st.warning(f"Rensa **alla** {len(h)} innehav för `{uname}`?")
                                        _cy, _cn = st.columns(2)
                                        if _cy.button("✅ Ja, rensa", key=f"clear_h_yes_{uname}",
                                                      use_container_width=True, type="primary"):
                                            empty_csv = "ticker,shares,cost_basis,konto,typ,buy_date,market_value\n"
                                            holdings_path.write_text(empty_csv, encoding="utf-8")
                                            if uname == "admin":
                                                token = _get_github_token()
                                                if token:
                                                    _github_commit_file("data/holdings.csv", empty_csv, token,
                                                                        message=f"Rensa innehav för {uname} (admin)")
                                            st.session_state.pop(_ck, None)
                                            st.success(f"✅ Innehav för `{uname}` rensade.")
                                            st.rerun()
                                        if _cn.button("❌ Avbryt", key=f"clear_h_no_{uname}",
                                                      use_container_width=True):
                                            st.session_state.pop(_ck, None)
                                            st.rerun()
                            except Exception as e:
                                st.warning(f"Kunde inte läsa holdings.csv: {e}")
                        else:
                            st.info("Inga innehav sparade")

                    with col_w:
                        st.markdown("**⭐ Bevakningslista**")
                        if has_watchlist:
                            try:
                                wl = json.loads(watchlist_path.read_text(encoding="utf-8"))
                                if wl:
                                    wl_df = pd.DataFrame(wl)
                                    show_wl_cols = [c for c in ["ticker", "name"] if c in wl_df.columns]
                                    st.dataframe(wl_df[show_wl_cols] if show_wl_cols else wl_df,
                                                 use_container_width=True, hide_index=True)
                                    _wck = f"confirm_clear_wl_{uname}"
                                    if not st.session_state.get(_wck):
                                        if st.button("🗑️ Rensa bevakningslista", key=f"clear_wl_{uname}",
                                                     use_container_width=True):
                                            st.session_state[_wck] = True
                                            st.rerun()
                                    else:
                                        st.warning(f"Rensa **hela** bevakningslistan för `{uname}`?")
                                        _wy, _wn = st.columns(2)
                                        if _wy.button("✅ Ja, rensa", key=f"clear_wl_yes_{uname}",
                                                      use_container_width=True, type="primary"):
                                            empty_wl = "[]"
                                            watchlist_path.write_text(empty_wl, encoding="utf-8")
                                            if uname == "admin":
                                                token = _get_github_token()
                                                if token:
                                                    _github_commit_file("data/watchlist.json", empty_wl, token,
                                                                        message=f"Rensa bevakningslista för {uname} (admin)")
                                            st.session_state.pop(_wck, None)
                                            st.success(f"✅ Bevakningslista för `{uname}` rensad.")
                                            st.rerun()
                                        if _wn.button("❌ Avbryt", key=f"clear_wl_no_{uname}",
                                                      use_container_width=True):
                                            st.session_state.pop(_wck, None)
                                            st.rerun()
                                else:
                                    st.info("Tom bevakningslista")
                            except Exception as e:
                                st.warning(f"Kunde inte läsa watchlist.json: {e}")
                        else:
                            st.info("Ingen bevakningslista")

    # ── Flik 8: Konfiguration ─────────────────────────────────────────────────
    with tab_config:
        _render_config_tab()

    # ── Flik 9: Cache ─────────────────────────────────────────────────────────
    with tab_cache:
        _render_cache_tab()

    # ── Flik 10: AI-logg ─────────────────────────────────────────────────────
    with tab_ai_log:
        _render_ai_log_tab()

    # ── Flik 11: Larm ────────────────────────────────────────────────────────
    with tab_alarms:
        _render_alarms_tab()

    # ── Flik 12: Felsökning ──────────────────────────────────────────────────
    with tab_debug:
        _render_debug_tab()
