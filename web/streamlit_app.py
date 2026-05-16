"""
MarketScan Dashboard – Interaktiv börsanalys
============================================
Läser utdata från scan.py, smallcap/scanner.py och portfolio.py.

Kör lokalt : streamlit run streamlit_app.py
Deploya    : anslut GitHub-repo till streamlit.io/cloud
"""

import json
import os
import sys
import tempfile
from datetime import datetime, date
from pathlib import Path

# ── Sökvägar – MÅSTE komma INNAN projekt-importer ────────────────────────────
# Streamlit Cloud kör filen från web/-mappen; projektroten måste läggas till
# explicit annars hittas inte core/, data_management/, portfolio/.
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
from data_management import avanza_import
from core import config
from core import ai_analysis
from portfolio import watchlist as wl
from web.stock_detail import render_stock_detail, _provider_selector

# ── Page-konfiguration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MarketScan",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Kompaktare tabeller */
  .stDataFrame thead th { font-size: 12px !important; }
  .stDataFrame tbody td { font-size: 12px !important; }

  /* Metrik-kort */
  div[data-testid="metric-container"] {
    background: #1e2230;
    border: 1px solid #2d3250;
    border-radius: 8px;
    padding: 12px 16px;
  }
  div[data-testid="metric-container"] label { color: #8892a4 !important; font-size: 12px; }
  div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #e8eaf0; }

  /* Taggar */
  .tag-green  { background:#1a3a2a; color:#4caf50; border:1px solid #4caf50;
                border-radius:4px; padding:1px 7px; font-size:11px; }
  .tag-yellow { background:#3a3010; color:#ffc107; border:1px solid #ffc107;
                border-radius:4px; padding:1px 7px; font-size:11px; }
  .tag-red    { background:#3a1010; color:#ef5350; border:1px solid #ef5350;
                border-radius:4px; padding:1px 7px; font-size:11px; }
  .tag-blue   { background:#0d2137; color:#42a5f5; border:1px solid #42a5f5;
                border-radius:4px; padding:1px 7px; font-size:11px; }
  .tag-grey   { background:#1e2230; color:#8892a4; border:1px solid #4a5568;
                border-radius:4px; padding:1px 7px; font-size:11px; }

  /* Sidebar navigation */
  div[data-testid="stSidebarContent"] { background: #131722; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATALADDNING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def load_scan_reports() -> dict:
    """Returnerar {datum_str: DataFrame} för alla vecko-scan CSVer."""
    result = {}
    for f in sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True):
        try:
            d   = f.stem.replace("scored_universe_", "")
            df  = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
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


@st.cache_data(ttl=60)
def load_portfolio() -> pd.DataFrame:
    """Laddar holdings.csv och berikar med senaste scan-data."""
    try:
        holdings = pd.read_csv(ROOT / "holdings.csv")
        holdings["ticker"] = holdings["ticker"].str.upper()
        return holdings
    except Exception:
        return pd.DataFrame(columns=["ticker", "shares", "cost_basis"])


@st.cache_data(ttl=60)
def load_watchlist() -> list:
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


def _get_provider() -> str:
    """Hämta vald AI-provider från sidebar/session state."""
    return st.session_state.get("selected_provider", "auto")


def _get_depth() -> str:
    """Hämta valt AI-djup från sidebar/session state."""
    return st.session_state.get("selected_depth", "Normal")


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def build_sidebar(scan_dates: list, sc_dates: list) -> tuple:
    """Bygger sidebar och returnerar (page, scan_date, sc_date, filters)."""
    with st.sidebar:
        st.markdown("## 📊 MarketScan")
        st.markdown("---")

        page = st.radio(
            "Navigering",
            ["📊 Översikt", "🔍 Veckoscanner", "🏦 Småbolag",
             "💼 Portfölj", "📈 Teknisk analys", "🤖 AI", "🔧 Admin"],
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.markdown("### 📅 Datumval")

        scan_date = st.selectbox(
            "Veckoscanner (datum)",
            scan_dates if scan_dates else ["Ingen data"],
            key="scan_date",
        )
        sc_date = st.selectbox(
            "Småbolag (datum)",
            sc_dates if sc_dates else ["Ingen data"],
            key="sc_date",
        )

        st.markdown("---")
        filters = {}

        if page == "🔍 Veckoscanner":
            st.markdown("### 🎛️ Filter – Veckoscanner")
            filters["score_min"] = st.slider("Min score", 0, 100, 40, 5)
            filters["score_max"] = st.slider("Max score", 0, 100, 100, 5)
            filters["sector"]    = st.multiselect("Sektor", [], placeholder="Välj sektorer…")
            filters["entry"]     = st.multiselect(
                "Entry-signal",
                ["STARK", "OK", "VÄNTA", "EJ AKTUELL"],
                default=["STARK", "OK"],
            )
            filters["confidence"] = st.multiselect(
                "Konfidens",
                ["HÖG", "MEDEL", "LÅG"],
                placeholder="Alla konfidensnivåer…",
            )
            filters["trend"] = st.selectbox(
                "Trend",
                ["Alla", "UPPTREND", "NEDTREND", "SIDLED"],
            )
            filters["piotroski_min"] = st.slider("Min Piotroski", 0, 9, 0)
            filters["show_holdings"] = st.checkbox("Visa bara mina innehav")
            filters["show_watchlist"] = st.checkbox("Inkludera bevakningslista")

        elif page == "🏦 Småbolag":
            st.markdown("### 🎛️ Filter – Småbolag")
            filters["sc_score_min"] = st.slider("Min poäng", 0, 100, 30, 5)
            filters["sc_stars"]     = st.multiselect(
                "Stjärnbetyg",
                ["★★★★★", "★★★★", "★★★", "★★", "★"],
                placeholder="Alla betyg…",
            )
            filters["sc_sector"]    = st.multiselect("Sektor", [], placeholder="Välj sektorer…")
            filters["sc_insider"]   = st.selectbox(
                "Insidersignal",
                ["Alla", "BUY", "NEUTRAL", "SELL", "N/A"],
            )
            filters["sc_fcf"]       = st.checkbox("Positivt FCF")
            filters["sc_market"]    = st.multiselect(
                "Marknadsplats",
                ["First North", "Small Cap", "Spotlight", "Övrigt"],
                placeholder="Alla marknader…",
            )
            filters["sc_max_de"]    = st.slider("Max skuldsättning D/E (%)", 0, 500, 300, 25)

        elif page == "📈 Teknisk analys":
            st.markdown("### 🎛️ Filter – Teknisk")
            filters["rsi_min"] = st.slider("Min RSI", 0, 100, 0)
            filters["rsi_max"] = st.slider("Max RSI", 0, 100, 100)
            filters["ma200"]   = st.selectbox(
                "MA200-status",
                ["Alla", "Över MA200 (bull)", "Under MA200 (bear)"],
            )
            filters["t_sector"] = st.multiselect("Sektor", [], placeholder="Välj sektorer…")
            filters["t_entry"]  = st.multiselect(
                "Entry",
                ["STARK", "OK", "VÄNTA", "EJ AKTUELL"],
                placeholder="Alla signaler…",
            )
            filters["trend_tech"] = st.selectbox("Trend", ["Alla", "UPPTREND", "Övriga"])

        # ── AI-provider selector ─────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🤖 AI-provider")
        ai_provider = st.selectbox(
            "Välj AI-tjänst",
            ["auto", "deepseek", "gemini"],
            format_func=lambda k: {
                "auto": f"Auto ({config.AI_PROVIDER})",
                "deepseek": "DeepSeek (komplex, kostar)",
                "gemini": "Gemini (enkel, gratis)",
            }.get(k, k),
            key="sidebar_ai_provider",
        )
        st.session_state["selected_provider"] = ai_provider

        # ── AI-djup selector ───────────────────────────────────────────────
        st.markdown("### 🎯 AI-djup")
        ai_depth = st.selectbox(
            "Välj analytiskt djup",
            ["Snabb", "Normal", "Djup", "Extra djup"],
            index=1,  # Normal som default
            key="sidebar_ai_depth",
        )
        st.session_state["selected_depth"] = ai_depth

        # Sektorlistan fylls i av respektive page-funktion (de anropar sidebar_update_sectors)
        st.markdown("---")
        st.caption(f"Senast uppdaterad: {datetime.now().strftime('%H:%M')}")

    return page, scan_date, sc_date, filters


# ══════════════════════════════════════════════════════════════════════════════
# GEMENSAMMA WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

def kpi_row(metrics: list):
    """Visar en rad med st.metric-kort. metrics = [(label, value, delta), ...]"""
    cols = st.columns(len(metrics))
    for col, (label, value, delta) in zip(cols, metrics):
        col.metric(label, value, delta)


def score_distribution_chart(df: pd.DataFrame, score_col: str = "score_total") -> go.Figure:
    if score_col not in df.columns:
        return go.Figure()
    fig = px.histogram(
        df, x=score_col, nbins=20,
        color_discrete_sequence=["#42a5f5"],
        title="Poängfördelning",
        labels={score_col: "Score", "count": "Antal bolag"},
        template="plotly_dark",
    )
    fig.update_layout(
        margin=dict(t=36, b=16, l=16, r=16),
        plot_bgcolor="#1e2230",
        paper_bgcolor="#131722",
        height=260,
    )
    return fig


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
    return fig


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
    return fig


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
    return fig


# ── Phase 2d: Sektor-nätverksgraf (spindelnät) ────────────────────────────────
def sector_network_graph(df: pd.DataFrame) -> go.Figure:
    """Bygger en Plotly-nätverksgraf som visar relationer mellan sektorer
    baserat på genomsnittlig score-korrelation."""
    if "sector" not in df.columns or "score_total" not in df.columns:
        return go.Figure()

    sec_avg = df.groupby("sector")["score_total"].mean().sort_values(ascending=False)
    sectors = sec_avg.index.tolist()
    n = len(sectors)
    if n < 2:
        return go.Figure()

    import math
    angles = [2 * math.pi * i / n for i in range(n)]
    pos_x = [math.cos(a) for a in angles]
    pos_y = [math.sin(a) for a in angles]

    sizes = sec_avg.values
    norm_sizes = 20 + (sizes - sizes.min()) / (sizes.max() - sizes.min() + 1e-6) * 40

    colors = []
    for v in sizes:
        if v >= 60: colors.append("#00c853")
        elif v >= 45: colors.append("#ffd600")
        else: colors.append("#ef5350")

    fig = go.Figure()

    for i in range(n):
        j = (i + 1) % n
        fig.add_trace(go.Scatter(
            x=[pos_x[i], pos_x[j], None],
            y=[pos_y[i], pos_y[j], None],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.15)", width=1),
            showlegend=False, hoverinfo="skip",
        ))

    for i in range(n):
        fig.add_trace(go.Scatter(
            x=[0, pos_x[i], None],
            y=[0, pos_y[i], None],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.06)", width=1),
            showlegend=False, hoverinfo="skip",
        ))

    fig.add_trace(go.Scatter(
        x=pos_x, y=pos_y,
        mode="markers+text",
        marker=dict(size=norm_sizes, color=colors, line=dict(color="white", width=1)),
        text=sectors,
        textposition="middle center",
        textfont=dict(size=10, color="white"),
        hovertemplate="<b>%{text}</b><br>Snittscore: %{customdata:.1f}<extra></extra>",
        customdata=sizes,
        showlegend=False,
    ))

    fig.update_layout(
        title=dict(text="🕸️ Sektornätverk – styrka & relationer", font=dict(size=14)),
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        height=450,
        margin=dict(t=40, b=16, l=16, r=16),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        hovermode="closest",
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 1 – ÖVERSIKT
# ══════════════════════════════════════════════════════════════════════════════

def page_overview(df: pd.DataFrame, sc_df: pd.DataFrame):
    st.title("📊 Översikt")

    if df.empty and sc_df.empty:
        st.warning("Ingen scandata hittad. Kör `python scan.py` och `python smallcap/scanner.py` först.")
        return

    # ── KPI-rad ──────────────────────────────────────────────────────────────
    col_score = "score_total" if "score_total" in df.columns else "sc_total"
    n_total   = len(df) if not df.empty else 0
    top_ticker = df.sort_values("score_total", ascending=False).iloc[0]["ticker"] \
        if not df.empty and "score_total" in df.columns else "—"
    top_score  = df.sort_values("score_total", ascending=False).iloc[0]["score_total"] \
        if not df.empty and "score_total" in df.columns else 0
    n_stark    = int((df.get("entry_signal", pd.Series()) == "STARK").sum()) \
        if "entry_signal" in df.columns else 0
    avg_score  = df["score_total"].mean() if "score_total" in df.columns else 0

    kpi_row([
        ("📈 Bolag i scan",  f"{n_total}",             None),
        ("🥇 Toppbolag",     f"{top_ticker}",           f"{top_score:.0f} poäng"),
        ("⚡ STARK entry",   f"{n_stark}",              None),
        ("📊 Snittpoäng",    f"{avg_score:.1f}/100",    None),
    ])

    st.markdown("---")

    # ── Topp 5 ───────────────────────────────────────────────────────────────
    st.subheader("🏆 Topp 5 just nu")
    if not df.empty and "score_total" in df.columns:
        top5 = df.sort_values("score_total", ascending=False).head(5)
        cols = st.columns(5)
        for i, (col, (_, r)) in enumerate(zip(cols, top5.iterrows())):
            medals = ["🥇", "🥈", "🥉", "4.", "5."]
            score  = r.get("score_total", 0)
            entry  = r.get("entry_signal", "—")
            sector = r.get("sector", "—")
            delta  = r.get("score_delta")
            d_str  = f"Δ {delta:+.1f}p" if delta and not pd.isna(delta) else ""
            col.metric(
                f"{medals[i]} {r['ticker']}",
                f"{score:.0f} poäng",
                d_str or f"{sector[:18]}",
            )

    st.markdown("---")

    # ── Diagram ───────────────────────────────────────────────────────────────
    c1, c2 = st.columns([3, 2])
    with c1:
        if not df.empty:
            st.plotly_chart(sector_bar_chart(df), use_container_width=True)
    with c2:
        if not df.empty:
            st.plotly_chart(score_distribution_chart(df), use_container_width=True)

    # ── Småbolag quick-view ────────────────────────────────────────────────────
    if not sc_df.empty:
        st.markdown("---")
        st.subheader("🏦 Småbolag – snabbvy")
        score_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
        if score_col in sc_df.columns:
            top_sc = sc_df.sort_values(score_col, ascending=False).head(5)
            show_cols = [c for c in ["ticker", "sc_stars", score_col, "insider_signal",
                                     "current_price", "day_change_pct", "week_change_pct"]
                         if c in top_sc.columns]
            st.dataframe(top_sc[show_cols].reset_index(drop=True), use_container_width=True)

    # ── Entry-signal-fördelning ───────────────────────────────────────────────
    if not df.empty and "entry_signal" in df.columns:
        st.markdown("---")
        st.subheader("⚡ Entry-signal fördelning")
        sig_counts = df["entry_signal"].value_counts().reset_index()
        sig_counts.columns = ["Signal", "Antal"]
        color_map = {
            "STARK": "#00c853", "OK": "#42a5f5",
            "VÄNTA": "#ffd600", "EJ AKTUELL": "#ef5350",
        }
        fig = px.bar(
            sig_counts, x="Signal", y="Antal",
            color="Signal", color_discrete_map=color_map,
            template="plotly_dark",
        )
        fig.update_layout(
            margin=dict(t=24, b=16, l=16, r=16),
            plot_bgcolor="#1e2230",
            paper_bgcolor="#131722",
            showlegend=False,
            height=240,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── AI Market Summary button (Feature 8) ────────────────────────────────
    st.markdown("---")
    ai_col1, ai_col2 = st.columns([3, 1])
    with ai_col1:
        st.subheader("🤖 AI-marknadssammanfattning")
    with ai_col2:
        open_ai = st.button("➡️ Öppna AI Dashboard", key="btn_ov_ai_go", use_container_width=True)
        if open_ai:
            st.switch_page("streamlit_app.py")  # Låter användaren navigera manuellt

    if st.button("🤖 Generera marknadssammanfattning", key="btn_ov_market_summary", use_container_width=True):
        with st.spinner("Analyserar marknaden..."):
            try:
                provider = _get_provider()
                depth = _get_depth()
                result = ai_analysis.generate_market_summary(
                    df=df if not df.empty else None,
                    sc_df=sc_df if not sc_df.empty else None,
                    provider=provider,
                    depth=depth,
                )
                with st.container(border=True):
                    st.markdown(result)
            except Exception as e:
                st.error(f"❌ {e}")

    # ── Phase 2c: Earnings Calendar ─────────────────────────────────────────
    st.markdown("---")
    st.subheader("📅 Earnings-kalender – kommande rapporter")
    st.caption("Topp-50 aktier som rapporterar inom 14 dagar. Var försiktig med köp precis innan rapport.")
    if not df.empty and "ticker" in df.columns:
        try:
            from core.earnings_calendar import upcoming_in_top
            top_n = st.selectbox("Antal toppaktier att kolla", [20, 30, 50, 100], index=2,
                                  key="ov_earnings_top")
            cal_df = upcoming_in_top(df, top_n=top_n, days_ahead=14)
            if not cal_df.empty:
                # Färgkoda dagar kvar
                def _days_color(d):
                    if d <= 3: return "🔴"
                    if d <= 7: return "🟡"
                    return "🟢"
                cal_df["_urgency"] = cal_df["days_until"].apply(_days_color)
                cal_df["Dagar"] = cal_df.apply(
                    lambda r: f"{r['_urgency']} {r['days_until']}d", axis=1
                )
                display_cal = cal_df[["earnings_date", "Dagar", "ticker", "name", "score_total"]].copy()
                display_cal.columns = ["Rapportdag", "Kvar", "Ticker", "Bolag", "Score"]
                display_cal["Score"] = display_cal["Score"].apply(
                    lambda v: f"{v:.0f}" if pd.notna(v) else "—"
                )
                col_cfg_cal = {}
                st.dataframe(display_cal, use_container_width=True, hide_index=True,
                             column_config=col_cfg_cal)
                st.caption(f"{len(display_cal)} kommande rapporter inom 14 dagar")
            else:
                st.info("Inga kommande rapporter inom 14 dagar för toppaktierna.")
        except Exception as e:
            st.caption(f"Earnings-kalender ej tillgänglig: {e}")
    else:
        st.info("Ladda scandata för att se earnings-kalender.")

    # ── Phase 2e: Interactive top list ────────────────────────────────────────
    st.markdown("---")
    st.subheader("🏆 Topplista – sök & filtrera")
    st.caption("Välj top-N, sök på ticker/namn och klicka för detaljvy.")
    col_top_n, col_search = st.columns([1, 3])
    with col_top_n:
        top_n = st.selectbox("Visa topp", [50, 100, 200, 500], index=1,
                             key="ov_toplists_topn")
    with col_search:
        search_q = st.text_input("🔍 Sök ticker eller bolagsnamn", "",
                                 key="ov_toplists_search",
                                 placeholder="T.ex. AAPL, Investor, ...")

    if df is not None and not df.empty:
        display_df = df.head(top_n).copy()
        if search_q.strip():
            q = search_q.strip().lower()
            mask = (
                display_df["ticker"].str.lower().str.contains(q, na=False)
                | display_df["name"].str.lower().str.contains(q, na=False)
            )
            display_df = display_df[mask]
        if display_df.empty:
            st.info("Inga sökresultat.")
        else:
            # Förbered kolumner
            cols_avail = [c for c in ["ticker", "name", "sector", "score_total",
                                        "price", "change_pct", "volume",
                                        "score_value", "score_momentum",
                                        "score_quality", "score_growth"]
                          if c in display_df.columns]
            shown = display_df[cols_avail].copy()
            # Formatera change_pct
            if "change_pct" in shown.columns:
                shown["change_pct"] = shown["change_pct"].apply(
                    lambda v: f"{v:+.1f}%" if pd.notna(v) else "—"
                )
            # Progress bar för score
            col_config = {
                "score_total": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%.0f"
                ),
            }
            # Kolumnetiketter
            col_rename = {
                "ticker": "Ticker", "name": "Bolag",
                "sector": "Sektor", "price": "Pris",
                "change_pct": "Förändring", "volume": "Volym",
                "score_value": "Värde", "score_momentum": "Momentum",
                "score_quality": "Kvalitet", "score_growth": "Tillväxt",
            }
            shown.rename(columns={k: v for k, v in col_rename.items()
                                  if k in shown.columns}, inplace=True)
            event = st.dataframe(
                shown, use_container_width=True, hide_index=True,
                column_config=col_config,
                on_select="rerun", selection_mode="single-row",
                key="ov_toplists_table",
            )
            # Klickbar rad → visa detaljvy
            if event and event.selection and event.selection.rows:
                selected_idx = event.selection.rows[0]
                sel_ticker = display_df.iloc[selected_idx]["ticker"]
                price_col = "price" if "price" in df.columns else "close"
                row = df[df["ticker"] == sel_ticker]
                if not row.empty:
                    with st.expander(f"🔍 Detaljvy: {sel_ticker}",
                                     expanded=True):
                        render_stock_detail(
                            sel_ticker, row=row.iloc[0], df=df,
                            show_ai=True, show_news=False,
                        )
        st.caption(f"{len(display_df)} aktier visas")
    else:
        st.info("Ladda scandata för att visa topplistan.")


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 2 – VECKOSCANNER
# ══════════════════════════════════════════════════════════════════════════════

def _apply_weekly_filters(df: pd.DataFrame, filters: dict,
                          holdings: pd.DataFrame, watchlist: list) -> pd.DataFrame:
    if df.empty:
        return df

    # Uppdatera sidebar-sektorlistan (hack: skickar via session_state)
    if "sector" in df.columns:
        secs = sorted(df["sector"].dropna().unique().tolist())
        st.session_state["weekly_sectors"] = secs

    out = df.copy()

    # Score-range
    if "score_total" in out.columns:
        lo, hi = filters.get("score_min", 0), filters.get("score_max", 100)
        out = out[out["score_total"].between(lo, hi)]

    # Sektor
    sel_sectors = filters.get("sector", [])
    if sel_sectors and "sector" in out.columns:
        out = out[out["sector"].isin(sel_sectors)]

    # Entry-signal
    sel_entry = filters.get("entry", [])
    if sel_entry and "entry_signal" in out.columns:
        out = out[out["entry_signal"].isin(sel_entry)]

    # Konfidens
    sel_conf = filters.get("confidence", [])
    if sel_conf and "confidence_label" in out.columns:
        out = out[out["confidence_label"].isin(sel_conf)]

    # Trend
    sel_trend = filters.get("trend", "Alla")
    if sel_trend != "Alla" and "trend_signal" in out.columns:
        out = out[out["trend_signal"] == sel_trend]

    # Piotroski
    pio_min = filters.get("piotroski_min", 0)
    if pio_min > 0 and "piotroski_f" in out.columns:
        out = out[out["piotroski_f"].fillna(0) >= pio_min]

    # Bara innehav
    if filters.get("show_holdings") and not holdings.empty:
        h_tickers = set(holdings["ticker"].str.upper())
        out = out[out["ticker"].isin(h_tickers)]

    # Inkludera bevakningslista (ingen filtrering, bara markering)
    return out.reset_index(drop=True)


def _main_ranking_table(df: pd.DataFrame, holdings: pd.DataFrame, watchlist: list):
    """Visar huvudrankingstabellen med färgkodning."""
    if df.empty:
        st.info("Inga bolag matchar aktuella filter.")
        return

    h_tickers = set(holdings["ticker"].str.upper()) if not holdings.empty else set()
    wl_tickers = {i["ticker"] for i in watchlist}

    # Markera innehav / bevakningslista
    def _flag(t):
        if t in h_tickers:  return "💼 Innehav"
        if t in wl_tickers: return "⭐ Bevakad"
        return ""

    show = df.copy()
    show["_status"] = show["ticker"].apply(_flag)

    # Välj kolumner
    base_cols = [c for c in [
        "rank", "ticker", "name", "_status", "sector",
        "score_total", "entry_signal", "confidence_label", "trend_signal",
        "delta_flag", "piotroski_f",
    ] if c in show.columns]

    display = show[base_cols].copy()
    display = display.rename(columns={
        "rank":            "Rank",
        "ticker":          "Ticker",
        "name":            "Bolag",
        "_status":         "Status",
        "sector":          "Sektor",
        "score_total":     "Score",
        "entry_signal":    "Entry",
        "confidence_label":"Konf.",
        "trend_signal":    "Trend",
        "delta_flag":      "Δ",
        "piotroski_f":     "Piotroski",
    })

    col_cfg = {}
    if "Score" in display.columns:
        col_cfg["Score"] = st.column_config.ProgressColumn(
            "Score", min_value=0, max_value=100, format="%.0f"
        )
    if "Piotroski" in display.columns:
        col_cfg["Piotroski"] = st.column_config.NumberColumn("Piotroski", format="%.0f/9")

    st.dataframe(
        display,
        use_container_width=True,
        height=min(700, max(350, len(display) * 36 + 40)),
        column_config=col_cfg,
        hide_index=True,
    )
    st.caption(f"Visar {len(display)} bolag")

    # ── "Fråga AI om denna aktie" per rad ──────────────────────────────────
    st.markdown("---")
    st.subheader("🤖 Fråga AI om en aktie")
    ticker_list = df["ticker"].tolist()
    col_q1, col_q2 = st.columns([3, 1])
    with col_q1:
        ai_ticker = st.selectbox("Välj aktie att analysera", ticker_list, key="ranking_ai_ticker")
    with col_q2:
        ai_go = st.button("🤖 Analysera", key="btn_ranking_ai", use_container_width=True)
    if ai_go and ai_ticker:
        row = df[df["ticker"] == ai_ticker]
        if not row.empty:
            with st.expander("🔍 Visa detaljvy + AI-analys", expanded=True):
                render_stock_detail(
                    ai_ticker, row=row.iloc[0], df=df,
                    show_ai=True, show_news=False, show_chart=True, show_detail_data=True,
                )


def page_weekly_scan(df: pd.DataFrame, filters: dict,
                     holdings: pd.DataFrame, watchlist: list):
    st.title("🔍 Veckoscanner")

    if df.empty:
        st.warning("Ingen veckodata. Kör `python scan.py` för att generera.")
        return

    # Uppdatera sidebars sektorlista dynamiskt
    if "sector" in df.columns:
        secs = sorted(df["sector"].dropna().unique().tolist())
        # Visa sektorer som info
        with st.sidebar:
            with st.expander("Tillgängliga sektorer", expanded=False):
                st.write(", ".join(secs))

    # Applicera filter
    filt_df = _apply_weekly_filters(df, filters, holdings, watchlist)

    # KPI
    n_total  = len(df)
    n_filt   = len(filt_df)
    avg_sc   = filt_df["score_total"].mean() if "score_total" in filt_df.columns else 0
    n_stark  = (filt_df["entry_signal"] == "STARK").sum() if "entry_signal" in filt_df.columns else 0
    kpi_row([
        ("Totalt i scan",    f"{n_total}",        None),
        ("Matchar filter",   f"{n_filt}",          None),
        ("Snittpoäng",       f"{avg_sc:.1f}",      None),
        ("STARK entry",      f"{n_stark}",         None),
    ])

    # Flikar
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📋 Ranking", "📊 Fundamental", "📈 Momentum & Teknisk", "🔬 Score-detalj"]
    )

    with tab1:
        _main_ranking_table(filt_df, holdings, watchlist)
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(sector_bar_chart(filt_df), use_container_width=True)
        with c2:
            st.plotly_chart(score_distribution_chart(filt_df), use_container_width=True)

        # ── Stock Detail Panel ──────────────────────────────────────────────
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

    with tab2:
        if filt_df.empty:
            st.info("Inga data.")
        else:
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
            st.dataframe(fund, use_container_width=True, hide_index=True, height=600)

    with tab3:
        if filt_df.empty:
            st.info("Inga data.")
        else:
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
            st.dataframe(tech, use_container_width=True, hide_index=True, height=600)
            st.markdown("---")
            st.plotly_chart(scatter_momentum_value(filt_df), use_container_width=True)

    with tab4:
        if filt_df.empty:
            st.info("Inga data.")
        else:
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
            st.dataframe(sc_disp, use_container_width=True, hide_index=True,
                         column_config=col_cfg, height=600)

            # Radar-chart för enskilt bolag
            st.markdown("---")
            st.subheader("🕸️ Score-radar – enskilt bolag")
            if not filt_df.empty and sc_cols:
                tickers_list = filt_df["ticker"].tolist()
                chosen = st.selectbox("Välj bolag", tickers_list, key="radar_ticker")
                row = filt_df[filt_df["ticker"] == chosen].iloc[0]
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


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 3 – SMÅBOLAG
# ══════════════════════════════════════════════════════════════════════════════

