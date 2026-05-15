"""
stock_detail.py – MarketScan Stock Detail Panel
================================================
En återanvändbar Streamlit-komponent som visar detaljerad information
för en enskild aktie: prisgraf, nyckeltal, nyhetsflöde och AI-analys.

Användning:
    from web.stock_detail import render_stock_detail

    # I din Streamlit-sida:
    render_stock_detail(
        ticker="AAPL",
        row=scored_df[scored_df["ticker"] == "AAPL"].iloc[0],  # rad från scored_universe
        df=scored_df,                                           # hela datasetet (för kontext)
    )
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core import config, data_fetcher
from core import ai_analysis

try:
    from core.news_fetcher import fetch_company_news as _fetch_news
except ImportError:
    _fetch_news = None


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _safe_val(val, fmt: str = "num", default: str = "—"):
    """Returnera formaterat värde eller default om None/NaN."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except Exception:
        pass
    if fmt == "pct":
        return f"{float(val):.1f}%"
    if fmt == "pct_plus":
        return f"{float(val):+.1f}%"
    if fmt == "dec2":
        return f"{float(val):.2f}"
    if fmt == "dec0":
        return f"{float(val):.0f}"
    if fmt == "ratio":
        return f"{float(val):.1f}/9"
    return str(val)


def _provider_selector(key: str = "provider_default") -> str:
    """Visa en provider-väljare i UI och returnera vald provider."""
    options = {
        "auto": f"Auto ({config.AI_PROVIDER})",
        "deepseek": "DeepSeek (komplex, kostar)",
        "gemini": "Gemini (enkel, gratis)",
    }
    default_key = f"provider_{key}"
    if default_key not in st.session_state:
        st.session_state[default_key] = "auto"
    return st.selectbox(
        "AI-provider",
        list(options.keys()),
        format_func=lambda k: options.get(k, k),
        key=default_key,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. PRISGRAF
# ══════════════════════════════════════════════════════════════════════════════

PERIOD_OPTIONS = {
    "1m":  "1 månad",
    "3m":  "3 månader",
    "6m":  "6 månader",
    "1y":  "1 år",
    "2y":  "2 år",
    "5y":  "5 år",
    "max": "Max",
}


def _price_chart(ticker: str, period: str = "1y") -> Optional[go.Figure]:
    """
    Skapa en prisgraf med volym och glidande medelvärden.
    Returnerar None om data saknas.
    """
    hist = data_fetcher.fetch_price_history(ticker, period=period)
    if hist.empty:
        return None

    # Beräkna glidande medelvärden
    hist["MA50"] = hist["Close"].rolling(50).mean() if len(hist) >= 50 else None
    hist["MA200"] = hist["Close"].rolling(200).mean() if len(hist) >= 200 else None

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.75, 0.25],
    )

    # ── Candlestick ──────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=hist.index,
        open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="Pris",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # ── Glidande medelvärden ─────────────────────────────────────────────
    if hist["MA50"] is not None and not hist["MA50"].isna().all():
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["MA50"],
            line=dict(color="#ffd600", width=1.2),
            name="MA50",
        ), row=1, col=1)

    if hist["MA200"] is not None and not hist["MA200"].isna().all():
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["MA200"],
            line=dict(color="#e040fb", width=1.2),
            name="MA200",
        ), row=1, col=1)

    # ── Volym ────────────────────────────────────────────────────────────
    colors = ["#26a69a" if hist["Close"].iloc[i] >= hist["Open"].iloc[i]
              else "#ef5350" for i in range(len(hist))]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=colors,
        name="Volym",
        opacity=0.4,
    ), row=2, col=1)

    # ── Layout ───────────────────────────────────────────────────────────
    fig.update_layout(
        title=f"{ticker} – Prisutveckling ({PERIOD_OPTIONS.get(period, period)})",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#131722",
        plot_bgcolor="#1e2230",
        height=440,
        margin=dict(t=44, b=16, l=16, r=16),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
    )

    fig.update_yaxes(title_text="Pris (SEK)", row=1, col=1, color="#8892a4")
    fig.update_yaxes(title_text="Volym", row=2, col=1, color="#8892a4")
    fig.update_xaxes(color="#8892a4")

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 2. DATA-KORT (snabbvy)
# ══════════════════════════════════════════════════════════════════════════════

