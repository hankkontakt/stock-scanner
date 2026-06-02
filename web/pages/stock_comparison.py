"""
stock_comparison.py -- Compare 2-5 stocks side-by-side.

Features:
- Side-by-side: scores, key metrics, charts
- Comparison table with color coding (green = best in group)
- Overlay chart: price performance normalized to 100
- Correlation matrix for selected tickers
- AI comparison: ensemble analysis
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from web.ui.charts import (
    _dark_fig, candlestick_chart, correlation_heatmap,
)
from web.ui.components import metric_card, panel
from web.ui.icons import ic


def page_stock_comparison(df: pd.DataFrame | None = None):
    """Main entry point for the stock comparison page."""
    st.title(f"{ic('stock')} Stock Comparison")
    st.caption("Compare 2-5 stocks side-by-side with metrics, charts, and AI analysis.")

    # Get available tickers
    available_tickers = []
    if df is not None and not df.empty and "ticker" in df.columns:
        available_tickers = sorted(df["ticker"].dropna().unique().tolist())

    # Ticker selection
    col1, col2 = st.columns([3, 1])
    with col1:
        tickers = st.multiselect(
            "Select 2-5 tickers to compare",
            options=available_tickers if available_tickers else [],
            max_selections=5,
            placeholder="Search and select tickers...",
            key="compare_tickers",
        )
    with col2:
        manual_ticker = st.text_input("Or add manually", placeholder="AAPL", key="compare_manual")

    if manual_ticker:
        ticker_upper = manual_ticker.strip().upper()
        if ticker_upper and ticker_upper not in tickers:
            tickers = tickers + [ticker_upper]

    if len(tickers) < 2:
        st.info("Select at least 2 tickers to start comparison.")
        return

    # Limit to 5
    tickers = tickers[:5]

    # Fetch data for all selected tickers
    with st.spinner("Loading data for comparison..."):
        comparison_data = _fetch_comparison_data(tickers, df)

    if not comparison_data:
        st.error("Could not load data for selected tickers.")
        return

    # ── Section 1: Overview KPIs ─────────────────────────────────────────────
    st.markdown(f"### {ic('analytics')} Key Metrics Overview")
    _render_kpi_comparison(comparison_data)

    # ── Section 2: Comparison Table ──────────────────────────────────────────
    st.markdown(f"### {ic('list')} Detailed Comparison")
    comp_table = _build_comparison_table(comparison_data)
    st.dataframe(comp_table, use_container_width=True, hide_index=True)

    # ── Section 3: Price Overlay Chart ───────────────────────────────────────
    st.markdown(f"### {ic('chart')} Price Performance (Normalized to 100)")

    period = st.selectbox(
        "Select period",
        ["1mo", "3mo", "6mo", "1y", "2y", "5y", "max"],
        index=2,
        key="compare_period",
    )

    price_fig = _price_overlay_chart(tickers, period)
    if price_fig:
        st.plotly_chart(price_fig, use_container_width=True)
    else:
        st.info("Price data not available for overlay chart.")

    # ── Section 4: Correlation Matrix ────────────────────────────────────────
    st.markdown(f"### {ic('sector')} Correlation Matrix")
    returns_fig = _correlation_view(tickers, period)
    if returns_fig:
        st.plotly_chart(returns_fig, use_container_width=True)

    # ── Section 5: Individual Detail Tabs ─────────────────────────────────────
    if len(tickers) <= 3:
        st.markdown(f"### {ic('technical')} Individual Price Charts")
        tabs = st.tabs(tickers)
        for i, ticker in enumerate(tickers):
            with tabs[i]:
                hist = _fetch_history(ticker, period)
                if hist is not None and not hist.empty:
                    fig = candlestick_chart(hist, ticker=ticker)
                    st.plotly_chart(fig, use_container_width=True)

    # ── Section 6: AI Comparison ─────────────────────────────────────────────
    st.markdown(f"### {ic('ai')} AI Comparison Analysis")
    st.caption("Get an ensemble analysis comparing the selected stocks.")

    if st.button("Compare These Stocks with AI", key="compare_ai_btn", type="primary"):
        _run_ai_comparison(tickers, comparison_data)


# ══════════════════════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_comparison_data(tickers: list[str], df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Fetch comparison data for all tickers."""
    result = {}

    for ticker in tickers:
        data = {}

        # Try to get data from the main dataframe first
        if df is not None and not df.empty and "ticker" in df.columns:
            row = df[df["ticker"] == ticker]
            if not row.empty:
                r = row.iloc[0]
                # Map common fields
                field_map = {
                    "name": "name", "sector": "sector", "current_price": "current_price",
                    "score_total": "score_total", "entry_signal": "entry_signal",
                    "trend_signal": "trend_signal", "pe_trailing": "P/E",
                    "pe_forward": "P/E Forward", "price_to_book": "P/B",
                    "roe": "ROE", "roa": "ROA", "profit_margin": "Profit Margin",
                    "revenue_growth": "Revenue Growth", "earnings_growth": "Earnings Growth",
                    "debt_to_equity": "D/E", "dividend_yield": "Dividend Yield",
                    "market_cap": "Market Cap", "rsi_14": "RSI",
                    "return_1m": "1m Return", "return_3m": "3m Return",
                    "return_6m": "6m Return", "return_12m": "12m Return",
                    "volatility": "Volatility", "beta": "Beta",
                    "price_vs_ma200": "vs MA200",
                }
                for csv_col, data_key in field_map.items():
                    if csv_col in r.index and pd.notna(r[csv_col]):
                        data[data_key] = r[csv_col]

        # Always try yfinance for price data
        hist = _fetch_history(ticker, "6mo")
        if hist is not None:
            data["_history"] = hist
            if "current_price" not in data and "Close" in hist.columns:
                data["current_price"] = hist["Close"].iloc[-1]

        result[ticker] = data

    return result


