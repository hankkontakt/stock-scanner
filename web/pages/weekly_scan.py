"""web/pages/weekly_scan.py - Sida 2: Veckoscanner"""

import glob as _glob
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pathlib import Path

from web.utils import (
    kpi_row, sector_bar_chart, score_distribution_chart,
    scatter_momentum_value, pct_fmt, REPORT_DIR,
    conviction_meter_chart, conviction_meter_breakdown,
)
from web.stock_detail import render_stock_detail
from web.ui.components import clickable_stock_table, page_header, section
from web.ui.screener_utils import (
    QUICK_FILTERS as _WS_QF,
    apply_quick_filters as _ws_apply_qf,
    render_enhanced_screener_bar as _ws_render_bar,
    paginate_dataframe as _ws_paginate,
    render_pagination as _ws_pagination,
    render_export_buttons as _ws_export,
    filter_changed_rows as _ws_filter_changed,
)
from core.country_flags import ticker_display as _ticker_display


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

    if filters.get("hide_illiquid") and "low_liquidity" in out.columns:
        out = out[~out["low_liquidity"].fillna(False)]

    # Visa bara aktier vars score förbättrats ≥5 poäng sedan förra scanningen
    if filters.get("only_improving") and "score_delta_4w" in out.columns:
        out = out[out["score_delta_4w"].fillna(0) >= 5]

    from core.suffix_map import COUNTRY_SUFFIXES as _SUFFIX_MAP
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

    # ── Score-delta: konvertera numerisk till pil-ikon ──────────────────────
    if "score_delta_4w" in show.columns:
        def _delta_icon(d):
            try:
                d = float(d)
                if d != d:  # NaN
                    return "─"
                if d >= 5:
                    return f"▲ {d:+.0f}"
                if d <= -5:
                    return f"▼ {d:+.0f}"
                return f"─ {d:+.0f}"
            except Exception:
                return "─"
        show["_score_delta"] = show["score_delta_4w"].apply(_delta_icon)
    else:
        show["_score_delta"] = "─"

    # ── Staleness-indikator: markera aktier med gammal data ─────────────────
    _has_stale = "data_stale_days" in show.columns and show["data_stale_days"].fillna(0).gt(0).any()

    # ── Experience mode: nybörjarläge visar färre kolumner ───────────────────
    try:
        from web.ui.experience_mode import InvestorExperience as _Exp
        _is_beginner = _Exp().is_beginner
    except Exception:
        _is_beginner = False

    _all_cols = [
        "rank", "ticker", "name", "_status", "sector",
        "score_total", "_score_delta", "predicted_return", "ml_rank",
        "entry_signal", "confidence_label", "trend_signal",
        "delta_flag", "piotroski_f", "low_liquidity",
        "data_stale_days",
    ]
    # Nybörjarläge: visa bara de viktigaste kolumnerna
    _beginner_cols = ["rank", "ticker", "name", "sector", "score_total", "entry_signal", "trend_signal", "data_stale_days"]
    _visible_cols  = _beginner_cols if _is_beginner else _all_cols

    base_cols = [c for c in _visible_cols if c in show.columns]

    display = show[base_cols].copy()
    display = display.rename(columns={
        "rank":              "Rank",
        "ticker":            "Ticker",
    })
    if "Ticker" in display.columns:
        # Lägg till varningsikon för illikvida aktier direkt i ticker-kolumnen
        _illiq = display.pop("low_liquidity") if "low_liquidity" in display.columns else None
        display["Ticker"] = display["Ticker"].apply(_ticker_display)
        if _illiq is not None:
            display["Ticker"] = display.apply(
                lambda r: r["Ticker"] + " [låg liq.]" if _illiq.get(r.name, False) else r["Ticker"],
                axis=1,
            )
    display = display.rename(columns={
        "name":              "Bolag",
        "_status":           "Status",
        "sector":            "Sektor",
        "score_total":       "Score",
        "_score_delta":      "Score Δ",
        "predicted_return":  "AI 30d-ret",
        "ml_rank":           "AI rank",
        "entry_signal":      "Entry",
        "confidence_label":  "Konf.",
        "trend_signal":      "Trend",
        "delta_flag":        "Δ",
        "piotroski_f":       "Piotroski",
        "data_stale_days":   "_stale",
    })

    # Lägg till staleness-markering i Ticker-kolumnen (= data ärvd från förra scan)
    if "_stale" in display.columns:
        display["Ticker"] = display.apply(
            lambda r: r["Ticker"] + " ⏱" if (r.get("_stale") or 0) > 0 else r["Ticker"],
            axis=1,
        )
        display.drop(columns=["_stale"], inplace=True)

    if "Rank" in display.columns:
        display["Rank"] = range(1, len(display) + 1)

    col_cfg = {
        "Rank": st.column_config.NumberColumn("Rank", help="Position i rankinglistan. Rank 1 = bäst poäng i det filtrerade urvalet.", format="%d"),
        "Ticker": st.column_config.TextColumn("Ticker", help="Börsticker. 💧 = illikvid (dagsomsättning < $50k). ⏱ = data från förra scan (Yahoo rate-limitad denna körning)."),
        "Bolag": st.column_config.TextColumn("Bolag", help="Bolagets fullständiga namn."),
        "Status": st.column_config.TextColumn("Status", help="💼 = du äger aktien * ⭐ = du bevakar den"),
        "Sektor": st.column_config.TextColumn("Sektor", help="Vilken bransch bolaget tillhör. Sektorrotation är viktigt -- starka sektorer presterar ofta bättre."),
        "Score Δ": st.column_config.TextColumn("Score Δ", help="Förändring i totalscore sedan förra veckans scan. ▲ = förbättring ≥5p. ▼ = försämring ≥5p. ─ = oförändrad."),
        "Entry": st.column_config.TextColumn("Entry", help="Köpsignal baserad på momentum och volym. STARK = tydlig uppåtrörelse med hög konfidensgrad. OK = måttlig signal. --= ingen signal just nu."),
        "Konf.": st.column_config.TextColumn("Konf.", help="Konfidensnivå för entry-signalen. HÖG = starka indikatorer samstämmer. MEDEL = blandat. LÅG = svag signal."),
        "Trend": st.column_config.TextColumn("Trend", help="Teknisk trend baserad på MA50/MA200. UPPTREND = aktien är i positiv trend och över sina glidande medelvärden."),
        "Δ": st.column_config.TextColumn("Δ", help="Förändring sedan förra scanningen -- t.ex. 'NYI TOPP20' eller rörelsepil. Visar rörlighet i rankinglistan."),
        "Piotroski": st.column_config.NumberColumn("Piotroski", format="%.0f/9", help="Piotroski F-Score: 0-9 poäng baserade på 9 nyckeltal för lönsamhet, hävstång och effektivitet. 7-9 = stark fundamenta. 0-2 = svag."),
    }
    if "Score" in display.columns:
        col_cfg["Score"] = st.column_config.ProgressColumn(
            "Score", min_value=0, max_value=100, format="%.0f",
            help="Totalt poäng 0-100 baserat på värdering, kvalitet, momentum, tillväxt, risk och storlek. 70+ = stark. 50-69 = neutral. <50 = svag.",
        )
    if "AI rank" in display.columns:
        col_cfg["AI rank"] = st.column_config.ProgressColumn(
            "AI rank", min_value=0, max_value=100, format="%.0f",
            help="ML-modellens rangordning 0-100. Kombinerar klassisk score med maskininlärd prediktion av framtida avkastning.",
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
    st.caption(f"Visar {len(display)} bolag -- klicka på en rad för detaljer")

    # CSV-export av filtrerade resultat
    csv_data = display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Ladda ner som CSV",
        data=csv_data,
        file_name=f"scanner_export_{datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv",
        key=f"ws_csv_{table_key}",
    )

    if event and event.selection and event.selection.rows:
        idx = event.selection.rows[0]
        # Använd råtickern från show (utan flagg-emoji) för lookup -
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