def _quick_data_cards(row: pd.Series):
    """Visa en rad med metrik-kort för aktuell aktie."""
    cols = st.columns(7)

    metrics = [
        ("Score", row.get("score_total"), "dec0", "🎯"),
        ("Entry", row.get("entry_signal"), None, "⚡"),
        ("Trend", row.get("trend_signal"), None, "📈"),
        ("RSI", row.get("rsi_14"), "dec0", "🌡️"),
        ("P/E", row.get("pe_trailing"), "dec1", "💰"),
        ("ROE", row.get("roe"), "pct", "📊"),
        ("Piotroski", row.get("piotroski_f"), "ratio", "🔬"),
    ]

    for col, (label, val, fmt, icon) in zip(cols, metrics):
        with col:
            formatted = _safe_val(val, fmt if fmt else "num")
            st.metric(f"{icon} {label}", formatted)


# ══════════════════════════════════════════════════════════════════════════════
# 3. DETALJERAD DATA-TABELL
# ══════════════════════════════════════════════════════════════════════════════

def _detail_table(row: pd.Series):
    """Visa detaljerad data i expanderbara sektioner."""
    with st.expander("📋 All data", expanded=False):
        tab_val, tab_qual, tab_mom, tab_risk, tab_div = st.tabs([
            "Värdering", "Kvalitet", "Momentum", "Risk", "Övrigt"
        ])

        with tab_val:
            val_data = {
                "P/E (trailing)": _safe_val(row.get("pe_trailing"), "dec1"),
                "P/E (forward)": _safe_val(row.get("pe_forward"), "dec1"),
                "P/B": _safe_val(row.get("price_to_book"), "dec2"),
                "P/S": _safe_val(row.get("price_to_sales"), "dec2"),
                "EV/EBITDA": _safe_val(row.get("ev_to_ebitda"), "dec1"),
                "EV/Revenue": _safe_val(row.get("ev_to_revenue"), "dec2"),
                "PEG Ratio": _safe_val(row.get("peg_ratio"), "dec2"),
                "Värderingsscore": _safe_val(row.get("score_value"), "dec0"),
            }
            st.dataframe(
                pd.DataFrame(val_data.items(), columns=["Mått", "Värde"]),
                use_container_width=True, hide_index=True,
            )

        with tab_qual:
            qual_data = {
                "ROE": _safe_val(row.get("roe"), "pct"),
                "ROA": _safe_val(row.get("roa"), "pct"),
                "Bruttomarginal": _safe_val(row.get("gross_margin"), "pct"),
                "Rörelsemarginal": _safe_val(row.get("operating_margin"), "pct"),
                "Nettomarginal": _safe_val(row.get("profit_margin"), "pct"),
                "FCF": _safe_val(row.get("free_cash_flow"), "dec0"),
                "Piotroski F-Score": _safe_val(row.get("piotroski_f"), "ratio"),
                "Kvalitetsscore": _safe_val(row.get("score_quality"), "dec0"),
            }
            st.dataframe(
                pd.DataFrame(qual_data.items(), columns=["Mått", "Värde"]),
                use_container_width=True, hide_index=True,
            )

        with tab_mom:
            mom_data = {
                "1 månad": _safe_val(row.get("return_1m"), "pct_plus"),
                "3 månader": _safe_val(row.get("return_3m"), "pct_plus"),
                "6 månader": _safe_val(row.get("return_6m"), "pct_plus"),
                "12 månader": _safe_val(row.get("return_12m"), "pct_plus"),
                "vs MA50": _safe_val(row.get("price_vs_ma50"), "pct_plus"),
                "vs MA200": _safe_val(row.get("price_vs_ma200"), "pct_plus"),
                "RSI (14)": _safe_val(row.get("rsi_14"), "dec0"),
                "MACD ovan signal": str(row.get("macd_above_signal", "—")),
                "Momentumscore": _safe_val(row.get("score_momentum"), "dec0"),
            }
            st.dataframe(
                pd.DataFrame(mom_data.items(), columns=["Mått", "Värde"]),
                use_container_width=True, hide_index=True,
            )

        with tab_risk:
            risk_data = {
                "Beta": _safe_val(row.get("beta"), "dec2"),
                "Volatilitet": _safe_val(row.get("volatility"), "pct"),
                "D/E": _safe_val(row.get("debt_to_equity"), "dec0"),
                "Current Ratio": _safe_val(row.get("current_ratio"), "dec2"),
                "Quick Ratio": _safe_val(row.get("quick_ratio"), "dec2"),
                "52v High": _safe_val(row.get("pct_from_52w_high"), "pct_plus"),
                "Riskscore": _safe_val(row.get("score_risk"), "dec0"),
            }
            st.dataframe(
                pd.DataFrame(risk_data.items(), columns=["Mått", "Värde"]),
                use_container_width=True, hide_index=True,
            )

        with tab_div:
            div_data = {
                "Utdelningsyield": _safe_val(row.get("dividend_yield"), "pct"),
                "Payout Ratio": _safe_val(row.get("payout_ratio"), "pct"),
                "Utdelningsscore": _safe_val(row.get("score_dividend"), "dec0"),
                "Sektor": str(row.get("sector", "—")),
                "Industri": str(row.get("industry", "—")),
                "Land": str(row.get("country", "—")),
                "Koncifens": str(row.get("confidence_label", "—")),
                "RS-labb": str(row.get("rs_label", "—")),
            }
            st.dataframe(
                pd.DataFrame(div_data.items(), columns=["Mått", "Värde"]),
                use_container_width=True, hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# 4. SCORE-RADARCHART
# ══════════════════════════════════════════════════════════════════════════════

def _radar_chart(row: pd.Series) -> go.Figure:
    """Skapa en radarchart över de 8 faktorerna."""
    score_fields = [
        ("score_value", "Värdering"),
        ("score_quality", "Kvalitet"),
        ("score_momentum", "Momentum"),
        ("score_growth", "Tillväxt"),
        ("score_risk", "Risk"),
        ("score_size", "Storlek"),
        ("score_dividend", "Utdelning"),
        ("score_sentiment", "Sentiment"),
    ]

    categories = [label for _, label in score_fields]
    values = []
    for field, _ in score_fields:
        v = row.get(field)
        v = float(v) if v is not None and not pd.isna(v) else 0
        values.append(v)

    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(66, 165, 245, 0.25)",
        line=dict(color="#42a5f5", width=2),
        name="Scoreprofil",
    ))

    fig.update_layout(
        title="🕸️ 8-faktorsprofil",
        template="plotly_dark",
        paper_bgcolor="#131722",
        polar=dict(
            bgcolor="#1e2230",
            radialaxis=dict(range=[0, 100], color="#8892a4", showticklabels=True),
            angularaxis=dict(color="#8892a4"),
        ),
        height=380,
        margin=dict(t=44, b=20, l=60, r=60),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 5. NYHETSFLÖDE
# ══════════════════════════════════════════════════════════════════════════════

def _news_feed(ticker: str):
    """Visa de senaste nyheterna för en aktie."""
    st.subheader("📰 Nyheter")

    if _fetch_news is None:
        st.info("news_fetcher-modulen är inte tillgänglig.")
        return

    try:
        news = _fetch_news(ticker, days_back=7)
    except Exception as e:
        st.info(f"Kunde inte hämta nyheter: {e}")
        news = []

    if not news:
        st.caption("Inga nyheter den senaste veckan.")
        return

    for item in news[:10]:
        title = item.get("headline") or item.get("title") or "—"
        source = item.get("source", "?")
        date_raw = item.get("datetime") or item.get("publishedAt") or ""
        date_str = ""
        if date_raw:
            try:
                dt = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                date_str = str(date_raw)[:10]

        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{title}**")
            with c2:
                if source and source.lower() not in ("", "?"):
                    st.caption(f"📡 {source}")
                if date_str:
                    st.caption(f"🕐 {date_str}")

            # Kort sammanfattning om tillgänglig
            summary = item.get("summary") or item.get("description") or ""
            if summary:
                st.caption(summary[:200])


# ══════════════════════════════════════════════════════════════════════════════
# 6. AI-ANALYS-PANEL
# ══════════════════════════════════════════════════════════════════════════════

AI_PRESET_PROMPTS = {
    "📈 Fullständig analys": "full",
    "🎯 Sammanfattning (kort)": "brief",
    "💰 Värderingsfokus": "value",
    "📊 Tekniskt fokus": "technical",
    "⚠️ Riskfokus": "risk",
    "🔮 Framtidsutsikter": "outlook",
    "✏️ Egen fråga": "custom",
}

AI_PROMPTS_MAP = {
    "full": ("Fullständig analys", ""),
    "brief": (
        "Kort sammanfattning",
        "Ge en kort sammanfattning av aktien. Max 100 ord. Fokusera på "
        "det viktigaste: är detta ett köp eller inte just nu?"
    ),
    "value": (
        "Värderingsfokus",
        "Analysera endast värderingen. Kommentera P/E, P/B, EV/EBITDA "
        "i relation till sektorn. Är aktien billig eller dyr?"
    ),
    "technical": (
        "Tekniskt fokus",
        "Analysera endast teknisk data: RSI, MACD, MA50/MA200, trender, "
        "volym. Bullish eller bearish setup?"
    ),
    "risk": (
        "Riskfokus",
        "Fokusera på risker: skuldsättning, volatilitet, beta, short-interest, "
        "sektorkoncentration. Vilka är de största riskerna?"
    ),
    "outlook": (
        "Framtidsutsikter",
        "Baserat på tillgänglig data, vad är dina framtidsutsikter för "
        "denna aktie de kommande 3-6 månaderna?"
    ),
}


def _ai_analysis_panel(ticker: str, row: pd.Series, df: pd.DataFrame):
    """AI-analyspanel med preset prompts och provider-väljare."""
    st.subheader("🤖 AI-analys")

    # Provider-väljare
    provider = _provider_selector(f"detail_{ticker}")

    # Förifyllda frågor
    preset_options = list(AI_PRESET_PROMPTS.keys())
    selected_preset = st.selectbox("Välj analys-typ", preset_options, key=f"ai_preset_{ticker}")

    custom_question = ""
    if selected_preset == "✏️ Egen fråga":
        custom_question = st.text_area(
            "Din fråga om aktien:",
            placeholder="Ställ en egen fråga om aktien...",
            key=f"ai_custom_q_{ticker}",
            height=80,
        )

    force_refresh = st.checkbox("Hoppa över cache", key=f"ai_refresh_{ticker}")

    # Analysera-knapp
    analyze_col1, analyze_col2 = st.columns([3, 1])
    with analyze_col1:
        clicked = st.button(
            "🤖 Analysera",
            key=f"btn_ai_detail_{ticker}",
            type="primary",
            use_container_width=True,
        )
    with analyze_col2:
        # Nyhetsanalys-knapp
        news_clicked = st.button(
            "📰 Analysera nyheter",
            key=f"btn_news_detail_{ticker}",
            use_container_width=True,
        )

    if clicked:
        # Bestäm vilken prompt som ska användas
        preset_key = AI_PRESET_PROMPTS[selected_preset]
        if preset_key == "custom":
            if not custom_question.strip():
                st.warning("Skriv en fråga först.")
                return
            # Använd chat-funktionen för egen fråga
            with st.spinner(f"🤖 AI (via {provider}) analyserar..."):
                try:
                    context = {}
                    for field in ["score_total", "sector", "current_price",
                                  "pe_trailing", "rsi_14", "trend_signal",
                                  "entry_signal", "piotroski_f"]:
                        v = row.get(field)
                        if v is not None and not pd.isna(v):
                            context[field] = float(v) if isinstance(v, (int, float)) else v

                    result = ai_analysis.ai_chat(
                        custom_question,
                        context=json.dumps(context, ensure_ascii=False),
                        force_refresh=force_refresh,
                        provider=provider,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")
        else:
            with st.spinner(f"🤖 AI (via {provider}) analyserar..."):
                try:
                    result = ai_analysis.analyze_stock(
                        ticker, df=df, force_refresh=force_refresh, provider=provider,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")

    if news_clicked:
        # Hämta och analysera nyheter
        with st.spinner("Hämtar och analyserar nyheter..."):
            try:
                news_items = None
                if _fetch_news is not None:
                    try:
                        raw_news = _fetch_news(ticker, days_back=7)
                        if raw_news:
                            news_items = [
                                {
                                    "title": n.get("headline", n.get("title", "")),
                                    "summary": n.get("summary", n.get("description", "")),
                                    "source": n.get("source", "?"),
                                    "date": n.get("datetime", n.get("publishedAt", "")),
                                }
                                for n in raw_news[:10]
                            ]
                    except Exception:
                        pass

                result = ai_analysis.analyze_news(
                    ticker, news_items=news_items,
                    force_refresh=force_refresh, provider=provider,
                )
                with st.container(border=True):
                    st.markdown(result)
            except Exception as e:
                st.error(f"❌ {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDKOMPONENT – render_stock_detail
# ══════════════════════════════════════════════════════════════════════════════

def render_stock_detail(
    ticker: str,
    row: pd.Series = None,
    df: pd.DataFrame = None,
    show_ai: bool = True,
    show_news: bool = True,
    show_chart: bool = True,
    show_detail_data: bool = True,
):
    """
    Rendera hela Stock Detail Panel för en ticker.

    Args:
        ticker: Ticker-symbol (t.ex. "AAPL")
        row: Rad från scored_universe DataFrame med aktuell data
        df: Hela scored_universe DataFrame (för AI-kontext)
        show_ai: Visa AI-analyspanel
        show_news: Visa nyhetsflöde
        show_chart: Visa prisgraf
        show_detail_data: Visa detaljerad data
    """
    st.markdown(f"## 📈 `{ticker}` – Detaljvy")
    st.markdown("---")

    # ── Sektion 1: Snabbdata-kort ──────────────────────────────────────────
    if row is not None and not row.empty:
        _quick_data_cards(row)

    # ── Sektion 2: Prisgraf + Radar ────────────────────────────────────────
    if show_chart:
        period = st.selectbox(
            "Välj tidsperiod",
            list(PERIOD_OPTIONS.keys()),
            format_func=lambda k: PERIOD_OPTIONS[k],
            index=3,  # Default: 1y
            key=f"period_{ticker}",
        )

        chart = _price_chart(ticker, period=period)
        if chart is not None:
            st.plotly_chart(chart, use_container_width=True)
        else:
            st.info("Prisdata saknas för denna aktie.")

        # Radar-chart bredvid prisgraf?
        if row is not None and not row.empty:
            c1, c2 = st.columns([3, 2])
            with c1:
                pass  # Utrymme för framtida användning
            with c2:
                st.plotly_chart(_radar_chart(row), use_container_width=True)

    st.markdown("---")

    # ── Sektion 3: Detaljerad data ─────────────────────────────────────────
    if show_detail_data and row is not None and not row.empty:
        _detail_table(row)

    # ── Sektion 4: Nyhetsflöde + AI sida vid sida ─────────────────────────
    col_news, col_ai = st.columns([1, 1])

    with col_news:
        if show_news:
            _news_feed(ticker)

    with col_ai:
        if show_ai and row is not None and not row.empty:
            _ai_analysis_panel(ticker, row, df)

    # ── Botten: API-status ─────────────────────────────────────────────────
    st.markdown("---")
    with st.container():
        st.caption(
            f"💰 Data från yfinance | "
            f"🤖 AI: {config.AI_PROVIDER} (DeepSeek) / Gemini | "
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
