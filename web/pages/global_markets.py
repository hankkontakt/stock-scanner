"""web/pages/global_markets.py - Sida 11: Globala marknader"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from web.utils import FX_PAIRS, fetch_fx_rows, fetch_rate_rows
from core import config


def page_global_markets():
    """Globala marknader - index, valutor, räntor och nyheter."""
    st.title("🌍 Globala marknader")
    st.caption("Realtidsdata för globala index, valutor, räntor och marknadsnyheter.")

    tab_idx, tab_fx, tab_rates, tab_news = st.tabs(
        ["📊 Index", "💱 Valutor", "📈 Räntor", "📰 Nyheter"]
    )

    with tab_idx:
        with st.spinner("Hämtar globala index..."):
            try:
                from core.global_markets import fetch_global_indices
                indices = fetch_global_indices()
                if indices:
                    asia_keys = ["^N225","^TOPX","^HSI","000001.SS","^KS11","^AXJO","^BSESN","^STI"]
                    euro_keys = ["^GDAXI","^FTSE","^FCHI","^STOXX50E","^OMX"]
                    us_keys   = ["^GSPC","^IXIC","^DJI","^VIX"]
                    rows = []
                    for region, keys in [("🇺🇸 USA", us_keys), ("🇪🇺 Europa", euro_keys), ("🌏 Asien/Pacific", asia_keys)]:
                        for k in keys:
                            d = indices.get(k)
                            if d:
                                chg = d.get("change_pct", 0) or 0
                                rows.append({
                                    "Region": region,
                                    "Index": d.get("name", k),
                                    "Senast": f"{d.get('close', 0):,.0f}" if d.get("close") else "--",
                                    "Förändring": f"{'🟢' if chg >= 0 else '🔴'} {chg:+.2f}%",
                                })
                    if rows:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                                     height=min(500, len(rows) * 37 + 40))
                        st.caption("Källa: yfinance * uppdateras varje sidladdning")
                    else:
                        st.info("Inga indexdata tillgängliga just nu.")
                else:
                    st.info("Kunde inte hämta indexdata.")
            except Exception as e:
                st.warning(f"Globala index ej tillgängliga: {e}")

    with tab_fx:
        with st.spinner("Hämtar valutakurser..."):
            try:
                fx_rows = fetch_fx_rows()
                if fx_rows:
                    try:
                        st.dataframe(pd.DataFrame(fx_rows), use_container_width=True,
                                     hide_index=True, height=220)
                    except Exception:
                        st.dataframe(pd.DataFrame(fx_rows), use_container_width=True,
                                     hide_index=True)
                else:
                    st.info("Kunde inte hämta valutakurser.")
            except Exception as e:
                st.warning(f"Valutor ej tillgängliga: {e}")

        with st.expander("📈 FX-historik (1 år)", expanded=False):
            try:
                fx_ticker = st.selectbox("Valutapar", list(FX_PAIRS.keys()), key="gm_fx_chart")
                fx_hist = yf.download(FX_PAIRS[fx_ticker], period="1y", progress=False)
                if not fx_hist.empty:
                    close_col = fx_hist["Close"] if "Close" in fx_hist.columns else fx_hist.iloc[:, 0]
                    if isinstance(close_col, pd.DataFrame):
                        close_col = close_col.iloc[:, 0]
                    fig_fx = go.Figure()
                    fig_fx.add_trace(go.Scatter(x=fx_hist.index, y=close_col, mode="lines",
                                                name=fx_ticker, line=dict(color="#42a5f5", width=2),
                                                fill="tozeroy", fillcolor="rgba(66,165,245,0.1)"))
                    fig_fx.update_layout(template="plotly_dark", paper_bgcolor="#131722",
                                         plot_bgcolor="#1e2230", height=280,
                                         margin=dict(t=16, b=16, l=16, r=16))
                    st.plotly_chart(fig_fx, use_container_width=True)
            except Exception as e:
                st.caption(f"FX-graf: {e}")

    with tab_rates:
        with st.spinner("Hämtar räntor..."):
            try:
                rate_rows = fetch_rate_rows()
                if rate_rows:
                    try:
                        st.dataframe(pd.DataFrame(rate_rows), use_container_width=True,
                                     hide_index=True, height=280)
                    except Exception:
                        st.dataframe(pd.DataFrame(rate_rows), use_container_width=True,
                                     hide_index=True)
                else:
                    st.info("Kunde inte hämta räntor.")
            except Exception as e:
                st.warning(f"Räntor ej tillgängliga: {e}")

    with tab_news:
        with st.spinner("Hämtar marknadsnyheter..."):
            try:
                from core.news_fetcher import fetch_swedish_market_news, fetch_global_market_news
                import os as _os
                # Läs nyckeln fresh vid körtid (inte cachad modulnivå-variabel),
                # eftersom st.secrets kan bli tillgängligt efter att config.py importerades.
                _fh_key = (
                    _os.getenv("FINNHUB_API_KEY", "")
                    or config.FINNHUB_API_KEY
                    or (st.secrets.get("FINNHUB_API_KEY", "") if hasattr(st, "secrets") else "")
                )
                swedish = fetch_swedish_market_news(max_articles=8)
                global_n = fetch_global_market_news(_fh_key, max_articles=6)

                c_se, c_gl = st.columns(2)
                with c_se:
                    st.subheader("🇸🇪 Svenska nyheter")
                    if swedish:
                        for a in swedish:
                            age = a.get("age_hours", 999)
                            icon = "🔴" if age < 6 else "🟡" if age < 24 else "⚪"
                            url = a.get("url", "")
                            title = f"[{a['headline']}]({url})" if url else a["headline"]
                            st.markdown(f"{icon} {title}  \n*{a.get('source','?')} * {a.get('datetime_str','--')}*")
                            st.divider()
                    else:
                        st.info("Inga svenska nyheter just nu.")
                with c_gl:
                    st.subheader("🌍 Globala nyheter")
                    if global_n:
                        for a in global_n:
                            age = a.get("age_hours", 999)
                            icon = "🔴" if age < 6 else "🟡" if age < 24 else "⚪"
                            url = a.get("url", "")
                            title = f"[{a['headline']}]({url})" if url else a["headline"]
                            st.markdown(f"{icon} {title}  \n*{a.get('source','?')} * {a.get('datetime_str','--')}*")
                            st.divider()
                    else:
                        if _fh_key:
                            st.info("Inga globala nyheter just nu.")
                        else:
                            st.warning(
                                "**FINNHUB_API_KEY saknas.** "
                                "Lägg till nyckeln under **Streamlit Cloud -> App settings -> Secrets** "
                                "(inte GitHub Secrets -- de är separata). "
                                "Format: `FINNHUB_API_KEY = \"din_nyckel\"`"
                            )
            except Exception as e:
                st.warning(f"Nyheter ej tillgängliga: {e}")