def _apply_sc_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    if df.empty:
        return df

    out       = df.copy()
    score_col = "sc_total" if "sc_total" in out.columns else "score_total"

    if score_col in out.columns:
        out = out[out[score_col] >= filters.get("sc_score_min", 30)]

    # Stjärnor
    sel_stars = filters.get("sc_stars", [])
    if sel_stars and "sc_stars" in out.columns:
        out = out[out["sc_stars"].isin(sel_stars)]

    # Sektor
    sel_sec = filters.get("sc_sector", [])
    if sel_sec and "sector" in out.columns:
        out = out[out["sector"].isin(sel_sec)]

    # Insider
    sel_ins = filters.get("sc_insider", "Alla")
    if sel_ins != "Alla" and "insider_signal" in out.columns:
        out = out[out["insider_signal"] == sel_ins]

    # Positivt FCF
    if filters.get("sc_fcf") and "free_cash_flow" in out.columns:
        out = out[out["free_cash_flow"] > 0]

    # D/E
    max_de = filters.get("sc_max_de", 300)
    if "debt_to_equity" in out.columns:
        out = out[out["debt_to_equity"].fillna(0) <= max_de]

    return out.reset_index(drop=True)


def page_smallcap(sc_df: pd.DataFrame, filters: dict):
    st.title("🏦 Småbolag – svenska small/micro cap")

    if sc_df.empty:
        st.warning(
            "Ingen smallcap-data hittad. Kör `python smallcap/scanner.py` för att generera."
        )
        return

    # Dynamisk sektorlista i sidebaren
    if "sector" in sc_df.columns:
        secs = sorted(sc_df["sector"].dropna().unique().tolist())
        with st.sidebar:
            with st.expander("Sektorer i småbolag", expanded=False):
                st.write(", ".join(secs))

    score_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
    filt      = _apply_sc_filters(sc_df, filters)

    # KPI
    n_five = (filt.get("sc_stars", pd.Series()) == "★★★★★").sum() \
        if "sc_stars" in filt.columns else 0
    n_buy  = (filt.get("insider_signal", pd.Series()) == "BUY").sum() \
        if "insider_signal" in filt.columns else 0
    avg_sc = filt[score_col].mean() if score_col in filt.columns else 0
    kpi_row([
        ("Bolag (filtrerat)", f"{len(filt)} / {len(sc_df)}", None),
        ("★★★★★ bolag",       f"{n_five}",                   None),
        ("Insider BUY",       f"{n_buy}",                    None),
        ("Snittpoäng",        f"{avg_sc:.1f}",               None),
    ])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["🏆 Rankinglista", "📊 Nyckeltal", "🔬 Faktortabell", "🕵️ Insider"]
    )

    with tab1:
        if filt.empty:
            st.info("Inga bolag matchar filter.")
        else:
            rank_cols = [c for c in [
                "ticker", "sc_stars", score_col, "insider_signal",
                "current_price", "day_change_pct", "week_change_pct",
                "return_6m", "return_12m", "piotroski_score",
            ] if c in filt.columns]
            rank_disp = filt[rank_cols].copy()
            rank_disp.insert(0, "Rank", range(1, len(rank_disp) + 1))
            rename = {
                "ticker": "Ticker", "sc_stars": "⭐",
                score_col: "Poäng",
                "insider_signal": "Insider",
                "current_price": "Pris",
                "day_change_pct": "Dag%",
                "week_change_pct": "Vecka%",
                "return_6m": "6m%",
                "return_12m": "12m%",
                "piotroski_score": "Piotroski",
            }
            rank_disp = rank_disp.rename(columns=rename)
            for c in ["Dag%", "Vecka%", "6m%", "12m%"]:
                if c in rank_disp.columns:
                    rank_disp[c] = rank_disp[c].apply(lambda v: pct_fmt(v))
            col_cfg = {}
            if "Poäng" in rank_disp.columns:
                col_cfg["Poäng"] = st.column_config.ProgressColumn(
                    "Poäng", min_value=0, max_value=100, format="%.0f"
                )
            st.dataframe(rank_disp, use_container_width=True, hide_index=True,
                         column_config=col_cfg, height=600)

            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(sector_bar_chart(filt, score_col), use_container_width=True)
            with c2:
                st.plotly_chart(score_distribution_chart(filt, score_col), use_container_width=True)

            # ── Stock Detail Panel ──────────────────────────────────────────
            st.markdown("---")
            st.subheader("📈 Detaljvy")
            if not filt.empty and "ticker" in filt.columns:
                sc_detail_ticker = st.selectbox("Välj smallcap-aktie", sorted(filt["ticker"].tolist()),
                                                key="sc_detail_ticker")
                sc_row = sc_df[sc_df["ticker"] == sc_detail_ticker]
                if not sc_row.empty:
                    with st.expander("🔍 Visa detaljvy", expanded=False):
                        render_stock_detail(
                            sc_detail_ticker, row=sc_row.iloc[0], df=sc_df,
                            show_ai=True, show_news=False, show_chart=True, show_detail_data=True,
                        )

    with tab2:
        if not filt.empty:
            key_cols = [c for c in [
                "ticker", "sc_stars", "current_price",
                "market_cap", "ev_to_ebitda", "price_to_book",
                "gross_margin", "operating_margin",
                "revenue_growth", "earnings_growth",
                "debt_to_equity", "current_ratio",
                "free_cash_flow", "total_cash",
            ] if c in filt.columns]
            kn = filt[key_cols].copy().rename(columns={
                "ticker": "Ticker", "sc_stars": "⭐",
                "current_price": "Pris", "market_cap": "Mkap (USD)",
                "ev_to_ebitda": "EV/EBITDA", "price_to_book": "P/B",
                "gross_margin": "Bruttomarg.", "operating_margin": "Rörelsmarg.",
                "revenue_growth": "Oms.tillv.", "earnings_growth": "Vinst.tillv.",
                "debt_to_equity": "D/E", "current_ratio": "CR",
                "free_cash_flow": "FCF", "total_cash": "Kassa",
            })
            for c in ["Bruttomarg.", "Rörelsmarg.", "Oms.tillv.", "Vinst.tillv."]:
                if c in kn.columns:
                    kn[c] = kn[c].apply(lambda v: pct_fmt(v))
            st.dataframe(kn, use_container_width=True, hide_index=True, height=600)

    with tab3:
        if not filt.empty:
            sc_factor_map = {
                "sc_insider":   "Insider",
                "sc_fcf":       "FCF",
                "sc_piotroski": "Piotroski",
                "sc_growth":    "Tillväxt",
                "sc_balance":   "Balans",
                "sc_valuation": "Värdering",
                "sc_momentum":  "Momentum",
                "sc_liquidity": "Likviditet",
                score_col:      "Totalt",
            }
            fact_cols = [c for c in sc_factor_map if c in filt.columns]
            fact = filt[["ticker"] + fact_cols].copy()
            fact = fact.rename(columns={"ticker": "Ticker", **{c: sc_factor_map[c] for c in fact_cols}})
            col_cfg2 = {lbl: st.column_config.ProgressColumn(lbl, min_value=0, max_value=100, format="%.0f")
                        for lbl in sc_factor_map.values() if lbl in fact.columns}
            st.dataframe(fact, use_container_width=True, hide_index=True,
                         column_config=col_cfg2, height=600)

    with tab4:
        if not filt.empty:
            ins_cols = [c for c in [
                "ticker", "insider_pct", "insider_signal",
                "insider_net_buy_6m", "insider_buy_count", "insider_sell_count",
            ] if c in filt.columns]
            if ins_cols:
                ins = filt[ins_cols].copy().rename(columns={
                    "ticker": "Ticker",
                    "insider_pct": "Insiders äger%",
                    "insider_signal": "Signal",
                    "insider_net_buy_6m": "Netto köp 6m (SEK)",
                    "insider_buy_count": "Antal köp",
                    "insider_sell_count": "Antal sälj",
                })
                if "Insiders äger%" in ins.columns:
                    ins["Insiders äger%"] = ins["Insiders äger%"].apply(lambda v: pct_fmt(v))
                st.dataframe(ins, use_container_width=True, hide_index=True, height=400)

                # BUY-tickers highlight
                buy_tickers = filt[filt.get("insider_signal", pd.Series()) == "BUY"]["ticker"].tolist() \
                    if "insider_signal" in filt.columns else []
                if buy_tickers:
                    st.success(f"Insiderköp-signaler: **{', '.join(buy_tickers)}**")
            else:
                st.info("Ingen insiderdata tillgänglig.")


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 4 – PORTFÖLJ
# ══════════════════════════════════════════════════════════════════════════════

