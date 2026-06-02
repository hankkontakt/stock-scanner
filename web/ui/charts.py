"""
charts.py -- Interactive Plotly chart library for MarketScan.

All charts use a dark theme template and are designed for Streamlit integration.
Provides reusable chart functions that accept data and return Plotly figures.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.figure_factory as ff
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# ══════════════════════════════════════════════════════════════════════════════
# DARK THEME TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════

DARK_TEMPLATE = go.layout.Template(
    layout=dict(
        font=dict(family="Inter, sans-serif", size=12, color="#e8eaf0"),
        paper_bgcolor="#0f1118",
        plot_bgcolor="#1a1f2e",
        colorway=["#4c9be8", "#4caf50", "#ffc107", "#ef5350", "#ab47bc", "#26c281", "#ff7043", "#42a5f5"],
        hovermode="closest",
        hoverlabel=dict(
            bgcolor="#1e2230",
            bordercolor="#2d3250",
            font=dict(color="#e8eaf0", size=12),
        ),
        xaxis=dict(
            gridcolor="#252b3b",
            zerolinecolor="#2d3250",
            tickfont=dict(color="#8892a4"),
            title_font=dict(color="#8892a4"),
        ),
        yaxis=dict(
            gridcolor="#252b3b",
            zerolinecolor="#2d3250",
            tickfont=dict(color="#8892a4"),
            title_font=dict(color="#8892a4"),
        ),
        legend=dict(
            font=dict(color="#e8eaf0", size=11),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="#2d3250",
        ),
        margin=dict(l=40, r=20, t=40, b=40),
    ),
)

# Register template so it can be referenced by name
import plotly.io as pio
pio.templates["marketscan_dark"] = DARK_TEMPLATE


def _dark_fig(fig: go.Figure, height: int = 400) -> go.Figure:
    """Apply the dark template and consistent layout to any figure."""
    fig.update_layout(template="marketscan_dark", height=height)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# A. CANDLESTICK CHART — with MA overlays, Bollinger Bands, Volume, RSI, MACD
# ══════════════════════════════════════════════════════════════════════════════

def candlestick_chart(
    df: pd.DataFrame,
    ticker: str = "",
    ma_periods: list[int] | None = None,
    bollinger: bool = True,
) -> go.Figure:
    """Interactive candlestick chart with technical indicators.

    Expects df with columns: Date (index or column), Open, High, Low, Close, Volume.
    Returns a Plotly figure with:
    - Candlestick OHLC
    - MA lines (default 20, 50, 200)
    - Bollinger Bands (20,2)
    - Volume bars
    - RSI subplot
    - MACD subplot
    - Range slider for zoom
    """
    if df is None or df.empty:
        return _empty_chart("No price data available")

    ma_periods = ma_periods or [20, 50, 200]
    _df = df.copy()

    # Ensure Date is the index
    if "Date" in _df.columns:
        _df = _df.set_index("Date")

    # Ensure index is datetime
    if not isinstance(_df.index, pd.DatetimeIndex):
        try:
            _df.index = pd.to_datetime(_df.index)
        except Exception:
            pass

    # Calculate MAs
    for p in ma_periods:
        if "Close" in _df.columns:
            _df[f"MA{p}"] = _df["Close"].rolling(window=p).mean()

    # Bollinger Bands (20,2)
    if bollinger and "Close" in _df.columns:
        _df["BB_MA"] = _df["Close"].rolling(window=20).mean()
        _df["BB_STD"] = _df["Close"].rolling(window=20).std()
        _df["BB_UPPER"] = _df["BB_MA"] + 2 * _df["BB_STD"]
        _df["BB_LOWER"] = _df["BB_MA"] - 2 * _df["BB_STD"]

    # RSI (14)
    if "Close" in _df.columns:
        delta = _df["Close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        _df["RSI"] = 100 - (100 / (1 + rs))

    # MACD (12,26,9)
    if "Close" in _df.columns:
        ema12 = _df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = _df["Close"].ewm(span=26, adjust=False).mean()
        _df["MACD"] = ema12 - ema26
        _df["MACD_SIGNAL"] = _df["MACD"].ewm(span=9, adjust=False).mean()
        _df["MACD_HIST"] = _df["MACD"] - _df["MACD_SIGNAL"]

    # Build subplots: 4 rows
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.45, 0.15, 0.20, 0.20],
        subplot_titles=(f"{ticker} — Price", "Volume", "RSI", "MACD") if ticker else ("Price", "Volume", "RSI", "MACD"),
    )

    # Row 1: Candlestick + MAs + Bollinger
    has_candle = all(c in _df.columns for c in ["Open", "High", "Low", "Close"])
    if has_candle:
        fig.add_trace(
            go.Candlestick(
                x=_df.index,
                open=_df["Open"], high=_df["High"],
                low=_df["Low"], close=_df["Close"],
                name="OHLC",
                showlegend=False,
                increasing_line_color="#26c281",
                decreasing_line_color="#ef5350",
            ),
            row=1, col=1,
        )

    # MA lines
    ma_colors = {20: "#f5a623", 50: "#4c9be8", 200: "#ab47bc"}
    for p in ma_periods:
        col = f"MA{p}"
        if col in _df.columns:
            fig.add_trace(
                go.Scatter(
                    x=_df.index, y=_df[col],
                    name=f"MA{p}",
                    line=dict(color=ma_colors.get(p, "#8892a4"), width=1.5),
                    showlegend=True,
                ),
                row=1, col=1,
            )

    # Bollinger Bands
    if bollinger and "BB_UPPER" in _df.columns:
        fig.add_trace(
            go.Scatter(
                x=_df.index, y=_df["BB_UPPER"],
                name="BB Upper",
                line=dict(color="#8892a4", width=1, dash="dash"),
                showlegend=True,
            ),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=_df.index, y=_df["BB_LOWER"],
                name="BB Lower",
                line=dict(color="#8892a4", width=1, dash="dash"),
                fill="tonexty",
                fillcolor="rgba(136,146,164,0.08)",
                showlegend=True,
            ),
            row=1, col=1,
        )

    # Row 2: Volume
    if "Volume" in _df.columns:
        vol_colors = ["#26c281" if r >= 0 else "#ef5350"
                      for r in (_df["Close"].diff() if has_candle else pd.Series(0, index=_df.index))]
        fig.add_trace(
            go.Bar(
                x=_df.index, y=_df["Volume"],
                name="Volume",
                marker_color=vol_colors,
                showlegend=False,
                opacity=0.6,
            ),
            row=2, col=1,
        )

    # Row 3: RSI
    if "RSI" in _df.columns:
        fig.add_trace(
            go.Scatter(
                x=_df.index, y=_df["RSI"],
                name="RSI",
                line=dict(color="#ab47bc", width=1.5),
                showlegend=False,
            ),
            row=3, col=1,
        )
        # RSI reference lines
        fig.add_hline(y=70, line_dash="dash", line_color="#ef5350", opacity=0.4, row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#26c281", opacity=0.4, row=3, col=1)
        fig.add_hline(y=50, line_dash="dot", line_color="#8892a4", opacity=0.3, row=3, col=1)
        fig.update_yaxes(range=[0, 100], row=3, col=1)

    # Row 4: MACD
    if "MACD" in _df.columns:
        macd_colors = ["#26c281" if v >= 0 else "#ef5350" for v in _df["MACD_HIST"].fillna(0)]
        fig.add_trace(
            go.Bar(
                x=_df.index, y=_df["MACD_HIST"],
                name="MACD Hist",
                marker_color=macd_colors,
                showlegend=False,
                opacity=0.5,
            ),
            row=4, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=_df.index, y=_df["MACD"],
                name="MACD",
                line=dict(color="#4c9be8", width=1.5),
                showlegend=False,
            ),
            row=4, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=_df.index, y=_df["MACD_SIGNAL"],
                name="Signal",
                line=dict(color="#f5a623", width=1),
                showlegend=False,
            ),
            row=4, col=1,
        )
        fig.add_hline(y=0, line_dash="dot", line_color="#8892a4", opacity=0.3, row=4, col=1)

    # Rangeslider for zoom
    fig.update_xaxes(rangeslider=dict(visible=False), row=1, col=1)

    # Add range slider to bottom subplot
    fig.update_xaxes(
        rangeslider=dict(
            visible=True,
            thickness=0.08,
            bgcolor="#1a1f2e",
            bordercolor="#2d3250",
        ),
        row=4, col=1,
    )

    fig.update_layout(
        template="marketscan_dark",
        height=700,
        hovermode="x unified",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
        ),
        margin=dict(l=40, r=20, t=60, b=40),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# B. EQUITY CURVE CHART — with drawdown, Sharpe, benchmark comparison
# ══════════════════════════════════════════════════════════════════════════════

def equity_curve_chart(
    equity_df: pd.DataFrame,
    benchmark_df: pd.DataFrame | None = None,
) -> go.Figure:
    """Equity curve with drawdown and Sharpe ratio annotation.

    Args:
        equity_df: DataFrame with Date index and 'Equity' column (cumulative returns).
        benchmark_df: Optional DataFrame with Date index and 'Equity' column for benchmark (SPY/OMX).
    """
    if equity_df is None or equity_df.empty:
        return _empty_chart("No equity data available")

    _eq = equity_df.copy()
    if "Date" in _eq.columns:
        _eq = _eq.set_index("Date")

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.70, 0.30],
        subplot_titles=("Equity Curve", "Drawdown"),
    )

    # Normalize to 100
    eq_col = "Equity" if "Equity" in _eq.columns else _eq.columns[0]
    first_val = _eq[eq_col].iloc[0] if not _eq.empty else 1
    normalized = _eq[eq_col] / first_val * 100

    fig.add_trace(
        go.Scatter(
            x=_eq.index, y=normalized,
            name="Strategy",
            line=dict(color="#4c9be8", width=2),
            fill="tozeroy",
            fillcolor="rgba(76,155,232,0.08)",
        ),
        row=1, col=1,
    )

    # Benchmark overlay
    if benchmark_df is not None and not benchmark_df.empty:
        _bm = benchmark_df.copy()
        if "Date" in _bm.columns:
            _bm = _bm.set_index("Date")
        bm_col = "Equity" if "Equity" in _bm.columns else _bm.columns[0]
        bm_first = _bm[bm_col].iloc[0] if not _bm.empty else 1
        bm_normalized = _bm[bm_col] / bm_first * 100
        fig.add_trace(
            go.Scatter(
                x=_bm.index, y=bm_normalized,
                name="Benchmark",
                line=dict(color="#8892a4", width=1.5, dash="dash"),
            ),
            row=1, col=1,
        )

    # Drawdown
    running_max = normalized.cummax()
    drawdown = (normalized - running_max) / running_max * 100
    fig.add_trace(
        go.Scatter(
            x=_eq.index, y=drawdown,
            name="Drawdown",
            line=dict(color="#ef5350", width=1),
            fill="tozeroy",
            fillcolor="rgba(239,83,80,0.10)",
        ),
        row=2, col=1,
    )
    fig.update_yaxes(title_text="Drawdown %", row=2, col=1, zerolinecolor="#2d3250")
    fig.add_hline(y=0, line_dash="dot", line_color="#8892a4", opacity=0.3, row=2, col=1)

    # Sharpe ratio annotation
    returns = _eq[eq_col].pct_change().dropna()
    if len(returns) > 0:
        sharpe = np.sqrt(252) * returns.mean() / returns.std() if returns.std() > 0 else 0
        fig.add_annotation(
            xref="paper", yref="paper",
            x=0.02, y=0.95,
            text=f"Sharpe: {sharpe:.2f}",
            showarrow=False,
            font=dict(size=14, color="#e8eaf0"),
            bgcolor="#1e2230",
            bordercolor="#2d3250",
            borderwidth=1,
            borderpad=6,
        )

    fig.update_layout(
        template="marketscan_dark",
        height=450,
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=50, b=30),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# C. FACTOR RADAR CHART — multi-overlay radar
# ══════════════════════════════════════════════════════════════════════════════

def factor_radar_chart(
    scores_dict: dict[str, dict[str, float]],
    sector_avg: dict[str, float] | None = None,
) -> go.Figure:
    """Interactive radar chart showing factor scores.

    Args:
        scores_dict: {"Current": {"Value": 75, "Quality": 60, ...}, "Last Month": {...}}
        sector_avg: Optional dict with sector average scores for reference overlay.
    """
    if not scores_dict:
        return _empty_chart("No score data available")

    # Extract categories from the first entry
    first_key = list(scores_dict.keys())[0]
    categories = list(scores_dict[first_key].keys())

    fig = go.Figure()

    colors = ["#4c9be8", "#f5a623", "#ab47bc", "#26c281"]
    for i, (label, scores) in enumerate(scores_dict.items()):
        values = [scores.get(c, 0) for c in categories]
        fig.add_trace(go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            name=label,
            fill="toself",
            fillcolor=f"rgba{_hex_to_rgb(colors[i % len(colors)], 0.20)}",
            line_color=colors[i % len(colors)],
            hovertemplate="%{theta}: %{r:.0f}<extra>" + label + "</extra>",
        ))

    # Sector average overlay
    if sector_avg:
        sector_values = [sector_avg.get(c, 0) for c in categories]
        fig.add_trace(go.Scatterpolar(
            r=sector_values + [sector_values[0]],
            theta=categories + [categories[0]],
            name="Sector Avg",
            fill="toself",
            fillcolor="rgba(136,146,164,0.10)",
            line=dict(color="#8892a4", width=1, dash="dot"),
            hovertemplate="%{theta}: %{r:.0f}<extra>Sector Avg</extra>",
        ))

    fig.update_layout(
        template="marketscan_dark",
        height=400,
        polar=dict(
            bgcolor="#1a1f2e",
            radialaxis=dict(
                range=[0, 100],
                color="#8892a4",
                tickfont=dict(size=10),
            ),
            angularaxis=dict(
                color="#e8eaf0",
                tickfont=dict(size=11),
            ),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.08, xanchor="center", x=0.5),
        margin=dict(l=60, r=60, t=30, b=30),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# D. CORRELATION HEATMAP — with hierarchical clustering
# ══════════════════════════════════════════════════════════════════════════════

def correlation_heatmap(returns_df: pd.DataFrame) -> go.Figure:
    """Correlation heatmap with hierarchical clustering (dendrogram).

    Args:
        returns_df: DataFrame where columns are tickers, rows are returns.
    """
    if returns_df is None or returns_df.empty or returns_df.shape[1] < 2:
        return _empty_chart("Need at least 2 tickers for correlation")

    corr = returns_df.corr()

    # Try to create dendrogram-ordered heatmap
    try:
        from scipy.cluster.hierarchy import linkage, leaves_list
        from scipy.spatial.distance import squareform

        # Convert correlation to distance
        dist = 1 - corr.abs()
        dist_array = squareform(dist)
        link = linkage(dist_array, method="average")
        order = leaves_list(link)

        ordered_tickers = [corr.index[i] for i in order]
        corr = corr.reindex(index=ordered_tickers, columns=ordered_tickers)
    except ImportError:
        pass  # scipy not available, use default order

    fig = ff.create_annotated_heatmap(
        z=corr.values,
        x=list(corr.columns),
        y=list(corr.index),
        annotation_text=[[f"{v:.2f}" for v in row] for row in corr.values],
        colorscale=[
            [0.0, "#ef5350"],
            [0.25, "#f5a623"],
            [0.5, "#1e2230"],
            [0.75, "#26c281"],
            [1.0, "#4caf50"],
        ],
        font_colors=["#e8eaf0", "#e8eaf0"],
        hoverinfo="z",
        showscale=True,
        zmin=-1, zmax=1,
    )

    fig.update_layout(
        template="marketscan_dark",
        height=max(400, len(corr.columns) * 35),
        xaxis=dict(tickangle=-45, side="bottom"),
        yaxis=dict(tickangle=0),
        margin=dict(l=80, r=40, t=30, b=100),
    )

    # Remove default annotation text and use our custom ones
    for i in range(len(fig.layout.annotations)):
        fig.layout.annotations[i].font.size = 9

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# E. RETURNS DISTRIBUTION — with normal overlay, VaR lines
# ══════════════════════════════════════════════════════════════════════════════

def returns_distribution(returns_series: pd.Series) -> go.Figure:
    """Returns distribution histogram with normal overlay and VaR lines.

    Args:
        returns_series: Series of daily (or periodic) returns.
    """
    if returns_series is None or returns_series.empty:
        return _empty_chart("No return data available")

    returns = returns_series.dropna()
    if len(returns) < 5:
        return _empty_chart("Not enough return data points")

    mean = returns.mean()
    std = returns.std()
    skew = returns.skew()
    kurt = returns.kurtosis()

    # VaR calculations
    var_95 = returns.quantile(0.05)
    var_99 = returns.quantile(0.01)

    fig = go.Figure()

    # Histogram
    fig.add_trace(go.Histogram(
        x=returns,
        nbinsx=50,
        name="Returns",
        marker_color="#4c9be8",
        opacity=0.7,
        hovertemplate="Return: %{x:.2%}<br>Count: %{y}<extra></extra>",
    ))

    # Normal distribution overlay
    x_range = np.linspace(returns.min(), returns.max(), 200)
    normal_vals = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_range - mean) / std) ** 2)
    # Scale to match histogram area
    hist_area = len(returns) * (returns.max() - returns.min()) / 50
    fig.add_trace(go.Scatter(
        x=x_range,
        y=normal_vals * hist_area,
        name="Normal Dist",
        line=dict(color="#f5a623", width=2, dash="dash"),
        hovertemplate="x: %{x:.2%}<br>Density: %{y:.2f}<extra></extra>",
    ))

    # VaR lines
    fig.add_vline(
        x=var_95,
        line_dash="dash",
        line_color="#ef5350",
        annotation_text=f"VaR 95%: {var_95:.1%}",
        annotation_font_color="#ef5350",
        annotation_font_size=11,
        annotation_position="top",
    )
    fig.add_vline(
        x=var_99,
        line_dash="dash",
        line_color="#ff1744",
        annotation_text=f"VaR 99%: {var_99:.1%}",
        annotation_font_color="#ff1744",
        annotation_font_size=11,
        annotation_position="top left",
    )

    # Skewness/Kurtosis annotation
    fig.add_annotation(
        xref="paper", yref="paper",
        x=0.98, y=0.95,
        text=f"Skew: {skew:.2f}<br>Kurt: {kurt:.2f}",
        showarrow=False,
        font=dict(size=12, color="#e8eaf0"),
        bgcolor="#1e2230",
        bordercolor="#2d3250",
        borderwidth=1,
        borderpad=6,
        align="left",
    )

    fig.update_layout(
        template="marketscan_dark",
        height=400,
        bargap=0.05,
        xaxis_title="Return",
        yaxis_title="Frequency",
        hovermode="x",
        margin=dict(l=40, r=20, t=30, b=40),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# F. SECTOR HEATMAP — sector rotation map
# ══════════════════════════════════════════════════════════════════════════════

def sector_heatmap(sector_returns_df: pd.DataFrame) -> go.Figure:
    """Sector rotation heatmap.

    Args:
        sector_returns_df: DataFrame indexed by period, columns are sectors,
                          values are returns (%).
    """
    if sector_returns_df is None or sector_returns_df.empty:
        return _empty_chart("No sector return data available")

    fig = ff.create_annotated_heatmap(
        z=sector_returns_df.values,
        x=list(sector_returns_df.columns),
        y=list(sector_returns_df.index),
        annotation_text=[[f"{v:.1f}%" for v in row] for row in sector_returns_df.values],
        colorscale=[
            [0.0, "#ef5350"],
            [0.25, "#f5a623"],
            [0.5, "#1a1f2e"],
            [0.75, "#26c281"],
            [1.0, "#4caf50"],
        ],
        font_colors=["#e8eaf0", "#e8eaf0"],
        hoverinfo="z",
        showscale=True,
        zmid=0,
    )

    fig.update_layout(
        template="marketscan_dark",
        height=max(300, len(sector_returns_df) * 40),
        xaxis=dict(tickangle=-45),
        yaxis=dict(tickangle=0),
        margin=dict(l=80, r=40, t=30, b=80),
    )

    for i in range(len(fig.layout.annotations)):
        fig.layout.annotations[i].font.size = 10

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# G. SCATTER PLOT — general purpose
# ══════════════════════════════════════════════════════════════════════════════

def scatter_plotly(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: str | None = None,
    size_col: str | None = None,
    hover_cols: list[str] | None = None,
    title: str = "",
) -> go.Figure:
    """General purpose scatter plot.

    Args:
        df: DataFrame with data.
        x_col: Column name for x-axis.
        y_col: Column name for y-axis.
        color_col: Column name for color encoding.
        size_col: Column name for point sizing.
        hover_cols: Additional columns to show on hover.
        title: Chart title.
    """
    if df is None or df.empty or x_col not in df.columns or y_col not in df.columns:
        return _empty_chart("Insufficient data for scatter plot")

    hover_data = hover_cols or []
    if color_col and color_col not in hover_data:
        hover_data.append(color_col)

    fig = px.scatter(
        df,
        x=x_col,
        y=y_col,
        color=color_col,
        size=size_col,
        hover_data=hover_data,
        title=title,
        template="marketscan_dark",
        color_continuous_scale=["#ef5350", "#f5a623", "#4c9be8", "#26c281", "#4caf50"],
    )

    fig.update_traces(
        marker=dict(
            line=dict(width=0.5, color="#2d3250"),
            opacity=0.8,
        ),
        hovertemplate="<br>".join([
            f"{x_col}: %{{x}}",
            f"{y_col}: %{{y}}",
        ] + [f"{c}: %{{customdata[{i}]}}" for i, c in enumerate(hover_data) if c not in (x_col, y_col, color_col)]) + "<extra></extra>",
    )

    fig.update_layout(
        height=450,
        hovermode="closest",
        margin=dict(l=40, r=20, t=50, b=40),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# H. CONVICTION METER — radar with factor breakdown
# ══════════════════════════════════════════════════════════════════════════════

def conviction_meter(row: pd.Series) -> go.Figure:
    """Conviction meter radar chart from a single stock row.

    Extracts score_* columns and renders them as a polar area chart.
    """
    score_cols = {
        "score_value": "Value",
        "score_quality": "Quality",
        "score_momentum": "Momentum",
        "score_growth": "Growth",
        "score_risk": "Risk",
        "score_size": "Size",
    }

    categories = []
    values = []
    for col_key, label in score_cols.items():
        if col_key in row.index and pd.notna(row[col_key]):
            categories.append(label)
            values.append(float(row[col_key]))

    if not categories:
        return _empty_chart("No score factors available")

    fig = go.Figure()

    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(76,155,232,0.25)",
        line_color="#4c9be8",
        name="Score",
        hovertemplate="%{theta}: %{r:.0f}/100<extra></extra>",
    ))

    fig.update_layout(
        template="marketscan_dark",
        height=380,
        polar=dict(
            bgcolor="#1a1f2e",
            radialaxis=dict(range=[0, 100], color="#8892a4", tickfont=dict(size=9)),
            angularaxis=dict(color="#e8eaf0", tickfont=dict(size=11)),
        ),
        margin=dict(t=20, b=20, l=40, r=40),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _empty_chart(message: str = "No data") -> go.Figure:
    """Return an empty chart with a centered message."""
    fig = go.Figure()
    fig.add_annotation(
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        text=message,
        showarrow=False,
        font=dict(size=16, color="#8892a4"),
    )
    fig.update_layout(
        template="marketscan_dark",
        height=300,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


def _hex_to_rgb(hex_color: str, alpha: float = 1.0) -> str:
    """Convert hex color to rgba string."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"{r},{g},{b},{alpha}"
