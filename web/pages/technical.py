"""web/pages/technical.py – Sida 5: Teknisk analys"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

from web.utils import (
    kpi_row, scatter_momentum_value, pct_fmt, _get_provider, _get_depth,
)
from core import ai_analysis


def page_technical(df: pd.DataFrame, filters: dict):
    st.title("📈 Teknisk analys")

    if df.empty:
        st.warning("Ingen scandata.")
        return

    out = df.copy()

    rsi_min  = filters.get("rsi_min", 0)
    rsi_max  = filters.get("rsi_max", 100)
    if "rsi_14" in out.columns:
        out = out[out["rsi_14"].fillna(50).between(rsi_min, rsi_max)]

    ma200_sel = filters.get("ma200", "Alla")
    if ma200_sel == "Över MA200 (bull)" and "price_vs_ma200" in out.columns:
        out = out[out["price_vs_ma200"] > 0]
    elif ma200_sel == "Under MA200 (bear)" and "price_vs_ma200" in out.columns:
        out = out[out["price_vs_ma200"] <= 0]

    sel_sec = filters.get("t_sector", [])
    if sel_sec and "sector" in out.columns:
        out = out[out["sector"].isin(sel_sec)]

    sel_entry = filters.get("t_entry", [])
    if sel_entry and "entry_signal" in out.columns:
        out = out[out["entry_signal"].isin(sel_entry)]

    if filters.get("trend_tech") == "UPPTREND" and "trend_signal" in out.columns:
        out = out[out["trend_signal"] == "UPPTREND"]

    n_upptrend = (out["trend_signal"] == "UPPTREND").sum() \
        if "trend_signal" in out.columns else 0
    n_over_ma  = (out["price_vs_ma200"] > 0).sum() \
        if "price_vs_ma200" in out.columns else 0
    avg_rsi    = out["rsi_14"].mean() if "rsi_14" in out.columns else 0
    n_overbought = (out["rsi_14"] > 70).sum() if "rsi_14" in out.columns else 0

    kpi_row([
        ("Visar",            f"{len(out)} / {len(df)}",  None,
         "Antal bolag som visas efter filter, av totalt antal i universumet."),
        ("UPPTREND",         f"{n_upptrend}",            None,
         "Antal bolag i teknisk upptrend — aktiekursen är över MA50 och MA200 (glidande medelvärden). Många upptrend = bullish marknadsklimat."),
        ("Över MA200",       f"{n_over_ma}",             None,
         "Antal bolag vars kurs är över 200-dagars glidande medelvärde. MA200 är det viktigaste långsiktiga trendmåttet. Under MA200 = potentiellt riskabelt."),
        ("Snitt RSI / >70",  f"{avg_rsi:.0f} / {n_overbought}", None,
         "Genomsnittlig RSI för universumet / antal bolag med RSI >70. RSI >70 = överköpt. Många överköpta bolag kan indikera att marknaden är het och riskerar korrigering."),
    ])

    tab1, tab2, tab3, tab4 = st.tabs(["📋 Tabell", "📊 Diagram", "📉 MACD/RSI", "🔀 Jämför"])

    with tab1:
        tech_show = [c for c in [
            "rank", "ticker", "name", "sector",
            "current_price", "rsi_14", "price_vs_ma50", "price_vs_ma200",
            "bb_position", "macd_above_signal", "trend_signal", "entry_signal",
            "return_1m", "return_3m", "return_6m", "return_12m",
            "volatility", "beta", "pct_from_52w_high",
        ] if c in out.columns]
        td = out[tech_show].copy().rename(columns={
            "rank": "#", "ticker": "Ticker", "name": "Bolag", "sector": "Sektor",
            "current_price": "Pris", "rsi_14": "RSI",
            "price_vs_ma50": "vs MA50", "price_vs_ma200": "vs MA200",
            "bb_position": "BB", "macd_above_signal": "MACD>sig.",
            "trend_signal": "Trend", "entry_signal": "Entry",
            "return_1m": "1m", "return_3m": "3m", "return_6m": "6m", "return_12m": "12m",
            "volatility": "Vol.", "beta": "Beta", "pct_from_52w_high": "från ATH",
        })
        for c in ["vs MA50", "vs MA200", "1m", "3m", "6m", "12m", "från ATH"]:
            if c in td.columns:
                td[c] = td[c].apply(lambda v: pct_fmt(v))
        st.dataframe(td, use_container_width=True, hide_index=True, height=600)

    with tab2:
        if "rsi_14" in out.columns and "ticker" in out.columns:
            c1, c2 = st.columns(2)
            with c1:
                rsi_data = out[["ticker", "rsi_14", "score_total", "sector"]].dropna()
                fig_rsi  = px.scatter(
                    rsi_data, x="rsi_14", y="score_total",
                    color="sector", hover_data=["ticker"],
                    title="RSI vs Score",
                    template="plotly_dark",
                )
                fig_rsi.add_vline(x=30, line_dash="dash", line_color="green", annotation_text="Översålt")
                fig_rsi.add_vline(x=70, line_dash="dash", line_color="red", annotation_text="Överköpt")
                fig_rsi.update_layout(
                    paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                    height=360, margin=dict(t=36, b=16, l=16, r=16),
                )
                st.plotly_chart(fig_rsi, use_container_width=True)

            with c2:
                if "price_vs_ma200" in out.columns and "return_12m" in out.columns:
                    ma_data = out[["ticker", "price_vs_ma200", "return_12m",
                                  "score_total", "sector"]].dropna()
                    fig_ma  = px.scatter(
                        ma_data, x="price_vs_ma200", y="return_12m",
                        color="sector", hover_data=["ticker"],
                        size="score_total",
                        title="vs MA200 vs 12m-avkastning",
                        template="plotly_dark",
                    )
                    fig_ma.add_vline(x=0, line_dash="dash", line_color="#8892a4")
                    fig_ma.add_hline(y=0, line_dash="dash", line_color="#8892a4")
                    fig_ma.update_layout(
                        paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                        height=360, margin=dict(t=36, b=16, l=16, r=16),
                    )
                    st.plotly_chart(fig_ma, use_container_width=True)

        if "return_12m" in out.columns:
            st.markdown("---")
            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("🚀 Starkast momentum (12m)")
                top_mom = (out[["ticker", "name", "return_12m", "return_3m", "score_total"]]
                           .dropna(subset=["return_12m"])
                           .sort_values("return_12m", ascending=False)
                           .head(10))
                top_mom["return_12m"] = top_mom["return_12m"].apply(lambda v: pct_fmt(v))
                top_mom["return_3m"]  = top_mom["return_3m"].apply(lambda v: pct_fmt(v)) \
                    if "return_3m" in top_mom.columns else "—"
                st.dataframe(top_mom.rename(columns={
                    "ticker": "Ticker", "name": "Bolag",
                    "return_12m": "12m", "return_3m": "3m", "score_total": "Score"
                }), use_container_width=True, hide_index=True)
            with col_b:
                st.subheader("📉 Svagast momentum (12m)")
                bot_mom = (out[["ticker", "name", "return_12m", "return_3m", "score_total"]]
                           .dropna(subset=["return_12m"])
                           .sort_values("return_12m")
                           .head(10))
                bot_mom["return_12m"] = bot_mom["return_12m"].apply(lambda v: pct_fmt(v))
                bot_mom["return_3m"]  = bot_mom["return_3m"].apply(lambda v: pct_fmt(v)) \
                    if "return_3m" in bot_mom.columns else "—"
                st.dataframe(bot_mom.rename(columns={
                    "ticker": "Ticker", "name": "Bolag",
                    "return_12m": "12m", "return_3m": "3m", "score_total": "Score"
                }), use_container_width=True, hide_index=True)

    with tab3:
        """MACD/RSI-diagram för vald aktie."""
        st.subheader("📉 MACD & RSI – realtidsdiagram")
        st.caption("Välj en aktie för att visa MACD (histogram + signal) och RSI (14) baserat på 6 månaders data.")

        if not out.empty and "ticker" in out.columns:
            tickers_sorted = sorted(out["ticker"].tolist())
            col_a, col_b = st.columns([3, 1])
            with col_a:
                tech_ticker = st.selectbox("Välj aktie", tickers_sorted, key="tech_macd_ticker")
            with col_b:
                period = st.selectbox("Period", ["3mo", "6mo", "1y"], index=1, key="tech_macd_period")

            if tech_ticker:
                with st.spinner("Hämtar data..."):
                    try:
                        yf_ticker = yf.Ticker(tech_ticker)
                        hist = yf_ticker.history(period=period, auto_adjust=True)
                        if hist.empty or len(hist) < 20:
                            st.info("Otillräcklig data för diagram.")
                        else:
                            close = hist["Close"]
                            low   = hist.get("Low", close)
                            high  = hist.get("High", close)
                            vol   = hist.get("Volume", pd.Series(0, index=hist.index))

                            ema12 = close.ewm(span=12, adjust=False).mean()
                            ema26 = close.ewm(span=26, adjust=False).mean()
                            macd_line   = ema12 - ema26
                            signal_line = macd_line.ewm(span=9, adjust=False).mean()
                            macd_hist   = macd_line - signal_line

                            delta = close.diff()
                            gain  = delta.where(delta > 0, 0).rolling(14).mean()
                            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
                            rs    = gain / loss.replace(0, float("nan"))
                            rsi   = 100 - (100 / (1 + rs))

                            fig_macd_rsi = make_subplots(
                                rows=2, cols=1,
                                shared_xaxes=True,
                                vertical_spacing=0.08,
                                row_heights=[0.55, 0.45],
                            )

                            fig_macd_rsi.add_trace(
                                go.Scatter(x=close.index, y=macd_line,
                                           name="MACD", line=dict(color="#42a5f5", width=1.5)),
                                row=1, col=1,
                            )
                            fig_macd_rsi.add_trace(
                                go.Scatter(x=close.index, y=signal_line,
                                           name="Signal", line=dict(color="#ff7043", width=1.5)),
                                row=1, col=1,
                            )
                            hist_colors = ["#4caf50" if v >= 0 else "#ef5350" for v in macd_hist]
                            fig_macd_rsi.add_trace(
                                go.Bar(x=close.index, y=macd_hist,
                                       name="MACD Hist", marker_color=hist_colors,
                                       opacity=0.6),
                                row=1, col=1,
                            )

                            fig_macd_rsi.add_trace(
                                go.Scatter(x=close.index, y=rsi,
                                           name="RSI (14)", line=dict(color="#ab47bc", width=2)),
                                row=2, col=1,
                            )
                            fig_macd_rsi.add_hline(y=70, line_dash="dash", line_color="#ef5350",
                                                   annotation_text="Överköpt 70", row=2, col=1)
                            fig_macd_rsi.add_hline(y=30, line_dash="dash", line_color="#4caf50",
                                                   annotation_text="Översålt 30", row=2, col=1)
                            fig_macd_rsi.add_hline(y=50, line_dash="dot", line_color="#8892a4",
                                                   annotation_text="50", row=2, col=1)

                            fig_macd_rsi.update_layout(
                                title=dict(
                                    text=f"{tech_ticker} – MACD & RSI ({period})",
                                    font=dict(size=14),
                                ),
                                template="plotly_dark",
                                paper_bgcolor="#131722",
                                plot_bgcolor="#1e2230",
                                height=550,
                                margin=dict(t=40, b=16, l=16, r=16),
                                hovermode="x unified",
                                showlegend=True,
                                legend=dict(
                                    orientation="h", y=1.12, x=0.5, xanchor="center",
                                    font=dict(size=10),
                                ),
                            )

                            fig_macd_rsi.update_yaxes(title_text="MACD", row=1, col=1,
                                                      color="#8892a4")
                            fig_macd_rsi.update_yaxes(title_text="RSI", row=2, col=1,
                                                      range=[0, 100], color="#8892a4")
                            fig_macd_rsi.update_xaxes(color="#8892a4")

                            st.plotly_chart(fig_macd_rsi, use_container_width=True)

                            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                            with col_m1:
                                st.metric("MACD", f"{macd_line.iloc[-1]:.3f}" if not macd_line.empty else "—")
                            with col_m2:
                                st.metric("Signal", f"{signal_line.iloc[-1]:.3f}" if not signal_line.empty else "—")
                            with col_m3:
                                rsi_val = rsi.iloc[-1] if not rsi.empty else float("nan")
                                rsi_str = f"{rsi_val:.1f}" if not pd.isna(rsi_val) else "—"
                                rsi_color = "🟢" if (not pd.isna(rsi_val) and 30 <= rsi_val <= 70) else ("🔴" if not pd.isna(rsi_val) else "⚪")
                                st.metric("RSI (14)", f"{rsi_color} {rsi_str}")
                            with col_m4:
                                macd_sig = "🟢 Bullish" if (not macd_line.empty and not signal_line.empty and macd_line.iloc[-1] > signal_line.iloc[-1]) else "🔴 Bearish"
                                st.metric("Signal", macd_sig)

                    except Exception as e:
                        st.error(f"Kunde inte hämta data för {tech_ticker}: {e}")

    with tab4:
        """Multi-ticker jämförelsediagram."""
        st.subheader("🔀 Jämför flera aktier")
        st.caption("Välj 2-5 aktier för att se deras kursutveckling i samma diagram.")

        if not out.empty and "ticker" in out.columns:
            all_tickers = sorted(out["ticker"].tolist())
            selected = st.multiselect("Välj aktier", all_tickers, default=all_tickers[:3] if len(all_tickers) >= 3 else all_tickers, max_selections=5, key="tech_compare_tickers")
            period = st.selectbox("Period", ["1mo", "3mo", "6mo", "1y", "2y"], index=1, key="tech_compare_period")
            normalize = st.checkbox("Normalisera (100 = start)", value=True, key="tech_compare_norm")

            if len(selected) >= 2:
                with st.spinner("Hämtar prisdata..."):
                    colors = ["#00d4aa", "#42a5f5", "#ff7043", "#ab47bc", "#ffc107"]
                    fig = go.Figure()
                    for i, ticker in enumerate(selected):
                        try:
                            hist = yf.download(ticker, period=period, auto_adjust=True, progress=False)
                            if not hist.empty and "Close" in hist.columns:
                                prices = hist["Close"]
                                if isinstance(prices, pd.DataFrame):
                                    prices = prices.iloc[:, 0]
                                if normalize and len(prices) > 0 and prices.iloc[0] and not pd.isna(prices.iloc[0]):
                                    prices = prices / prices.iloc[0] * 100
                                fig.add_trace(go.Scatter(
                                    x=prices.index, y=prices,
                                    mode="lines", name=ticker,
                                    line=dict(color=colors[i % len(colors)], width=2),
                                ))
                        except Exception:
                            pass
                    fig.update_layout(
                        title=f"Prisjämförelse ({'normaliserad' if normalize else 'absolut'})",
                        template="plotly_dark", paper_bgcolor="#131722",
                        plot_bgcolor="#1e2230", height=450,
                        margin=dict(t=40, b=16, l=16, r=16),
                        hovermode="x unified",
                        legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
                        yaxis_title="Pris" if not normalize else "Index (100 = start)",
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    if len(selected) >= 2:
                        with st.expander("📊 Korrelationsmatris", expanded=False):
                            corr_data = {}
                            for ticker in selected:
                                try:
                                    h = yf.download(ticker, period=period, auto_adjust=True, progress=False)
                                    if not h.empty:
                                        close = h["Close"]
                                        if isinstance(close, pd.DataFrame):
                                            close = close.iloc[:, 0]
                                        corr_data[ticker] = close.pct_change()
                                except:
                                    pass
                            if corr_data:
                                corr_list = []
                                for _k, _v in corr_data.items():
                                    if isinstance(_v, pd.Series) and len(_v) > 5:
                                        _s = _v.copy()
                                        _s.name = _k
                                        corr_list.append(_s)
                                if len(corr_list) > 1:
                                    corr_df = pd.concat(corr_list, axis=1).dropna()
                                    if len(corr_df) > 5 and len(corr_df.columns) > 1:
                                        st.dataframe(corr_df.corr().round(3), use_container_width=True)
            else:
                st.info("Välj minst 2 aktier för att visa diagram.")
        else:
            st.info("Ladda scandata för att se aktier att jämföra.")

    # ── AI-knapp: AI tolkning av teknisk data (Feature 3) ───────────────────
    st.markdown("---")
    st.subheader("🤖 AI-tolkning")
    if st.button("🤖 Tolka teknisk data med AI", key="btn_tech_ai", use_container_width=True):
        provider = _get_provider()
        depth = _get_depth()
        with st.spinner("Analyserar teknisk data..."):
            try:
                tech_context = {
                    "n_upptrend": n_upptrend,
                    "n_over_ma200": n_over_ma,
                    "avg_rsi": round(avg_rsi, 1),
                    "n_overbought": n_overbought,
                    "n_stocks": len(out),
                }
                result = ai_analysis.ai_chat(
                    "Ge mig en teknisk analys av marknaden baserat på denna data",
                    context=ai_analysis._safe_json(tech_context, ensure_ascii=False),
                    provider=provider,
                    depth=depth,
                )
                with st.container(border=True):
                    st.markdown(result)
            except Exception as e:
                st.error(f"❌ {e}")