def page_portfolio(df: pd.DataFrame, holdings: pd.DataFrame, watchlist: list):
    st.title("💼 Portfölj & Bevakningslista")

    if holdings.empty:
        st.info("Ingen portföljdata. Lägg till innehav i `data/holdings.csv`.")
    else:
        # Berika med scan-data
        if not df.empty and "ticker" in df.columns:
            score_data = df.set_index("ticker").to_dict("index")
        else:
            score_data = {}

        rows = []
        for _, h in holdings.iterrows():
            t     = str(h["ticker"]).upper()
            sc    = score_data.get(t, {})
            price = sc.get("current_price")
            cost  = h.get("cost_basis")
            shares = h.get("shares", 0)
            pnl_pct = ((price / float(cost)) - 1) * 100 \
                if price and cost and float(cost) > 0 else None
            mv = price * float(shares) if price and shares else None
            rows.append({
                "Ticker":    t,
                "Bolag":     sc.get("name", t)[:30],
                "Sektor":    sc.get("sector", "—"),
                "Antal":     shares,
                "Inköpspris": cost,
                "Pris nu":   f"{price:.2f}" if price else "—",
                "P&L %":     f"{pnl_pct:+.1f}%" if pnl_pct is not None else "—",
                "Marknadsvärde": f"{mv:,.0f}" if mv else "—",
                "Score":     sc.get("score_total"),
                "Entry":     sc.get("entry_signal", "—"),
                "Trend":     sc.get("trend_signal", "—"),
                "Piotroski": sc.get("piotroski_f"),
                "RS":        sc.get("rs_label", "—"),
            })

        port_df = pd.DataFrame(rows)

        # KPI
        total_mv   = sum(float(r["Marknadsvärde"].replace(",", "").replace(" ", ""))
                        for r in rows if isinstance(r["Marknadsvärde"], str)
                        and r["Marknadsvärde"] != "—") if rows else 0
        pnl_vals   = [float(r["P&L %"].replace("%", "").replace("+", ""))
                      for r in rows if r["P&L %"] not in ("—", None)]
        avg_pnl    = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0
        best       = max(pnl_vals) if pnl_vals else 0
        worst      = min(pnl_vals) if pnl_vals else 0

        kpi_row([
            ("Positioner",       f"{len(rows)}",            None),
            ("Totalt värde",     f"{total_mv:,.0f} kr",     None),
            ("Snitt P&L",        f"{avg_pnl:+.1f}%",        None),
            ("Bäst / Sämst",     f"+{best:.1f}% / {worst:.1f}%", None),
        ])

        col_cfg = {}
        if "Score" in port_df.columns:
            col_cfg["Score"] = st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f"
            )
        st.dataframe(port_df, use_container_width=True, hide_index=True,
                     column_config=col_cfg)

        # Rekommendationer
        if score_data:
            st.markdown("---")
            st.subheader("💡 Rekommendationer (baserat på senaste scan)")
            for r in sorted(rows, key=lambda x: x.get("Score") or 0, reverse=True):
                t  = r["Ticker"]
                sc = score_data.get(t, {})
                entry = sc.get("entry_signal", "—")
                score = sc.get("score_total", 0) or 0
                if score >= 70 and entry == "STARK":
                    icon = "🟢"; rec = "BEHÅLL STARKT / KÖP MER"
                elif score >= 55:
                    icon = "🔵"; rec = "BEHÅLL"
                elif score >= 40:
                    icon = "🟡"; rec = "BEVAKA"
                else:
                    icon = "🔴"; rec = "MINSKA / SÄLJ"
                st.markdown(f"{icon} **`{t}`** — {rec} (score {score:.0f})")

        # Sektorpaj
        if len(rows) > 1:
            st.markdown("---")
            st.plotly_chart(holdings_pie(pd.DataFrame(rows).rename(columns={"Sektor": "sector"})),
                            use_container_width=True)

    # ── AI Portfolio Optimizer button (Feature 4) ──────────────────────────
    if not holdings.empty:
        st.markdown("---")
        st.subheader("🤖 AI-portföljoptimering")
        st.caption("Få AI-analys av din portfölj med förslag")
        if st.button("🤖 Analysera portfölj med AI", key="btn_portfolio_ai",
                     use_container_width=True, type="primary"):
            provider = _get_provider()
            depth = _get_depth()
            with st.spinner("Analyserar portfölj..."):
                try:
                    result = ai_analysis.analyze_portfolio(
                        holdings, df=df if not df.empty else None,
                        provider=provider,
                        depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")

    # Bevakningslista
    st.markdown("---")
    st.subheader("⭐ Bevakningslista")
    if not watchlist:
        st.info("Bevakningslistan är tom. Redigera `data/watchlist.json`.")
    else:
        if not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")
        else:
            score_lu = {}

        wl_rows = []
        for item in watchlist:
            t  = item["ticker"]
            sc = score_lu.get(t, {})
            wl_rows.append({
                "Ticker":  t,
                "Bolag":   item.get("name", sc.get("name", t))[:28],
                "Sektor":  sc.get("sector", "—"),
                "Tillagd": item.get("added", "—"),
                "Score":   sc.get("score_total"),
                "Entry":   sc.get("entry_signal", "Ej scannad"),
                "Konf.":   sc.get("confidence_label", "—"),
                "Trend":   sc.get("trend_signal", "—"),
                "P/E":     num_fmt(sc.get("pe_trailing")),
                "P/B":     num_fmt(sc.get("price_to_book")),
                "ROE":     pct_fmt(sc.get("roe")),
            })

        wl_df   = pd.DataFrame(wl_rows)
        col_cfg = {}
        if "Score" in wl_df.columns:
            col_cfg["Score"] = st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f"
            )
        st.dataframe(wl_df, use_container_width=True, hide_index=True,
                     column_config=col_cfg)


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 5 – TEKNISK ANALYS
# ══════════════════════════════════════════════════════════════════════════════

