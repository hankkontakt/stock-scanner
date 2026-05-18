"""
web/utils.py
============
Delade hjälpfunktioner och dataladdning för MarketScan-appen.
Importeras av alla page-moduler via: from web.utils import *
"""

import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

# ── Sökvägar ────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
DATA_DIR   = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf
from core import config


# ══════════════════════════════════════════════════════════════════════════════
# DATALADDNING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_scan_reports() -> dict:
    """Returnerar {datum_str: DataFrame} för alla vecko-scan CSVer."""
    _OPTIONAL_COLS = [
        "score_value", "score_quality", "score_momentum", "score_growth",
        "score_risk", "score_size", "score_dividend", "score_sentiment",
        "entry_signal", "trend_signal", "confidence_label",
        "price", "close", "change_pct", "volume",
        "rsi_14", "price_vs_ma50", "price_vs_ma200",
        "return_1m", "return_3m", "return_6m", "return_12m",
        "pe_trailing", "pe_forward", "price_to_book",
        "roe", "roa", "profit_margin", "gross_margin",
        "revenue_growth", "earnings_growth",
        "debt_to_equity", "current_ratio", "dividend_yield",
        "free_cash_flow", "piotroski_f",
        "beta", "volatility", "pct_from_52w_high",
        "score_delta", "delta_flag", "sector",
        "name", "industry", "country",
    ]
    result = {}
    for f in sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True):
        try:
            d  = f.stem.replace("scored_universe_", "")
            df = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
            for col in _OPTIONAL_COLS:
                if col not in df.columns:
                    df[col] = np.nan
            result[d] = df
        except Exception:
            pass
    return result


@st.cache_data(ttl=300)
def load_smallcap_reports() -> dict:
    """Returnerar {datum_str: DataFrame} för alla smallcap CSVer."""
    result = {}
    for f in sorted(REPORT_DIR.glob("smallcap_scored_*.csv"), reverse=True):
        try:
            d   = f.stem.replace("smallcap_scored_", "")
            df  = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
            result[d] = df
        except Exception:
            pass
    return result


@st.cache_data(ttl=300)
def _load_nth_latest_scored(n: int = 2) -> pd.DataFrame:
    """Laddar den N:e senaste scored_universe-filen (n=1 = senast, n=2 = igår)."""
    files = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
    if len(files) < n:
        return pd.DataFrame()
    try:
        df = pd.read_csv(files[n - 1], low_memory=False)
        df.columns = df.columns.str.strip()
        return df
    except Exception:
        return pd.DataFrame()


def load_portfolio() -> pd.DataFrame:
    """Laddar holdings.csv och berikar med senaste scan-data.
    Ingen cache – filen ändras när användaren lägger till tickers."""
    try:
        holdings = pd.read_csv(DATA_DIR / "holdings.csv")
        holdings["ticker"] = holdings["ticker"].str.upper()
        return holdings
    except Exception:
        return pd.DataFrame(columns=["ticker", "shares", "cost_basis"])


def load_watchlist() -> list:
    """Laddar watchlist.json. Ingen cache – filen ändras när användaren lägger till tickers."""
    wl_path = DATA_DIR / "watchlist.json"
    try:
        return json.loads(wl_path.read_text(encoding="utf-8"))
    except Exception:
        return []


@st.cache_data(ttl=300)
def load_history_snapshots() -> dict:
    result = {}
    for f in sorted((DATA_DIR / "history").glob("snapshot_*.csv"), reverse=True)[:10]:
        try:
            d  = f.stem.replace("snapshot_", "")
            df = pd.read_csv(f, low_memory=False)
            result[d] = df
        except Exception:
            pass
    return result


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _get(df: pd.DataFrame, col: str, default=None) -> pd.Series:
    return df[col] if col in df.columns else pd.Series([default] * len(df))


def score_color(val) -> str:
    try:
        v = float(val)
        if v >= 75: return "#00c853"
        if v >= 60: return "#69f0ae"
        if v >= 45: return "#ffd600"
        if v >= 30: return "#ff6d00"
        return "#d50000"
    except Exception:
        return "#78909c"


def signal_tag(sig: str) -> str:
    sig = str(sig).upper().strip()
    m = {
        "STARK": ("green", "🟢 STARK"),
        "OK":    ("blue",  "🔵 OK"),
        "VÄNTA": ("yellow","🟡 VÄNTA"),
        "EJ AKTUELL": ("red", "🔴 EJ"),
        "BUY":   ("green", "🟢 KÖP"),
        "SELL":  ("red",   "🔴 SÄLJ"),
        "NEUTRAL": ("grey","⚪ NEUTRAL"),
    }
    cls, label = m.get(sig, ("grey", sig))
    return f'<span class="tag-{cls}">{label}</span>'


