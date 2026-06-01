"""web/pages/sector_rotation.py - Sida 10: Sektorrotation"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from web.utils import kpi_row, _get_provider, _get_depth
from core import ai_analysis
from web.ui.components import clickable_stock_table


def page_sector_rotation(df: pd.DataFrame):
    """Sektorrotation - heatmap och momentum för alla sektorer."""
    st.title("🏭 Sektorrotation")
    st.caption("Analysera sektorstyrka, rotation och momentum. Data från sektor-ETFer via yfinance.")

    with st.expander("ℹ️ Vad är sektorrotation? -- Förklaring för nybörjare", expanded=False):
        st.markdown("""
### 🏭 Vad är en sektor?
Börsen är uppdelad i **sektorer** -- grupper av bolag som gör liknande saker.
Exempel: **Technology** (Apple, Microsoft), **Healthcare** (läkemedel, sjukvård),
**Energy** (olja, gas), **Consumer Defensive** (mat, hushållsprodukter).

### 🔄 Vad är sektorrotation?
Pengar flödar ständigt mellan sektorer beroende på ekonomins fas.
- **Lågkonjunktur:** Pengar flödar till defensiva sektorer (mat, sjukvård) som folk alltid köper
- **Uppgångsfas:** Teknik och konsumtion leder
- **Hög inflation:** Energi och råvaror gynnas

Att förstå rotationen hjälper dig välja rätt sektorer *vid rätt tid*.

### 📊 Momentum (1m / 3m)
Hur mycket en sektor-ETF stigit (positivt) eller fallit (negativt) de senaste 1 respektive 3 månaderna.
**Positivt momentum = sektorn är het just nu.**

### ✅ MA50 / ✅ MA200
**Glidande medelvärde (Moving Average):**
- **MA50** = snittaktien sista 50 dagarna. Aktier *ovanför* MA50 = kortsiktig upptrend.
- **MA200** = snittaktien sista 200 dagarna. Ovanför MA200 = långsiktig upptrend.

En ETF som är ovanför **både MA50 och MA200** (✅✅) är i stark upptrend.