def page_technical(df: pd.DataFrame, filters: dict):
    st.title("📈 Teknisk analys")

    if df.empty:
        st.warning("Ingen scandata.")
        return

    out = df.copy()

    # Filter
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

    # KPI
    n_upptrend = (out["trend_signal"] == "UPPTREND").sum() \
        if "trend_signal" in out.columns else 0
    n_over_ma  = (out["price_vs_ma200"] > 0).sum() \
        if "price_vs_ma200" in out.columns else 0
    avg_rsi    = out["rsi_14"].mean() if "rsi_14" in out.columns else 0
    n_overbought = (out["rsi_14"] > 70).sum() if "rsi_14" in out.columns else 0

    kpi_row([
        ("Visar",            f"{len(out)} / {len(df)}",  None),
        ("UPPTREND",         f"{n_upptrend}",            None),
        ("Över MA200",       f"{n_over_ma}",             None),
        ("Snitt RSI / >70",  f"{avg_rsi:.0f} / {n_overbought}", None),
    ])

    tab1, tab2, tab3 = st.tabs(["📋 Tabell", "📊 Diagram", "📉 MACD/RSI"])

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
            # RSI-scatterplot
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

        # Momentum-ranking (top / bottom 10)
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

                            # Beräkna MACD
                            ema12 = close.ewm(span=12, adjust=False).mean()
                            ema26 = close.ewm(span=26, adjust=False).mean()
                            macd_line   = ema12 - ema26
                            signal_line = macd_line.ewm(span=9, adjust=False).mean()
                            macd_hist   = macd_line - signal_line

                            # Beräkna RSI (14)
                            delta = close.diff()
                            gain  = delta.where(delta > 0, 0).rolling(14).mean()
                            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
                            rs    = gain / loss.replace(0, float("nan"))
                            rsi   = 100 - (100 / (1 + rs))

                            # Subplots: MACD + RSI
                            fig_macd_rsi = make_subplots(
                                rows=2, cols=1,
                                shared_xaxes=True,
                                vertical_spacing=0.08,
                                row_heights=[0.55, 0.45],
                            )

                            # MACD Line
                            fig_macd_rsi.add_trace(
                                go.Scatter(x=close.index, y=macd_line,
                                           name="MACD", line=dict(color="#42a5f5", width=1.5)),
                                row=1, col=1,
                            )
                            # Signal Line
                            fig_macd_rsi.add_trace(
                                go.Scatter(x=close.index, y=signal_line,
                                           name="Signal", line=dict(color="#ff7043", width=1.5)),
                                row=1, col=1,
                            )
                            # MACD Histogram
                            hist_colors = ["#4caf50" if v >= 0 else "#ef5350" for v in macd_hist]
                            fig_macd_rsi.add_trace(
                                go.Bar(x=close.index, y=macd_hist,
                                       name="MACD Hist", marker_color=hist_colors,
                                       opacity=0.6),
                                row=1, col=1,
                            )

                            # RSI Line
                            fig_macd_rsi.add_trace(
                                go.Scatter(x=close.index, y=rsi,
                                           name="RSI (14)", line=dict(color="#ab47bc", width=2)),
                                row=2, col=1,
                            )
                            # RSI nivåer
                            fig_macd_rsi.add_hline(y=70, line_dash="dash", line_color="#ef5350",
                                                   annotation_text="Överköpt 70", row=2, col=1)
                            fig_macd_rsi.add_hline(y=30, line_dash="dash", line_color="#4caf50",
                                                   annotation_text="Översålt 30", row=2, col=1)
                            fig_macd_rsi.add_hline(y=50, line_dash="dot", line_color="#8892a4",
                                                   annotation_text="50", row=2, col=1)

                            # Layout
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

                            # Y-axis labels
                            fig_macd_rsi.update_yaxes(title_text="MACD", row=1, col=1,
                                                      color="#8892a4")
                            fig_macd_rsi.update_yaxes(title_text="RSI", row=2, col=1,
                                                      range=[0, 100], color="#8892a4")
                            fig_macd_rsi.update_xaxes(color="#8892a4")

                            st.plotly_chart(fig_macd_rsi, use_container_width=True)

                            # Visa senaste värdet som metrics
                            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                            with col_m1:
                                st.metric("MACD", f"{macd_line.iloc[-1]:.3f}" if not macd_line.empty else "—")
                            with col_m2:
                                st.metric("Signal", f"{signal_line.iloc[-1]:.3f}" if not signal_line.empty else "—")
                            with col_m3:
                                rsi_val = rsi.iloc[-1]
                                rsi_str = f"{rsi_val:.1f}" if not pd.isna(rsi_val) else "—"
                                rsi_color = "🟢" if (not pd.isna(rsi_val) and 30 <= rsi_val <= 70) else ("🔴" if not pd.isna(rsi_val) else "⚪")
                                st.metric("RSI (14)", f"{rsi_color} {rsi_str}")
                            with col_m4:
                                macd_sig = "🟢 Bullish" if (not macd_line.empty and not signal_line.empty and macd_line.iloc[-1] > signal_line.iloc[-1]) else "🔴 Bearish"
                                st.metric("Signal", macd_sig)

                    except Exception as e:
                        st.error(f"Kunde inte hämta data för {tech_ticker}: {e}")

    # ── AI-knapp: AI tolkning av teknisk data (Feature 3) ───────────────────
    st.markdown("---")
    st.subheader("🤖 AI-tolkning")
    if st.button("🤖 Tolka teknisk data med AI", key="btn_tech_ai", use_container_width=True):
        provider = _get_provider()
        depth = _get_depth()
        with st.spinner("Analyserar teknisk data..."):
            try:
                # Skapa en prompt baserad på teknisk data
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


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 6 – AI (Features 2-5, 8)
# ══════════════════════════════════════════════════════════════════════════════

