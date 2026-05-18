"""web/pages/weekly_scan.py – Sida 2: Veckoscanner"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from web.utils import (
    kpi_row, sector_bar_chart, score_distribution_chart,
    scatter_momentum_value, pct_fmt,
)
from web.stock_detail import render_stock_detail
from core.country_flags import flag_for_ticker


def _apply_weekly_filters(df: pd.DataFrame, filters: dict,
                          holdings: pd.DataFrame, watchlist: list) -> pd.DataFrame:
    if df.empty:
        return df

    if "sector" in df.columns:
        secs = sorted(df["sector"].dropna().unique().tolist())
        st.session_state["weekly_sectors"] = secs

    out = df.copy()

    if "score_total" in out.columns:
        lo, hi = filters.get("score_min", 0), filters.get("score_max", 100)
        out = out[out["score_total"].between(lo, hi)]

    sel_sectors = filters.get("sector", [])
    if sel_sectors and "sector" in out.columns:
        out = out[out["sector"].isin(sel_sectors)]

    sel_entry = filters.get("entry", [])
    if sel_entry and "entry_signal" in out.columns:
        out = out[out["entry_signal"].isin(sel_entry)]

    sel_conf = filters.get("confidence", [])
    if sel_conf and "confidence_label" in out.columns:
        out = out[out["confidence_label"].isin(sel_conf)]

    sel_trend = filters.get("trend", "Alla")
    if sel_trend != "Alla" and "trend_signal" in out.columns:
        out = out[out["trend_signal"] == sel_trend]

    pio_min = filters.get("piotroski_min", 0)
    if pio_min > 0 and "piotroski_f" in out.columns:
        out = out[out["piotroski_f"].fillna(0) >= pio_min]

    if filters.get("show_holdings") and not holdings.empty:
        h_tickers = set(holdings["ticker"].str.upper())
        out = out[out["ticker"].isin(h_tickers)]

    if filters.get("only_swedish"):
        out = out[out["ticker"].str.endswith(".ST", na=False)]

    _SUFFIX_MAP = {
        "🇸🇪 Sverige": ".ST",
        "🇬🇧 UK":      ".L",
        "🇩🇪 Tyskland": ".DE",
        "🇫🇮 Finland": ".HE",
        "🇩🇰 Danmark": ".CO",
        "🇳🇴 Norge":   ".OL",
        "🇨🇳 Kina":    ".SS",
        "🇯🇵 Japan":   ".T",
    }
    _ALL_NON_US = set(_SUFFIX_MAP.values())
    selected_countries = filters.get("countries", [])
    if selected_countries:
        us_sel = "🇺🇸 USA" in selected_countries
        suffixes = [_SUFFIX_MAP[c] for c in selected_countries if c in _SUFFIX_MAP]
        def _country_match(t: str) -> bool:
            t = str(t)
            if any(t.endswith(s) for s in suffixes):
                return True
            if us_sel and not any(t.endswith(s) for s in _ALL_NON_US):
                return True
            return False
        out = out[out["ticker"].apply(_country_match)]

    return out.reset_index(drop=True)


def _main_ranking_table(df: pd.DataFrame, holdings: pd.DataFrame, watchlist: list, table_key: str = "main_ranking_table"):
    """Visar huvudrankingstabellen med färgkodning."""
    if df.empty:
        st.info("Inga bolag matchar aktuella filter.")
        return

    h_tickers = set(holdings["ticker"].str.upper()) if not holdings.empty else set()
    wl_tickers = {i["ticker"] for i in watchlist}

    def _flag(t):
        if t in h_tickers:  return "💼 Innehav"
        if t in wl_tickers: return "⭐ Bevakad"
        return ""

    show = df.copy()
    show["_status"] = show["ticker"].apply(_flag)

    base_cols = [c for c in [
        "rank", "ticker", "name", "_status", "sector",
        "score_total", "predicted_return", "ml_rank",
        "entry_signal", "confidence_label", "trend_signal",
        "delta_flag", "piotroski_f",
    ] if c in show.columns]

    display = show[base_cols].copy()
    display = display.rename(columns={
        "rank":              "Rank",
        "ticker":            "Ticker",
    })
    if "Ticker" in display.columns:
        display["Ticker"] = display["Ticker"].apply(lambda t: f"{flag_for_ticker(t)} {t}")
    display = display.rename(columns={
        "name":              "Bolag",
        "_status":           "Status",
        "sector":            "Sektor",
        "score_total":       "Score (klassisk)",
        "predicted_return":  "AI 30d-ret",
        "ml_rank":           "AI rank",
        "entry_signal":      "Entry",
        "confidence_label":  "Konf.",
        "trend_signal":      "Trend",
        "delta_flag":        "Δ",
        "piotroski_f":       "Piotroski",
    })

    if "Rank" in display.columns:
        display["Rank"] = range(1, len(display) + 1)

    col_cfg = {
        "Rank": st.column_config.NumberColumn("Rank", help="Position i rankinglistan. Rank 1 = bäst poäng i det filtrerade urvalet.", format="%d"),
        "Ticker": st.column_config.TextColumn("Ticker", help="Börsticker — den förkortade koden som identifierar aktien på börsen."),
        "Bolag": st.column_config.TextColumn("Bolag", help="Bolagets fullständiga namn."),
        "Status": st.column_config.TextColumn("Status", help="💼 = du äger aktien · ⭐ = du bevakar den"),
        "Sektor": st.column_config.TextColumn("Sektor", help="Vilken bransch bolaget tillhör. Sektorrotation är viktigt — starka sektorer presterar ofta bättre."),
        "Entry": st.column_config.TextColumn("Entry", help="Köpsignal baserad på momentum och volym. STARK = tydlig uppåtrörelse med hög konfidensgrad. OK = måttlig signal. —= ingen signal just nu."),
        "Konf.": st.column_config.TextColumn("Konf.", help="Konfidensnivå för entry-signalen. HÖG = starka indikatorer samstämmer. MEDEL = blandat. LÅG = svag signal."),
        "Trend": st.column_config.TextColumn("Trend", help="Teknisk trend baserad på MA50/MA200. UPPTREND = aktien är i positiv trend och över sina glidande medelvärden."),
        "Δ": st.column_config.TextColumn("Δ", help="Förändring sedan förra scanningen — t.ex. 'NYI TOPP20' eller rörelsepil. Visar rörlighet i rankinglistan."),
        "Piotroski": st.column_config.NumberColumn("Piotroski", format="%.0f/9", help="Piotroski F-Score: 0–9 poäng baserade på 9 nyckeltal för lönsamhet, hävstång och effektivitet. 7–9 = stark fundamenta. 0–2 = svag."),
    }
    if "Score (klassisk)" in display.columns:
        col_cfg["Score (klassisk)"] = st.column_config.ProgressColumn(
            "Score (klassisk)", min_value=0, max_value=100, format="%.0f",
            help="Totalt poäng 0–100 baserat på värdering, kvalitet, momentum, tillväxt, risk och storlek. 70+ = stark. 50–69 = neutral. <50 = svag.",
        )
    if "AI rank" in display.columns:
        col_cfg["AI rank"] = st.column_config.ProgressColumn(
            "AI rank", min_value=0, max_value=100, format="%.0f",
            help="ML-modellens rangordning 0–100. Kombinerar klassisk score med maskininlärd prediktion av framtida avkastning.",
        )
    if "AI 30d-ret" in display.columns:
        col_cfg["AI 30d-ret"] = st.column_config.NumberColumn(
            "AI 30d-ret", format="%.1f%%",
            help="ML-modellens prediktion av avkastning kommande 30 dagar. Baseras på momentum, fundamenta och historiska mönster. Inte en garanti.",
        )
        if not display["AI 30d-ret"].isna().all():
            display["AI 30d-ret"] = display["AI 30d-ret"] * 100

    event = st.dataframe(
        display,
        use_container_width=True,
        height=min(700, max(350, len(display) * 36 + 40)),
        column_config=col_cfg,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
    )
    st.caption(f"Visar {len(display)} bolag — klicka på en rad för detaljer")

    if event and event.selection and event.selection.rows:
        idx = event.selection.rows[0]
        # Använd råtickern från show (utan flagg-emoji) för lookup –
        # display["Ticker"] har "🇸🇪 VOLV-B.ST" som inte matchar df["ticker"].
        sel_ticker     = show.iloc[idx]["ticker"]
        sel_display    = display.iloc[idx]["Ticker"]   # med flagg, bara för UI-titel
        sel_row = df[df["ticker"] == sel_ticker]
        if not sel_row.empty:
            with st.expander(f"🔍 Detaljvy: {sel_display}", expanded=True):
                render_stock_detail(sel_ticker, row=sel_row.iloc[0], df=df,
                                    show_ai=True, show_news=False,
                                    show_chart=True, show_detail_data=True)

    st.markdown("---")
    st.subheader("🤖 Fråga AI om en aktie")
    ticker_list = df["ticker"].tolist()
    col_q1, col_q2 = st.columns([3, 1])
    with col_q1:
        ai_ticker = st.selectbox("Välj aktie att analysera", ticker_list, key=f"{table_key}_ai_ticker")
    with col_q2:
        ai_go = st.button("🤖 Analysera", key=f"btn_{table_key}_ai", use_container_width=True)
    if ai_go and ai_ticker:
        row = df[df["ticker"] == ai_ticker]
        if not row.empty:
            with st.expander("🔍 Visa detaljvy + AI-analys", expanded=True):
                render_stock_detail(
                    ai_ticker, row=row.iloc[0], df=df,
                    show_ai=True, show_news=False, show_chart=True, show_detail_data=True,
                )


def page_weekly_scan(df: pd.DataFrame, filters: dict,
                     holdings: pd.DataFrame, watchlist: list):
    st.title("🔍 Veckoscanner")

    if df.empty:
        st.warning("Aktiedata håller på att laddas in. Systemet uppdateras automatiskt varje vecka — prova igen om en stund.")
        return

    if "sector" in df.columns:
        secs = sorted(df["sector"].dropna().unique().tolist())
        with st.sidebar:
            with st.expander("Tillgängliga sektorer", expanded=False):
                st.write(", ".join(secs))

    has_ml = "predicted_return" in df.columns
    if has_ml:
        rank_mode = st.radio(
            "🤖 Ranking-läge",
            ["Klassisk score", "AI prediction", "Båda (side-by-side)"],
            horizontal=True,
            key="weekly_rank_mode",
            help="AI-modellen (XGBoost) lär sig från historisk prishistorik och förutspår 30-dagars avkastning."
        )
    else:
        rank_mode = "Klassisk score"

    filt_df = _apply_weekly_filters(df, filters, holdings, watchlist)

    if rank_mode == "AI prediction" and "predicted_return" in filt_df.columns:
        filt_df = filt_df.sort_values("predicted_return", ascending=False)
    elif rank_mode == "Båda (side-by-side)" and "predicted_return" in filt_df.columns:
        pass

    n_total  = len(df)
    n_filt   = len(filt_df)
    avg_sc   = filt_df["score_total"].mean() if "score_total" in filt_df.columns else 0
    n_stark  = (filt_df["entry_signal"] == "STARK").sum() if "entry_signal" in filt_df.columns else 0
    kpi_row([
        ("Totalt i scan",    f"{n_total}",        None,
         "Totalt antal bolag i universumet innan filter appliceras."),
        ("Matchar filter",   f"{n_filt}",          None,
         "Antal bolag som uppfyller dina valda filtervillkor (sektor, land, poäng etc.)."),
        ("Snittpoäng",       f"{avg_sc:.1f}",      None,
         "Genomsnittlig totalpoäng bland filtrerade bolag. Högt snitt = starkt filtrerat urval."),
        ("STARK entry",      f"{n_stark}",         None,
         "Antal bolag med STARK köpsignal bland filtrerade bolag. Dessa är de starkaste köpkandidaterna just nu."),
    ])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 Ranking", "📊 Fundamental", "📈 Momentum & Teknisk", "🔬 Score-detalj"]
    )

    with tab1:
        if rank_mode == "Båda (side-by-side)" and "predicted_return" in filt_df.columns:
            col_classic, col_ml = st.columns(2)
            with col_classic:
                st.subheader("📊 Klassisk score")
                _main_ranking_table(filt_df, holdings, watchlist)
            with col_ml:
                st.subheader("🤖 ML-prediktion")
                ml_sorted = filt_df.sort_values("predicted_return", ascending=False)
                _main_ranking_table(ml_sorted, holdings, watchlist, table_key="main_ranking_table_ml")
        else:
            _main_ranking_table(filt_df, holdings, watchlist)
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(sector_bar_chart(filt_df), use_container_width=True)
        with c2:
            st.plotly_chart(score_distribution_chart(filt_df), use_container_width=True)

        st.markdown("---")
        st.subheader("📈 Detaljvy")
        if not filt_df.empty and "ticker" in filt_df.columns:
            ws_ticker = st.selectbox("Välj aktie", sorted(filt_df["ticker"].tolist()),
                                     key="ws_detail_ticker")
            ws_row = df[df["ticker"] == ws_ticker]
            if not ws_row.empty:
                with st.expander("🔍 Visa detaljvy", expanded=False):
                    render_stock_detail(
                        ws_ticker, row=ws_row.iloc[0], df=df,
                        show_ai=True, show_news=False, show_chart=True, show_detail_data=True,
                    )

    with tab2:
        if filt_df.empty:
            st.info("Inga data.")
        else:
            fund_cols = [c for c in [
                "ticker", "name", "sector",
                "pe_trailing", "pe_forward", "price_to_book",
                "roe", "roa", "profit_margin", "gross_margin",
                "revenue_growth", "earnings_growth",
                "debt_to_equity", "current_ratio", "dividend_yield",
                "free_cash_flow", "piotroski_f",
            ] if c in filt_df.columns]
            fund = filt_df[fund_cols].copy()
            fund = fund.rename(columns={
                "ticker": "Ticker", "name": "Bolag", "sector": "Sektor",
                "pe_trailing": "P/E", "pe_forward": "P/E fwd",
                "price_to_book": "P/B", "roe": "ROE", "roa": "ROA",
                "profit_margin": "Nettomarg.", "gross_margin": "Bruttomarg.",
                "revenue_growth": "Oms.tillv.", "earnings_growth": "Vinst.tillv.",
                "debt_to_equity": "D/E", "current_ratio": "CR",
                "dividend_yield": "Utd.yield", "free_cash_flow": "FCF",
                "piotroski_f": "Piotroski",
            })
            pct_fcols = ["ROE", "ROA", "Nettomarg.", "Bruttomarg.",
                         "Oms.tillv.", "Vinst.tillv.", "Utd.yield"]
            for c in pct_fcols:
                if c in fund.columns:
                    fund[c] = fund[c].apply(lambda v: pct_fmt(v))
            st.dataframe(fund, use_container_width=True, hide_index=True, height=600)

    with tab3:
        if filt_df.empty:
            st.info("Inga data.")
        else:
            tech_cols = [c for c in [
                "ticker", "name", "sector",
                "current_price", "price_vs_ma50", "price_vs_ma200",
                "rsi_14", "bb_position", "macd_above_signal",
                "return_1m", "return_3m", "return_6m", "return_12m",
                "volatility", "beta", "pct_from_52w_high",
                "52_week_high", "52_week_low",
                "avg_volume", "volume_ratio",
            ] if c in filt_df.columns]
            tech = filt_df[tech_cols].copy()
            tech = tech.rename(columns={
                "ticker": "Ticker", "name": "Bolag", "sector": "Sektor",
                "current_price": "Pris", "price_vs_ma50": "vs MA50",
                "price_vs_ma200": "vs MA200", "rsi_14": "RSI",
                "bb_position": "BB pos", "macd_above_signal": "MACD>signal",
                "return_1m": "1m", "return_3m": "3m",
                "return_6m": "6m", "return_12m": "12m",
                "volatility": "Volatilitet", "beta": "Beta",
                "pct_from_52w_high": "från 52v-high",
                "52_week_high": "52v High", "52_week_low": "52v Low",
                "avg_volume": "Avg vol", "volume_ratio": "Vol ratio",
            })
            for c in ["vs MA50", "vs MA200", "1m", "3m", "6m", "12m", "från 52v-high"]:
                if c in tech.columns:
                    tech[c] = tech[c].apply(lambda v: pct_fmt(v))
            st.dataframe(tech, use_container_width=True, hide_index=True, height=600)
            st.markdown("---")
            st.plotly_chart(scatter_momentum_value(filt_df), use_container_width=True)

    with tab4:
        if filt_df.empty:
            st.info("Inga data.")
        else:
            score_cols_map = {
                "score_value":    "Värdering",
                "score_quality":  "Kvalitet",
                "score_momentum": "Momentum",
                "score_growth":   "Tillväxt",
                "score_risk":     "Risk",
                "score_size":     "Storlek",
                "score_dividend": "Utdelning",
                "score_sentiment":"Sentiment",
                "score_total":    "Totalt",
            }
            sc_cols = [c for c in score_cols_map if c in filt_df.columns]
            sc_disp = filt_df[["ticker", "name"] + sc_cols].copy()
            rename  = {c: score_cols_map[c] for c in sc_cols}
            rename.update({"ticker": "Ticker", "name": "Bolag"})
            sc_disp = sc_disp.rename(columns=rename)
            col_cfg = {}
            for lbl in score_cols_map.values():
                if lbl in sc_disp.columns:
                    col_cfg[lbl] = st.column_config.ProgressColumn(
                        lbl, min_value=0, max_value=100, format="%.0f"
                    )
            st.dataframe(sc_disp, use_container_width=True, hide_index=True,
                         column_config=col_cfg, height=600)

            st.markdown("---")
            st.subheader("🕸️ Score-radar – enskilt bolag")
            if not filt_df.empty and sc_cols:
                tickers_list = filt_df["ticker"].tolist()
                chosen = st.selectbox("Välj bolag", tickers_list, key="radar_ticker")
                _match = filt_df[filt_df["ticker"] == chosen]
                if _match.empty:
                    st.info("Vald aktie hittades inte i filtrerad data.")
                    return
                row = _match.iloc[0]
                r_vals  = [row.get(c, 0) for c in sc_cols]
                r_cats  = [score_cols_map[c] for c in sc_cols]
                fig_rad = go.Figure(go.Scatterpolar(
                    r=r_vals + [r_vals[0]],
                    theta=r_cats + [r_cats[0]],
                    fill="toself",
                    fillcolor="rgba(66,165,245,0.25)",
                    line_color="#42a5f5",
                ))
                fig_rad.update_layout(
                    polar=dict(
                        bgcolor="#1e2230",
                        radialaxis=dict(range=[0, 100], color="#8892a4"),
                        angularaxis=dict(color="#8892a4"),
                    ),
                    paper_bgcolor="#131722",
                    template="plotly_dark",
                    height=380,
                    margin=dict(t=40, b=20, l=40, r=40),
                )
                st.plotly_chart(fig_rad, use_container_width=True)
