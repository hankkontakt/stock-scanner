"""web/pages/watchlist_detail.py – Sida 16: Bevakningar"""

import pandas as pd
import streamlit as st
import yfinance as yf

from web.utils import kpi_row, _get_provider, _get_depth
from core import ai_analysis


def _save_watchlist_data(items):
    from web.pages.admin import _save_watchlist_data as _swd
    _swd(items)


def page_watchlist_detail(df: pd.DataFrame, watchlist: list):
    """⭐ Bevakningar – förbättrad bevakningssida med live-data och detaljvy."""
    st.title("⭐ Bevakningar")
    st.caption("Dina bevakade aktier med live-data från yfinance. Klicka på en rad för detaljvy.")

    if not watchlist:
        st.info("Bevakningslistan är tom. Sök efter aktier på 🔍 Aktie-sök eller lägg till i Admin.")
        return

    # Hämta tickers som finns i scan-data vs som inte finns
    scanned_tickers = set(df["ticker"].tolist()) if not df.empty and "ticker" in df.columns else set()

    # Skapa DataFrame med live-data för ALLA bevakade tickers
    rows = []
    for item in watchlist:
        t = item["ticker"]
        name = item.get("name", t)

        # Kolla om den finns i scan-data
        if t in scanned_tickers:
            sc = df[df["ticker"] == t]
            if not sc.empty:
                r = sc.iloc[0]
                rows.append({
                    "Ticker": t,
                    "Bolag": name,
                    "Sektor": r.get("sector", "—"),
                    "Pris": r.get("current_price") or r.get("close", "—"),
                    "Score": r.get("score_total"),
                    "Entry": r.get("entry_signal", "—"),
                    "Trend": r.get("trend_signal", "—"),
                    "RSI": r.get("rsi_14"),
                    "Tillagd": item.get("added", "—"),
                    "_source": "scan",
                })
                continue

        # Hämta live-data från yfinance
        try:
            yt = yf.Ticker(t)
            info = yt.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            sector = info.get("sector", "—")
            rows.append({
                "Ticker": t,
                "Bolag": info.get("shortName") or name,
                "Sektor": sector,
                "Pris": f"{price:.2f}" if price else "—",
                "Score": None,
                "Entry": "Ej scannad",
                "Trend": "—",
                "RSI": None,
                "Tillagd": item.get("added", "—"),
                "_source": "yfinance",
            })
        except Exception:
            rows.append({
                "Ticker": t, "Bolag": name, "Sektor": "—",
                "Pris": "—", "Score": None, "Entry": "—",
                "Trend": "—", "RSI": None,
                "Tillagd": item.get("added", "—"), "_source": "error",
            })

    wl_df = pd.DataFrame(rows)

    # KPI
    n_scanned = sum(1 for r in rows if r.get("_source") == "scan")
    n_live = sum(1 for r in rows if r.get("_source") == "yfinance")
    kpi_row([
        ("Bevakade totalt", len(rows), None,
         "Totalt antal aktier på din bevakningslista."),
        ("I scan-data", n_scanned, None,
         "Antal bevakade aktier som finns i senaste scanningens data — får fullständig poänganalys."),
        ("Live från yfinance", n_live, None,
         "Antal bevakade aktier som hämtas direkt från yfinance (inte i scan) — får bara grundläggande prisdata."),
    ])

    # Kolumn-konfiguration
    col_cfg = {}
    if "Score" in wl_df.columns:
        col_cfg["Score"] = st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f")

    # Visa tabell
    display_cols = [c for c in ["Ticker", "Bolag", "Sektor", "Pris", "Score", "Entry", "Trend", "Tillagd"] if c in wl_df.columns]
    event = st.dataframe(
        wl_df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config=col_cfg,
        on_select="rerun",
        selection_mode="single-row",
        key="wl_detail_table",
    )
    st.caption(f"{len(rows)} bevakade aktier — klicka på en rad för detaljvy")

    # Klickbar rad → visa detaljvy
    if event and event.selection and event.selection.rows:
        sel_idx = event.selection.rows[0]
        sel_ticker = wl_df.iloc[sel_idx]["Ticker"]
        sel_source = wl_df.iloc[sel_idx].get("_source", "")

        with st.expander(f"🔍 Detaljvy: {sel_ticker}", expanded=True):
            if sel_source == "scan" and not df.empty:
                # Använd render_stock_detail om den finns i scan-data
                sel_row = df[df["ticker"] == sel_ticker]
                if not sel_row.empty:
                    from web.stock_detail import render_stock_detail
                    render_stock_detail(
                        sel_ticker, row=sel_row.iloc[0], df=df,
                        show_ai=True, show_news=True, show_chart=True, show_detail_data=True,
                    )
            else:
                # Visa direkt via yfinance
                st.markdown(f"### 📈 `{sel_ticker}` – Live-data från yfinance")
                try:
                    yt = yf.Ticker(sel_ticker)
                    info = yt.info or {}
                    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
                    sector = info.get("sector", "—")
                    pe = info.get("trailingPE")
                    market_cap = info.get("marketCap")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.metric("Pris", f"{price:.2f}" if price else "—")
                        st.metric("Sektor", sector)
                    with col_b:
                        st.metric("P/E", f"{pe:.1f}" if pe else "—")
                        st.metric("Marknadsvärde", f"{market_cap/1e9:.1f}B" if market_cap else "—")

                    # Prisgraf
                    from web.stock_detail import _price_chart
                    chart = _price_chart(sel_ticker, period="1y")
                    if chart:
                        st.plotly_chart(chart, use_container_width=True)

                    # AI-knapp
                    if st.button(f"🤖 AI-analys för {sel_ticker}", key=f"wl_ai_{sel_ticker}", use_container_width=True):
                        provider = _get_provider()
                        depth = _get_depth()
                        with st.spinner("Analyserar..."):
                            try:
                                result = ai_analysis.analyze_stock(sel_ticker, provider=provider, depth=depth)
                                with st.container(border=True):
                                    st.markdown(result)
                            except Exception as e:
                                st.error(f"❌ {e}")

                except Exception as e:
                    st.error(f"Kunde inte hämta data: {e}")

    # Ta bort-knapp
    st.markdown("---")
    col_rm1, col_rm2 = st.columns([3, 1])
    with col_rm1:
        remove_ticker = st.selectbox("Ta bort från bevakningslistan", [""] + [r["Ticker"] for r in rows], key="wl_remove_detail")
    with col_rm2:
        if remove_ticker and st.button("🗑️ Ta bort", key="btn_wl_remove_detail", use_container_width=True):
            items = [i for i in watchlist if i["ticker"] != remove_ticker]
            _save_watchlist_data(items)
            st.success(f"`{remove_ticker}` borttagen!")
            st.rerun()