def pct_fmt(v, plus=True) -> str:
    try:
        v = float(v)
        s = f"{v*100:+.1f}%" if plus else f"{v*100:.1f}%"
        return s
    except Exception:
        return "—"


def num_fmt(v, decimals=1) -> str:
    try:
        return f"{float(v):.{decimals}f}"
    except Exception:
        return "—"


def score_bar_col(col_name: str):
    """Returnerar ColumnConfig för ett score-fält med progress-bar."""
    return st.column_config.ProgressColumn(
        col_name, min_value=0, max_value=100, format="%.0f"
    )


def _sector_options(df: pd.DataFrame) -> list:
    if "sector" not in df.columns:
        return ["Alla"]
    secs = sorted(df["sector"].dropna().unique().tolist())
    return ["Alla"] + secs


def _stars_options() -> list:
    return ["Alla", "★★★★★", "★★★★", "★★★", "★★", "★"]


def _entry_options(df: pd.DataFrame) -> list:
    if "entry_signal" not in df.columns:
        return ["Alla"]
    opts = sorted(df["entry_signal"].dropna().unique().tolist())
    return ["Alla"] + opts


FX_PAIRS = {
    "EUR/SEK": "EURSEK=X",
    "USD/SEK": "USDSEK=X",
    "NOK/SEK": "NOKSEK=X",
    "GBP/SEK": "GBPSEK=X",
    "DKK/SEK": "DKKSEK=X",
}

RATE_TICKERS = {
    "🇺🇸 US 10Y (Fed proxy)":      "^TNX",
    "🇩🇪 Tysk 10Y (ECB proxy)":    "DE10Y.DE",
    "🇸🇪 Svensk 10Y (Riksbanken)": "SE10Y.ST",
    "🇬🇧 UK 10Y (BOE proxy)":      "UK10Y.L",
    "🇳🇴 Norsk 10Y":               "NO10Y.OL",
}


@st.cache_data(ttl=300)
def fetch_fx_rows() -> list:
    """Hämtar FX-rader (1 anrop per par, rate-limited). Cachas 5 min."""
    import time as _t
    rows = []
    for name, ticker in FX_PAIRS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            if not hist.empty and len(hist) >= 2:
                curr = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                chg = ((curr / prev) - 1) * 100 if prev else 0.0
                arrow = "🟢" if chg >= 0 else "🔴"
                rows.append({"Par": name, "Kurs": f"{curr:.4f}",
                             "Förändring": f"{arrow} {chg:+.2f}%"})
        except Exception:
            pass
        _t.sleep(0.3)
    return rows


@st.cache_data(ttl=300)
def fetch_rate_rows() -> list:
    """Hämtar ränte-rader (1 anrop per land, rate-limited). Cachas 5 min."""
    import time as _t
    rows = []
    for name, ticker in RATE_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            if not hist.empty and len(hist) >= 2:
                curr = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                chg = curr - prev
                arrow = "⬆️" if chg >= 0 else "⬇️"
                rows.append({"Ränta": name, "Nivå": f"{curr:.2f}%",
                             "Δ": f"{arrow} {chg:+.2f}%"})
        except Exception:
            pass
        _t.sleep(0.3)
    return rows


def _get_provider() -> str:
    """Hämta vald AI-provider från sidebar/session state."""
    return st.session_state.get("selected_provider", "auto")


def _get_depth() -> str:
    """Hämta valt AI-djup från sidebar/session state."""
    return st.session_state.get("selected_depth", "Normal")


# ══════════════════════════════════════════════════════════════════════════════
# GEMENSAMMA WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

def kpi_row(metrics: list):
    """Custom HTML KPI-kort. metrics = [(label, value, delta[, help]), ...]"""
    cols = st.columns(len(metrics))
    for col, item in zip(cols, metrics):
        label     = item[0]
        value     = item[1]
        delta     = item[2]
        help_t    = item[3] if len(item) > 3 else None

        delta_html = ""
        if delta:
            color = "#4caf50" if not str(delta).startswith("-") else "#ef5350"
            delta_html = (
                f'<div style="font-size:12px;color:{color};margin-top:5px;'
                f'font-weight:500;">{delta}</div>'
            )

        title_attr = f'title="{help_t}"' if help_t else ""
        col.markdown(
            f'<div {title_attr} style="'
            f'background:#1e2230;border:1px solid #2d3250;border-radius:10px;'
            f'padding:18px 20px;cursor:default;">'
            f'<div style="font-size:10px;font-weight:600;color:#8892a4;'
            f'text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px;">'
            f'{label}</div>'
            f'<div style="font-size:26px;font-weight:700;color:#e8eaf0;line-height:1;">'
            f'{value}</div>'
            f'{delta_html}'
            f'</div>',
            unsafe_allow_html=True,
        )


