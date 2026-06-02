"""
web/pages/options_dashboard.py — Options Dashboard
===================================================
Ny Streamlit-sida "Options" för optioner och derivat:
- Chain table (strike, IV, delta, gamma, theta, vega, OI, volume)
- Volatility smile chart, IV surface, put/call ratio
- Max pain, expected move, support/resistance
- Options flow (unusual activity)
- Earnings play analyzer
- Strategy builder med payoff diagram
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except ImportError:
    _PLOTLY_AVAILABLE = False

from core.options_chain import OptionsChain
from core.options_greeks import calculate_greeks, implied_volatility, greek_sensitivities
from core.options_flow import (
    analyze_options_flow,
    put_call_ratio,
    unusual_options_activity,
    whales,
    options_sentiment,
)
from core.options_maxpain import (
    calculate_max_pain,
    max_pain_chart,
    expected_move,
    support_resistance_from_options,
)
from core.options_volsurface import VolatilitySurface
from core.options_earnings import (
    analyze_earnings_play,
    historical_earnings_moves,
    straddle_cost,
    play_recommendation,
)
from core.options_strategies import (
    CoveredCallStrategy,
    WheelStrategy,
    ProtectivePutAnalysis,
    BullPutSpread,
    BearCallSpread,
)

logger = logging.getLogger(__name__)


def _get_ticker_input() -> str:
    """Hämta ticker från input eller session_state."""
    default = st.session_state.get("options_ticker", "")
    ticker = st.text_input(
        "Ticker",
        value=default,
        placeholder="t.ex. AAPL, TSLA, SPY",
        key="options_ticker_input",
        label_visibility="collapsed",
    ).upper().strip()
    if ticker:
        st.session_state["options_ticker"] = ticker
    return ticker


@st.cache_data(ttl=300)
def _cached_chain(ticker: str, expiration: str = ""):
    """Cachad optionskedja (5 min)."""
    exp = expiration if expiration else None
    return OptionsChain.fetch_chain(ticker, expiration=exp)


@st.cache_data(ttl=300)
def _cached_expirations(ticker: str):
    """Cachade expirationer (5 min)."""
    return OptionsChain.fetch_all_expirations(ticker)


@st.cache_data(ttl=600)
def _cached_maxpain(ticker: str):
    """Cachad max pain (10 min)."""
    chain = _cached_chain(ticker)
    if chain is None:
        return None
    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}
    S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))
    return calculate_max_pain(chain, S)


def _render_chain_table(chain: pd.DataFrame, ticker: str):
    """Visa optionskedja med Greeks."""
    if chain is None or chain.empty:
        st.warning("Ingen optionsdata tillgänglig.")
        return

    st.subheader("Options Chain")

    # Hämta current price
    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}
    S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))

    # Beräkna T (tid till expiration)
    exp_str = str(chain.get("expiration", chain.get("contractSymbol", "")).iloc[0] if not chain.empty else "")
    try:
        exp_date = pd.to_datetime(exp_str)
        T = max((exp_date - pd.Timestamp.now()).days / 365.0, 0.01)
    except Exception:
        T = 0.5

    r = 0.05  # riskfri ränta

    # Beräkna Greeks för varje rad
    rows = []
    for _, row in chain.iterrows():
        K = float(row["strike"])
        iv = float(row.get("impliedVolatility", 0.3) or 0.3)
        opt_type = str(row.get("option_type", "call"))
        last_price = float(row.get("lastPrice", 0) or 0)
        volume = int(row.get("volume", 0) or 0)
        oi = int(row.get("openInterest", 0) or 0)

        greeks = calculate_greeks(opt_type, S, K, T, r, iv)

        rows.append({
            "Option Type": opt_type.upper(),
            "Strike": K,
            "Last": round(last_price, 2),
            "IV %": round(iv * 100, 1),
            "Delta": greeks.get("delta"),
            "Gamma": greeks.get("gamma"),
            "Theta": greeks.get("theta"),
            "Vega": greeks.get("vega"),
            "OI": oi,
            "Volume": volume,
        })

    df = pd.DataFrame(rows)

    # Färgkodning
    def _color_iv(val):
        if val is None:
            return ""
        if val > 50:
            return "color: #ef5350"
        if val > 30:
            return "color: #ffd600"
        return "color: #4caf50"

    def _color_delta(val):
        if val is None:
            return ""
        if abs(val) > 0.7:
            return "color: #ef5350"
        if abs(val) > 0.4:
            return "color: #ffd600"
        return "color: #4caf50"

    st.dataframe(
        df.style.applymap(_color_iv, subset=["IV %"])
        .applymap(_color_delta, subset=["Delta"]),
        use_container_width=True,
        hide_index=True,
        height=400,
    )

    st.caption(f"Aktiepris: ${S:.2f} | Riskfri ränta: {r*100:.1f}% | Dagar till expiry: {T*365:.0f}")


def _render_volatility_analysis(ticker: str):
    """Visa volatility smile och IV surface."""
    st.subheader("Volatility Analysis")

    vol_surface = VolatilitySurface()
    exps = _cached_expirations(ticker)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Volatility Smile**")
        smile_exp = st.selectbox(
            "Expiration",
            options=exps if exps else ["N/A"],
            key="vol_smile_exp",
            label_visibility="collapsed",
        )
        if smile_exp and smile_exp != "N/A":
            fig = vol_surface.volatility_smile(ticker, expiration=smile_exp)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Kunde inte skapa volatility smile.")

    with col2:
        st.markdown("**Term Structure**")
        fig_ts = vol_surface.term_structure(ticker)
        if fig_ts:
            st.plotly_chart(fig_ts, use_container_width=True)
        else:
            st.info("Kunde inte skapa term structure.")

    # IV Surface (full bredd)
    st.markdown("**IV Surface (3D)**")
    surface_data = vol_surface.build_surface(ticker)
    if surface_data is not None and not surface_data.empty:
        fig_surf = vol_surface.plot_surface(surface_data)
        if fig_surf:
            st.plotly_chart(fig_surf, use_container_width=True)
        else:
            st.info("Kunde inte skapa 3D surface.")
    else:
        st.info("Kunde inte bygga IV-surface.")

    # IV Percentile + Skew
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**IV Percentile (252d)**")
        ivp = vol_surface.iv_percentile(ticker)
        if ivp:
            st.metric("Current IV", f"{ivp['current_iv']:.1f}%")
            st.metric("Percentile", f"{ivp['percentile']:.0f}%", delta=f"{ivp['iv_rank']}")
            st.metric("Median IV", f"{ivp['median_iv']:.1f}%")
            st.metric("Range", f"{ivp['min_iv']:.1f}% - {ivp['max_iv']:.1f}%")
        else:
            st.info("Kunde inte beräkna IV-percentil.")

    with col4:
        st.markdown("**Skew (25-delta Put/Call)**")
        skew_data = vol_surface.skew(ticker)
        if skew_data:
            st.metric("Skew", f"{skew_data['skew']:.1f}%",
                      delta="Put premium" if skew_data['skew'] > 0 else "Call premium")
            st.metric("Put IV (25∆)", f"{skew_data['put_iv_25']:.1f}%")
            st.metric("Call IV (25∆)", f"{skew_data['call_iv_25']:.1f}%")
            st.caption(f"Expiration: {skew_data['expiration']}")
        else:
            st.info("Kunde inte beräkna skew.")


def _render_max_pain_analysis(ticker: str):
    """Visa max pain, expected move och S/R-nivåer."""
    st.subheader("Max Pain & Expected Move")

    chain = _cached_chain(ticker)
    if chain is None or chain.empty:
        st.warning("Ingen optionsdata.")
        return

    yf_ticker = yf.Ticker(ticker)
    info = yf_ticker.info or {}
    S = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Max Pain**")
        mp = calculate_max_pain(chain, S)
        fig_mp = max_pain_chart(chain, S)
        if fig_mp:
            st.plotly_chart(fig_mp, use_container_width=True)
        if mp.get("max_pain_strike"):
            st.metric(
                "Max Pain Strike",
                f"${mp['max_pain_strike']:.2f}",
                delta=f"{mp['max_pain_strike'] - S:+.2f} mot spot",
                delta_color="inverse",
            )

    with col2:
        st.markdown("**Expected Move**")
        em = expected_move(chain, S)
        if em:
            st.metric("Expected Move", f"{em['expected_move_pct']:.1f}%",
                      delta=f"${em['expected_move_amount']:.2f}")
            st.metric("Upside", f"${em['expected_move_up']:.2f}")
            st.metric("Downside", f"${em['expected_move_down']:.2f}")
        else:
            st.info("Kunde inte beräkna expected move.")

    # Support/Resistance nivåer
    st.markdown("**Support & Resistance från OI-koncentration**")
    sr = support_resistance_from_options(chain)
    cols_sr = st.columns(2)
    with cols_sr[0]:
        st.markdown("**Support (Put OI)**")
        if sr.get("support_levels"):
            for s in sr["support_levels"]:
                st.markdown(f"- **${s['strike']:.2f}** (OI: {s['oi']:,})")
        else:
            st.caption("Inga tydliga supportnivåer.")
    with cols_sr[1]:
        st.markdown("**Resistance (Call OI)**")
        if sr.get("resistance_levels"):
            for r in sr["resistance_levels"]:
                st.markdown(f"- **${r['strike']:.2f}** (OI: {r['oi']:,})")
        else:
            st.caption("Inga tydliga resistancenivåer.")


def _render_options_flow(ticker: str):
    """Visa options flow och unusual activity."""
    st.subheader("Options Flow")

    # Sentiment
    sentiment = options_sentiment(ticker)
    sentiment_color = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}
    st.metric("Market Sentiment", f"{sentiment_color.get(sentiment, '⚪')} {sentiment.upper()}")

    # P/C Ratio
    pc = put_call_ratio(ticker)
    if pc:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("P/C Volym", f"{pc['ratio_volume']:.2f}")
        col2.metric("P/C OI", f"{pc['ratio_oi']:.2f}")
        col3.metric("Call Volym", f"{pc['call_volume']:,}")
        col4.metric("Put Volym", f"{pc['put_volume']:,}")

    # Unusual Activity
    st.markdown("**Unusual Options Activity (z-score > 2)**")
    unusual = unusual_options_activity(ticker)
    if not unusual.empty:
        display = unusual[["option_type", "strike", "volume", "open_interest", "premium", "z_score"]].copy()
        display["premium"] = display["premium"].apply(lambda x: f"${x:,.0f}")
        display["z_score"] = display["z_score"].apply(lambda x: f"{x:.1f}")
        st.dataframe(display.head(10), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen ovanlig aktivitet detekterad.")

    # Whale Alerts
    st.markdown("**Whale Alerts ($100k+ premium)**")
    w = whales(ticker, min_premium=100000)
    if not w.empty:
        display_w = w[["option_type", "strike", "volume", "premium", "iv"]].copy()
        display_w["premium"] = display_w["premium"].apply(lambda x: f"${x:,.0f}")
        display_w["iv"] = display_w["iv"].apply(lambda x: f"{x*100:.1f}%")
        st.dataframe(display_w.head(10), use_container_width=True, hide_index=True)
    else:
        st.info("Inga whale alerts detekterade.")


def _render_earnings_analyzer(ticker: str):
    """Visa earnings play analys."""
    st.subheader("Earnings Play Analyzer")

    # Hämta earnings dates
    try:
        yf_ticker = yf.Ticker(ticker)
        earnings = yf_ticker.earnings_dates
        if earnings is not None and not earnings.empty:
            upcoming = earnings.index[0]
            upcoming_str = pd.Timestamp(upcoming).strftime("%Y-%m-%d")
            st.info(f"Nästa earnings: **{upcoming_str}**")

            analysis = analyze_earnings_play(ticker, upcoming_str)

            if "error" in analysis and analysis["error"]:
                st.warning(analysis["error"])
            else:
                col1, col2, col3 = st.columns(3)
                em = analysis.get("expected_move", {})
                if em:
                    col1.metric("Expected Move", f"{em.get('expected_move_pct', '--')}%")
                strad = analysis.get("straddle", {})
                if strad:
                    col2.metric("Straddle Cost", f"${strad.get('straddle_price', '--')}")
                rec = analysis.get("recommendation", {})
                if rec:
                    action = rec.get("action", "---")
                    conf = rec.get("confidence", "---")
                    col3.metric("Recommendation", action, delta=conf)

                # Break-even
                be = analysis.get("break_even", {})
                if be and be.get("lower") and be.get("upper"):
                    st.markdown(f"**Break-Even Range:** ${be['lower']:.2f} — ${be['upper']:.2f} (Range: {be['range_pct']:.1f}%)")

                # Recommendation details
                if rec and rec.get("reason"):
                    st.info(f"**Why:** {rec['reason']}")

            # Historical moves
            st.markdown("**Historiska Earnings Moves**")
            hist = historical_earnings_moves(ticker, n=6)
            if hist:
                hist_df = pd.DataFrame(hist)
                hist_df["move_pct"] = hist_df["move_pct"].apply(lambda x: f"{x:+.2f}%")
                st.dataframe(hist_df, use_container_width=True, hide_index=True)
                avg_move = np.mean([abs(h["move_pct"]) for h in hist])
                st.caption(f"Genomsnittlig |rörelse|: {avg_move:.2f}%")
            else:
                st.info("Inga historiska earnings-data tillgängliga.")
        else:
            st.info("Inga earnings-datum hittades.")
    except Exception as e:
        st.info(f"Earnings-data ej tillgänglig: {e}")


def _render_strategy_builder(ticker: str):
    """Strategy builder med payoff-diagram."""
    st.subheader("Strategy Builder")

    strategy = st.selectbox(
        "Välj strategi",
        ["Covered Call", "Wheel Strategy", "Protective Put", "Bull Put Spread", "Bear Call Spread"],
        key="strategy_selector",
    )

    if strategy == "Covered Call":
        st.markdown("**Covered Call — Sälj call mot innehav**")
        col1, col2, col3 = st.columns(3)
        with col1:
            shares = st.number_input("Antal aktier", min_value=1, value=100, step=100, key="cc_shares")
        with col2:
            avg_price = st.number_input("Genomsnittspris", min_value=0.01, value=0.0, step=0.01, format="%.2f", key="cc_avg")
        with col3:
            current_price = 0.0
            try:
                yf_ticker = yf.Ticker(ticker)
                info = yf_ticker.info or {}
                current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))
            except Exception:
                pass
            st.metric("Current Price", f"${current_price:.2f}" if current_price else "--")

        holding = {"ticker": ticker, "shares": shares, "avg_price": avg_price, "current_price": current_price}
        analysis = CoveredCallStrategy.analyze(holding)
        if "error" in analysis and analysis["error"]:
            st.warning(analysis["error"])
        elif analysis.get("recommendations"):
            st.dataframe(
                pd.DataFrame(analysis["recommendations"]),
                use_container_width=True,
                hide_index=True,
            )

    elif strategy == "Wheel Strategy":
        st.markdown("**Wheel Strategy — CSP + CC**")
        analysis = WheelStrategy.analyze(ticker)
        if "error" in analysis:
            st.warning(analysis["error"])
        else:
            if analysis.get("support_levels"):
                st.markdown(f"**Supportnivåer:** {', '.join(f'${s:.2f}' for s in analysis['support_levels'])}")
            if analysis.get("resistance_levels"):
                st.markdown(f"**Resistancenivåer:** {', '.join(f'${r:.2f}' for r in analysis['resistance_levels'])}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Cash-Secured Puts**")
                if analysis.get("cash_secured_puts"):
                    st.dataframe(pd.DataFrame(analysis["cash_secured_puts"]), use_container_width=True, hide_index=True)
                else:
                    st.info("Inga CSP-möjligheter hittades.")

            with col2:
                st.markdown("**Covered Calls**")
                if analysis.get("covered_calls"):
                    st.dataframe(pd.DataFrame(analysis["covered_calls"]), use_container_width=True, hide_index=True)
                else:
                    st.info("Inga CC-möjligheter hittades.")

    elif strategy == "Protective Put":
        st.markdown("**Protective Put — Portfolio Insurance**")
        col1, col2, col3 = st.columns(3)
        with col1:
            p_shares = st.number_input("Antal aktier", min_value=1, value=100, step=100, key="pp_shares")
        with col2:
            protection = st.slider("Skyddsnivå", 0.80, 1.0, 0.95, 0.05, key="pp_protection")
        with col3:
            p_price = 0.0
            try:
                yf_ticker = yf.Ticker(ticker)
                info = yf_ticker.info or {}
                p_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0))
            except Exception:
                pass
            st.metric("Current Price", f"${p_price:.2f}" if p_price else "--")

        holding_pp = {"ticker": ticker, "shares": p_shares, "current_price": p_price}
        pp_analysis = ProtectivePutAnalysis.analyze(holding_pp, protection_level=protection)
        if "error" in pp_analysis:
            st.warning(pp_analysis["error"])
        elif pp_analysis.get("options"):
            st.dataframe(
                pd.DataFrame(pp_analysis["options"]),
                use_container_width=True,
                hide_index=True,
            )

    elif strategy in ("Bull Put Spread", "Bear Call Spread"):
        st.markdown(f"**{strategy} — Credit Spread**")
        exps = _cached_expirations(ticker)
        exp = st.selectbox("Expiration", options=exps if exps else ["N/A"], key=f"spread_exp_{strategy}")
        col1, col2 = st.columns(2)
        with col1:
            short_strike = st.number_input("Såld strike", min_value=0.0, value=0.0, step=0.5, format="%.1f", key=f"short_{strategy}")
        with col2:
            long_strike = st.number_input("Köpt strike", min_value=0.0, value=0.0, step=0.5, format="%.1f", key=f"long_{strategy}")

        if st.button("Analysera Spread", key=f"btn_{strategy}", use_container_width=True):
            if exp and exp != "N/A" and short_strike > 0 and long_strike > 0:
                if strategy == "Bull Put Spread":
                    result = BullPutSpread.analyze(ticker, exp, short_strike, long_strike)
                else:
                    result = BearCallSpread.analyze(ticker, exp, short_strike, long_strike)

                if "error" in result:
                    st.warning(result["error"])
                else:
                    cols = st.columns(4)
                    cols[0].metric("Max Profit", f"${result.get('max_profit', 0):.2f}")
                    cols[1].metric("Max Loss", f"${result.get('max_loss', 0):.2f}")
                    cols[2].metric("Risk/Reward", f"{result.get('risk_reward', 0):.2f}")
                    cols[3].metric("Prob. of Profit", f"{result.get('probability_of_profit', 0):.1f}%")
                    st.metric("Breakeven", f"${result.get('breakeven', 0):.2f}")
            else:
                st.warning("Vänligen välj expiration och strikes.")


def page_options_dashboard():
    """Huvudsidan för Options Dashboard."""
    st.title("📊 Options & Derivatives")
    st.caption("Analysera optioner, volatilitet, earnings plays och strategier.")

    ticker = _get_ticker_input()
    if not ticker:
        st.info(
            "Ange en ticker ovan för att börja analysera optioner.\n\n"
            "Exempel: AAPL, TSLA, SPY, NVDA, AMZN"
        )
        return

    # Tabs för olika vyer
    tab_chain, tab_vol, tab_maxpain, tab_flow, tab_earnings, tab_strategy = st.tabs([
        "📋 Options Chain",
        "📈 Volatilitet",
        "🎯 Max Pain",
        "🔀 Options Flow",
        "💰 Earnings",
        "🏗️ Strategier",
    ])

    # Ladda data (görs en gång)
    chain = _cached_chain(ticker)
    exps = _cached_expirations(ticker)

    # Visning av varje tab
    with tab_chain:
        if exps:
            selected_exp = st.selectbox(
                "Välj expiration",
                options=exps,
                key="chain_exp",
            )
            chain = _cached_chain(ticker, selected_exp)
            _render_chain_table(chain, ticker)
        else:
            st.warning(f"Inga optioner tillgängliga för {ticker}.")

    with tab_vol:
        _render_volatility_analysis(ticker)

    with tab_maxpain:
        _render_max_pain_analysis(ticker)

    with tab_flow:
        _render_options_flow(ticker)

    with tab_earnings:
        _render_earnings_analyzer(ticker)

    with tab_strategy:
        _render_strategy_builder(ticker)
