"""admin/health.py – Universe Health tab for admin page."""
from datetime import date

import pandas as pd
import streamlit as st

from core import config
from web.utils import DATA_DIR, REPORT_DIR, load_watchlist


def render():
    st.subheader("Universe Health – underhall av aktieuniversum")
    st.caption("Upptack avnoterade/ogiltiga tickers, hantera svartlista och hitta nya aktier med AI.")

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
                "Ta bort fran svartlistan",
                [""] + [i.get("ticker", "") for i in blacklist],
                key="bl_remove",
            )
            if remove_bl and st.button("Ta bort", key="btn_bl_remove"):
                if remove_from_blacklist(remove_bl):
                    st.success(f"`{remove_bl}` borttagen fran svartlistan!")
                    st.rerun()
        else:
            st.info("Svartlistan ar tom.")

    with st.expander("Lagg till i svartlistan manuellt", expanded=False):
        col_bl_t, col_bl_r = st.columns([2, 3])
        with col_bl_t:
            bl_ticker = st.text_input("Ticker", key="bl_add_ticker", max_chars=15,
                                       placeholder="AAPL").upper().strip()
        with col_bl_r:
            bl_reason = st.text_input("Anledning", key="bl_add_reason",
                                       placeholder="t.ex. avnoterad")
        if st.button("Lagg till i svartlistan", key="btn_bl_add"):
            if bl_ticker:
                if add_to_blacklist(bl_ticker, bl_reason or "manuell"):
                    st.success(f"`{bl_ticker}` tillagd i svartlistan!")
                    st.rerun()
                else:
                    st.info(f"`{bl_ticker}` finns redan i svartlistan.")
            else:
                st.warning("Ange en ticker.")

    st.markdown("---")
    st.markdown("### Kor halsokontroll")
    st.caption("Kontrollerar alla tickers i senaste scandatan mot yfinance.")

    health_provider = st.selectbox(
        "AI-provider for nya aktieforslag",
        ["auto", "deepseek", "gemini"],
        format_func=lambda k: {
            "auto": f"Auto ({config.AI_PROVIDER})",
            "deepseek": "DeepSeek (komplex, kostar)",
            "gemini": "Gemini (enkel, gratis)",
        }.get(k, k),
        key="health_provider",
    )

    if st.button("Kor halsokontroll", key="btn_health_check",
                 type="primary", use_container_width=True):
        with st.spinner("Kor halsokontroll..."):
            try:
                reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                if not reports:
                    st.warning("Ingen scandata hittad. Kor en scan forst.")
                else:
                    df_health = pd.read_csv(reports[0], low_memory=False)
                    df_health.columns = df_health.columns.str.strip()
                    result = run_health_check(df=df_health, provider=health_provider)
                    st.success("Halsokontroll klar!")

                    col_h1, col_h2, col_h3 = st.columns(3)
                    with col_h1:
                        st.metric("Ogiltiga tickers", len(result.get("invalid_tickers", [])))
                    with col_h2:
                        st.metric("Svartlistade", result.get("blacklist_count", 0))
                    with col_h3:
                        st.metric("Nya AI-forslag", len(result.get("new_stocks", [])))

                    invalid = result.get("invalid_tickers", [])
                    if invalid:
                        st.markdown("---")
                        st.error(f"Hittade {len(invalid)} ogiltiga/avnoterade tickers!")
                        inv_df = pd.DataFrame(invalid)
                        st.dataframe(inv_df, use_container_width=True, hide_index=True)

                        st.markdown("### Ersattningsforslag")
                        suggestions = result.get("suggestions", {})
                        for bad_ticker, replacements in suggestions.items():
                            with st.expander(f"`{bad_ticker}` -> ersattningsforslag", expanded=True):
                                if replacements:
                                    rep_df = pd.DataFrame(replacements)
                                    st.dataframe(rep_df, use_container_width=True, hide_index=True)
                                else:
                                    st.caption("Inga ersattningsforslag.")
                    else:
                        st.success("Alla tickers verkar vara giltiga!")

                    new_stocks = result.get("new_stocks", [])
                    if new_stocks:
                        st.markdown("---")
                        st.subheader("AI-forslag: nya intressanta aktier")
                        for s in new_stocks:
                            ticker_s = s.get("ticker", "?")
                            name_s = s.get("name", "")
                            reason_s = s.get("reason", "")
                            with st.container(border=True):
                                st.markdown(f"**{ticker_s}** -- {name_s}")
                                st.caption(reason_s)

            except Exception as e:
                st.error(f"Halsokontrollen misslyckades: {e}")
                import traceback
                st.code(traceback.format_exc())
