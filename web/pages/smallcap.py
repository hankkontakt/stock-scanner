"""web/pages/smallcap.py – Sida 3: Småbolag"""

import pandas as pd
import streamlit as st

from web.utils import (
    kpi_row, sector_bar_chart, score_distribution_chart, pct_fmt,
)
from web.stock_detail import render_stock_detail


def _apply_sc_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    if df.empty:
        return df

    out       = df.copy()
    score_col = "sc_total" if "sc_total" in out.columns else "score_total"

    if score_col in out.columns:
        out = out[out[score_col] >= filters.get("sc_score_min", 30)]

    sel_stars = filters.get("sc_stars", [])
    if sel_stars and "sc_stars" in out.columns:
        out = out[out["sc_stars"].isin(sel_stars)]

    sel_sec = filters.get("sc_sector", [])
    if sel_sec and "sector" in out.columns:
        out = out[out["sector"].isin(sel_sec)]

    sel_ins = filters.get("sc_insider", "Alla")
    if sel_ins != "Alla" and "insider_signal" in out.columns:
        out = out[out["insider_signal"] == sel_ins]

    if filters.get("sc_fcf") and "free_cash_flow" in out.columns:
        out = out[out["free_cash_flow"] > 0]

    max_de = filters.get("sc_max_de", 300)
    if "debt_to_equity" in out.columns:
        out = out[out["debt_to_equity"].fillna(0) <= max_de]

    return out.reset_index(drop=True)