def section_divider():
    """Gradient-avdelare — ersätter st.markdown('---')."""
    st.markdown(
        '<div style="height:1px;background:linear-gradient(to right,transparent,'
        '#2d3250 20%,#2d3250 80%,transparent);margin:28px 0 20px 0;"></div>',
        unsafe_allow_html=True,
    )


def _apply_chart_style(fig: "go.Figure") -> "go.Figure":
    """Applicera gemensamt Inter-typsnitt och finare gridlines på alla Plotly-figurer."""
    fig.update_layout(
        font=dict(family="Inter, -apple-system, sans-serif", size=12, color="#8892a4"),
        title_font=dict(
            family="Inter, -apple-system, sans-serif", size=14,
            color="#c8cfe0",
        ),
        xaxis=dict(
            gridcolor="#252b3b", linecolor="#2d3250",
            tickfont=dict(size=11, color="#8892a4"),
        ),
        yaxis=dict(
            gridcolor="#252b3b", linecolor="#2d3250",
            tickfont=dict(size=11, color="#8892a4"),
        ),
    )
    return fig


def score_distribution_chart(df: pd.DataFrame, score_col: str = "score_total") -> go.Figure:
    if score_col not in df.columns:
        return go.Figure()
    fig = px.histogram(
        df, x=score_col, nbins=20,
        color_discrete_sequence=["#42a5f5"],
        title="Poängfördelning",
        labels={score_col: "Score", "count": "Antal bolag"},
        template="plotly_dark",
        range_x=[0, 100],
    )
    fig.update_layout(
        margin=dict(t=36, b=16, l=16, r=16),
        plot_bgcolor="#1e2230",
        paper_bgcolor="#131722",
        height=260,
        xaxis=dict(range=[0, 100], dtick=10),
    )
    return _apply_chart_style(fig)


def sector_bar_chart(df: pd.DataFrame, score_col: str = "score_total") -> go.Figure:
    if "sector" not in df.columns or score_col not in df.columns:
        return go.Figure()
    agg = (df.groupby("sector")[score_col]
           .agg(["mean", "count"])
           .rename(columns={"mean": "Snittpoäng", "count": "Antal"})
           .sort_values("Snittpoäng", ascending=True)
           .reset_index())
    fig = px.bar(
        agg, x="Snittpoäng", y="sector", orientation="h",
        color="Snittpoäng",
        color_continuous_scale=[[0, "#d50000"], [0.5, "#ffd600"], [1, "#00c853"]],
        text="Antal",
        title="Sektorstyrka (snittpoäng)",
        template="plotly_dark",
    )
    fig.update_traces(textposition="inside")
    fig.update_layout(
        margin=dict(t=36, b=16, l=16, r=16),
        plot_bgcolor="#1e2230",
        paper_bgcolor="#131722",
        coloraxis_showscale=False,
        height=max(200, len(agg) * 28),
        yaxis_title="",
    )
    return _apply_chart_style(fig)


def scatter_momentum_value(df: pd.DataFrame) -> go.Figure:
    cols_needed = {"score_momentum", "score_value", "score_total", "ticker"}
    if not cols_needed.issubset(df.columns):
        return go.Figure()
    plot_df = df.dropna(subset=["score_momentum", "score_value"]).head(100)
    fig = px.scatter(
        plot_df,
        x="score_value", y="score_momentum",
        size="score_total", color="score_total",
        color_continuous_scale=[[0, "#d50000"], [0.5, "#ffd600"], [1, "#00c853"]],
        hover_data={"ticker": True, "score_total": ":.1f",
                    "score_value": ":.1f", "score_momentum": ":.1f"},
        text="ticker",
        title="Momentum vs Värdering (storlek = totalpoäng)",
        template="plotly_dark",
    )
    fig.update_traces(textposition="top center", textfont_size=9)
    fig.update_layout(
        margin=dict(t=36, b=16, l=16, r=16),
        plot_bgcolor="#1e2230",
        paper_bgcolor="#131722",
        coloraxis_showscale=False,
        height=380,
        xaxis_title="Värderingspoäng",
        yaxis_title="Momentumpoäng",
    )
    return _apply_chart_style(fig)


def holdings_pie(df: pd.DataFrame) -> go.Figure:
    if "sector" not in df.columns:
        return go.Figure()
    agg = df["sector"].value_counts().reset_index()
    agg.columns = ["Sektor", "Antal"]
    fig = px.pie(
        agg, names="Sektor", values="Antal",
        title="Sektorfördelning",
        template="plotly_dark",
        hole=0.4,
    )
    fig.update_layout(
        margin=dict(t=36, b=16, l=16, r=16),
        paper_bgcolor="#131722",
        height=300,
    )
    return _apply_chart_style(fig)
