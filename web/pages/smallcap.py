"""web/pages/smallcap.py - Sida 3: Småbolag"""

import pandas as pd
import streamlit as st

from web.utils import (
    kpi_row, sector_bar_chart, score_distribution_chart, pct_fmt,
)
from web.stock_detail import render_stock_detail
from web.ui.components import clickable_stock_table, page_header, section
from web.ui.screener_utils import (
    QUICK_FILTERS as _SC_QF,
    apply_quick_filters as _sc_apply_qf,
    render_enhanced_screener_bar as _sc_render_bar,
    paginate_dataframe as _sc_paginate,
    render_pagination as _sc_pagination,
    render_export_buttons as _sc_export,
    filter_changed_rows as _sc_filter_changed,
)
from core.country_flags import ticker_display as _ticker_display


from core.suffix_map import COUNTRY_SUFFIXES as _COUNTRY_SUFFIX_MAP
_ALL_NON_US_SUFFIXES = set(_COUNTRY_SUFFIX_MAP.values())


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

    # A6-FIX: använd centraliserad apply_country_filter() istf lokal kopia
    from web.utils import apply_country_filter as _acf
    if filters.get("sc_only_swedish") and "ticker" in out.columns:
        out = out[out["ticker"].str.endswith(".ST", na=False)]
    else:
        sel_countries = filters.get("sc_countries", [])
        if sel_countries and "ticker" in out.columns:
            out = _acf(out, sel_countries)

    return out.reset_index(drop=True)