def page_smallcap(sc_df: pd.DataFrame, filters: dict):
    st.title("🏦 Småbolag – svenska small/micro cap")

    if sc_df.empty:
        st.warning(
            "Ingen smallcap-data hittad. Kör `python smallcap/scanner.py` för att generera."
        )
        return

    if "sector" in sc_df.columns:
        secs = sorted(sc_df["sector"].dropna().unique().tolist())
        with st.sidebar:
            with st.expander("Sektorer i småbolag", expanded=False):
                st.write(", ".join(secs))

    score_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"

    has_ml = "predicted_return" in sc_df.columns
    if has_ml:
        sc_rank_mode = st.radio(
            "🤖 Ranking-läge",
            ["Klassisk score", "AI prediction"],
            horizontal=True,
            key="smallcap_rank_mode",
            help="AI-modellen (XGBoost) tränas separat på svenska småbolag och förutspår 30-dagars avkastning."
        )
    else:
        sc_rank_mode = "Klassisk score"

    filt = _apply_sc_filters(sc_df, filters)
    if sc_rank_mode == "AI prediction" and "predicted_return" in filt.columns:
        filt = filt.sort_values("predicted_return", ascending=False)

    n_five = (filt.get("sc_stars", pd.Series()) == "★★★★★").sum() \
        if "sc_stars" in filt.columns else 0
    n_buy  = (filt.get("insider_signal", pd.Series()) == "BUY").sum() \
        if "insider_signal" in filt.columns else 0
    avg_sc = filt[score_col].mean() if score_col in filt.columns else 0
    kpi_row([
        ("Bolag (filtrerat)", f"{len(filt)} / {len(sc_df)}", None,
         "Antal smallcap-bolag som uppfyller aktuella filter av totalt antal i smallcap-universumet."),
        ("★★★★★ bolag",       f"{n_five}",                   None,
         "Bolag med 5 stjärnor — högsta betygskategorin. Indikerar stark kombination av fundamenta, momentum och värdering."),
        ("Insider BUY",       f"{n_buy}",                    None,
         "Bolag där insiders (styrelse/ledning) nyligen köpt aktier i det egna bolaget. Insiderköp är ett positivt signal — de känner bolaget bäst."),
        ("Snittpoäng",        f"{avg_sc:.1f}",               None,
         "Genomsnittlig totalpoäng bland filtrerade smallcap-bolag."),
    ])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["🏆 Rankinglista", "📊 Nyckeltal", "🔬 Faktortabell", "🕵️ Insider"]
    )

    with tab1:
        if filt.empty:
            st.info("Inga bolag matchar filter.")
        else:
            rank_cols = [c for c in [
                "ticker", "sc_stars", score_col, "predicted_return", "ml_rank",
                "insider_signal",
                "current_price", "day_change_pct", "week_change_pct",
                "return_6m", "return_12m", "piotroski_score",
            ] if c in filt.columns]
            rank_disp = filt[rank_cols].copy()
            rank_disp.insert(0, "Rank", range(1, len(rank_disp) + 1))
            rename = {
                "ticker": "Ticker", "sc_stars": "⭐",
                score_col: "Poäng",
                "predicted_return": "AI 30d-ret",
                "ml_rank": "AI rank",
                "insider_signal": "Insider",
                "current_price": "Pris",
                "day_change_pct": "Dag%",
                "week_change_pct": "Vecka%",
                "return_6m": "6m%",
                "return_12m": "12m%",
                "piotroski_score": "Piotroski",
            }
            rank_disp = rank_disp.rename(columns=rename)
            for c in ["Dag%", "Vecka%", "6m%", "12m%"]:
                if c in rank_disp.columns:
                    rank_disp[c] = rank_disp[c].apply(lambda v: pct_fmt(v))
            if "AI 30d-ret" in rank_disp.columns and not rank_disp["AI 30d-ret"].isna().all():
                rank_disp["AI 30d-ret"] = rank_disp["AI 30d-ret"] * 100
            col_cfg = {}
            if "Poäng" in rank_disp.columns:
                col_cfg["Poäng"] = st.column_config.ProgressColumn(
                    "Poäng", min_value=0, max_value=100, format="%.0f"
                )
            if "AI rank" in rank_disp.columns:
                col_cfg["AI rank"] = st.column_config.ProgressColumn(
                    "AI rank", min_value=0, max_value=100, format="%.0f"
                )
            if "AI 30d-ret" in rank_disp.columns:
                col_cfg["AI 30d-ret"] = st.column_config.NumberColumn(
                    "AI 30d-ret", format="%.1f%%",
                    help="ML-modellens prediktion av avkastning kommande 30 dagar"
                )
            sc_event = st.dataframe(rank_disp, use_container_width=True, hide_index=True,
                                    column_config=col_cfg, height=600,
                                    on_select="rerun", selection_mode="single-row",
                                    key="sc_ranking_table")

            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(sector_bar_chart(filt, score_col), use_container_width=True)
            with c2:
                st.plotly_chart(score_distribution_chart(filt, score_col), use_container_width=True)

            if sc_event and sc_event.selection and sc_event.selection.rows:
                sc_detail_ticker = rank_disp.iloc[sc_event.selection.rows[0]]["Ticker"]
                sc_row = sc_df[sc_df["ticker"] == sc_detail_ticker]
                if not sc_row.empty:
                    with st.expander(f"🔍 Detaljvy: {sc_detail_ticker}", expanded=True):
                        render_stock_detail(
                            sc_detail_ticker, row=sc_row.iloc[0], df=sc_df,
                            show_ai=True, show_news=False, show_chart=True, show_detail_data=True,
                        )

    with tab2:
        if not filt.empty:
            key_cols = [c for c in [
                "ticker", "sc_stars", "current_price",
                "market_cap", "ev_to_ebitda", "price_to_book",
                "gross_margin", "operating_margin",
                "revenue_growth", "earnings_growth",
                "debt_to_equity", "current_ratio",
                "free_cash_flow", "total_cash",
            ] if c in filt.columns]
            kn = filt[key_cols].copy().rename(columns={
                "ticker": "Ticker", "sc_stars": "⭐",
                "current_price": "Pris", "market_cap": "Mkap (USD)",
                "ev_to_ebitda": "EV/EBITDA", "price_to_book": "P/B",
                "gross_margin": "Bruttomarg.", "operating_margin": "Rörelsmarg.",
                "revenue_growth": "Oms.tillv.", "earnings_growth": "Vinst.tillv.",
                "debt_to_equity": "D/E", "current_ratio": "CR",
                "free_cash_flow": "FCF", "total_cash": "Kassa",
            })
            for c in ["Bruttomarg.", "Rörelsmarg.", "Oms.tillv.", "Vinst.tillv."]:
                if c in kn.columns:
                    kn[c] = kn[c].apply(lambda v: pct_fmt(v))
            st.dataframe(kn, use_container_width=True, hide_index=True, height=600)

    with tab3:
        if not filt.empty:
            sc_factor_map = {
                "sc_insider":   "Insider",
                "sc_fcf":       "FCF",
                "sc_piotroski": "Piotroski",
                "sc_growth":    "Tillväxt",
                "sc_balance":   "Balans",
                "sc_valuation": "Värdering",
                "sc_momentum":  "Momentum",
                "sc_liquidity": "Likviditet",
                score_col:      "Totalt",
            }
            fact_cols = [c for c in sc_factor_map if c in filt.columns]
            fact = filt[["ticker"] + fact_cols].copy()
            fact = fact.rename(columns={"ticker": "Ticker", **{c: sc_factor_map[c] for c in fact_cols}})
            col_cfg2 = {lbl: st.column_config.ProgressColumn(lbl, min_value=0, max_value=100, format="%.0f")
                        for lbl in sc_factor_map.values() if lbl in fact.columns}
            st.dataframe(fact, use_container_width=True, hide_index=True,
                         column_config=col_cfg2, height=600)

    with tab4:
        if not filt.empty:
            ins_cols = [c for c in [
                "ticker", "insider_pct", "insider_signal",
                "insider_net_buy_6m", "insider_buy_count", "insider_sell_count",
            ] if c in filt.columns]
            if ins_cols:
                ins = filt[ins_cols].copy().rename(columns={
                    "ticker": "Ticker",
                    "insider_pct": "Insiders äger%",
                    "insider_signal": "Signal",
                    "insider_net_buy_6m": "Netto köp 6m (SEK)",
                    "insider_buy_count": "Antal köp",
                    "insider_sell_count": "Antal sälj",
                })
                if "Insiders äger%" in ins.columns:
                    ins["Insiders äger%"] = ins["Insiders äger%"].apply(lambda v: pct_fmt(v))
                st.dataframe(ins, use_container_width=True, hide_index=True, height=400)

                buy_tickers = filt[filt.get("insider_signal", pd.Series()) == "BUY"]["ticker"].tolist() \
                    if "insider_signal" in filt.columns else []
                if buy_tickers:
                    st.success(f"Insiderköp-signaler: **{', '.join(buy_tickers)}**")
            else:
                st.info("Ingen insiderdata tillgänglig.")