def _fetch_history(ticker: str, period: str = "6mo") -> pd.DataFrame | None:
    """Fetch historical price data from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist.empty:
            return None
        return hist
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# RENDERING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _render_kpi_comparison(data: dict) -> None:
    """Show key KPIs in a grid across all tickers."""
    cols = st.columns(len(data))

    for i, (ticker, d) in enumerate(data.items()):
        with cols[i]:
            name = d.get("name", ticker)
            price = d.get("current_price", None)
            score = d.get("score_total", None)
            pe = d.get("P/E", None)
            entry = d.get("entry_signal", "")

            st.markdown(
                f"<div style='text-align:center;padding:8px;'>"
                f"<div style='font-size:16px;font-weight:700;color:#e8eaf0;'>{ticker}</div>"
                f"<div style='font-size:11px;color:#8892a4;'>{name}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            if price is not None:
                st.metric("Price", f"${price:.2f}" if price < 1000 else f"${price:,.0f}")

            if score is not None:
                score_val = float(score)
                score_color = "#26c281" if score_val >= 70 else ("#f5a623" if score_val >= 50 else "#ef5350")
                st.markdown(
                    f"<div style='text-align:center;margin:8px 0;'>"
                    f"<div style='font-size:10px;color:#8892a4;'>Score</div>"
                    f"<div style='font-size:28px;font-weight:700;color:{score_color};'>{score_val:.0f}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            if pe is not None:
                st.metric("P/E", f"{pe:.1f}")


def _build_comparison_table(data: dict) -> pd.DataFrame:
    """Build a color-coded comparison table.

    Each row is a metric, each column is a ticker.
    Best value in each row is highlighted in green.
    """
    # Collect all metrics
    all_metrics = {}
    for ticker, d in data.items():
        for key, val in d.items():
            if key.startswith("_"):  # Skip internal keys
                continue
            if key not in all_metrics:
                all_metrics[key] = {}
            if isinstance(val, (int, float, np.generic)):
                all_metrics[key][ticker] = val

    rows = []
    for metric, values in all_metrics.items():
        row = {"Metric": metric}
        numeric_vals = {}
        for ticker in data:
            val = values.get(ticker, None)
            if val is not None and isinstance(val, (int, float, np.generic)):
                row[ticker] = val
                numeric_vals[ticker] = val
            else:
                row[ticker] = None

        # Determine best value for coloring
        # For ratios, lower is often better (P/E, D/E). For returns/quality, higher is better.
        higher_is_better = not any(k in metric.lower() for k in ["p/e", "d/e", "debt", "volatility", "beta", "pe"])
        if numeric_vals:
            if higher_is_better:
                best = max(numeric_vals.values())
            else:
                best = min(numeric_vals.values())
            row["_best"] = best
            row["_higher_better"] = higher_is_better
        else:
            row["_best"] = None

        rows.append(row)

    # Build display HTML
    display_rows = []
    for row in rows:
        display_row = {"Metric": row["Metric"]}
        for ticker in data:
            val = row.get(ticker)
            best = row.get("_best")
            higher = row.get("_higher_better", True)

            if val is None:
                display_row[ticker] = "--"
            else:
                is_best = (best is not None and abs(float(val) - float(best)) < 0.001)
                formatted = _fmt_val(val, row["Metric"])
                if is_best and len(data) > 1:
                    display_row[ticker] = f"✅ {formatted}"  # Best in group
                else:
                    display_row[ticker] = formatted
        display_rows.append(display_row)

    return pd.DataFrame(display_rows)


def _fmt_val(val: Any, metric: str = "") -> str:
    """Format a metric value for display."""
    if val is None:
        return "--"
    try:
        v = float(val)
    except (ValueError, TypeError):
        return str(val)

    # Percentage metrics
    pct_keys = ["roe", "roa", "return", "growth", "margin", "yield", "profit"]
    if any(k in metric.lower() for k in pct_keys):
        return f"{v:.1f}%"

    # Dollar metrics
    if "price" in metric.lower() or "market cap" in metric.lower():
        if abs(v) >= 1_000_000_000:
            return f"${v/1e9:.2f}B"
        elif abs(v) >= 1_000_000:
            return f"${v/1e6:.1f}M"
        elif abs(v) >= 1_000:
            return f"${v:,.0f}"
        return f"${v:.2f}"

    # Ratios
    if any(k in metric.lower() for k in ["p/e", "p/b", "pe", "d/e", "beta", "rsi"]):
        return f"{v:.2f}"

    return f"{v:.2f}"


def _price_overlay_chart(tickers: list[str], period: str = "6mo") -> go.Figure | None:
    """Create a price overlay chart with all tickers normalized to 100."""
    fig = go.Figure()
    colors = ["#4c9be8", "#26c281", "#f5a623", "#ab47bc", "#ef5350"]

    for i, ticker in enumerate(tickers):
        hist = _fetch_history(ticker, period)
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue

        close = hist["Close"]
        normalized = close / close.iloc[0] * 100

        fig.add_trace(go.Scatter(
            x=hist.index,
            y=normalized,
            name=ticker,
            line=dict(color=colors[i % len(colors)], width=2),
            hovertemplate=f"{ticker}: %{{y:.1f}}<extra></extra>",
        ))

    if not fig.data:
        return None

    fig.update_layout(
        template="marketscan_dark",
        height=450,
        hovermode="x unified",
        title="Price Performance (Normalized to 100)",
        xaxis_title="Date",
        yaxis_title="Normalized Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=50, b=40),
    )

    fig.add_hline(y=100, line_dash="dot", line_color="#8892a4", opacity=0.3)

    return fig


def _correlation_view(tickers: list[str], period: str = "6mo") -> go.Figure | None:
    """Build a correlation matrix from historical returns."""
    returns_dict = {}
    for ticker in tickers:
        hist = _fetch_history(ticker, period)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            returns = hist["Close"].pct_change().dropna()
            returns_dict[ticker] = returns

    if len(returns_dict) < 2:
        return None

    returns_df = pd.DataFrame(returns_dict)
    return correlation_heatmap(returns_df)


def _run_ai_comparison(tickers: list[str], data: dict) -> None:
    """Run AI ensemble analysis comparing the selected stocks."""
    placeholder = st.empty()
    with placeholder.container():
        st.info(f"🤖 Analyzing {', '.join(tickers)}... This feature is under development.")

    # Build a text summary for AI context
    summary_lines = [f"Stock Comparison: {', '.join(tickers)}", ""]
    for ticker, d in data.items():
        summary_lines.append(f"--- {ticker} ---")
        for key, val in d.items():
            if not key.startswith("_"):
                summary_lines.append(f"{key}: {val}")

    context = "\n".join(summary_lines)

    # Try to run AI analysis if available
    try:
        from core import ai_analysis
        depth = st.session_state.get("selected_depth", "Normal")

        with st.spinner("Running AI comparison analysis..."):
            result = ai_analysis.compare_stocks(
                tickers=tickers,
                context=context,
                depth=depth,
            )

        if result:
            placeholder.empty()
            with placeholder.container():
                st.markdown("### 🤖 AI Comparison Result")
                st.markdown(result)
        else:
            placeholder.empty()
            st.warning("AI comparison returned no result. The system may need API keys configured.")
    except ImportError:
        placeholder.empty()
        st.warning("AI analysis module not available. Please configure AI providers.")
    except AttributeError:
        placeholder.empty()
        st.info("AI comparison function not yet implemented in the analysis module.")
    except Exception as e:
        placeholder.empty()
        st.warning(f"AI comparison failed: {e}")
