"""
MarketScan Dashboard – Interaktiv börsanalys
============================================
Läser utdata från scan.py, smallcap/scanner.py och portfolio.py.

Kör lokalt : streamlit run streamlit_app.py
Deploya    : anslut GitHub-repo till streamlit.io/cloud
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Sökvägar ──────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
REPORT_DIR = ROOT / "reports"
DATA_DIR   = ROOT / "data"
sys.path.insert(0, str(ROOT))

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
        holdings = pd.read_csv(DATA_DIR / "holdings.csv")
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
             "💼 Portfölj", "📈 Teknisk analys"],
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

    tab1, tab2 = st.tabs(["📋 Tabell", "📊 Diagram"])

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


if __name__ == "__main__":
    main()