def page_smallcap(sc_df: pd.DataFrame, filters: dict):
    from web.ui.components import page_header
    page_header("Småbolag", "smallcap", subtitle="Nordiska & globala micro/small cap — ranked efter fundamenta, momentum och insider.")

    if sc_df.empty:
        st.warning("Småbolagsdata håller på att laddas in. Systemet uppdateras automatiskt varje måndag -- kom tillbaka då för de senaste analyserna.")
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
         "Bolag med 5 stjärnor -- högsta betygskategorin. Indikerar stark kombination av fundamenta, momentum och värdering."),
        ("Insider BUY",       f"{n_buy}",                    None,
         "Bolag där insiders (styrelse/ledning) nyligen köpt aktier i det egna bolaget. Insiderköp är ett positivt signal -- de känner bolaget bäst."),
        ("Snittpoäng",        f"{avg_sc:.1f}",               None,
         "Genomsnittlig totalpoäng bland filtrerade smallcap-bolag."),
    ])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["🏆 Rankinglista", "📊 Nyckeltal", "🔬 Faktortabell", "🕵️ Insider"]
    )

    # ── Enhanced screener bar (columns, quick filters, export) ────────────────
    _sc_cols_map = {
        "ticker": "Ticker", "sc_stars": "⭐", score_col: "Poäng",
        "predicted_return": "AI 30d-ret", "ml_rank": "AI rank",
        "insider_signal": "Insider", "current_price": "Pris",
        "day_change_pct": "Dag%", "week_change_pct": "Vecka%",
        "return_6m": "6m%", "return_12m": "12m%",
        "piotroski_score": "Piotroski", "sector": "Sektor",
        "ev_to_ebitda": "EV/EBITDA", "price_to_book": "P/B",
        "revenue_growth": "Tillväxt", "debt_to_equity": "D/E",
    }
    _sc_view_opts = _sc_render_bar(
        _sc_cols_map,
        default_columns=["ticker", "sc_stars", score_col, "insider_signal", "current_price", "return_6m"],
        filter_presets=_SC_QF,
        key="sc",
    )

    # Apply quick filter if selected
    if _sc_view_opts["quick_filter"]:
        filt = _sc_apply_qf(filt, _sc_view_opts["quick_filter"], _SC_QF)

    with tab1:
        with st.expander("ℹ️ Hur läser jag rankinglistan? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
**Rankinglistan sorterar alla småbolag efter systemets totalpoäng (0-100).**

### ⭐ Stjärnbetyg
Systemet delar in bolagen i 1-5 stjärnor baserat på totalpoängen:
- **★★★★★ (5 stjärnor):** Starka på nästan alla faktorer -- fundamenta, momentum, värdering, insider
- **★★★★☆ (4 stjärnor):** Mycket bra bolag med bara mindre svagheter
- **★★★☆☆ (3 stjärnor):** OK bolag -- varken bra eller dåliga
- **★★☆☆☆ (2 stjärnor):** Tydliga svagheter i analysen
- **★☆☆☆☆ (1 stjärna):** Undvik eller analysera noggrant

### 📊 Kolumnförklaringar
| Kolumn | Vad det betyder |
|--------|----------------|
| **Poäng** | Totalpoäng 0-100 (blå stapel) -- ju högre desto bättre |
| **AI 30d-ret** | AI-modellens prediktion: hur mycket aktien förväntas röra sig kommande 30 dagar |
| **AI rank** | AI-ranking (0-100) -- kompletterande till klassisk poäng |
| **Insider** | BUY = insiders har nyligen köpt egna aktier (positivt signal) |
| **Dag% / Vecka%** | Kursrörelse senaste dag/vecka |
| **6m% / 12m%** | Avkastning senaste 6 resp. 12 månader |
| **Piotroski** | Finansiell styrka 0-9 (se Faktortabell-fliken för förklaring) |

**Klicka på en aktie** i tabellen för att öppna en full analys!
""")
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
            if "Ticker" in rank_disp.columns:
                rank_disp["Ticker"] = rank_disp["Ticker"].apply(
                    _ticker_display
                )
            for c in ["Dag%", "Vecka%", "6m%", "12m%"]:
                if c in rank_disp.columns:
                    rank_disp[c] = rank_disp[c].apply(lambda v: pct_fmt(v))
            # Dölj AI-kolumner om >80% NaN (ML-modell ej tränad)
            for ai_col in ["AI 30d-ret", "AI rank"]:
                if ai_col in rank_disp.columns and rank_disp[ai_col].isna().mean() > 0.8:
                    rank_disp = rank_disp.drop(columns=[ai_col])
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
            _sc_height = min(600, max(150, len(rank_disp) * 36 + 38))
            sc_event = st.dataframe(rank_disp, use_container_width=True, hide_index=True,
                                    column_config=col_cfg, height=_sc_height,
                                    on_select="rerun", selection_mode="single-row",
                                    key="sc_ranking_table")

            # ── Pagination + Export ───────────────────────────────────────────
            _sc_page_size, _sc_page = _sc_pagination(len(filt), key="sc_rank")
            _sc_export(filt, filename_prefix="smallcap_results", key="sc_rank_export")

            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(sector_bar_chart(filt, score_col), use_container_width=True)
            with c2:
                st.plotly_chart(score_distribution_chart(filt, score_col), use_container_width=True)

            if sc_event and sc_event.selection and sc_event.selection.rows:
                idx = sc_event.selection.rows[0]
                # filt har reset index från _apply_sc_filters -> iloc matchar rank_disp
                sc_detail_ticker = filt.iloc[idx]["ticker"]       # råticker, ingen flagg
                sc_display_name  = rank_disp.iloc[idx]["Ticker"]  # med flagg, för titel
                sc_row = sc_df[sc_df["ticker"] == sc_detail_ticker]
                if not sc_row.empty:
                    with st.expander(f"🔍 Detaljvy: {sc_display_name}", expanded=True):
                        render_stock_detail(
                            sc_detail_ticker, row=sc_row.iloc[0], df=sc_df,
                            show_ai=True, show_news=False, show_chart=True, show_detail_data=True,
                        )

    with tab2:
        with st.expander("ℹ️ Vad är nyckeltal? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
**Nyckeltal hjälper dig bedöma om ett bolag är billigt, lönsamt och finansiellt stabilt.**

| Nyckeltal | Vad det mäter | Bra värde (tumregel) |
|-----------|--------------|---------------------|
| **EV/EBITDA** | Pris relativt rörelseresultat | < 10 = billigt * > 20 = dyrt |
| **P/B** | Pris relativt bokfört värde | < 1,5 = billigt * > 3 = dyrt |
| **Bruttomarg.** | Hur stor andel av intäkten som är vinst efter direkta kostnader | > 40% = stark * < 20% = svag |
| **Rörelsmarg.** | Vinst efter alla driftskostnader (mer komplett än bruttomarginal) | > 10% = bra |
| **Oms.tillv.** | Hur snabbt omsättningen växer | > 10%/år = bra |
| **Vinst.tillv.** | Hur snabbt vinsten växer | > 10%/år = bra |
| **D/E** | Skulder i förhållande till eget kapital (skuldsättning) | < 1 = låg risk * > 2 = hög risk |
| **CR (Current Ratio)** | Förmåga att betala kortfristiga skulder | > 1,5 = bra * < 1 = varning |
| **FCF** | Fritt kassaflöde -- faktiska pengar bolaget genererar | Positivt = bra |
| **Kassa** | Likvida medel bolaget har | Mer = bättre buffert |

**Tumregel:** Bra bolag har hög lönsamhet (marginaler), låg skuldsättning (D/E) och positivt kassaflöde (FCF).

**Klicka på en aktie** för full analys med AI-kommentarer!
""")
        if not filt.empty:
            key_cols = [c for c in [
                "ticker", "sc_stars", "current_price",
                "market_cap", "ev_to_ebitda", "price_to_book",
                "gross_margin", "operating_margin",
                "revenue_growth", "earnings_growth",
                "debt_to_equity", "current_ratio",
                "free_cash_flow", "total_cash",
            ] if c in filt.columns]
            kn = filt[key_cols].copy()
            kn["ticker"] = kn["ticker"].apply(_ticker_display)
            kn = kn.rename(columns={
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
            clickable_stock_table(kn, ticker_col="Ticker", context_df=filt,
                                  key="sc_keynums_table", height=600)

    with tab3:
        with st.expander("ℹ️ Vad är faktortabellen? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
**Systemet betygsätter varje bolag på 7 delfaktorer -- se hur stark varje aspekt är.**

| Faktor | Vad bedöms | Högt = bra? |
|--------|-----------|------------|
| **Insider** | Insiderägande + senaste köp/sälj av styrelse/ledning | ✅ Ja -- insiders som köper tror på bolaget |
| **FCF** | Fritt kassaflöde -- hur mycket pengar bolaget faktiskt tjänar | ✅ Ja -- positivt kassaflöde = finansiellt friskt |
| **Piotroski** | Finansiell hälsocheck (9 kriterier: lönsamhet, likviditet, effektivitet) | ✅ Ja -- 7-9 = starkt bolag |
| **Tillväxt** | Omsättnings- och vinsttillväxt | ✅ Ja -- växande bolag är bättre på sikt |
| **Balans** | Skuldsättning och kreditvärdighet | ✅ Ja -- låg skuld = lägre risk |
| **Värdering** | Är aktien billig eller dyr vs. bolagets verkliga värde? | ✅ Ja -- billig = mer uppsida |
| **Momentum** | Prismomentumet -- rör sig aktien uppåt? | ✅ Ja -- aktier i upptrend fortsätter ofta upp |
| **Likviditet** | Hur lätt det är att köpa/sälja aktien utan att påverka kursen | ✅ Ja -- hög likviditet = lättare att handla |
| **Totalt** | Viktad summa av alla faktorer (0-100) | ✅ Ja -- > 60 = starkt bolag |

**Blå staplar:** Poäng 0-100. Längre stapel = bättre på den faktorn.

**Klicka på en aktie** för att se detaljerad analys och AI-kommentarer!
""")
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
            fact["ticker"] = fact["ticker"].apply(_ticker_display)
            fact = fact.rename(columns={"ticker": "Ticker", **{c: sc_factor_map[c] for c in fact_cols}})
            col_cfg2 = {lbl: st.column_config.ProgressColumn(lbl, min_value=0, max_value=100, format="%.0f")
                        for lbl in sc_factor_map.values() if lbl in fact.columns}
            clickable_stock_table(fact, ticker_col="Ticker", context_df=filt,
                                  key="sc_factors_table", height=600,
                                  column_config=col_cfg2 or None)

    with tab4:
        with st.expander("ℹ️ Vad är insider-data? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
### 👔 Vad är insiderhandel (laglig)?
**Insiders** = VD, CFO, styrelseledamöter och storägare (>=10%) i bolaget.
De måste rapportera alla köp och sälj av egna aktier till Finansinspektionen inom 3 dagar.

Det är **helt lagligt** att handla i det egna bolagets aktier -- det som är olagligt är att göra det
baserat på hemlig information som inte är offentlig.

### 📊 Kolumnförklaringar
| Kolumn | Vad det betyder |
|--------|----------------|
| **Insiders äger%** | Andel av totalt aktiekapital som ägs av insiders. Högt (>10%) = insiders tror starkt på bolaget |
| **Signal** | BUY = nettoköp senaste perioden * SELL = nettosälj |
| **Netto köp 6m** | Totalt köpvärde minus säljvärde senaste 6 månaderna (i SEK) |
| **Antal köp** | Antal insidertransaktioner som var köp |
| **Antal sälj** | Antal insidertransaktioner som var sälj |

### 🔍 Hur tolkar jag det?
- **BUY-signal + högt ägarskap:** Insiders satsar egna pengar -> stark positiv signal
- **SELL-signal:** Inte nödvändigtvis dåligt -- de kan sälja av skattemässiga skäl eller diversifiering
- **Klusterköp (flera insiders köper samtidigt):** Starkaste möjliga signal

**Klicka på en aktie** för full analys!
""")
        if not filt.empty:
            ins_cols = [c for c in [
                "ticker", "insider_pct", "insider_signal",
                "insider_net_buy_6m", "insider_buy_count", "insider_sell_count",
            ] if c in filt.columns]
            if ins_cols:
                ins = filt[ins_cols].copy()
                ins["ticker"] = ins["ticker"].apply(_ticker_display)
                ins = ins.rename(columns={
                    "ticker": "Ticker",
                    "insider_pct": "Insiders äger%",
                    "insider_signal": "Signal",
                    "insider_net_buy_6m": "Netto köp 6m (SEK)",
                    "insider_buy_count": "Antal köp",
                    "insider_sell_count": "Antal sälj",
                })
                if "Insiders äger%" in ins.columns:
                    ins["Insiders äger%"] = ins["Insiders äger%"].apply(lambda v: pct_fmt(v))
                clickable_stock_table(ins, ticker_col="Ticker", context_df=filt,
                                      key="sc_insider_table", height=400)

                buy_tickers = filt[filt.get("insider_signal", pd.Series()) == "BUY"]["ticker"].tolist() \
                    if "insider_signal" in filt.columns else []
                if buy_tickers:
                    st.success(f"Insiderköp-signaler: **{', '.join(buy_tickers)}**")
            else:
                st.info("Ingen insiderdata tillgänglig.")