def _ai_section_header():
    """Gemensam rubrik för AI-sektioner."""
    return '<div style="background:#1a2332;border:1px solid #2d3250;border-radius:8px;padding:12px 18px;margin-bottom:16px">'


def _ai_section_footer():
    return '</div>'


def page_ai(df: pd.DataFrame, sc_df: pd.DataFrame, holdings: pd.DataFrame):
    """AI Dashboard – alla AI-funktioner samlade."""
    st.title("🤖 AI – MarketScan Intelligence")

    provider = _get_provider()
    api_key = config.DEEPSEEK_API_KEY or config.GEMINI_API_KEY
    if not api_key:
        st.warning("⚠️ Ingen AI API-nyckel konfigurerad. Ställ in DEEPSEEK_API_KEY eller GEMINI_API_KEY i .env.")
        return

    # API-status
    status = ai_analysis.test_api_key(provider=provider)
    if status.get("status") == "ok":
        st.caption(f"✅ {status['message']}")
    else:
        st.warning(f"⚠️ {status['message']}")
        if "saknas" in status.get("message", "").lower():
            return

    tab_market, tab_stock, tab_compare, tab_sector, tab_chat, tab_portfolio, tab_news = st.tabs([
        "📊 Marknad", "📈 Aktieanalys", "🔄 Jämför", "🏭 Sektor",
        "💬 Chat", "💼 Portfölj", "📰 Nyheter"
    ])

    # ── Flik 1: Market Dashboard Summary (Feature 8) ────────────────────────
    with tab_market:
        st.subheader("📊 AI-marknadssammanfattning")
        st.caption("Få en snabb AI-genererad överblick över dagens marknad baserat på senaste scandata.")

        refresh_market = st.checkbox("Hoppa över cache", key="ai_market_refresh")

        if st.button("🤖 Generera marknadssammanfattning", key="btn_market_summary",
                     type="primary", use_container_width=True):
            with st.spinner("Analyserar marknaden..."):
                try:
                    depth = _get_depth()
                    result = ai_analysis.generate_market_summary(
                        df=df if not df.empty else None,
                        sc_df=sc_df if not sc_df.empty else None,
                        force_refresh=refresh_market,
                        provider=provider,
                        depth=depth,
                    )
                    st.markdown(_ai_section_header(), unsafe_allow_html=True)
                    st.markdown(result)
                    st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"❌ Kunde inte generera sammanfattning: {e}")

        if not df.empty:
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Bolag i scan", len(df))
            with c2:
                if "score_total" in df.columns:
                    st.metric("Snittpoäng", f"{df['score_total'].mean():.1f}")
            with c3:
                if "entry_signal" in df.columns:
                    n_stark = int((df["entry_signal"] == "STARK").sum())
                    st.metric("STARK entry", n_stark)
            with c4:
                if not df.empty and "score_total" in df.columns:
                    top = df.nlargest(1, "score_total").iloc[0]
                    st.metric("Topp", f"{top['ticker']} ({top['score_total']:.0f}p)")

        # ── AI Ticker Search med ett-klick-lägg-till ────────────────────────
        st.markdown("---")
        st.subheader("🔍 Sök och lägg till aktie")
        st.caption("Sök efter ticker/bolag via yfinance och lägg till i bevakningslista eller portfölj med ett klick.")

        col_search, col_target = st.columns([3, 1])
        with col_search:
            ai_search_q = st.text_input(
                "Sök ticker eller bolagsnamn",
                key="ai_market_ticker_search",
                placeholder="t.ex. AAPL, TSLA, NVDA...",
            )
        with col_target:
            target = st.selectbox(
                "Lägg till i",
                ["Bevakningslista", "Portfölj"],
                key="ai_market_add_target",
            )

        if ai_search_q:
            hits = _search_ticker_yfinance(ai_search_q.upper().strip())
            if hits:
                st.success(f"Hittade {len(hits)} träffar")
                for h in hits:
                    cols = st.columns([2, 3, 1, 1])
                    with cols[0]:
                        st.markdown(f"**{h['ticker']}**")
                    with cols[1]:
                        st.markdown(f"{h['name'][:50]}")
                    with cols[2]:
                        st.markdown(f"`{h.get('exchange', '?')}`")
                    with cols[3]:
                        if st.button("➕ Lägg till", key=f"ai_mkt_add_{h['ticker']}"):
                            if target == "Bevakningslista":
                                items = load_watchlist()
                                if not any(i["ticker"] == h["ticker"] for i in items):
                                    items.append({
                                        "ticker": h["ticker"],
                                        "name": h["name"],
                                        "added": str(date.today()),
                                    })
                                    _save_watchlist_data(items)
                                    st.success(f"`{h['ticker']}` tillagd i bevakningslistan!")
                                    st.rerun()
                                else:
                                    st.info(f"`{h['ticker']}` finns redan i bevakningslistan.")
                            else:  # Portfölj
                                holdings = load_portfolio()
                                if h["ticker"] not in holdings["ticker"].values:
                                    new_row = pd.DataFrame([{
                                        "ticker": h["ticker"],
                                        "shares": 0,
                                        "cost_basis": 0,
                                    }])
                                    holdings = pd.concat([holdings, new_row], ignore_index=True)
                                    _save_holdings_df(holdings)
                                    st.success(f"`{h['ticker']}` tillagd i portföljen! Fyll i antal och pris i Admin.")
                                    st.rerun()
                                else:
                                    st.info(f"`{h['ticker']}` finns redan i portföljen.")
            else:
                st.caption("Inga sökresultat. Prova med annat sökord.")

    # ── Flik 2: One-click Stock Analysis (Feature 2b) ───────────────────────
    with tab_stock:
        st.subheader("📈 AI-aktieanalys")
        st.caption("Välj en aktie för djupgående AI-analys av alla faktorer.")

        if not df.empty and "ticker" in df.columns:
            tickers = sorted(df["ticker"].tolist())
            col1, col2 = st.columns([3, 1])
            with col1:
                sel_ticker = st.selectbox("Välj aktie", tickers, key="ai_stock_ticker")
            with col2:
                force_refresh = st.checkbox("Hoppa över cache", key="ai_stock_refresh")

            if st.button("🤖 Analysera aktie", key="btn_stock_analysis",
                         type="primary", use_container_width=True):
                with st.spinner(f"Analyserar {sel_ticker}..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.analyze_stock(
                            sel_ticker, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Analys misslyckades: {e}")

            # Visa snabbdata för vald aktie
            if sel_ticker:
                row = df[df["ticker"] == sel_ticker]
                if not row.empty:
                    r = row.iloc[0]
                    st.markdown("---")
                    st.caption("📋 Snabbdata")
                    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
                    with cc1:
                        st.metric("Score", f"{r.get('score_total', '—'):.0f}/100" if not pd.isna(r.get('score_total')) else "—")
                    with cc2:
                        st.metric("Entry", r.get("entry_signal", "—"))
                    with cc3:
                        st.metric("Trend", r.get("trend_signal", "—"))
                    with cc4:
                        st.metric("RSI", f"{r.get('rsi_14', '—'):.0f}" if not pd.isna(r.get('rsi_14', '—')) else "—")
                    with cc5:
                        st.metric("Piotroski", f"{r.get('piotroski_f', '—')}/9" if not pd.isna(r.get('piotroski_f', '—')) else "—")
        else:
            st.info("Ingen scandata tillgänglig för aktieval.")

    # ── Flik 3: Compare Two Stocks (Feature 2c) ────────────────────────────
    with tab_compare:
        st.subheader("🔄 AI-jämförelse – två aktier")
        st.caption("Jämför två aktier sida vid sida med AI-analys.")

        if not df.empty and "ticker" in df.columns:
            tickers = sorted(df["ticker"].tolist())
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                 ticker_a = st.selectbox("Aktie A", tickers, key="ai_cmp_a")
            with col2:
                 ticker_b = st.selectbox("Aktie B", tickers, index=min(1, len(tickers)-1), key="ai_cmp_b")
            with col3:
                 force_refresh = st.checkbox("Hoppa över cache", key="ai_cmp_refresh")

            if st.button("🤖 Jämför aktier", key="btn_compare",
                         type="primary", use_container_width=True):
                with st.spinner(f"Jämför {ticker_a} vs {ticker_b}..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.compare_stocks(
                            ticker_a, ticker_b, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Jämförelse misslyckades: {e}")

            # Snabbjämförelsetabell
            if ticker_a and ticker_b and ticker_a != ticker_b:
                row_a = df[df["ticker"] == ticker_a].iloc[0] if not df[df["ticker"] == ticker_a].empty else None
                row_b = df[df["ticker"] == ticker_b].iloc[0] if not df[df["ticker"] == ticker_b].empty else None
                if row_a is not None and row_b is not None:
                    st.markdown("---")
                    st.caption("📋 Snabbjämförelse")
                    cmp_data = []
                    for field, label in [("score_total", "Total Score"), ("score_momentum", "Momentum"),
                                         ("score_value", "Värdering"), ("score_quality", "Kvalitet"),
                                         ("score_growth", "Tillväxt"), ("rsi_14", "RSI"),
                                         ("pe_trailing", "P/E"), ("roe", "ROE"),
                                         ("return_12m", "12m-avkastning"), ("price_vs_ma200", "vs MA200")]:
                        va = row_a.get(field)
                        vb = row_b.get(field)
                        if va is not None and not pd.isna(va):
                            va = f"{va:.1f}" if isinstance(va, float) else va
                        if vb is not None and not pd.isna(vb):
                            vb = f"{vb:.1f}" if isinstance(vb, float) else vb
                        cmp_data.append({"Mått": label, ticker_a: va if va is not None else "—", ticker_b: vb if vb is not None else "—"})
                    st.dataframe(pd.DataFrame(cmp_data), use_container_width=True, hide_index=True)
        else:
            st.info("Ingen scandata tillgänglig för jämförelse.")

    # ── Flik 4: Sector Analysis (Feature 2d) ───────────────────────────────
    with tab_sector:
        st.subheader("🏭 AI-sektoranalys")
        st.caption("Få en AI-genererad analys av en hel sektor.")

        if not df.empty and "sector" in df.columns:
            sectors = sorted(df["sector"].dropna().unique().tolist())
            col1, col2 = st.columns([3, 1])
            with col1:
                sel_sector = st.selectbox("Välj sektor", sectors, key="ai_sector")
            with col2:
                force_refresh = st.checkbox("Hoppa över cache", key="ai_sector_refresh")

            if st.button("🤖 Analysera sektor", key="btn_sector_analysis",
                         type="primary", use_container_width=True):
                with st.spinner(f"Analyserar sektorn {sel_sector}..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.analyze_sector(
                            sel_sector, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Sektoranalys misslyckades: {e}")

            # Visa sektorns bolag
            if sel_sector:
                st.markdown("---")
                sec_df = df[df["sector"] == sel_sector].copy()
                st.caption(f"📋 Bolag i sektorn ({len(sec_df)} st)")
                show_cols = [c for c in ["ticker", "name", "score_total", "entry_signal",
                                         "trend_signal", "rsi_14"] if c in sec_df.columns]
                if show_cols:
                    st.dataframe(sec_df[show_cols].reset_index(drop=True), use_container_width=True, height=300)
        else:
            st.info("Ingen sektordata tillgänglig.")

    # ── Flik 5: AI Chat (adaptiv med historik) ─────────────────────────────
    with tab_chat:
        st.subheader("AI-chatt – fraga MarketScan AI")
        st.caption("Stall fragor om marknaden, aktier, strategier. Skriv t.ex. 'sok bland 50 basta' for att fa mer data.",
                   unsafe_allow_html=True)

        # Initiera chatt-historik i session state
        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []

        # Knapp för att rensa historik
        col_clear, col_refresh = st.columns([1, 3])
        with col_clear:
            if st.button("Rensa historik", key="btn_clear_chat"):
                st.session_state["chat_history"] = []
                st.rerun()
        with col_refresh:
            force_refresh = st.checkbox("Hoppa over cache", key="ai_chat_refresh2")

        # Visa chatt-historik (senaste 20 meddelanden)
        for msg in st.session_state["chat_history"][-20:]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Input
        prompt = st.chat_input("Stall en fraga om marknaden...")

        if prompt:
            # Visa anvandarens meddelande
            with st.chat_message("user"):
                st.markdown(prompt)

            # Bygg adaptiv kontext
            context_parts = []

            # 1. Extrahera onskat antal ur fragan (t.ex. "50 basta", "top 100")
            import re
            match_num = re.search(r"(\d+)", prompt)
            top_n = int(match_num.group(1)) if match_num else 10
            top_n = max(3, min(top_n, 200))

            # 2. Global scan-data
            if not df.empty:
                context_parts.append(f"Global scan: {len(df)} bolag scannade")
                if "score_total" in df.columns:
                    context_parts.append(f"snittscore {df['score_total'].mean():.1f}")
                if "entry_signal" in df.columns:
                    n_stark = int((df["entry_signal"] == "STARK").sum())
                    context_parts.append(f"STARK-signaler: {n_stark}")

                # Adaptiv topplista – dynamiskt baserat pa siffra i fragan
                score_col = "score_total"
                if score_col in df.columns:
                    top_df = df.nlargest(top_n, score_col)
                    topp_lista = "; ".join(
                        f"{r['ticker']} ({r[score_col]:.0f}p)"
                        for _, r in top_df.iterrows()
                    )
                    context_parts.append(f"Topp {top_n}: {topp_lista}")

            # 3. Smabolagsdata
            if not sc_df.empty:
                sc_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
                context_parts.append(f"Smabolag: {len(sc_df)} bolag")
                if sc_col in sc_df.columns:
                    context_parts.append(f"smabolagssnitt: {sc_df[sc_col].mean():.1f}")
                    sc_top = sc_df.nlargest(top_n, sc_col)
                    sc_lista = "; ".join(
                        f"{r['ticker']} ({r[sc_col]:.0f}p)"
                        for _, r in sc_top.iterrows()
                    )
                    context_parts.append(f"Topp {top_n} smabolag: {sc_lista}")

            # 4. Bygg kontext-strang
            context_str = ". ".join(context_parts) + "." if context_parts else ""

            # 5. Bygg historik-kontext (senaste 6 meddelanden)
            history_context = ""
            if st.session_state["chat_history"]:
                recent = st.session_state["chat_history"][-6:]
                history_lines = []
                for m in recent:
                    role = "anvandare" if m["role"] == "user" else "AI"
                    # Begransa langden pa tidigare svar
                    content = m["content"][:300]
                    history_lines.append(f"{role}: {content}")
                history_context = "\n".join(history_lines)

            # 6. Kombinera all kontext
            # Anvander chat_history direkt som lista for battre AI-forstaelse
            full_context = context_str

            # 7. Anropa AI med historik som lista
            with st.chat_message("assistant"):
                with st.spinner("AI tanker..."):
                    try:
                        depth = _get_depth()
                        history_data = st.session_state.get("chat_history", [])
                        result = ai_analysis.ai_chat(
                            prompt,
                            context=full_context,
                            history=history_data,  # Skicka som lista, inte text
                            force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(result)
                    except Exception as e:
                        st.error(f"Chatten misslyckades: {e}")
                        result = f"Fel: {e}"

            # 8. Spara i historik
            st.session_state["chat_history"].append({"role": "user", "content": prompt})
            st.session_state["chat_history"].append({"role": "assistant", "content": result})

            # Begransa historik till 20 meddelanden
            if len(st.session_state["chat_history"]) > 20:
                st.session_state["chat_history"] = st.session_state["chat_history"][-20:]

            st.rerun()

    # ── Flik 6: Portfolio Optimizer (Feature 4) ────────────────────────────
    with tab_portfolio:
        st.subheader("💼 AI-portföljoptimering")
        st.caption("Få AI-analys av din portfölj med förslag på förbättringar.")

        if not holdings.empty:
            if st.button("🤖 Analysera portfölj", key="btn_portfolio_ai_tab",
                         type="primary", use_container_width=True):
                with st.spinner("Analyserar portfölj..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.analyze_portfolio(
                            holdings, df=df if not df.empty else None,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Portföljanalys misslyckades: {e}")

            # Visa portföljinnehav
            st.markdown("---")
            st.caption(f"📋 Dina {len(holdings)} innehav")
            if not df.empty and "ticker" in df.columns:
                score_lu = df.set_index("ticker").to_dict("index")
            else:
                score_lu = {}
            rows = []
            for _, h in holdings.iterrows():
                t = h["ticker"]
                sc = score_lu.get(t, {})
                rows.append({
                    "Ticker": t,
                    "Score": sc.get("score_total", "—"),
                    "Entry": sc.get("entry_signal", "—"),
                    "Trend": sc.get("trend_signal", "—"),
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Inga portföljinnehav hittade. Lägg till innehav i Admin-fliken först.")

    # ── Flik 7: News Analysis (Feature 5) ──────────────────────────────────
    with tab_news:
        st.subheader("📰 AI-nyhetsanalys")
        st.caption("Sök och analysera nyheter för en specifik aktie.")

        # Sökfält för aktie (även om den inte finns i scan-datan)
        news_search = st.text_input("Sök aktie (ticker eller bolagsnamn)", "",
                                    key="news_search_input",
                                    placeholder="t.ex. TSLA, AAPL, Investor, Volvo...")
        news_ticker = ""

        if news_search.strip():
            news_hits = _search_ticker_yfinance(news_search.strip())
            if news_hits:
                news_options = {f"{h['ticker']} — {h['name'][:50]}": h for h in news_hits}
                news_label = st.selectbox("Välj från sökresultat", list(news_options.keys()),
                                          key="ai_news_ticker_select")
                news_ticker = news_options[news_label]["ticker"]

        # Fallback: om inget sökresultat, använd dropdown från scandata
        if not news_ticker and not df.empty and "ticker" in df.columns and df["ticker"].nunique() > 0:
            tickers = sorted(df["ticker"].dropna().unique().tolist())
            news_ticker = st.selectbox("Eller välj från senaste scan", tickers, key="ai_news_ticker_fallback")
        elif not news_ticker:
            st.info("Sök på en aktie ovan för att komma igång.")

        col1, col2 = st.columns([3, 1])
        with col1:
            if news_ticker:
                st.markdown(f"**Vald aktie:** `{news_ticker}`")
        with col2:
            force_refresh = st.checkbox("Hoppa över cache", key="ai_news_refresh")

            if st.button("📰 Hämta och analysera nyheter", key="btn_news_analysis",
                         type="primary", use_container_width=True):
                with st.spinner(f"Hämtar nyheter för {news_ticker}..."):
                    try:
                        # Försök hämta nyheter via Finnhub
                        news_items = None
                        try:
                            from core.news_fetcher import fetch_company_news
                            items = fetch_company_news(news_ticker, days_back=7)
                            if items:
                                news_items = [{"title": n.get("headline", n.get("title", "")),
                                               "summary": n.get("summary", n.get("description", "")),
                                               "source": n.get("source", "Finnhub"),
                                               "date": n.get("datetime", n.get("publishedAt", ""))}
                                              for n in items[:10]]
                        except ImportError:
                            pass
                        except Exception:
                            pass

                        depth = _get_depth()
                        result = ai_analysis.analyze_news(
                            news_ticker, news_items=news_items, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)

                        # Visa rånyheter
                        if news_items:
                            st.markdown("---")
                            st.caption(f"📋 Senaste {len(news_items)} nyheterna för {news_ticker}")
                            for item in news_items:
                                st.markdown(f"- **{item['title']}** ({item.get('source', '?')})")
                    except Exception as e:
                        st.error(f"❌ Nyhetsanalys misslyckades: {e}")

            # Visa senaste nyheter i en expander
            with st.expander("Visa senaste nyheter utan AI-analys"):
                try:
                    from core.news_fetcher import fetch_company_news
                    if 'news_ticker' in dir() and news_ticker:
                        raw_news = fetch_company_news(news_ticker, days_back=3)
                        if raw_news:
                            for n in raw_news[:5]:
                                title = n.get("headline", n.get("title", "—"))
                                st.markdown(f"- {title}")
                        else:
                            st.caption("Inga nyheter hittade.")
                    else:
                        st.caption("Välj en ticker först.")
                except Exception:
                    st.caption("Kunde inte hämta nyheter (news_fetcher saknas eller API-nyckel ej konfigurerad).")


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER – FILHANTERING (lokal)
# ══════════════════════════════════════════════════════════════════════════════

def _save_holdings_df(df: pd.DataFrame) -> bool:
    """Spara holdings.csv."""
    try:
        path = ROOT / "holdings.csv"
        df.to_csv(path, index=False)
        return True
    except Exception as e:
        st.error(f"Kunde inte spara: {e}")
        return False


def _save_watchlist_data(items: list):
    path = DATA_DIR / "watchlist.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def _search_ticker_yfinance(query: str) -> list:
    """Sök ticker via yfinance. Returnerar lista med {ticker, name}.
    
    Forbattrad version:
    - Okar sökresultat till 20 for att hitta svenska aktier
    - Direkt ticker-koll om fragan ser ut som en ticker
    - Prioriterar aktier (EQUITY) framfor ETFer
    """
    if not query or len(query) < 1:
        return []
    
    hits = []
    try:
        # Steg 1: Om fragan ser ut som en ticker (kort, versaler, punkter), kolla direkt
        clean_q = query.strip().upper()
        is_ticker_like = (
            len(clean_q) <= 15 and
            (clean_q.isalpha() or "." in clean_q or "-" in clean_q)
        )
        
        if is_ticker_like:
            try:
                ticker_info = yf.Ticker(clean_q).info or {}
                if ticker_info.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
                    hits.append({
                        "ticker": clean_q,
                        "name": ticker_info.get("shortName") or ticker_info.get("longName") or clean_q,
                        "exchange": ticker_info.get("exchange", ""),
                    })
            except Exception:
                pass
        
        # Steg 2: Sok fritt med Yahoo Search (okad till 20 resultat)
        results = yf.Search(query, max_results=20).quotes or []
        seen_tickers = {h["ticker"] for h in hits}
        for r in results:
            ticker = r.get("symbol", "")
            if ticker in seen_tickers:
                continue
            qtype = r.get("quoteType", "")
            if qtype in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
                hits.append({
                    "ticker": ticker,
                    "name": r.get("shortname") or r.get("longname") or "",
                    "exchange": r.get("exchange", ""),
                })
                seen_tickers.add(ticker)
        
        # Sortera: aktier forst, sen ETFer
        hits.sort(key=lambda h: (0 if h.get("exchange") in ("STO", "OMX", "HE", "CO", "OL", "DE", "PA", "L", "SW") else 1))
        
        return hits[:15]  # Max 15 resultat
    except Exception:
        return hits if hits else []


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN-LÖSENORDSSKYDD
# ══════════════════════════════════════════════════════════════════════════════

def _check_admin_access() -> bool:
    """Kontrollera om användaren är admin (lösenordsskyddat).
    
    Lösenordet hämtas från:
    1. Streamlit Secrets: ADMIN_PASSWORD
    2. Om ej satt → alla är admin (lokalt)
    """
    admin_pw = st.secrets.get("ADMIN_PASSWORD", "") if hasattr(st, "secrets") else os.getenv("ADMIN_PASSWORD", "")
    
    # Inget lösenord satt → öppen admin (t.ex. lokalt)
    if not admin_pw:
        return True
    
    # Kolla session
    if st.session_state.get("admin_authenticated", False):
        return True
    
    # Visa inloggningsruta
    st.title("🔒 Admin – Lösenordsskyddad sida")
    st.info(
        "Den här sidan kräver administratörsbehörighet. "
        "Kontakta administratören för lösenordet."
    )
    
    pw_input = st.text_input(
        "Ange admin-lösenord",
        type="password",
        key="admin_pw_input",
        placeholder="••••••••",
    )
    
    if st.button("🔓 Lås upp", key="btn_admin_unlock", use_container_width=True):
        if pw_input == admin_pw:
            st.session_state["admin_authenticated"] = True
            st.rerun()
        else:
            st.error("❌ Fel lösenord!")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# SIDA 7 – ADMIN (Portfölj, Watchlist, GitHub Actions, Avanza-import)
# ══════════════════════════════════════════════════════════════════════════════

def page_admin():
    """Admin-sida – kräver lösenord."""
    
    # Kolla admin-åtkomst först
    if not _check_admin_access():
        # Lås upp-knapp för utloggning (om man vill logga ut)
        if st.session_state.get("admin_authenticated", False):
            if st.button("🚪 Logga ut från admin", key="btn_admin_logout"):
                st.session_state["admin_authenticated"] = False
                st.rerun()
        return
    
    st.title("🔧 Admin – Hantera portfölj, bevakning & scannar")

    tab_wl, tab_hold, tab_scan, tab_import, tab_health = st.tabs([
        "⭐ Bevakningslista", "💼 Portfölj", "🚀 Starta scan", "📥 Avanza-import",
        "🩺 Universe Health"
    ])

    # ── St1: Bevakningslista ────────────────────────────────────────────────
    with tab_wl:
        st.subheader("⭐ Bevakningslista")

        # Ladda nuvarande
        items = load_watchlist()

        # Visa nuvarande lista
        if items:
            wl_df = pd.DataFrame(items)
            st.dataframe(wl_df, use_container_width=True, hide_index=True)

            # Ta bort ticker
            remove_ticker = st.selectbox(
                "Ta bort ticker", [""] + [i["ticker"] for i in items],
                key="wl_remove"
            )
            if remove_ticker and st.button("🗑️ Ta bort", key="btn_wl_remove"):
                items = [i for i in items if i["ticker"] != remove_ticker]
                _save_watchlist_data(items)
                st.success(f"`{remove_ticker}` borttagen från bevakningslistan!")
                st.rerun()
        else:
            st.info("Bevakningslistan är tom.")

        st.markdown("---")
        st.markdown("### Lägg till ny ticker")

        search_q = st.text_input("Sök aktie (ticker eller namn)", key="wl_search",
                                 placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
        if search_q:
            hits = _search_ticker_yfinance(search_q)
            if hits:
                options = {f"{h['ticker']} — {h['name'][:40]}": h for h in hits}
                selected = st.selectbox("Välj från sökresultat", list(options.keys()),
                                        key="wl_hit")
                if selected:
                    h = options[selected]
                    col1, col2 = st.columns([2, 1])
                    if col1.button("✅ Lägg till i bevakningslistan", key="btn_wl_add"):
                        new_ticker = h["ticker"]
                        exists = any(i["ticker"] == new_ticker for i in items)
                        if not exists:
                            items.append({
                                "ticker": new_ticker,
                                "name": h["name"],
                                "added": str(date.today()),
                            })
                            _save_watchlist_data(items)
                            st.success(f"`{new_ticker}` tillagd i bevakningslistan!")
                            st.rerun()
                        else:
                            st.info(f"`{new_ticker}` finns redan i bevakningslistan.")
            else:
                st.caption("Inga sökresultat. Prova med annat sökord.")

        # Snabb inmatning manuellt
        with st.expander("Eller lägg till manuellt (ticker)"):
            manual_ticker = st.text_input("Ticker (t.ex. AAPL)", key="wl_manual",
                                          placeholder="Ticker-symbol").upper().strip()
            manual_name = st.text_input("Namn (valfritt)", key="wl_manual_name")
            if st.button("➕ Lägg till", key="btn_wl_manual"):
                if manual_ticker:
                    exists = any(i["ticker"] == manual_ticker for i in items)
                    if not exists:
                        items.append({
                            "ticker": manual_ticker,
                            "name": manual_name or manual_ticker,
                            "added": str(date.today()),
                        })
                        _save_watchlist_data(items)
                        st.success(f"`{manual_ticker}` tillagd!")
                        st.rerun()
                    else:
                        st.info(f"`{manual_ticker}` finns redan.")
                else:
                    st.warning("Ange en ticker.")

    # ── Flik 2: Portfölj ──────────────────────────────────────────────────
    with tab_hold:
        st.subheader("💼 Portfölj (holdings.csv)")

        holdings = load_portfolio()

        # --- Ta bort innehav ---
        col_del_left, col_del_right = st.columns([3, 1])
        with col_del_left:
            if not holdings.empty:
                remove_h = st.selectbox(
                    "Välj innehav att ta bort",
                    [""] + holdings["ticker"].tolist(),
                    key="hold_remove"
                )
            else:
                remove_h = ""
        with col_del_right:
            if remove_h and st.button("🗑️ Ta bort", key="btn_hold_remove",
                                      use_container_width=True):
                holdings = load_portfolio()
                if remove_h in holdings["ticker"].values:
                    holdings = holdings[holdings["ticker"] != remove_h]
                    ok = _save_holdings_df(holdings)
                    if ok:
                        st.cache_data.clear()
                        st.success(f"`{remove_h}` borttagen från portföljen!")
                        st.rerun()
                    else:
                        st.error("Kunde inte spara. Kontrollera filrättigheter.")
                else:
                    st.info(f"`{remove_h}` finns inte i portföljen.")

        if not holdings.empty:
            st.dataframe(holdings, use_container_width=True, hide_index=True)
        else:
            st.info("Portföljen är tom. Lägg till innehav nedan.")

        st.markdown("---")
        st.markdown("### Lägg till / uppdatera innehav")

        # Sök ticker (valfritt) – fyller i ticker-fältet automatiskt
        search_h = st.text_input("Sök aktie (ticker eller namn) – valfritt", key="hold_search",
                                 placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
        suggested_ticker = ""
        if search_h:
            hits = _search_ticker_yfinance(search_h)
            if hits:
                options = {f"{h['ticker']} — {h['name'][:40]}": h for h in hits}
                selected = st.selectbox("Välj från sökresultat", [""] + list(options.keys()),
                                        key="hold_hit")
                if selected:
                    suggested_ticker = options[selected]["ticker"]

        # Ticker, antal, pris – använder text_inputs egna key som session_state
        # (st.text_input med key="hold_ticker_input" lagrar sitt varde i
        #  st.session_state["hold_ticker_input"] automatiskt)

        # Uppdatera session_state om användaren valde från sök – använd SAMMA nyckel
        if suggested_ticker:
            st.session_state["hold_ticker_input"] = suggested_ticker

        # Vanliga widgets (INGET st.form – så value uppdateras korrekt)
        col1, col2, col3 = st.columns(3)
        with col1:
            ticker = st.text_input(
                "Ticker *",
                key="hold_ticker_input",
                placeholder="AAPL"
            ).upper().strip()
        with col2:
            shares = st.number_input("Antal aktier", min_value=0.0, step=1.0,
                                     format="%.2f", key="hold_shares")
        with col3:
            cost = st.number_input("Inköpspris (SEK)", min_value=0.0, step=1.0,
                                   format="%.2f", key="hold_cost")

        saved = st.button("💾 Spara i portföljen", key="btn_hold_save",
                          use_container_width=True, type="primary")

        if saved:
            ticker = st.session_state.get("hold_ticker_input", "").upper().strip()
            shares = st.session_state.get("hold_shares", 0)
            cost = st.session_state.get("hold_cost", 0)

            if not ticker:
                st.warning("Ange en ticker.")
            elif shares <= 0:
                st.warning("Ange antal aktier (> 0).")
            elif cost <= 0:
                st.warning("Ange inköpspris (> 0).")
            else:
                # Ladda om senaste portföljdata
                holdings = load_portfolio()
                if ticker in holdings["ticker"].values:
                    holdings.loc[holdings["ticker"] == ticker, "shares"] = shares
                    holdings.loc[holdings["ticker"] == ticker, "cost_basis"] = cost
                    msg = f"`{ticker}` uppdaterad i portföljen!"
                else:
                    new_row = pd.DataFrame([{"ticker": ticker, "shares": shares,
                                              "cost_basis": cost}])
                    holdings = pd.concat([holdings, new_row], ignore_index=True)
                    msg = f"`{ticker}` tillagd i portföljen!"
                ok = _save_holdings_df(holdings)
                if ok:
                    st.cache_data.clear()
                    st.success(msg)
                    st.rerun()
                else:
                    st.error("Kunde inte spara portföljen. Se felmeddelandet ovan.")

    # ── Flik 3: GitHub Actions – starta scannar ─────────────────────────────
    with tab_scan:
        st.subheader("🚀 Starta scanning via GitHub Actions")
        st.caption("Triggar en scanning i GitHub. Scannern körs i molnet (även när din dator är avstängd).")

        # Läs GITHUB_TOKEN från miljövariabel eller session state
        gh_token = os.getenv("GITHUB_TOKEN") or st.session_state.get("gh_token", "")
        gh_owner = os.getenv("GITHUB_OWNER") or "hankkontakt"
        gh_repo  = os.getenv("GITHUB_REPO")  or "stock-scanner"

        if not gh_token:
            gh_token = st.text_input(
                "GitHub token (krävs för att starta scannar)",
                type="password",
                key="gh_token_input",
                placeholder="ghp_...",
            )
            st.session_state["gh_token"] = gh_token
        else:
            st.success("✅ GitHub token läst från miljövariabel")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**🌅 Morgonscan (vardagar)**")
            if st.button("▶️ Starta morgonscan", key="btn_morning",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "morning_scan.yml", "Morgonscan")
                st.toast("Morgonscan startad! ⏳", icon="🌅")

            st.markdown("**🌆 Kvällsscan (vardagar)**")
            if st.button("▶️ Starta kvällsscan", key="btn_evening",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "evening_scan.yml", "Kvällsscan")
                st.toast("Kvällsscan startad! ⏳", icon="🌆")

        with col_b:
            st.markdown("**📊 Veckoscan (söndagar)**")
            if st.button("▶️ Starta veckoscan", key="btn_weekly",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "weekly_scan.yml", "Veckoscan",
                                     inputs={"send_email": "true"})
                st.toast("Veckoscan startad! ⏳", icon="📊")

            st.markdown("**🏆 Småbolagsscan (måndagar)**")
            col_c, col_d = st.columns(2)
            with col_c:
                market = st.selectbox("Marknad", ["all", "first_north", "small_cap", "spotlight"],
                                      key="sc_market", label_visibility="collapsed")
            with col_d:
                top_n = st.number_input("Topp N", min_value=5, max_value=50, value=20,
                                        key="sc_top", label_visibility="collapsed")
            if st.button("▶️ Starta småbolagsscan", key="btn_smallcap",
                         disabled=not gh_token, use_container_width=True):
                _trigger_gh_workflow(gh_token, gh_owner, gh_repo,
                                     "smallcap_scan.yml", "Småbolagsscan",
                                     inputs={"market": market, "top_n": str(top_n),
                                             "send_email": "true"})
                st.toast("Småbolagsscan startad! ⏳", icon="🏆")

        st.markdown("---")
        st.info(
            "Scan-resultaten visas här när GitHub Actions har kört klart och "
            "committat tillbaka CSV-filerna (tar 2–10 min beroende på scannern). "
            "Uppdatera sidan för att se nya resultat."
        )

    # ── Flik 4: Avanza-import ──────────────────────────────────────────────
    with tab_import:
        st.subheader("📥 Importera portfölj från Avanza CSV")
        st.caption("Exportera din portfölj från Avanza som CSV och ladda upp här.")

        uploaded = st.file_uploader("Välj Avanza CSV-fil", type=["csv"],
                                    key="avanza_csv")
        if uploaded is not None:
            try:
                # Skriv till temporär fil för att kunna använda avanza_import.parse_avanza_csv()
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name
                try:
                    df_avanza = avanza_import.parse_avanza_csv(tmp_path)
                finally:
                    os.unlink(tmp_path)

                if df_avanza.empty:
                    st.error(
                        "Kunde inte läsa filen. Kontrollera att det är en "
                        "Avanza-export (kolumner: namn, antal, inköpspris)."
                    )
                else:
                    st.success(f"Läste {len(df_avanza)} rader från Avanza-filen.")
                    st.caption("Granska och bekräfta importen nedan.")

                    # Konvertera DataFrame till listan av dicts som resten av flödet förväntar sig
                    rows = []
                    for _, r in df_avanza.iterrows():
                        rows.append({
                            "name": r.get("name", ""),
                            "shares": r.get("shares", 0),
                            "cost_basis": r.get("cost_basis", 0),
                        })

                    import_data = []
                    for i, row in enumerate(rows):
                        hits = _search_ticker_yfinance(row["name"])
                        suggested = hits[0]["ticker"] if hits else ""
                        with st.container(border=True):
                            cc1, cc2, cc3, cc4, cc5 = st.columns([3, 1, 1, 2, 2])
                            with cc1:
                                st.markdown(f"**{row['name']}**")
                            with cc2:
                                st.markdown(f"Antal: {row['shares']}")
                            with cc3:
                                st.markdown(f"Pris: {row['cost_basis']}")
                            with cc4:
                                ticker_val = st.text_input(
                                    "Ticker", value=suggested,
                                    key=f"import_ticker_{i}",
                                    label_visibility="collapsed",
                                ).upper().strip()
                            with cc5:
                                import_me = st.checkbox("Importera", value=True,
                                                        key=f"import_ok_{i}")
                            import_data.append({
                                "row": row,
                                "ticker": ticker_val,
                                "import": import_me,
                            })

                    if st.button("✅ Bekräfta import", type="primary",
                                 use_container_width=True):
                        holdings = load_portfolio()
                        n_add = 0
                        n_upd = 0
                        for item in import_data:
                            if not item["import"] or not item["ticker"]:
                                continue
                            t = item["ticker"]
                            s = float(item["row"]["shares"])
                            c = item["row"]["cost_basis"]
                            if t in holdings["ticker"].values:
                                holdings.loc[holdings["ticker"] == t, "shares"] = s
                                holdings.loc[holdings["ticker"] == t, "cost_basis"] = c
                                n_upd += 1
                            else:
                                new_row = pd.DataFrame([{
                                    "ticker": t, "shares": s, "cost_basis": c
                                }])
                                holdings = pd.concat([holdings, new_row], ignore_index=True)
                                n_add += 1
                        _save_holdings_df(holdings)
                        st.success(f"Import klar! {n_add} tillagda, {n_upd} uppdaterade.")
                        st.rerun()
            except Exception as e:
                    st.error(f"Fel vid läsning av fil: {e}")

    # ── Flik 5: Universe Health ────────────────────────────────────────────
    with tab_health:
        st.subheader("🩺 Universe Health – underhåll av aktieuniversum")
        st.caption(
            "Upptäck avnoterade/ogiltiga tickers, hantera svartlista "
            "och hitta nya intressanta aktier med AI-hjälp."
        )

        try:
            from core.universe_health import (
                detect_invalid_tickers, suggest_replacements,
                find_new_stocks, run_health_check,
                load_blacklist, add_to_blacklist, remove_from_blacklist,
            )
        except ImportError as e:
            st.error(f"Kunde inte ladda universe_health-modulen: {e}")
            return

        # -- Blacklist overview --
        blacklist = load_blacklist()
        st.markdown(f"**Svartlista:** {len(blacklist)} tickers")

        with st.expander("📋 Visa svartlista", expanded=False):
            if blacklist:
                st.dataframe(pd.DataFrame(blacklist), use_container_width=True, hide_index=True)

                # Remove from blacklist
                remove_bl = st.selectbox(
                    "Ta bort från svartlistan",
                    [""] + [i.get("ticker", "") for i in blacklist],
                    key="bl_remove",
                )
                if remove_bl and st.button("🗑️ Ta bort", key="btn_bl_remove"):
                    if remove_from_blacklist(remove_bl):
                        st.success(f"`{remove_bl}` borttagen från svartlistan!")
                        st.rerun()
            else:
                st.info("Svartlistan är tom.")

        # Manual add to blacklist
        with st.expander("➕ Lägg till i svartlistan manuellt", expanded=False):
            col_bl_t, col_bl_r = st.columns([2, 3])
            with col_bl_t:
                bl_ticker = st.text_input("Ticker", key="bl_add_ticker",
                                          placeholder="AAPL").upper().strip()
            with col_bl_r:
                bl_reason = st.text_input("Anledning", key="bl_add_reason",
                                          placeholder="t.ex. avnoterad")
            if st.button("➕ Lägg till i svartlistan", key="btn_bl_add"):
                if bl_ticker:
                    if add_to_blacklist(bl_ticker, bl_reason or "manuell"):
                        st.success(f"`{bl_ticker}` tillagd i svartlistan!")
                        st.rerun()
                    else:
                        st.info(f"`{bl_ticker}` finns redan i svartlistan.")
                else:
                    st.warning("Ange en ticker.")

        st.markdown("---")

        # -- Run Health Check --
        st.markdown("### 🔍 Kör hälsokontroll")
        st.caption("Kontrollerar alla tickers i senaste scandatan mot yfinance.")

        health_provider = st.selectbox(
            "AI-provider för nya aktieförslag",
            ["auto", "deepseek", "gemini"],
            format_func=lambda k: {
                "auto": f"Auto ({config.AI_PROVIDER})",
                "deepseek": "DeepSeek (komplex, kostar)",
                "gemini": "Gemini (enkel, gratis)",
            }.get(k, k),
            key="health_provider",
        )

        if st.button("🩺 Kör hälsokontroll", key="btn_health_check",
                     type="primary", use_container_width=True):
            with st.spinner("Kör hälsokontroll (kan ta några minuter)..."):
                try:
                    # Ladda senaste scandata
                    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                    if not reports:
                        st.warning("Ingen scandata hittad. Kör en scan först.")
                    else:
                        df_health = pd.read_csv(reports[0], low_memory=False)
                        df_health.columns = df_health.columns.str.strip()

                        result = run_health_check(df=df_health, provider=health_provider)
                        st.success("✅ Hälsokontroll klar!")

                        # Visa resultat
                        col_h1, col_h2, col_h3 = st.columns(3)
                        with col_h1:
                            st.metric("Ogiltiga tickers", len(result.get("invalid_tickers", [])))
                        with col_h2:
                            st.metric("Svartlistade", result.get("blacklist_count", 0))
                        with col_h3:
                            st.metric("Nya AI-förslag", len(result.get("new_stocks", [])))

                        # Invalid tickers
                        invalid = result.get("invalid_tickers", [])
                        if invalid:
                            st.markdown("---")
                            st.error(f"⚠️ Hittade {len(invalid)} ogiltiga/avnoterade tickers!")
                            inv_df = pd.DataFrame(invalid)
                            st.dataframe(inv_df, use_container_width=True, hide_index=True)

                            # Ersättningsförslag
                            st.markdown("### 💡 Ersättningsförslag")
                            suggestions = result.get("suggestions", {})
                            for bad_ticker, replacements in suggestions.items():
                                with st.expander(f"`{bad_ticker}` → ersättningsförslag", expanded=True):
                                    if replacements:
                                        rep_df = pd.DataFrame(replacements)
                                        st.dataframe(rep_df, use_container_width=True, hide_index=True)
                                        if st.button(f"➕ Lägg till `{replacements[0]['ticker']}` i bevakningslistan",
                                                     key=f"health_add_{bad_ticker}"):
                                            items = load_watchlist()
                                            if not any(i["ticker"] == replacements[0]["ticker"] for i in items):
                                                items.append({
                                                    "ticker": replacements[0]["ticker"],
                                                    "name": replacements[0].get("name", ""),
                                                    "added": str(date.today()),
                                                })
                                                _save_watchlist_data(items)
                                                st.success(f"{replacements[0]['ticker']} tillagd i bevakningslistan!")
                                                st.rerun()
                                            else:
                                                st.info("Finns redan i bevakningslistan.")
                                    else:
                                        st.caption("Inga ersättningsförslag tillgängliga.")
                        else:
                            st.success("✅ Alla tickers verkar vara giltiga!")

                        # New stock suggestions
                        new_stocks = result.get("new_stocks", [])
                        if new_stocks:
                            st.markdown("---")
                            st.subheader("🚀 AI-förslag: nya intressanta aktier")
                            st.caption("AI-genererade förslag på aktier att titta närmare på.")
                            for s in new_stocks:
                                ticker_s = s.get("ticker", "?")
                                name_s = s.get("name", "")
                                reason_s = s.get("reason", "")
                                with st.container(border=True):
                                    col_s1, col_s2 = st.columns([3, 1])
                                    with col_s1:
                                        st.markdown(f"**{ticker_s}** – {name_s}")
                                        if reason_s:
                                            st.caption(reason_s)
                                    with col_s2:
                                        if st.button("➕ Lägg till", key=f"health_new_{ticker_s}"):
                                            items = load_watchlist()
                                            if not any(i["ticker"] == ticker_s for i in items):
                                                items.append({
                                                    "ticker": ticker_s,
                                                    "name": name_s or ticker_s,
                                                    "added": str(date.today()),
                                                })
                                                _save_watchlist_data(items)
                                                st.success(f"{ticker_s} tillagd i bevakningslistan!")
                                                st.rerun()
                                            else:
                                                st.info("Finns redan i bevakningslistan.")

                except Exception as e:
                    st.error(f"❌ Hälsokontroll misslyckades: {e}")

        # -- Quick check: detect invalid tickers only --
        st.markdown("---")
        st.markdown("### ⚡ Snabbkontroll")
        st.caption("Kontrollera om specifika tickers är ogiltiga (utan AI-förslag).")
        if st.button("🔍 Kör snabbkontroll", key="btn_health_quick",
                     use_container_width=True):
            with st.spinner("Kontrollerar tickers..."):
                try:
                    reports = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
                    if reports:
                        df_quick = pd.read_csv(reports[0], low_memory=False)
                        df_quick.columns = df_quick.columns.str.strip()
                        invalid = detect_invalid_tickers(df_quick)
                        if invalid:
                            st.error(f"⚠️ Hittade {len(invalid)} ogiltiga tickers")
                            st.dataframe(pd.DataFrame(invalid), use_container_width=True, hide_index=True)
                        else:
                            st.success("✅ Alla tickers verkar giltiga!")
                except Exception as e:
                    st.error(f"❌ {e}")


def _trigger_gh_workflow(token: str, owner: str, repo: str,

                         workflow: str, label: str, inputs: dict = None):
    """Trigga en GitHub Actions workflow_dispatch."""
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    payload = {"ref": "main"}
    if inputs:
        payload["inputs"] = inputs
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "MarketScan-Streamlit",
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code in (204, 201, 200):
            st.success(f"✅ **{label}** startad via GitHub Actions!")
        else:
            st.error(f"❌ Kunde inte starta {label}: HTTP {resp.status_code}"
                     f"\n{resp.text[:200]}")
    except Exception as e:
        st.error(f"❌ Nätverksfel: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# HUVUD / ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def main():

    # Ladda all data
    scan_reports  = load_scan_reports()
    sc_reports    = load_smallcap_reports()
    holdings      = load_portfolio()
    watchlist     = load_watchlist()

    scan_dates = list(scan_reports.keys())
    sc_dates   = list(sc_reports.keys())

    # Bygg sidebar
    page, scan_date, sc_date, filters = build_sidebar(scan_dates, sc_dates)

    # Hämta aktuell DataFrame
    df    = scan_reports.get(scan_date,  pd.DataFrame()) if scan_dates else pd.DataFrame()
    sc_df = sc_reports.get(sc_date,      pd.DataFrame()) if sc_dates   else pd.DataFrame()

    # Uppdatera sektordropdowns i sidebaren med faktiska sektorer
    if not df.empty and "sector" in df.columns and page == "🔍 Veckoscanner":
        secs = sorted(df["sector"].dropna().unique().tolist())
        # Sätt ny multiselect om sektorer inte redan valts
        if not filters.get("sector"):
            filters["sector"] = []  # Ingen begränsning = visa alla
        # Lägg till sektorer i sidebar (efter att sidan byggs)
    if not sc_df.empty and "sector" in sc_df.columns and page == "🏦 Småbolag":
        secs = sorted(sc_df["sector"].dropna().unique().tolist())

    # Router
    if page == "📊 Översikt":
        page_overview(df, sc_df)

    elif page == "🔍 Veckoscanner":
        # Injicera faktiska sektorer i filter
        if not df.empty and "sector" in df.columns:
            secs = sorted(df["sector"].dropna().unique().tolist())
            if not filters.get("sector"):
                filters["sector"] = []  # visa alla
        page_weekly_scan(df, filters, holdings, watchlist)

    elif page == "🏦 Småbolag":
        if not sc_df.empty and "sector" in sc_df.columns:
            secs = sorted(sc_df["sector"].dropna().unique().tolist())
        page_smallcap(sc_df, filters)

    elif page == "💼 Portfölj":
        page_portfolio(df, holdings, watchlist)

    elif page == "📈 Teknisk analys":
        if not df.empty and "sector" in df.columns:
            secs = sorted(df["sector"].dropna().unique().tolist())
        page_technical(df, filters)

    elif page == "🤖 AI":
        page_ai(df, sc_df, holdings)

    elif page == "🔧 Admin":
        page_admin()


if __name__ == "__main__":

    main()
