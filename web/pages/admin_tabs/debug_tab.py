"""admin/debug_tab.py - Felsökning tab för admin page."""
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR, REPORT_DIR


def render(load_scan_log_fn):
    st.subheader("Systemdiagnostik")
    st.caption("Pipeline-status, felhistorik, datakvalitet.")

    scan_log = load_scan_log_fn()
    blacklist_path = DATA_DIR / "blacklist.json"
    strike_path = DATA_DIR / "strike_list.json"

    # -- 1. Pipeline-statuskort
    st.markdown("### Pipeline-status")

    if scan_log:
        last = scan_log[-1]
        last_status = last.get("status", "?")
        icon = "OK" if last_status == "OK" else ("ERROR" if last_status == "ERROR" else "WARN")
        last_type = last.get("scan_type", "?")
        last_time = last.get("timestamp", "?")[:16].replace("T", " ")
        last_detail = last.get("details", {})
        last_elapsed = last_detail.get("elapsed_seconds", "--")
        last_n = last_detail.get("n_scored", last_detail.get("n_tickers", "--"))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Senaste korning", f"{icon} {last_type}", last_time)
        c2.metric("Status", last_status)
        c3.metric("Tickers", str(last_n))
        c4.metric("Kortid", f"{last_elapsed}s" if isinstance(last_elapsed, (int, float)) else "--")

        errors = [e for e in reversed(scan_log) if e.get("status") == "ERROR"][:10]
        if errors:
            st.markdown("#### Senaste pipeline-fel")
            rows = []
            for e in errors:
                ts = e.get("timestamp", "?")[:16].replace("T", " ")
                typ = e.get("scan_type", "?")
                err = e.get("error", "")
                remedy = e.get("remediation", "")
                short_err = err[:120] + "..." if len(err) > 120 else err
                rows.append({"Tid": ts, "Typ": typ, "Fel": short_err, "Atgard": remedy})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        ok_runs = [e for e in reversed(scan_log) if e.get("status") == "OK"][:5]
        if ok_runs:
            st.markdown("#### Senaste OK-korningar")
            rows = []
            for e in ok_runs:
                d = e.get("details", {})
                rows.append({
                    "Tid": e.get("timestamp", "?")[:16].replace("T", " "),
                    "Typ": e.get("scan_type", "?"),
                    "Tickers": d.get("n_scored", d.get("n_tickers", "--")),
                    "Portfölj": d.get("n_holdings", "--"),
                    "Kortid": f"{d.get('elapsed_seconds', '--')}s",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen pipeline-logg hittades anu.")

    # -- 2. Blacklist & Strikes
    st.markdown("---")
    col_bl, col_st = st.columns(2)
    with col_bl:
        st.markdown("### Blacklist")
        try:
            bl = json.loads(blacklist_path.read_text(encoding="utf-8")) if blacklist_path.exists() else {}
            if bl:
                bl_rows = [{"Ticker": t, "Anledning": v.get("reason", "?"), "Datum": v.get("date", "?")}
                           for t, v in bl.items()]
                st.dataframe(pd.DataFrame(bl_rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(bl)} tickers blacklistade")
            else:
                st.info("Blacklist ar tom.")
        except Exception as e:
            st.warning(f"Kunde inte lasa blacklist: {e}")

    with col_st:
        st.markdown("### Strikes (varningar)")
        try:
            sl = json.loads(strike_path.read_text(encoding="utf-8")) if strike_path.exists() else {}
            if sl:
                sl_rows = [{"Ticker": t, "Strikes": v.get("count", 0), "Senast": v.get("date", "?")}
                           for t, v in sl.items()]
                st.dataframe(pd.DataFrame(sl_rows), use_container_width=True, hide_index=True)
                st.caption(f"{len(sl)} tickers med strikes")
            else:
                st.info("Strike-listan ar tom.")
        except Exception as e:
            st.warning(f"Kunde inte lasa strike_list: {e}")

    # -- 3. Cache-alder
    st.markdown("---")
    st.markdown("### Cache-status")
    _render_cache_age()

    # -- 4. API-nycklar
    st.markdown("---")
    st.markdown("### API-nycklar")
    _check_api_key("DEEPSEEK_API_KEY", "DeepSeek", core_required=True)
    _check_api_key("GEMINI_API_KEY", "Gemini (fallback)")
    _check_api_key("FMP_API_KEY", "FMP (earnings)")
    _check_api_key("FINNHUB_API_KEY", "Finnhub (sentiment)")
    _check_api_key("EMAIL_SENDER", "E-post (avsandare)")
    _check_api_key("EMAIL_PASSWORD", "E-post (losenord)")
    _check_api_key("EMAIL_TO", "E-post (mottagare)")
    _check_api_key("GITHUB_TOKEN", "GitHub (synk)")

    # -- 5. Datatackning
    st.markdown("---")
    st.markdown("### Datatackning (senaste scored_universe)")
    _render_data_coverage()

    # -- 6. FAQ
    st.markdown("---")
    st.markdown("### Vanliga fel & felsokning")
    with st.expander("Pipeline misslyckades med ModuleNotFoundError"):
        st.markdown("""
**Orsak:** En dependency saknas i requirements.txt eller pip-installationen misslyckades.

**Lösning:** Kolla GitHub Actions-loggen — vilket modul saknas? Lägg till i requirements.txt och pusha.
        """)
    with st.expander("Pipeline timeout (30 min)"):
        st.markdown("""
**Orsak:** yfinance hanger pa en eller flera tickers.

**Lösning:** Använd `targeted`-läge eller `refresh_missing` för att reparera specifika tickers.
        """)
    with st.expander("'ValueError: If using all scalar values'"):
        st.markdown("""
**Orsak:** `dict -> DataFrame` med skalarvarden.

**Lösning:** Se `web/streamlit_app.py` för guard.
        """)
    with st.expander("Streamlit Cloud kraschar efter deploy"):
        st.markdown("""
**Orsak:** Import som inte finns i Streamlit Cloud eller fil som inte commitats.

**Lösning:** Kolla Streamlit Cloud → Manage app → Logs.
        """)
    with st.expander("Streamlit Cloud sleepar -- data forsvinner"):
        st.markdown("""
**Orsak:** Gratis-plan sleepar efter ~30 min. Keep-alive-workflowet hindrar detta.

**Lösning:** Se `.github/workflows/keep_alive.yml`.
        """)


def _render_cache_age():
    cache_dir = DATA_DIR / "cache"
    if not cache_dir.exists():
        st.info("Cache-katalogen finns inte anu.")
        return
    files = list(cache_dir.glob("*.pkl"))
    if not files:
        st.info("Cache-katalogen ar tom.")
        return

    now = datetime.now()
    ages = [(datetime.fromtimestamp(f.stat().st_mtime) - now).total_seconds() / 3600 for f in files]
    oldest = max(ages)
    newest = min(ages)
    avg_age = sum(ages) / len(ages)
    total_size = sum(f.stat().st_size for f in files) / (1024 * 1024)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cache-filer", str(len(files)))
    c2.metric("Storlek", f"{total_size:.0f} MB")
    c3.metric("Aldsta", f"{oldest:.0f}h" if oldest < 720 else f"{oldest / 24:.0f}d")
    c4.metric("Nyaste", f"{newest:.0f}h" if newest < 24 else f"{newest / 24:.0f}d")
    c5.metric("Medelalder", f"{avg_age:.0f}h" if avg_age < 24 else f"{avg_age / 24:.0f}d")

    if oldest > 720:
        st.warning(f"Aldsta cache-fil ar {oldest / 24:.0f} dagar -- statiska fundamenta borde refreshas snart.")


def _check_api_key(key_name, label, core_required=False):
    try:
        from web.pages.admin import _get_st_secret
        val = _get_st_secret(key_name)
    except Exception:
        val = ""
    has = bool(val and val.strip())
    status = "OK" if has else ("SAKNAS (kravs)" if core_required else "Saknas (valfri)")
    st.markdown(f"- {status} -- **{label}** (`{key_name}`)")


def _render_data_coverage():
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
        st.info("Ingen scored_universe-fil hittades -- kor en pipeline forst.")
        return

    st.caption(f"Baserad pa senaste filen ({len(latest)} tickers)")

    vital_cols = {
        "score_value": "Value", "score_quality": "Quality",
        "score_momentum": "Momentum", "score_growth": "Growth",
        "score_risk": "Risk", "score_size": "Size",
        "score_dividend": "Dividend", "score_sentiment": "Sentiment",
        "score_total": "Total Score", "entry_signal": "Entry Signal",
    }
    raw_cols = {
        "pe_trailing": "P/E", "roe": "ROE", "return_12m": "Return 12m",
        "revenue_growth": "Revenue Growth", "debt_to_equity": "D/E",
        "volatility": "Volatility", "market_cap": "Market Cap",
        "dividend_yield": "Div Yield", "free_cash_flow": "FCF",
    }

    rows = []
    for col, label in {**vital_cols, **raw_cols}.items():
        if col in latest.columns:
            pct = latest[col].notna().mean() * 100
            missing = latest[col].isna().sum()
        else:
            pct = 0.0
            missing = len(latest)
        rows.append({"Faktor/Matt": label, "Kolumn": col, "Tackning": f"{pct:.0f}%",
                     "Saknas": str(missing)})

    df_cov = pd.DataFrame(rows)
    def _color(val):
        try:
            p = float(val.strip("%"))
            if p >= 95: return "color: #16a34a"
            if p >= 70: return "color: #f59e0b"
            return "color: #dc2626"
        except Exception:
            return ""
    styled = df_cov.style.applymap(_color, subset=["Tackning"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
