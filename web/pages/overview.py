"""web/pages/overview.py – Sida 1: Översikt"""

from datetime import date

import pandas as pd
import streamlit as st

from web.utils import (
    kpi_row, sector_bar_chart, score_distribution_chart,
    load_watchlist, load_portfolio, _get_provider, _get_depth,
)
from web.stock_detail import render_stock_detail
from core import ai_analysis
from core.country_flags import flag_for_ticker


_COUNTRY_SUFFIX_MAP = {
    "🇸🇪 Sverige":  ".ST",
    "🇬🇧 UK":       ".L",
    "🇩🇪 Tyskland": ".DE",
    "🇫🇮 Finland":  ".HE",
    "🇩🇰 Danmark":  ".CO",
    "🇳🇴 Norge":    ".OL",
    "🇨🇳 Kina":     ".SS",
    "🇯🇵 Japan":    ".T",
}
_ALL_NON_US_SUFFIXES = set(_COUNTRY_SUFFIX_MAP.values())


def _save_watchlist_data(items):
    from web.pages.admin import _save_watchlist_data as _swd
    _swd(items)


def page_overview(df: pd.DataFrame, sc_df: pd.DataFrame, holdings: pd.DataFrame = None):
    st.title("📊 Översikt")

    if df.empty and sc_df.empty:
        st.warning("Aktiedata håller på att laddas in. Systemet uppdateras automatiskt varje vecka — kom tillbaka snart.")
        return

    # ── KPI-rad ──────────────────────────────────────────────────────────────
    col_score = "score_total" if "score_total" in df.columns else "sc_total"
    n_total   = len(df) if not df.empty else 0
    top_ticker = df.sort_values("score_total", ascending=False).iloc[0]["ticker"] \
        if not df.empty and "score_total" in df.columns else "—"
    top_score  = df.sort_values("score_total", ascending=False).iloc[0]["score_total"] \
        if not df.empty and "score_total" in df.columns else 0
    n_stark    = int((df.get("entry_signal", pd.Series()) == "STARK").sum()) \
        if "entry_signal" in df.columns else 0
    avg_score  = df["score_total"].mean() if "score_total" in df.columns else 0

    kpi_row([
        ("📈 Bolag i scan",  f"{n_total}",             None,
         "Totalt antal bolag i det scannnade universumet. Inkluderar stora, medelstora och småbolag från alla marknader."),
        ("🥇 Toppbolag",     f"{top_ticker}",           f"{top_score:.0f} poäng",
         "Bolaget med högst totalpoäng just nu. Poängen baseras på 8 faktorer: värdering, kvalitet, momentum, tillväxt, risk, storlek, utdelning och sentiment."),
        ("⚡ STARK entry",   f"{n_stark}",              None,
         "Antal bolag med en STARK köpsignal — tydlig uppåtrörelse med hög volym och teknisk styrka. Dessa är prioriterade köpkandidater."),
        ("📊 Snittpoäng",    f"{avg_score:.1f}/100",    None,
         "Genomsnittlig totalpoäng för alla bolag i scannningen. Mäter hur stark marknaden är generellt. Över 60 = bullish marknad."),
    ])

    st.markdown("---")

    # ── KÖP NU – STARK entry-signaler ────────────────────────────────────────
    frames_all = [f for f in [df, sc_df] if not f.empty and "entry_signal" in f.columns]
    if frames_all:
        combined_all = pd.concat(frames_all, ignore_index=True).drop_duplicates("ticker")
        score_col_c = "score_total" if "score_total" in combined_all.columns else combined_all.columns[0]
        buy_now = (combined_all[combined_all["entry_signal"] == "STARK"]
                   .sort_values(score_col_c, ascending=False).head(12))
        if not buy_now.empty:
            st.subheader("🚀 Köp nu — STARK entry-signal")
            st.caption(f"{len(buy_now)} aktier med starkast entry just nu. Klicka på en rad för detaljvy.")
            _buy_cols = [c for c in ["ticker", "name", score_col_c, "sector",
                                     "rsi_14", "return_1m", "return_3m"]
                         if c in buy_now.columns]
            _buy_show = buy_now[_buy_cols].copy()
            _buy_show.rename(columns={score_col_c: "Score", "ticker": "Ticker", "name": "Bolag",
                                       "sector": "Sektor", "rsi_14": "RSI",
                                       "return_1m": "1m%", "return_3m": "3m%"}, inplace=True)
            if "Ticker" in _buy_show.columns:
                _buy_show["Ticker"] = _buy_show["Ticker"].apply(
                    lambda t: f"{flag_for_ticker(t)} {t}"
                )
            _buy_ev = st.dataframe(
                _buy_show, use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="single-row", key="ov_buynow_table",
                column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f")},
            )
            if _buy_ev and _buy_ev.selection and _buy_ev.selection.rows:
                _bt = buy_now.iloc[_buy_ev.selection.rows[0]]["ticker"]
                _br = combined_all[combined_all["ticker"] == _bt]
                if not _br.empty:
                    with st.expander(f"🔍 {_bt}", expanded=True):
                        render_stock_detail(_bt, row=_br.iloc[0], df=combined_all,
                                            show_ai=True, show_news=False,
                                            show_chart=True, show_detail_data=True)

    # ── BEVAKA / SÄLJ – innehav med låg score ────────────────────────────────
    if holdings is not None and not holdings.empty and frames_all:
        score_lookup = combined_all.set_index("ticker").to_dict("index") if frames_all else {}
        sell_rows = []
        for _, h in holdings.iterrows():
            t = str(h["ticker"]).upper()
            sc = score_lookup.get(t, {})
            if not sc:
                continue
            score = sc.get("score_total", 0) or 0
            entry = sc.get("entry_signal", "—")
            if score < 45 or entry == "EJ AKTUELL":
                sell_rows.append({
                    "Ticker": f"{flag_for_ticker(t)} {t}",
                    "Bolag": str(sc.get("name", t))[:28],
                    "Score": round(score),
                    "Entry": entry,
                    "Orsak": "Låg score" if score < 45 else "Ej aktuell signal",
                })
        if sell_rows:
            st.subheader("⚠️ Innehav att se över")
            st.caption("Portföljinnehav med score < 45 eller 'EJ AKTUELL' signal.")
            st.dataframe(pd.DataFrame(sell_rows), use_container_width=True, hide_index=True,
                         column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f")})

    st.markdown("---")

    # ── Topp 5 ───────────────────────────────────────────────────────────────
    st.subheader("🏆 Topp 5 just nu")
    if not df.empty and "score_total" in df.columns:
        top5 = df.sort_values("score_total", ascending=False).head(5)
        cols = st.columns(5)
        wl_items = load_watchlist()
        hlds = load_portfolio()
        for i, (col, (_, r)) in enumerate(zip(cols, top5.iterrows())):
            medals = ["🥇", "🥈", "🥉", "4.", "5."]
            tkr    = r.get("ticker", "")
            score  = r.get("score_total", 0)
            sector = r.get("sector", "—")
            delta  = r.get("score_delta")
            d_str  = f"Δ {delta:+.1f}p" if delta and not pd.isna(delta) else ""
            col.markdown(f"**{medals[i]}**")
            if col.button(f"{flag_for_ticker(tkr)} {tkr}", key=f"ov_top5_nav_{tkr}",
                          use_container_width=True, help="Klicka för aktieanalys"):
                st.session_state["top5_detail"] = tkr
            col.metric("", f"{score:.0f} poäng", d_str or f"↑ {sector[:18]}")
            btn_col1, btn_col2 = col.columns(2)
            if btn_col1.button("⭐", key=f"ov_top_wl_{tkr}", help="Lägg till i bevakning"):
                st.session_state[f"_add_wl_{tkr}"] = True
            if btn_col2.button("💰", key=f"ov_top_add_{tkr}", help="Lägg till i nästa scan"):
                st.session_state[f"_add_scan_{tkr}"] = True
        # Process pending watchlist/scan adds
        for i, (_, r) in enumerate(top5.iterrows()):
            tkr = r.get("ticker", "")
            if st.session_state.pop(f"_add_wl_{tkr}", False):
                if not any(item["ticker"] == tkr for item in load_watchlist()):
                    wl = load_watchlist()
                    wl.append({"ticker": tkr, "name": r.get("name", tkr), "added": str(date.today())})
                    _save_watchlist_data(wl)
                    st.toast(f"✅ {tkr} tillagd i bevakning!", icon="⭐")
                    st.rerun()
            if st.session_state.pop(f"_add_scan_{tkr}", False):
                is_sc = any(suf in str(tkr).upper() for suf in [".ST", ".HE", ".CO", ".OL"])
                try:
                    if is_sc:
                        from smallcap.universe import add_custom
                        add_custom(tkr, str(r.get("name", tkr)))
                    else:
                        from core.config import add_custom_to_universe
                        add_custom_to_universe(tkr, str(r.get("name", tkr)))
                    st.toast(f"✅ {tkr} tillagd i nästa scan!", icon="📡")
                except:
                    pass

        # ── Detaljvy för klickad Topp 5-aktie ────────────────────────────
        sel_detail = st.session_state.get("top5_detail")
        if sel_detail:
            sel_row = df[df["ticker"] == sel_detail]
            if not sel_row.empty:
                with st.expander(f"🔍 Detaljvy: {sel_detail}", expanded=True):
                    close_col = st.columns([10, 1])[1]
                    if close_col.button("✕", key="top5_detail_close", help="Stäng"):
                        del st.session_state["top5_detail"]
                        st.rerun()
                    render_stock_detail(sel_detail, row=sel_row.iloc[0], df=df,
                                        show_ai=True, show_news=False,
                                        show_chart=True, show_detail_data=True)
            else:
                del st.session_state["top5_detail"]

    st.markdown("---")

    # ── Diagram ───────────────────────────────────────────────────────────────
    c1, c2 = st.columns([3, 2])
    with c1:
        if not df.empty:
            st.plotly_chart(sector_bar_chart(df), use_container_width=True)
    with c2:
        if not df.empty:
            st.plotly_chart(score_distribution_chart(df), use_container_width=True)

    # ── Småbolag quick-view ────────────────────────────────────────────────────
    if not sc_df.empty:
        st.markdown("---")
        st.subheader("🏦 Småbolag – snabbvy")
        score_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
        if score_col in sc_df.columns:
            top_sc = sc_df.sort_values(score_col, ascending=False).head(5)
            show_cols = [c for c in ["ticker", "sc_stars", score_col, "insider_signal",
                                     "current_price", "day_change_pct", "week_change_pct"]
                         if c in top_sc.columns]
            sc_show = top_sc[show_cols].copy()
            if "ticker" in sc_show.columns:
                sc_show["ticker"] = sc_show["ticker"].apply(
                    lambda t: f"{flag_for_ticker(t)} {t}"
                )
            st.dataframe(sc_show.reset_index(drop=True), use_container_width=True)

    # ── Entry-signal-fördelning ───────────────────────────────────────────────
    if not df.empty and "entry_signal" in df.columns:
        st.markdown("---")
        st.subheader("⚡ Entry-signal fördelning")
        sig_counts = df["entry_signal"].value_counts().reset_index()
        sig_counts.columns = ["Signal", "Antal"]
        color_map = {
            "STARK": "#00c853", "OK": "#42a5f5",
            "VÄNTA": "#ffd600", "EJ AKTUELL": "#ef5350",
        }
        import plotly.express as px
        fig = px.bar(
            sig_counts, x="Signal", y="Antal",
            color="Signal", color_discrete_map=color_map,
            template="plotly_dark",
        )
        fig.update_layout(
            margin=dict(t=24, b=16, l=16, r=16),
            plot_bgcolor="#1e2230",
            paper_bgcolor="#131722",
            showlegend=False,
            height=240,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── AI Market Summary button (Feature 8) ────────────────────────────────
    st.markdown("---")
    ai_col1, ai_col2 = st.columns([3, 1])
    with ai_col1:
        st.subheader("🤖 AI-marknadssammanfattning")
    with ai_col2:
        open_ai = st.button("➡️ Öppna AI Dashboard", key="btn_ov_ai_go", use_container_width=True)
        if open_ai:
            st.info("💡 Du är redan på översiktssidan. Använd navigeringsmenyn eller webbläsarens bakåt-knapp.")

    if st.button("🤖 Generera marknadssammanfattning", key="btn_ov_market_summary", use_container_width=True):
        with st.spinner("Analyserar marknaden..."):
            try:
                provider = _get_provider()
                depth = _get_depth()
                result = ai_analysis.generate_market_summary(
                    df=df if not df.empty else None,
                    sc_df=sc_df if not sc_df.empty else None,
                    provider=provider,
                    depth=depth,
                )
                with st.container(border=True):
                    st.markdown(result)
            except Exception as e:
                st.error(f"❌ {e}")

    # ── Phase 2c: Earnings Calendar ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("📅 Earnings-kalender – kommande rapporter")
    st.caption("Topp-50 aktier som rapporterar inom 14 dagar. Var försiktig med köp precis innan rapport.")
    if not df.empty and "ticker" in df.columns:
        try:
            from core.earnings_calendar import upcoming_in_top
            top_n = st.selectbox("Antal toppaktier att kolla", [20, 30, 50, 100], index=2,
                                  key="ov_earnings_top")
            cal_df = upcoming_in_top(df, top_n=top_n, days_ahead=14)
            if not cal_df.empty:
                def _days_color(d):
                    if d <= 3: return "🔴"
                    if d <= 7: return "🟡"
                    return "🟢"
                cal_df["_urgency"] = cal_df["days_until"].apply(_days_color)
                cal_df["Dagar"] = cal_df.apply(
                    lambda r: f"{r['_urgency']} {r['days_until']}d", axis=1
                )
                display_cal = cal_df[["earnings_date", "Dagar", "ticker", "name", "score_total"]].copy()
                display_cal.columns = ["Rapportdag", "Kvar", "Ticker", "Bolag", "Score"]
                display_cal["Ticker"] = display_cal["Ticker"].apply(
                    lambda t: f"{flag_for_ticker(t)} {t}"
                )
                display_cal["Score"] = display_cal["Score"].apply(
                    lambda v: f"{v:.0f}" if pd.notna(v) else "—"
                )
                col_cfg_cal = {}
                st.dataframe(display_cal, use_container_width=True, hide_index=True,
                             column_config=col_cfg_cal)
                st.caption(f"{len(display_cal)} kommande rapporter inom 14 dagar")
            else:
                st.info("Inga kommande rapporter inom 14 dagar för toppaktierna.")
        except Exception as e:
            st.caption(f"Earnings-kalender ej tillgänglig: {e}")
    else:
        st.info("Ladda scandata för att se earnings-kalender.")

    # ── Phase 2e: Interactive top list ────────────────────────────────────────
    st.markdown("---")
    st.subheader("🏆 Topplista – sök & filtrera")
    st.caption("Välj top-N, sök på ticker/namn och klicka för detaljvy.")
    col_ov_sw, col_ov_ctry = st.columns([1, 3])
    with col_ov_sw:
        ov_only_swedish = st.checkbox("🇸🇪 Endast svenska aktier", value=False,
                                      key="ov_only_swedish")
    with col_ov_ctry:
        ov_countries = [] if ov_only_swedish else st.multiselect(
            "🌍 Länder",
            options=["🇸🇪 Sverige", "🇺🇸 USA", "🇬🇧 UK", "🇩🇪 Tyskland",
                     "🇫🇮 Finland", "🇩🇰 Danmark", "🇳🇴 Norge", "🇨🇳 Kina", "🇯🇵 Japan"],
            default=[],
            key="ov_countries",
            help="Filtrera på börsland. Tomt = alla länder visas.",
        )
    col_top_n, col_search = st.columns([1, 3])
    with col_top_n:
        top_n = st.selectbox("Visa topp", [50, 100, 200, 500], index=1,
                             key="ov_toplists_topn")
    with col_search:
        search_q = st.text_input("🔍 Sök ticker eller bolagsnamn", "",
                                 key="ov_toplists_search",
                                 placeholder="T.ex. AAPL, Investor, ...")

    if df is not None and not df.empty:
        display_df = df.head(top_n).copy()
        # Country filter
        if ov_only_swedish:
            display_df = display_df[display_df["ticker"].str.endswith(".ST", na=False)]
        elif ov_countries:
            _us_sel   = "🇺🇸 USA" in ov_countries
            _suffixes = [_COUNTRY_SUFFIX_MAP[c] for c in ov_countries if c in _COUNTRY_SUFFIX_MAP]
            def _ov_cm(t: str) -> bool:
                if any(t.endswith(s) for s in _suffixes): return True
                if _us_sel and not any(t.endswith(s) for s in _ALL_NON_US_SUFFIXES): return True
                return False
            display_df = display_df[display_df["ticker"].apply(_ov_cm)]
        if search_q.strip():
            q = search_q.strip().lower()
            mask = (
                display_df["ticker"].str.lower().str.contains(q, na=False)
                | display_df["name"].str.lower().str.contains(q, na=False)
            )
            display_df = display_df[mask]
        if display_df.empty:
            st.info("Inga sökresultat.")
        else:
            cols_avail = [c for c in ["ticker", "name", "sector", "score_total",
                                        "price", "change_pct", "volume",
                                        "score_value", "score_momentum",
                                        "score_quality", "score_growth"]
                          if c in display_df.columns]
            shown = display_df[cols_avail].copy()
            if "change_pct" in shown.columns:
                shown["change_pct"] = shown["change_pct"].apply(
                    lambda v: f"{v:+.1f}%" if pd.notna(v) else "—"
                )
            col_config = {
                "score_total": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.0f"
                ),
            }
            col_rename = {
                "ticker": "Ticker", "name": "Bolag",
                "sector": "Sektor", "price": "Pris",
                "change_pct": "Förändring", "volume": "Volym",
                "score_value": "Värde", "score_momentum": "Momentum",
                "score_quality": "Kvalitet", "score_growth": "Tillväxt",
            }
            shown.rename(columns={k: v for k, v in col_rename.items()
                                  if k in shown.columns}, inplace=True)
            if "Ticker" in shown.columns:
                shown["Ticker"] = shown["Ticker"].apply(
                    lambda t: f"{flag_for_ticker(t)} {t}"
                )
            event = st.dataframe(
                shown, use_container_width=True, hide_index=True,
                column_config=col_config,
                on_select="rerun", selection_mode="single-row",
                key="ov_toplists_table",
            )
            if event and event.selection and event.selection.rows:
                selected_idx = event.selection.rows[0]
                sel_ticker = display_df.iloc[selected_idx]["ticker"]
                price_col = "price" if "price" in df.columns else "close"
                row = df[df["ticker"] == sel_ticker]
                if not row.empty:
                    with st.expander(f"🔍 Detaljvy: {sel_ticker}",
                                     expanded=True):
                        c1, c2 = st.columns(2)
                        wl_items_ov = load_watchlist()
                        if c1.button("➕ Lägg till i bevakning", key=f"ov_det_wl_{sel_ticker}", use_container_width=True):
                            if not any(i["ticker"] == sel_ticker for i in wl_items_ov):
                                wl_items_ov.append({"ticker": sel_ticker, "name": row.iloc[0].get("name", sel_ticker), "added": str(date.today())})
                                _save_watchlist_data(wl_items_ov)
                                st.toast(f"✅ {sel_ticker} tillagd i bevakning!", icon="⭐")
                                st.rerun()
                        if c2.button("➕ Lägg till i nästa scan", key=f"ov_det_add_{sel_ticker}", use_container_width=True):
                            is_sc = any(suf in str(sel_ticker).upper() for suf in [".ST", ".HE", ".CO", ".OL"])
                            try:
                                if is_sc:
                                    from smallcap.universe import add_custom
                                    add_custom(sel_ticker, str(row.iloc[0].get("name", sel_ticker)))
                                else:
                                    from core.config import add_custom_to_universe
                                    add_custom_to_universe(sel_ticker, str(row.iloc[0].get("name", sel_ticker)))
                                st.toast(f"✅ {sel_ticker} tillagd i nästa scan!", icon="📡")
                            except Exception as e:
                                st.error(f"Fel: {e}")
                        render_stock_detail(
                            sel_ticker, row=row.iloc[0], df=df,
                            show_ai=True, show_news=False,
                        )
        st.caption(f"{len(display_df)} aktier visas")
    else:
        st.info("Ladda scandata för att visa topplistan.")
