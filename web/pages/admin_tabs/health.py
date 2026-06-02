"""admin/health.py - Universe Health tab for admin page."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from core import config
from web.utils import DATA_DIR, REPORT_DIR, load_watchlist


def _render_coverage_dashboard():
    """Visar täcknings-dashboard för universe vs senaste scored parquet."""
    st.markdown("### 📊 Universum-täckning")
    st.caption("Hur stor andel av universe.json representeras i senaste scored_universe.parquet?")

    parquet_files = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
    if not parquet_files:
        st.warning("Ingen scored_universe.parquet hittad. Kör en weekly scan först.")
        return

    try:
        scored_df = pd.read_parquet(parquet_files[0], columns=["ticker", "data_stale_days"] if True else ["ticker"])
    except Exception:
        try:
            scored_df = pd.read_parquet(parquet_files[0])
        except Exception as _e:
            st.error(f"Kunde inte läsa parquet: {_e}")
            return

    universe_tickers = set(t.upper() for t in config.UNIVERSE)
    scored_tickers   = set(scored_df["ticker"].str.upper().tolist())
    covered          = scored_tickers & universe_tickers
    missing          = universe_tickers - scored_tickers
    coverage_pct     = len(covered) / len(universe_tickers) * 100 if universe_tickers else 0

    n_stale = 0
    if "data_stale_days" in scored_df.columns:
        n_stale = int(scored_df["data_stale_days"].fillna(0).gt(0).sum())

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Universe.json", len(universe_tickers))
    with col2:
        st.metric("Täckning", f"{coverage_pct:.0f}%", help="≥80% = bra. <60% = problem med Yahoo rate-limiting.")
    with col3:
        st.metric("Saknas i parquet", len(missing), help="Tickers i universe.json som inte finns i senaste scan-resultat.")
    with col4:
        st.metric("Stale data", n_stale, help="Aktier vars data är ärvd från förra scan (Yahoo rate-limitad).")

    if coverage_pct < 60:
        st.error(f"Täckning {coverage_pct:.0f}% — under 60%. Många aktier saknas p.g.a. Yahoo rate-limiting. "
                 "Staleness-merge och retry_rate_limited-körning hjälper.")
    elif coverage_pct < 80:
        st.warning(f"Täckning {coverage_pct:.0f}% — under 80%. Staleness-merge aktiveras automatiskt i weekly scan.")
    else:
        st.success(f"Täckning {coverage_pct:.0f}% — bra!")


def _render_universe_audit():
    """Separat synlig sektion för Universe Audit."""
    st.markdown("---")
    st.markdown("### 🔍 Universe Audit")
    st.caption(
        "Analyserar alla historiska parquet-snapshots och identifierar vilka tickers som "
        "aldrig eller sällan lyckats hämtas — kandidater för borttagning ur universum."
    )

    audit_path = DATA_DIR / "universe_audit.json"

    # Visa senaste audit-resultat om de finns
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            generated = audit.get("generated", "")[:10]
            n_snapshots = audit.get("n_snapshots", "?")
            never  = audit.get("never_appeared", [])
            rarely = audit.get("rarely_appeared", [])
            always = audit.get("always_present", [])

            st.info(f"Senaste audit: **{generated}** · baserat på **{n_snapshots}** snapshots")

            c1, c2, c3 = st.columns(3)
            c1.metric("Aldrig scorade", len(never),
                      help="Tickers som aldrig dykt upp i någon historisk parquet. "
                           "Troligen genuint döda (404) eller aldrig hämtade av Yahoo.")
            c2.metric("Sällan scorade", len(rarely),
                      help="Tickers i <33% av snapshots — kroniskt rate-limitade.")
            c3.metric("Alltid scorade", len(always),
                      help="Tickers i ≥80% av snapshots — pålitliga datakällor.")

            if never:
                with st.expander(f"Visa {len(never)} aldrig-scorade tickers", expanded=False):
                    st.caption("Dessa tickers har aldrig dykt upp i någon scan-parquet. "
                               "Kan vara genuint delistade, eller Yahoo har aldrig returnerat data för dem.")
                    # Dela upp i kolumner för bättre läsbarhet
                    chunk = 6
                    rows = [never[i:i+chunk] for i in range(0, min(len(never), 120), chunk)]
                    for row in rows:
                        st.code("  ".join(row))
                    if len(never) > 120:
                        st.caption(f"... och {len(never) - 120} till.")

            if rarely:
                with st.expander(f"Visa {len(rarely)} sällan-scorade tickers", expanded=False):
                    chunk = 6
                    rows = [rarely[i:i+chunk] for i in range(0, min(len(rarely), 60), chunk)]
                    for row in rows:
                        st.code("  ".join(row))

        except Exception as _e:
            st.warning(f"Kunde inte läsa universe_audit.json: {_e}")
    else:
        st.info("Ingen audit körd ännu. Klicka på knappen nedan för att starta.")

    # Visa retry_pending-status om filen finns
    retry_path = DATA_DIR / "retry_pending.json"
    if retry_path.exists():
        try:
            rp = json.loads(retry_path.read_text(encoding="utf-8"))
            n_pending = rp.get("n_tickers", len(rp.get("tickers", [])))
            pass_count = rp.get("pass_count", 0)
            created = rp.get("created", "")[:16]
            st.info(
                f"♻️ **Retry pending:** {n_pending} tickers väntar på nästa retry-körning "
                f"(pass {pass_count}, sparad {created}). "
                "Nästa retry körs automatiskt via schema, eller starta manuellt nedan."
            )
        except Exception:
            pass

    # Knappar
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Kör universe-audit nu", key="btn_run_universe_audit",
                     use_container_width=True,
                     help="Analyserar alla historiska parquets och identifierar tickers som aldrig lyckas hämtas."):
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
                            f"{len(result['always_present'])} alltid "
                            f"({result['coverage_pct']:.0f}% täckning, {result['n_snapshots']} snapshots)"
                        )
                        st.rerun()
                except Exception as _ae:
                    st.error(f"Audit misslyckades: {_ae}")

    with col_b:
        if st.button("Kör retry av rate-limitade nu", key="btn_run_retry_rl",
                     use_container_width=True,
                     help="Hämtar om tickers som rate-limitades i senaste scan. Kör flera pass tills alla klarar sig."):
            with st.spinner("Kör retry... (kan ta några minuter)"):
                try:
                    from core.daily_pipeline import run_retry_rate_limited
                    result = run_retry_rate_limited(max_passes=3, pass_delay_s=60)
                    st.success(
                        f"Retry klar! {result['n_succeeded']} lyckades, "
                        f"{result['n_still_pending']} kvar, "
                        f"{result['n_skipped']} delistade, "
                        f"{result['passes_run']} pass körda."
                    )
                    st.rerun()
                except Exception as _re:
                    st.error(f"Retry misslyckades: {_re}")


def render():
    st.subheader("Universe Health · underhåll av aktieuniversum")
    st.caption("Täckning, audit, svartlista och hälsokontroll av aktieuniversumet.")

    # ── Täcknings-dashboard ────────────────────────────────────────────────────
    _render_coverage_dashboard()

    # ── Universe Audit (tydlig egen sektion) ──────────────────────────────────
    _render_universe_audit()

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

    with st.expander("Visa svartlista", expanded=False):
        if blacklist:
            st.dataframe(pd.DataFrame(blacklist), use_container_width=True, hide_index=True)
            remove_bl = st.selectbox(
                "Ta bort från svartlistan",
                [""] + [i.get("ticker", "") for i in blacklist],
                key="bl_remove",
            )
            if remove_bl and st.button("Ta bort", key="btn_bl_remove"):
                if remove_from_blacklist(remove_bl):
                    st.success(f"`{remove_bl}` borttagen från svartlistan!")
                    st.rerun()
        else:
            st.info("Svartlistan är tom.")

    with st.expander("Lägg till i svartlistan manuellt", expanded=False):
        col_bl_t, col_bl_r = st.columns([2, 3])
        with col_bl_t:
            bl_ticker = st.text_input("Ticker", key="bl_add_ticker", max_chars=15,
                                       placeholder="AAPL").upper().strip()
        with col_bl_r:
            bl_reason = st.text_input("Anledning", key="bl_add_reason",
                                       placeholder="t.ex. avnoterad")
        if st.button("Lägg till i svartlistan", key="btn_bl_add"):
            if bl_ticker:
                if add_to_blacklist(bl_ticker, bl_reason or "manuell"):
                    st.success(f"`{bl_ticker}` tillagd i svartlistan!")
                    st.rerun()
                else:
                    st.info(f"`{bl_ticker}` finns redan i svartlistan.")
            else:
                st.warning("Ange en ticker.")

    st.markdown("---")
    st.markdown("### Kör hälsokontroll")
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

    if st.button("Kör hälsokontroll", key="btn_health_check",
                 type="primary", use_container_width=True):
        with st.spinner("Kör hälsokontroll..."):
            try:
                reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                if not reports:
                    st.warning("Ingen scandata hittad. Kör en scan först.")
                else:
                    df_health = pd.read_csv(reports[0], low_memory=False)
                    df_health.columns = df_health.columns.str.strip()
                    result = run_health_check(df=df_health, provider=health_provider)
                    st.success("Hälsokontroll klar!")

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
                        st.error(f"Hittade {len(invalid)} ogiltiga/avnoterade tickers!")
                        inv_df = pd.DataFrame(invalid)
                        st.dataframe(inv_df, use_container_width=True, hide_index=True)

                        st.markdown("### Ersättningsförslag")
                        suggestions = result.get("suggestions", {})
                        for bad_ticker, replacements in suggestions.items():
                            with st.expander(f"`{bad_ticker}` → ersättningsförslag", expanded=True):
                                if replacements:
                                    rep_df = pd.DataFrame(replacements)
                                    st.dataframe(rep_df, use_container_width=True, hide_index=True)
                                else:
                                    st.caption("Inga ersättningsförslag.")
                    else:
                        st.success("Alla tickers verkar vara giltiga!")

                    new_stocks = result.get("new_stocks", [])
                    if new_stocks:
                        st.markdown("---")
                        st.subheader("AI-förslag: nya intressanta aktier")
                        for s in new_stocks:
                            ticker_s = s.get("ticker", "?")
                            name_s = s.get("name", "")
                            reason_s = s.get("reason", "")
                            with st.container(border=True):
                                st.markdown(f"**{ticker_s}** — {name_s}")
                                st.caption(reason_s)

            except Exception as e:
                st.error(f"Hälsokontrollen misslyckades: {e}")
                import traceback
                st.code(traceback.format_exc())