### 💡 Handelssignaler -- Vad gör jag med det här?
- **Övervikta:** Köp/äg mer aktier i sektorer med stark trend
- **Undervikta:** Minska eller undvik sektorer i nedtrend
- **Neutral:** Håll normal vikt -- varken öka eller minska
""")

    # Använd sektor-data från scored_df om tillgänglig
    if df.empty or "sector" not in df.columns:
        st.info("Ladda scandata för att visa sektorrotation baserad på scoring.")
        sectors_only = []
    else:
        sectors_only = df["sector"].dropna().unique().tolist()

    with st.spinner("Hämtar sektor-ETF data..."):
        try:
            from core.sector_momentum import fetch_sector_momentum
            raw = fetch_sector_momentum(verbose=False)
            # Normalisera fältnamn till vad sidan förväntar sig
            _sig_scores = {"STARK UPPTREND": 4, "UPPTREND": 3, "NEUTRAL": 2, "NEDTREND": 1, "STARK NEDTREND": 0}
            trends = {
                sec: {
                    **v,
                    "momentum_3m":   (v.get("return_3m") or 0) * 100,
                    "momentum_1m":   (v.get("return_1m") or 0) * 100,
                    "current_price": v.get("current"),
                    "signal_score":  _sig_scores.get(v.get("signal", "NEUTRAL"), 2),
                }
                for sec, v in raw.items()
            }
        except Exception as e:
            st.warning(f"Kunde inte hämta sektordata: {e}")
            trends = {}

    # Sektor ETF mapping från scored_df sektorer
    etf_map = {
        "Technology": "XLK", "Healthcare": "XLV",
        "Financial Services": "XLF", "Consumer Cyclical": "XLY",
        "Consumer Defensive": "XLP", "Energy": "XLE",
        "Industrials": "XLI", "Utilities": "XLU",
        "Basic Materials": "XLB", "Real Estate": "XLRE",
        "Communication Services": "XLC",
    }

    # KPI-kort
    if trends:
        strong_up = sum(1 for v in trends.values() if v.get("signal") == "STARK UPPTREND")
        strong_down = sum(1 for v in trends.values() if v.get("signal") == "STARK NEDTREND")
        kpi_row([
            ("Sektorer totalt", len(trends), None,
             "Antal bevakade sektorer med tillgänglig ETF-data för trendanalys."),
            ("🚀 STARK UPPTREND", strong_up, None,
             "Antal sektorer i stark teknisk upptrend baserat på ETF-momentum och glidande medelvärden. Fler = bredare bullish marknad."),
            ("💀 STARK NEDTREND", strong_down, None,
             "Antal sektorer i stark nedtrend. Undvik att köpa aktier i sektorer med stark nedtrend -- de drar ofta ned hela portföljsektorn."),
            ("📊 Sektorrotation", f"{strong_up - strong_down:+d}", None,
             "Skillnad mellan sektorer i upptrend minus nedtrend. Positivt = fler sektorer stiger. Negativt = marknaden roterar nedåt. ±3 eller mer = tydlig signal."),
        ])

    tab1, tab2, tab3, tab4 = st.tabs(["🔥 Heatmap", "📋 Momentum-tabell", "🏆 Topp/botten sektorer", "💡 Handelssignaler"])

    with tab1:
        # Heatmap: sektor -> signaler
        if trends:
            import math
            sectors_list, signals_list, mom3m_list, n_stocks_list = [], [], [], []
            for sec, data in sorted(trends.items()):
                sectors_list.append(sec)
                sig = data.get("signal", "NEUTRAL")
                sig_score = {"STARK UPPTREND": 4, "UPPTREND": 3, "NEUTRAL": 2, "NEDTREND": 1, "STARK NEDTREND": 0}.get(sig, 2)
                signals_list.append(sig_score)
                mom3m_list.append(data.get("momentum_3m", 0))
                # Antal aktier i sektorn från scored_df
                if df.empty or "sector" not in df.columns:
                    n_stocks_list.append(0)
                else:
                    n_stocks_list.append(int((df["sector"] == sec).sum()))

            # Gauge chart (enklare: bar med färg)
            fig_heat = go.Figure()
            colors_h = ["#d50000" if s <= 1 else "#ff6d00" if s == 2 else "#ffd600" if s == 3 else "#00c853" for s in signals_list]
            fig_heat.add_trace(go.Bar(
                x=sectors_list, y=[s * 25 for s in signals_list],
                marker_color=colors_h,
                text=[f"{m:+.1f}%" if m else "--" for m in mom3m_list],
                textposition="outside",
                hovertemplate="<b>%{x}</b><br>Signalstyrka: %{y:.0f}%<br>3m-momentum: %{text}<br>Antal: %{customdata}<extra></extra>",
                customdata=n_stocks_list,
            ))
            fig_heat.update_layout(
                title="Sektorstyrka (0=stark nedtrend, 100=stark upptrend)",
                template="plotly_dark",
                paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                height=400, margin=dict(t=40, b=48, l=16, r=16),
                yaxis=dict(range=[0, 110], showticklabels=False),
                xaxis=dict(tickangle=-45),
            )
            st.plotly_chart(fig_heat, use_container_width=True)

            # Förklaring
            st.caption("🟢 100 = STARK UPPTREND * 🟡 75 = UPPTREND * ⚪ 50 = NEUTRAL * 🟠 25 = NEDTREND * 🔴 0 = STARK NEDTREND")
        else:
            st.info("Hämtar sektor-ETF data... (kan ta några sekunder)")

    with tab2:
        if trends:
            rows = []
            for sec, data in sorted(trends.items(), key=lambda x: x[1].get("signal_score", 0), reverse=True):
                sig = data.get("signal", "--")
                etf = etf_map.get(sec, "--")
                mom3m = data.get("momentum_3m")
                price = data.get("current_price")
                mom1m = data.get("momentum_1m")
                above50  = data.get("above_ma50")
                above200 = data.get("above_ma200")
                ma_txt = ("✅ MA50 ✅ MA200" if above50 and above200
                          else "✅ MA50 ❌ MA200" if above50
                          else "❌ MA50 ✅ MA200" if above200
                          else "❌ MA50 ❌ MA200")
                rows.append({
                    "Sektor": sec,
                    "ETF": etf,
                    "Signal": f"{'🟢' if 'UPPTREND' in sig else '🔴' if 'NEDTREND' in sig else '⚪'} {sig}",
                    "1m": f"{mom1m:+.1f}%" if mom1m else "--",
                    "3m": f"{mom3m:+.1f}%" if mom3m else "--",
                    "Pris": f"{price:.2f}" if price else "--",
                    "Trend": ma_txt,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=400)
        else:
            st.info("Ingen data än.")

    with tab3:
        if trends:
            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("🚀 Starkast sektorer")
                top_secs = sorted(trends.items(), key=lambda x: x[1].get("momentum_3m", 0), reverse=True)[:5]
                for sec, data in top_secs:
                    mom = data.get("momentum_3m", 0)
                    st.markdown(f"**{sec}** -- {mom:+.1f}%" if mom else f"**{sec}** -- --")
            with col_b:
                st.subheader("📉 Svagast sektorer")
                bot_secs = sorted(trends.items(), key=lambda x: x[1].get("momentum_3m", 0))[:5]
                for sec, data in bot_secs:
                    mom = data.get("momentum_3m", 0)
                    st.markdown(f"**{sec}** -- {mom:+.1f}%" if mom else f"**{sec}** -- --")
        else:
            st.info("Hämtar data...")

    with tab4:
        st.subheader("💡 Sektorrotation - Handelssignaler")
        st.caption("Baserat på sektors ETF-momentum och styrkerankning.")

        if not trends:
            st.info("Ingen sektordata tillgänglig.")
        else:
            # Build recommendations
            buy_sectors = []
            avoid_sectors = []
            neutral_sectors = []

            for sec, data in trends.items():
                # signal in trends is a string like "STARK UPPTREND", "UPPTREND", "NEUTRAL" etc.
                sig_str = data.get("signal", "NEUTRAL")
                sig_score = data.get("signal_score", 2)
                mom3m = data.get("momentum_3m", 0) or 0
                etf = etf_map.get(sec, "--")

                if sig_score >= 3 and mom3m > 3:
                    buy_sectors.append({"Sektor": sec, "ETF": etf, "Signal": "ÖVERVIKTA",
                                         "3m momentum": f"+{mom3m:.1f}%",
                                         "Motivering": "Stark upptrend + positivt momentum"})
                elif sig_score <= 1 or mom3m < -3:
                    avoid_sectors.append({"Sektor": sec, "ETF": etf, "Signal": "UNDERVIKTA",
                                           "3m momentum": f"{mom3m:.1f}%",
                                           "Motivering": "Nedtrend eller negativt momentum"})
                else:
                    neutral_sectors.append({"Sektor": sec, "ETF": etf, "Signal": "NEUTRAL",
                                             "3m momentum": f"{mom3m:+.1f}%"})

            col1_sr, col2_sr = st.columns(2)
            with col1_sr:
                st.markdown("**Övervikta (starka sektorer)**")
                if buy_sectors:
                    st.dataframe(pd.DataFrame(buy_sectors), use_container_width=True, hide_index=True)
                else:
                    st.info("Inga sektorer uppfyller överviktskriterierna just nu")

            with col2_sr:
                st.markdown("**Undervikta (svaga sektorer)**")
                if avoid_sectors:
                    st.dataframe(pd.DataFrame(avoid_sectors), use_container_width=True, hide_index=True)
                else:
                    st.info("Inga sektorer i tydlig nedtrend just nu")

            if neutral_sectors:
                with st.expander("Neutrala sektorer", expanded=False):
                    st.dataframe(pd.DataFrame(neutral_sectors), use_container_width=True, hide_index=True)

            # Stock picks from strong sectors
            st.markdown("---")
            st.markdown("**Bästa aktier från starka sektorer**")
            if buy_sectors and not df.empty and "sector" in df.columns:
                strong_sector_names = [s["Sektor"] for s in buy_sectors]
                strong_stocks = df[df["sector"].isin(strong_sector_names)].copy() if strong_sector_names else pd.DataFrame()

                # Also try partial match
                if strong_stocks.empty and strong_sector_names:
                    try:
                        mask = df["sector"].str.contains("|".join(strong_sector_names[:3]), case=False, na=False)
                        strong_stocks = df[mask].copy()
                    except Exception:
                        pass

                if not strong_stocks.empty:
                    show_cols_sr = [c for c in ["ticker", "name", "sector", "score_total", "entry_signal", "return_3m"]
                                    if c in strong_stocks.columns]
                    if "score_total" in strong_stocks.columns:
                        top_strong = strong_stocks.sort_values("score_total", ascending=False).head(10)
                    else:
                        top_strong = strong_stocks.head(10)
                    _sr_disp = top_strong[show_cols_sr].rename(columns={"ticker": "Ticker"})
                    clickable_stock_table(_sr_disp, ticker_col="Ticker", context_df=df,
                                         key="sector_top_stocks_table", caption="Klicka för full analys.")
                else:
                    st.info("Ingen direktmatchning mellan ETF-sektorer och universumsektorer just nu")

            # Rotation summary
            st.markdown("---")
            rotation_score = len(buy_sectors) - len(avoid_sectors)
            if rotation_score >= 3:
                st.success(f"Bred bull-marknad -- {len(buy_sectors)} sektorer i upptrend, {len(avoid_sectors)} i nedtrend")
            elif rotation_score <= -3:
                st.error(f"Bred bear-marknad -- {len(avoid_sectors)} sektorer i nedtrend")
            else:
                st.info(f"Blandad marknad -- {len(buy_sectors)} upp, {len(avoid_sectors)} ned, {len(neutral_sectors)} neutrala")

    # AI-knapp
    if trends:
        st.markdown("---")
        if st.button("🤖 Analysera sektorrotation med AI", key="btn_sector_rotation_ai", use_container_width=True):
            with st.spinner("Analyserar sektorrotation..."):
                try:
                    provider = _get_provider()
                    depth = _get_depth()
                    top = sorted(trends.items(), key=lambda x: x[1].get("momentum_3m", 0), reverse=True)[:3]
                    bot = sorted(trends.items(), key=lambda x: x[1].get("momentum_3m", 0))[:3]
                    context = {
                        "top_sectors": [{"name": s, "mom3m": d.get("momentum_3m")} for s, d in top],
                        "bottom_sectors": [{"name": s, "mom3m": d.get("momentum_3m")} for s, d in bot],
                    }
                    result = ai_analysis.ai_chat(
                        "Analysera sektorrotationen och ge rekommendationer för sektorallokering",
                        context=ai_analysis._safe_json(context, ensure_ascii=False),
                        provider=provider, depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")
