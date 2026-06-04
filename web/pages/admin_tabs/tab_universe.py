"""
web/pages/admin_tabs/tab_universe.py
=====================================
Admin — Flik 3: Universe

Sub-tabs:
  - Täckning (coverage bar, universe audit)
  - Kandidater (pending, bulk approve/reject, discovery)
  - Strikes & Blacklist (strikes, blacklist, fetch-fel)
  - Datakvalitet (täckning per faktor)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR, REPORT_DIR


# ── Hjälpfunktioner (strikes/blacklist/universe) ──────────────────────────────

def _load_json(rel_path: str) -> dict:
    p = DATA_DIR / rel_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(rel_path: str, data: dict):
    p = DATA_DIR / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_universe_json() -> dict:
    p = DATA_DIR / "universe.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_universe_json(data: dict):
    p = DATA_DIR / "universe.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def remove_ticker_from_universe_json(ticker: str, data: dict) -> bool:
    ticker = ticker.upper().strip()
    found = False
    for cat, val in data.items():
        if isinstance(val, dict):
            if "tickers" in val:
                before = len(val["tickers"])
                val["tickers"] = [t for t in val["tickers"] if t.upper().strip() != ticker]
                if len(val["tickers"]) < before:
                    found = True
            if "markets" in val:
                for mkt_name in list(val["markets"].keys()):
                    mkt_list = val["markets"][mkt_name]
                    if isinstance(mkt_list, list):
                        before = len(mkt_list)
                        val["markets"][mkt_name] = [t for t in mkt_list if t.upper().strip() != ticker]
                        if len(val["markets"][mkt_name]) < before:
                            found = True
    return found


# ── Hjälpfunktion (datakvalitet) ─────────────────────────────────────────────

FACTOR_COLUMNS: dict[str, list[str]] = {
    "value":         ["free_cash_flow", "enterprise_value", "pe_forward", "pe_trailing",
                       "price_to_book", "price_to_sales"],
    "quality":       ["roe", "roa", "profit_margin", "operating_margin", "gross_margin"],
    "momentum":      ["return_12m", "return_6m", "return_3m", "pct_from_52w_high"],
    "growth":        ["revenue_growth", "earnings_growth", "earnings_quarterly_growth"],
    "risk":          ["debt_to_equity", "current_ratio", "volatility", "beta"],
    "size":          ["market_cap"],
    "dividend":      ["dividend_yield", "payout_ratio"],
    "sentiment":     ["sentiment_raw"],
    "short_interest": ["short_pct_float", "short_ratio"],
    "options_flow":  ["options_flow_signal"],
}

FACTOR_PRIMARY: dict[str, list[str]] = {
    "value":         ["free_cash_flow", "pe_forward", "pe_trailing", "price_to_book"],
    "quality":       ["roe", "profit_margin"],
    "momentum":      ["return_12m", "return_6m"],
    "growth":        ["revenue_growth", "earnings_growth"],
    "risk":          ["debt_to_equity", "volatility"],
    "size":          ["market_cap"],
    "dividend":      ["dividend_yield"],
    "sentiment":     ["sentiment_raw"],
    "short_interest": ["short_pct_float", "short_ratio"],
    "options_flow":  ["options_flow_signal"],
}


def _load_latest_scored() -> pd.DataFrame | None:
    parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
    if parquets:
        try:
            return pd.read_parquet(parquets[0])
        except Exception:
            pass
    csvs = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
    if csvs:
        try:
            return pd.read_csv(csvs[0])
        except Exception:
            pass
    return None


# ── Render ────────────────────────────────────────────────────────────────────

def render():
    st.markdown('<div class="section-header">Universe</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">Hantera aktieuniversumet: täckning, kandidater, kvalitet och blacklist.</div>',
        unsafe_allow_html=True,
    )

    sub_tabs = st.tabs(["Täckning", "Kandidater", "Strikes & Blacklist", "Datakvalitet"])

    # ── Sub-tab 1: Täckning ──────────────────────────────────────────────────
    with sub_tabs[0]:
        st.markdown("#### Univserum-täckning")
        st.caption("Hur stor andel av universe.json representeras i senaste scan-resultatet.")

        try:
            from core import config
            universe_tickers = set(t.upper() for t in config.UNIVERSE)
        except Exception:
            st.info("Kunde inte läsa core.config.UNIVERSE")
            universe_tickers = set()

        parquet_files = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
        scored_df = None
        file_name = ""
        if parquet_files:
            try:
                scored_df = pd.read_parquet(parquet_files[0])
                file_name = parquet_files[0].name
            except Exception:
                pass

        if scored_df is not None and universe_tickers:
            scored_tickers = set(scored_df["ticker"].str.upper().tolist())
            covered = scored_tickers & universe_tickers
            missing = universe_tickers - scored_tickers
            coverage_pct = len(covered) / len(universe_tickers) * 100

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Universe.json", len(universe_tickers))
            c2.metric(
                "Täckning",
                f"{coverage_pct:.0f}%",
                help="Andel tickers i universe.json som finns i senaste scanresultatet.",
            )
            c3.metric(
                "Scorades senast",
                len(scored_tickers),
                help=f"Tickers i {file_name}",
            )
            c4.metric(
                "Saknas",
                len(missing),
                help="Tickers i universe.json som inte finns i senaste scan.",
            )

            if coverage_pct < 60:
                st.error(
                    f"Täckning {coverage_pct:.0f}% — under 60%. "
                    "Många aktier saknas, troligen på grund av Yahoo Finance rate-limiting."
                )
            elif coverage_pct < 80:
                st.warning(f"Täckning {coverage_pct:.0f}% — under 80%.")
            else:
                st.success(f"Täckning {coverage_pct:.0f}% — bra!")
        else:
            st.info("Ingen scored_universe hittades. Kör en pipeline först.")

        # Universe Audit
        st.markdown("---")
        st.markdown("#### Universe Audit")
        st.caption(
            "Analyserar historiska snapshots för att identifiera tickers som aldrig eller sällan hämtats."
        )
        audit_path = DATA_DIR / "universe_audit.json"
        if audit_path.exists():
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
                generated = audit.get("generated", "")[:10]
                n_snapshots = audit.get("n_snapshots", "?")
                never  = audit.get("never_appeared", [])
                rarely = audit.get("rarely_appeared", [])
                always = audit.get("always_present", [])

                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Aldrig scorade",
                    len(never),
                    help="Tickers som aldrig dykt upp i någon historisk parquet.",
                )
                c2.metric(
                    "Sällan scorade",
                    len(rarely),
                    help="I mindre än 33% av snapshots — kroniskt rate-limited.",
                )
                c3.metric("Alltid scorade", len(always))
                st.caption(f"Senaste audit: {generated} · {n_snapshots} snapshots")

                if never:
                    with st.expander(f"Visa {len(never)} aldrig-scorade tickers"):
                        chunk = 6
                        rows = [never[i:i+chunk] for i in range(0, min(len(never), 120), chunk)]
                        for row in rows:
                            st.code("  ".join(row))
            except Exception:
                pass
        else:
            st.info("Ingen audit körd ännu.")

        if st.button("Kör universe-audit", help="Analyserar alla historiska parquet-filer."):
            with st.spinner("Analyserar snapshots..."):
                try:
                    from core.daily_pipeline import run_universe_audit
                    result = run_universe_audit(min_snapshots=1)
                    if "error" in result:
                        st.warning(result["error"])
                    else:
                        st.success(
                            f"Audit klar! {len(result['never_appeared'])} aldrig, "
                            f"{len(result['rarely_appeared'])} sällan, "
                            f"{result['coverage_pct']:.0f}% täckning."
                        )
                        st.rerun()
                except Exception as e:
                    st.error(f"Audit misslyckades: {e}")

        # Retry rate-limited
        with st.expander("Kör om rate-limiteda tickers"):
            st.caption(
                "Hämtar om tickers som rate-limitades i senaste scan. "
                "Systemet försöker flera gånger tills alla är hämtade."
            )
            if st.button("Kör retry nu", key="btn_retry_rl"):
                with st.spinner("Kör retry..."):
                    try:
                        from core.daily_pipeline import run_retry_rate_limited
                        result = run_retry_rate_limited(max_passes=3, pass_delay_s=60)
                        st.success(
                            f"{result['n_succeeded']} lyckades, "
                            f"{result['n_still_pending']} kvarvarande."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Retry misslyckades: {e}")

    # ── Sub-tab 2: Kandidater ────────────────────────────────────────────────
    with sub_tabs[1]:
        st.markdown("#### Kandidater")
        st.caption("Nya aktier som systemet hittat via discovery, redo för granskning.")

        from core.universe_manager import (
            load_candidates, approve_candidate, reject_candidate,
            get_removal_candidates, save_candidates,
        )

        cands_data = load_candidates()
        pending   = [c for c in cands_data["candidates"] if c.get("status") == "pending"]
        approved  = cands_data.get("auto_added", [])
        rejected  = [c for c in cands_data["candidates"] if c.get("status") == "rejected"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Väntar granskning", len(pending))
        c2.metric("Auto-tillagda", len(approved))
        c3.metric("Avvisade", len(rejected))

        # Discovery
        st.markdown("---")
        st.markdown("#### Kör discovery")
        with st.expander("Sök efter nya aktier"):
            col_src, col_opts = st.columns([2, 1])
            with col_src:
                sources = st.multiselect(
                    "Källor",
                    ["finviz", "index", "news", "ai", "etf"],
                    default=["index", "news", "ai"],
                    key="disc_sources",
                )
            with col_opts:
                dry_run = st.checkbox("Simulering (ingen ändring)", value=True, key="disc_dry")

            if st.button("Starta discovery", key="btn_discovery"):
                if not sources:
                    st.warning("Välj minst en källa.")
                else:
                    with st.spinner("Kör discovery..."):
                        try:
                            from core.universe_manager import run_full_maintenance
                            result = run_full_maintenance(
                                sources=sources,
                                auto_add_threshold=0.90,
                                auto_remove=False,
                                dry_run=dry_run,
                                commit=False,
                                verbose=True,
                            )
                            st.success(
                                f"Hittade {result['candidates_found']} kandidater, "
                                f"{result['candidates_new']} nya."
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"Discovery misslyckades: {e}")

        # Pending-kandidater
        st.markdown("---")
        st.markdown(f"#### Väntar granskning ({len(pending)})")

        if not pending:
            st.info("Inga väntande kandidater. Kör discovery ovan för att hitta nya.")
        else:
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                source_filter = st.selectbox(
                    "Filtrera källa",
                    ["Alla"] + sorted({c.get("source", "?") for c in pending}),
                    key="disc_source_filter",
                )
            with col_f2:
                region_filter = st.selectbox(
                    "Filtrera region",
                    ["Alla"] + sorted({c.get("region", "?") for c in pending}),
                    key="disc_region_filter",
                )
            with col_f3:
                tier_filter = st.selectbox(
                    "Kvalitetsnivå",
                    ["Alla", "HIGH", "MEDIUM", "SPECULATIVE"],
                    key="disc_tier_filter",
                )

            filtered = pending
            if source_filter != "Alla":
                filtered = [c for c in filtered if c.get("source") == source_filter]
            if region_filter != "Alla":
                filtered = [c for c in filtered if c.get("region") == region_filter]
            if tier_filter != "Alla":
                filtered = [c for c in filtered if c.get("quality_tier", "MEDIUM") == tier_filter]

            tier_order = {"HIGH": 0, "MEDIUM": 1, "SPECULATIVE": 2}
            filtered.sort(key=lambda x: (tier_order.get(x.get("quality_tier", "MEDIUM"), 1), -x.get("confidence", 0)))

            col_ba1, col_ba2 = st.columns([1, 4])
            with col_ba1:
                select_all = st.checkbox("Välj alla", key="disc_sel_all")
            with col_ba2:
                col_ap, col_rj = st.columns(2)
                with col_ap:
                    if st.button("Godkänn valda", type="primary", key="btn_bulk_approve"):
                        approved_tickers = []
                        for c in filtered[:50]:
                            if st.session_state.get(f"disc_sel_{c['ticker']}", False):
                                if approve_candidate(c["ticker"]):
                                    approved_tickers.append(c["ticker"])
                        if approved_tickers:
                            st.success(f"{len(approved_tickers)} tillagda.")
                            st.rerun()
                with col_rj:
                    if st.button("Avvisa valda", key="btn_bulk_reject"):
                        rejected_tickers = []
                        for c in filtered[:50]:
                            if st.session_state.get(f"disc_sel_{c['ticker']}", False):
                                if reject_candidate(c["ticker"]):
                                    rejected_tickers.append(c["ticker"])
                        if rejected_tickers:
                            st.info(f"{len(rejected_tickers)} avvisade.")
                            st.rerun()

            for c in filtered[:50]:
                ticker   = c["ticker"]
                source   = c.get("source", "?")
                conf     = c.get("confidence", 0)
                region   = c.get("region", "")
                tier     = c.get("quality_tier", "MEDIUM")
                q_score  = c.get("quality_score", 0)
                fraud    = c.get("fraud_flags", [])
                yf       = c.get("yf_data") or c.get("metadata", {})
                name     = yf.get("name", "")
                sector   = yf.get("sector", "")
                mc_raw   = yf.get("market_cap", 0) or 0
                mc_str   = f"${mc_raw/1e9:.1f}B" if mc_raw >= 1e9 else f"${mc_raw/1e6:.0f}M" if mc_raw > 0 else "?"

                tier_label = {"HIGH": "Hög", "MEDIUM": "Medel", "SPECULATIVE": "Spekulativ"}.get(tier, tier)

                with st.container(border=True):
                    col_cb, col_l = st.columns([1, 11])
                    with col_cb:
                        st.checkbox("", key=f"disc_sel_{ticker}", value=select_all)
                    with col_l:
                        st.markdown(f"**{ticker}** — {name[:25]} | {tier_label} | Källa: {source}")
                        details = []
                        if sector:
                            details.append(f"Sektor: {sector}")
                        if mc_str != "?":
                            details.append(f"Market cap: {mc_str}")
                        details.append(f"Confidence: {conf:.0%}")
                        if details:
                            st.caption(" | ".join(details))
                        if fraud:
                            for f_flag in fraud[:2]:
                                st.caption(f"Varning: {f_flag}")

        # Borttagningskandidater
        st.markdown("---")
        with st.expander("Borttagningskandidater (låg score / låg likviditet)"):
            try:
                removal = get_removal_candidates()
            except Exception:
                removal = []
            if not removal:
                st.success("Inga uppenbara borttagningskandidater.")
            else:
                st.dataframe(pd.DataFrame(removal), use_container_width=True, hide_index=True)

        # Rensa gamla pending
        if st.button("Rensa pending äldre än 30 dagar", key="btn_clean_pending"):
            from datetime import timedelta, date as dt_date
            cutoff = (dt_date.today() - timedelta(days=30)).isoformat()
            cands = load_candidates()
            before = len([c for c in cands["candidates"] if c.get("status") == "pending"])
            cands["candidates"] = [
                c for c in cands["candidates"]
                if not (c.get("status") == "pending" and c.get("discovered", "9999") < cutoff)
            ]
            save_candidates(cands)
            st.success(f"Rensade {before - len([c for c in cands['candidates'] if c.get('status') == 'pending'])} gamla.")
            st.rerun()

    # ── Sub-tab 3: Strikes & Blacklist ───────────────────────────────────────
    with sub_tabs[2]:
        st.markdown("#### Strikes & Blacklist")
        st.caption(
            "En strike registreras när data inte kan hämtas. "
            "Tre strikes för samma ticker leder till automatisk blacklistning."
        )

        strikes = _load_json("strike_list.json")
        blacklist = _load_json("blacklist.json")
        universe_data = load_universe_json()

        sub = st.tabs(["Strikes (pågående)", "Blacklist (borttagna)", "Fetch-fel"])

        # Strikes
        with sub[0]:
            if not strikes:
                st.success("Inga pågående strikes.")
            else:
                strike_rows = []
                for ticker, info in sorted(strikes.items()):
                    if isinstance(info, dict):
                        cnt = info.get("count", 1)
                        dt_str = info.get("date", "?")
                    else:
                        cnt = int(info)
                        dt_str = "?"
                    strike_rows.append({"Ticker": ticker, "Strikes": cnt, "Senaste": dt_str})
                sdf = pd.DataFrame(strike_rows)
                st.dataframe(sdf, use_container_width=True, hide_index=True)

                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("Rensa alla strikes", key="btn_clear_strikes"):
                        for t in list(strikes.keys()):
                            strikes.pop(t, None)
                        _save_json("strike_list.json", strikes)
                        st.success("Alla strikes rensade.")
                        st.rerun()
                with col_b2:
                    if not blacklist and st.button("Blacklista alla med strikes", key="btn_bl_strikes"):
                        for t in list(strikes.keys()):
                            blacklist[t] = {"reason": "Blacklistad från strike-lista", "date": "?"}
                            remove_ticker_from_universe_json(t, universe_data)
                        _save_json("strike_list.json", {})
                        _save_json("blacklist.json", blacklist)
                        save_universe_json(universe_data)
                        st.success("Blacklistade alla.")
                        st.rerun()

        # Blacklist
        with sub[1]:
            if not blacklist:
                st.success("Blacklisten är tom.")
            else:
                bl_rows = []
                for ticker, info in sorted(blacklist.items()):
                    if isinstance(info, dict):
                        reason = info.get("reason", "")[:60]
                        dt_str = info.get("date", "?")
                    else:
                        reason = str(info)[:60]
                        dt_str = "?"
                    bl_rows.append({"Ticker": ticker, "Anledning": reason, "Datum": dt_str})
                st.dataframe(pd.DataFrame(bl_rows), use_container_width=True, hide_index=True)

                if st.button("Återställ alla från blacklist", key="btn_restore_bl"):
                    blacklist.clear()
                    _save_json("blacklist.json", blacklist)
                    st.success("Blacklisten rensad.")
                    st.rerun()

            # Lägg till i blacklist manuellt
            st.markdown("---")
            st.markdown("#### Lägg till i blacklist")
            col_t, col_r = st.columns([1, 2])
            with col_t:
                bl_ticker = st.text_input("Ticker", key="bl_add_ticker", max_chars=15, placeholder="AAPL").upper().strip()
            with col_r:
                bl_reason = st.text_input("Anledning", key="bl_add_reason", placeholder="t.ex. avnoterad")
            if st.button("Blacklista", key="btn_add_blacklist") and bl_ticker:
                if bl_ticker not in blacklist:
                    blacklist[bl_ticker] = {"reason": bl_reason or "Manuellt blacklistad", "date": "?"}
                    _save_json("blacklist.json", blacklist)
                    remove_ticker_from_universe_json(bl_ticker, universe_data)
                    save_universe_json(universe_data)
                    st.success(f"{bl_ticker} blacklistad.")
                    st.rerun()
                else:
                    st.warning(f"{bl_ticker} finns redan i blacklist.")

        # Fetch-fel
        with sub[2]:
            st.caption(
                "Fel från senaste pipeline-körningen. "
                "Hjälper dig skilja på rate-limiting (tillfälligt) och genuina fel (tickern finns inte)."
            )
            fe_path = DATA_DIR / "fetch_errors.json"
            if not fe_path.exists():
                st.info("Ingen fetch_errors.json ännu — kör en pipeline först.")
            else:
                try:
                    fe_data = json.loads(fe_path.read_text(encoding="utf-8"))
                    if not fe_data:
                        st.info("Tom fetch-logg.")
                    else:
                        latest = fe_data[-1]
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("OK", latest.get("n_ok", 0))
                        c2.metric("Misslyckade", latest.get("n_failed", 0))
                        c3.metric("Rate-limited", latest.get("n_rate_limited", 0))
                        c4.metric("Delistade", latest.get("n_delisted", 0))

                        failed = latest.get("failed_tickers", [])
                        if failed:
                            rows = []
                            for fd in failed:
                                t = fd.get("ticker", "?")
                                sts = fd.get("status", "?")
                                rows.append({"Ticker": t, "Status": sts, "Rekommendation": "Överväg blacklist"})
                            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                            if st.button("Blacklista alla misslyckade", key="btn_bl_fetch"):
                                bl = _load_json("blacklist.json")
                                ud = load_universe_json()
                                for fd in failed:
                                    t = fd.get("ticker", "")
                                    if t and t not in bl:
                                        bl[t] = {"reason": "Genuint fetch-fel", "date": "?"}
                                        remove_ticker_from_universe_json(t, ud)
                                _save_json("blacklist.json", bl)
                                save_universe_json(ud)
                                st.success("Blacklistade misslyckade tickers.")
                                st.rerun()
                except Exception as e:
                    st.warning(f"Kunde inte läsa fetch_errors.json: {e}")

    # ── Sub-tab 4: Datakvalitet ──────────────────────────────────────────────
    with sub_tabs[3]:
        st.markdown("#### Datakvalitet")
        st.caption(
            "Täckningsgrad per faktor. Aktier utan data för en faktor scoreas neutralt (50p). "
            "Låg täckning kan tyda på hämtningsproblem."
        )

        df = _load_latest_scored()
        if df is None:
            st.info("Ingen scored_universe-fil hittades. Kör en pipeline först.")
        else:
            n = len(df)
            rows = []
            for factor, cols in FACTOR_COLUMNS.items():
                present_cols = [c for c in cols if c in df.columns]
                prim = [c for c in FACTOR_PRIMARY.get(factor, present_cols) if c in df.columns]
                if not prim:
                    prim = present_cols
                if prim:
                    has_data = int(df[prim].notna().any(axis=1).sum())
                    pct = round(100 * has_data / n, 1) if n else 0.0
                else:
                    has_data = 0
                    pct = 0.0
                status = "green" if pct >= 90 else "orange" if pct >= 70 else "red"
                rows.append({
                    "Faktor": factor.capitalize(),
                    "Täckning %": pct,
                    "Med data": has_data,
                    "Saknar data": n - has_data,
                    "_status": status,
                })
            summary = pd.DataFrame(rows)
            # Color-code coverage
            def _color(val):
                c = summary.loc[summary["Täckning %"] == val, "_status"].values[0] if any(summary["Täckning %"] == val) else ""
                if c == "green":
                    return "color: #16a34a; font-weight: 600"
                if c == "orange":
                    return "color: #f59e0b; font-weight: 600"
                if c == "red":
                    return "color: #dc2626; font-weight: 600"
                return ""
            styled = summary.drop(columns=["_status"]).style.applymap(_color, subset=["Täckning %"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Kolumntäckning per faktor
            st.markdown("---")
            st.markdown("#### Kolumntäckning per faktor")
            factor_choice = st.selectbox(
                "Välj faktor",
                list(FACTOR_COLUMNS.keys()),
                key="dq_factor_choice",
            )
            col_rows = []
            for col in FACTOR_COLUMNS.get(factor_choice, []):
                if col in df.columns:
                    filled = int(df[col].notna().sum())
                    pct = round(100 * filled / n, 1) if n else 0.0
                else:
                    filled = 0
                    pct = 0.0
                col_rows.append({
                    "Kolumn": col,
                    "Fyllda": filled,
                    "Tomma": n - filled,
                    "Täckning %": pct,
                })
            st.dataframe(pd.DataFrame(col_rows), use_container_width=True, hide_index=True)

            # Drilldown
            st.markdown("---")
            st.markdown("#### Tickers utan data")
            st.caption("Välj en faktor för att se tickers som saknar primärdata för den faktorn.")
            drill_factor = st.selectbox(
                "Faktor att granska",
                list(FACTOR_COLUMNS.keys()),
                key="dq_drill_choice",
            )
            prim_cols = [c for c in FACTOR_PRIMARY.get(drill_factor, []) if c in df.columns]
            if prim_cols:
                missing_mask = ~df[prim_cols].notna().any(axis=1)
                subset = df[missing_mask].copy()
                if not subset.empty:
                    display_cols = ["ticker"]
                    if "name" in subset.columns:
                        display_cols.append("name")
                    if "sector" in subset.columns:
                        display_cols.append("sector")
                    with st.container(border=True):
                        st.warning(f"{len(subset)} tickers saknar primärdata för {drill_factor}.")
                        st.dataframe(subset[display_cols].head(30), use_container_width=True, hide_index=True)
                else:
                    st.success(f"Alla tickers har data för {drill_factor}.")