def _build_signal_scorecard() -> pd.DataFrame:
    """
    Loads all available scored_universe CSV files and calculates:
    - For each entry_signal value: how many stocks, avg return_1m, avg return_3m, win_rate
    Returns a DataFrame or empty DataFrame.
    """
    files = sorted(_glob.glob(str(REPORT_DIR / "scored_universe_*.csv")), reverse=True)

    if len(files) < 1:
        return pd.DataFrame()

    dfs = []
    for f in files[:10]:  # max 10 files for performance
        try:
            df_f = pd.read_csv(f, usecols=lambda c: c in [
                "ticker", "entry_signal", "score_total", "return_1m", "return_3m",
                "confidence_label", "trend_signal", "sector"
            ])
            df_f["_file"] = Path(f).stem.replace("scored_universe_", "")
            dfs.append(df_f)
        except Exception:
            continue

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs, ignore_index=True)

    # Only rows with actual return data
    has_returns = combined["return_1m"].notna() | combined["return_3m"].notna()
    combined = combined[has_returns]

    if combined.empty:
        return pd.DataFrame()

    rows = []
    for signal in ["STARK", "OK", "VÄNTA", "EJ AKTUELL"]:
        sub = combined[combined["entry_signal"] == signal]
        if sub.empty:
            continue
        r1 = sub["return_1m"].dropna()
        r3 = sub["return_3m"].dropna()
        rows.append({
            "Signal": signal,
            "Antal observationer": len(sub),
            "Avg 1m avkastning %": round(r1.mean(), 2) if len(r1) else None,
            "Avg 3m avkastning %": round(r3.mean(), 2) if len(r3) else None,
            "Win rate 1m %": round((r1 > 0).mean() * 100, 1) if len(r1) else None,
            "Win rate 3m %": round((r3 > 0).mean() * 100, 1) if len(r3) else None,
            "Median score": round(sub["score_total"].median(), 1),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def page_weekly_scan(df: pd.DataFrame, filters: dict,
                     holdings: pd.DataFrame, watchlist: list):
    st.title("🔍 Veckoscanner")

    if df.empty:
        st.warning("Aktiedata håller på att laddas in. Systemet uppdateras automatiskt varje vecka -- prova igen om en stund.")
        return

    if "sector" in df.columns:
        secs = sorted(df["sector"].dropna().unique().tolist())
        with st.sidebar:
            with st.expander("Tillgängliga sektorer", expanded=False):
                st.write(", ".join(secs))

    has_ml = "predicted_return" in df.columns and df["predicted_return"].notna().any()
    if has_ml:
        rank_mode = st.radio(
            "🤖 Ranking-läge",
            ["Klassisk score", "AI prediction", "Båda (side-by-side)"],
            horizontal=True,
            key="weekly_rank_mode",
            help=(
                "**Klassisk score** rankar på fundamenta + värdering + momentum (bred, stabil).\n\n"
                "**AI prediction** (XGBoost) rankar på tekniska mönster i prishistorik -- "
                "förutspår 30-dagars avkastning. Modellen kan prioritera aktier annorlunda "
                "än klassisk score: t.ex. en aktie med stark teknisk momentum men svag "
                "fundamental kan hamna högt i AI-ranken och tvärtom. "
                "Använd helst **Båda** för att jämföra."
            )
        )
    else:
        rank_mode = "Klassisk score"

    filt_df = _apply_weekly_filters(df, filters, holdings, watchlist)

    if rank_mode == "AI prediction" and "predicted_return" in filt_df.columns:
        # Filtrera bort aktier utan giltig prediktion (NaN = ingen prisdata i cache)
        filt_df = filt_df[filt_df["predicted_return"].notna()].sort_values(
            "predicted_return", ascending=False
        )
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

    # ── Enhanced screener bar (columns, quick filters, export) ────────────────
    _ws_cols_map = {
        "ticker": "Ticker", "name": "Bolag", "sector": "Sektor",
        "score_total": "Score", "entry_signal": "Entry",
        "confidence_label": "Konf.", "trend_signal": "Trend",
        "current_price": "Pris", "rsi_14": "RSI",
        "pe_trailing": "P/E", "price_to_book": "P/B",
        "roe": "ROE", "revenue_growth": "Tillväxt",
        "debt_to_equity": "D/E", "dividend_yield": "Utdelning",
        "return_1m": "1m", "return_3m": "3m", "return_6m": "6m",
        "piotroski_f": "Piotroski", "delta_flag": "Δ",
    }
    _ws_view_opts = _ws_render_bar(
        _ws_cols_map,
        default_columns=["ticker", "name", "sector", "score_total", "entry_signal", "trend_signal", "rsi_14", "pe_trailing"],
        filter_presets=_WS_QF,
        key="ws",
    )

    # Apply quick filter if selected
    if _ws_view_opts["quick_filter"]:
        filt_df = _ws_apply_qf(filt_df, _ws_view_opts["quick_filter"], _WS_QF)

    # Show changes only
    if _ws_view_opts.get("show_changes_only"):
        filt_df = _ws_filter_changed(filt_df)

    # ── Förbättrande aktier-filter (score_delta_4w >= +5) ─────────────────────
    has_delta = "score_delta_4w" in filt_df.columns and filt_df["score_delta_4w"].notna().any()
    _n_stale  = (filt_df.get("data_stale_days", 0) > 0).sum() if "data_stale_days" in filt_df.columns else 0
    col_imp, col_stale_info = st.columns([3, 2])
    with col_imp:
        only_improving = st.checkbox(
            "▲ Visa bara förbättrande aktier (score ≥ +5 sedan förra scan)",
            key="ws_only_improving",
            help="Filtrerar till aktier vars totalpoäng ökat med minst 5 poäng sedan förra veckans scan. Bra för att hitta aktier på väg mot köpsignal.",
        ) if has_delta else False
    with col_stale_info:
        if _n_stale > 0:
            st.caption(f"⏱ {_n_stale} aktier visas med data från förra scan (⏱ i Ticker = Yahoo rate-limitad)")
    if only_improving and has_delta:
        filt_df = filt_df[filt_df["score_delta_4w"].fillna(0) >= 5]

    tab1, tab2, tab3, tab4, tab_scorecard = st.tabs(
        ["📋 Ranking", "📊 Fundamental", "📈 Momentum & Teknisk", "🔬 Score-detalj", "📊 Signal Scorecard"]
    )

    with tab1:
        if rank_mode == "Båda (side-by-side)" and "predicted_return" in filt_df.columns:
            col_classic, col_ml = st.columns(2)
            with col_classic:
                st.subheader("📊 Klassisk score")
                _main_ranking_table(filt_df, holdings, watchlist)
            with col_ml:
                st.subheader("🤖 ML-prediktion")
                ml_sorted = filt_df[filt_df["predicted_return"].notna()].sort_values(
                    "predicted_return", ascending=False
                )
                _main_ranking_table(ml_sorted, holdings, watchlist, table_key="main_ranking_table_ml")
        else:
            _main_ranking_table(filt_df, holdings, watchlist)

        # ── Pagination + Export ───────────────────────────────────────────────
        _ws_page_size, _ws_page = _ws_pagination(len(filt_df), key="ws_rank")
        _ws_paged = _ws_paginate(filt_df, _ws_page_size, _ws_page)
        if _ws_page_size > 0:
            _main_ranking_table(_ws_paged, holdings, watchlist, table_key="main_ranking_table_paged")
        else:
            _main_ranking_table(filt_df, holdings, watchlist, table_key="main_ranking_table_full")

        _ws_export(filt_df, filename_prefix="scanner_results", key="ws_rank_export")
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

        st.markdown("---")
        st.subheader("🎯 Conviction Meter")
        st.caption("Radar-diagram med de 8 faktorscore för en enskild aktie.")
        if not filt_df.empty and "ticker" in filt_df.columns:
            cm_ticker = st.selectbox("Välj aktie för conviction meter",
                                     sorted(filt_df["ticker"].tolist()),
                                     key="ws_conviction_ticker")
            cm_row = filt_df[filt_df["ticker"] == cm_ticker]
            if not cm_row.empty:
                cm_fig = conviction_meter_chart(cm_row.iloc[0])
                st.plotly_chart(cm_fig, use_container_width=True)
                breakdown = conviction_meter_breakdown(cm_row.iloc[0])
                if breakdown:
                    st.markdown(breakdown)

    with tab2:
        if filt_df.empty:
            st.info("Inga data.")
        else:
            with st.expander("ℹ️ Guide: Vad är fundamental analys? Klicka för förklaring", expanded=False):
                st.markdown("""
Fundamental analys handlar om att bedöma **bolagets faktiska ekonomiska hälsa** -- inte bara hur kursen rör sig.
Du tittar på vinster, skulder, tillväxt och lönsamhet för att avgöra om ett bolag är värt sitt pris.

| Nyckeltal | Förklaring | Vad är bra? |
|---|---|---|
| **P/E (Price/Earnings)** | Aktiekurs delat med vinst per aktie. Visar hur "dyrt" marknaden värderar bolaget | Lågt P/E (<15) = billigare; Högt P/E (>30) = dyrt. Beror på bransch |
| **P/B (Price/Book)** | Aktiekurs delat med bokfört värde. Visar hur mycket du betalar för bolagets tillgångar | Under 1 = handlas under bokfört värde (möjlig fynd); >3 = dyrt |
| **ROE (Return on Equity)** | Hur mycket vinst bolaget genererar per investerad krona av aktieägarna | >15% = bra; >20% = utmärkt |
| **ROA (Return on Assets)** | Hur effektivt bolaget använder sina tillgångar | >5% är generellt bra |
| **Nettomarginal** | Andel av omsättningen som blir vinst efter alla kostnader | >10% = bra; Negativt = bolaget går med förlust |
| **Bruttomarginal** | Andel av intäkter kvar efter direkta produktionskostnader | Högt är bra; beror på bransch (SaaS >60%, handel ~30%) |
| **Omsättningstillväxt** | Hur mycket bolagets försäljning vuxit senaste år | >10% = god tillväxt; >20% = snabbväxande |
| **D/E (Skuldsättning)** | Total skuld i förhållande till eget kapital | Under 1.0 = låg skuldsättning; >2.0 = hög risk |
| **Current Ratio** | Om bolaget kan betala sina kortfristiga skulder | >1.5 = tryggt; <1.0 = likviditetsproblem |
| **Piotroski F-score** | Sammanfattar 9 finansiella styrkekriterier (0-9) | 7-9 = stark; 0-2 = svag finansiell hälsa |

**Klicka på en rad** för att se full analys av aktien.
""")

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
            clickable_stock_table(fund, ticker_col="Ticker", context_df=filt_df,
                                  key="ws_fund_table", height=600)

    with tab3:
        if filt_df.empty:
            st.info("Inga data.")
        else:
            with st.expander("ℹ️ Guide: Tekniska indikatorer - vad kollar man på? Klicka för förklaring", expanded=False):
                st.markdown("""
Tekniska indikatorer hjälper dig förstå **hur aktien rör sig** och om det är ett bra tillfälle att köpa/sälja.

| Indikator | Förklaring | Vad är bra att leta efter? |
|---|---|---|
| **vs MA50** | Hur mycket aktiekursen avviker från 50-dagars medelvärde | Positivt värde = kursen är *över* snittet (styrka) |
| **vs MA200** | Hur mycket kursen avviker från 200-dagars medelvärde | Positivt = långsiktig upptrend; Negativt = nedtrend |
| **RSI** | Relativ styrkeindikator (0-100) | 30-70 = normalt; <30 = kan vara köpläge; >70 = var försiktig |
| **BB pos** | Bollinger-position - var kursen befinner sig i sina prissvängningar | Nära 0 = vid nedre bandet (billig relativt swinget); Nära 1 = övre bandet |
| **MACD>signal** | Om MACD-linjen är över signallinjen | Sant (✓) = positivt momentum (köpsignal) |
| **1m / 3m / 6m / 12m** | Avkastning senaste 1, 3, 6 och 12 månader | Positiva värden = kursen har stigit; Flera gröna perioder = stark trend |
| **Volatilitet** | Hur mycket aktien svänger i pris | Hög = rörligare aktie; bra om du vill ha snabba rörelser, riskigt för stabilt sparande |
| **Beta** | Hur aktien rör sig jämfört med marknaden som helhet | Beta 1.0 = följer marknaden; >1.5 = rör sig mer än marknaden (hög risk) |
| **från 52v-high** | Hur långt under årets högsta punkt kursen befinner sig | Nära 0% = nära toppen; -30% = 30% under toppnivån |

**Klicka på en rad** för att öppna fullständig analys av aktien.
""")

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
            clickable_stock_table(tech, ticker_col="Ticker", context_df=filt_df,
                                  key="ws_tech_table", height=600)
            st.markdown("---")
            st.plotly_chart(scatter_momentum_value(filt_df), use_container_width=True)

    with tab4:
        if filt_df.empty:
            st.info("Inga data.")
        else:
            # Feature 4: ML caption
            has_ml_data = "predicted_return" in filt_df.columns and filt_df["predicted_return"].notna().any()
            if has_ml_data:
                st.caption("AI rank = ML-modellens 30-dagars avkastningsprediktion. Lägre rank = bättre förutsagd avkastning.")
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
            clickable_stock_table(sc_disp, ticker_col="Ticker", context_df=filt_df,
                                  key="ws_score_table", height=600,
                                  column_config=col_cfg or None)

            st.markdown("---")
            st.subheader("🕸️ Score-radar - enskilt bolag")
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

    # ── Tab: Signal Scorecard (Feature 2) ─────────────────────────────────────
    with tab_scorecard:
        st.subheader("📊 Entry Signal Scorecard")
        st.caption("Historisk träffsäkerhet per entry-signal baserat på tillgängliga scan-filer.")

        sc_df_card = _build_signal_scorecard()
        if sc_df_card.empty:
            st.info("Inte tillräckligt med historisk data ännu. Scorecard byggs upp automatiskt över tid.")
        else:
            st.dataframe(sc_df_card, use_container_width=True, hide_index=True)

            # Bar chart of avg returns
            colors_map = {"STARK": "#4caf50", "OK": "#4c9be8", "VÄNTA": "#ff9800", "EJ AKTUELL": "#ef5350"}
            fig_sc = go.Figure()
            for _, sc_row in sc_df_card.iterrows():
                signal = sc_row["Signal"]
                val = sc_row.get("Avg 1m avkastning %")
                if val is not None and not pd.isna(val):
                    fig_sc.add_trace(go.Bar(
                        name=signal, x=[signal],
                        y=[val],
                        marker_color=colors_map.get(signal, "#8892a4"),
                        hovertemplate=f"{signal}: %{{y:.2f}}%<extra></extra>",
                    ))
            fig_sc.update_layout(
                title="Genomsnittlig 1-månadsavkastning per signal",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#8892a4"), xaxis=dict(gridcolor="#252b3b"),
                yaxis=dict(gridcolor="#252b3b", title="%"), height=300,
                showlegend=False, margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_sc, use_container_width=True)

        # Also show by sector for STARK signals
        st.markdown("---")
        st.markdown("**STARK-signaler per sektor (nuvarande scan)**")
        if not filt_df.empty and "entry_signal" in filt_df.columns and "sector" in filt_df.columns:
            stark_df = filt_df[filt_df["entry_signal"] == "STARK"]
            if not stark_df.empty:
                by_sector = stark_df.groupby("sector").agg(
                    Antal=("ticker", "count"),
                    Avg_score=("score_total", "mean"),
                ).round(1).sort_values("Antal", ascending=False)
                st.dataframe(by_sector, use_container_width=True)
            else:
                st.info("Inga STARK-signaler i nuvarande scan")
