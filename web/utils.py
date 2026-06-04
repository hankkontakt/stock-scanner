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


def _active_data_dir() -> Path:
    """Returnerar datakatalogen för den inloggade användaren.

    - Admin (username == 'admin') -> DATA_DIR (roten, bakåtkompatibelt)
    - Övriga användare -> DATA_DIR / 'users' / {username}
    - Ej inloggad / lokal körning -> DATA_DIR (fallback)
    """
    username = st.session_state.get("username", "")
    if not username or username == "admin":
        return DATA_DIR
    d = DATA_DIR / "users" / username
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_portfolio(data_dir: Path | None = None) -> pd.DataFrame:
    """Laddar holdings.csv för den inloggade användaren.
    Ingen cache - filen ändras när användaren lägger till tickers.
    Bakåtkompatibel: lägger till kolumnerna 'konto', 'typ' och 'buy_date' om de saknas."""
    base = data_dir if data_dir is not None else _active_data_dir()
    try:
        holdings = pd.read_csv(base / "holdings.csv")
        holdings["ticker"] = holdings["ticker"].str.upper()
        # Bakåtkompatibilitet - fyll i saknade kolumner
        if "konto" not in holdings.columns:
            holdings["konto"] = "Huvud"
        else:
            holdings["konto"] = holdings["konto"].fillna("Huvud")
        # typ: per-innehavs-klassificering (aktier/fond/etf/certificate)
        # Används för att avgöra om scanner-signaler ska visas
        if "typ" not in holdings.columns:
            holdings["typ"] = ""   # tomt = bestäms av kontotyp
        else:
            holdings["typ"] = holdings["typ"].fillna("")
        # buy_date: ISO-datumsträngformat (YYYY-MM-DD) eller tom sträng
        if "buy_date" not in holdings.columns:
            holdings["buy_date"] = ""
        else:
            holdings["buy_date"] = holdings["buy_date"].fillna("")
        # predicted_return_at_buy: ML-modellens prediktion vid köptillfället
        # Används för att jämföra "vad ML trodde" vs faktisk avkastning
        if "predicted_return_at_buy" not in holdings.columns:
            holdings["predicted_return_at_buy"] = None
        return holdings
    except Exception:
        return pd.DataFrame(columns=["ticker", "shares", "cost_basis", "konto", "typ", "buy_date"])


def load_watchlist(data_dir: Path | None = None) -> list:
    """Laddar watchlist.json för den inloggade användaren.
    Ingen cache - filen ändras när användaren lägger till tickers."""
    base = data_dir if data_dir is not None else _active_data_dir()
    try:
        return json.loads((base / "watchlist.json").read_text(encoding="utf-8"))
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _get(df: pd.DataFrame, col: str, default=None) -> pd.Series:
    # OBS: ingen @st.cache_data här - en felplacerad dekorator cachade tidigare
    # denna kolumn-accessor, vilket gav fel index/innehåll vid återanvändning.
    if col in df.columns:
        return df[col]
    return pd.Series([default] * len(df), index=df.index)



def pct_fmt(v, plus=True) -> str:
    try:
        v = float(v)
        s = f"{v*100:+.1f}%" if plus else f"{v*100:.1f}%"
        return s
    except Exception:
        return "--"


def num_fmt(v, decimals=1) -> str:
    try:
        return f"{float(v):.{decimals}f}"
    except Exception:
        return "--"



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
    """KPI-kort. Thin wrapper runt kpi_grid() för bakåtkompatibilitet.

    metrics = [(label, value, delta[, help]), ...]  — gammal tupel-form
    """
    try:
        from web.ui.components import kpi_grid
        kpi_grid([
            {
                "label": str(m[0]),
                "value": str(m[1]),
                "delta": str(m[2]) if len(m) > 2 and m[2] is not None else None,
                "help":  m[3] if len(m) > 3 else None,
            }
            for m in metrics
        ])
    except Exception:
        # Fallback: enkel inline-layout om kpi_grid inte är tillgänglig
        cols = st.columns(len(metrics))
        for col, item in zip(cols, metrics):
            col.metric(label=str(item[0]), value=str(item[1]),
                       delta=str(item[2]) if len(item) > 2 and item[2] else None)



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


def conviction_meter_chart(row) -> "go.Figure":
    """
    Radar/spider chart for the 8 factor scores of a single stock.
    row: dict or Series with score_value, score_quality, etc.
    Returns a Plotly figure ready for st.plotly_chart().
    """
    factors = [
        ("Värde",      row.get("score_value",    50) or 50),
        ("Kvalitet",   row.get("score_quality",  50) or 50),
        ("Momentum",   row.get("score_momentum", 50) or 50),
        ("Tillväxt",   row.get("score_growth",   50) or 50),
        ("Risk",       row.get("score_risk",     50) or 50),
        ("Storlek",    row.get("score_size",     50) or 50),
        ("Utdelning",  row.get("score_dividend", 50) or 50),
        ("Sentiment",  row.get("score_sentiment",50) or 50),
    ]
    labels = [f[0] for f in factors]
    values = [round(float(f[1]), 1) for f in factors]
    # Close the polygon
    labels_closed = labels + [labels[0]]
    values_closed = values + [values[0]]

    # Color based on average
    avg = sum(values) / len(values)
    color = "#4caf50" if avg >= 65 else ("#ff9800" if avg >= 45 else "#ef5350")

    # Convert hex to rgba for plotly compatibility
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    fill_color = f"rgba({r}, {g}, {b}, 0.15)"

    fig = go.Figure(go.Scatterpolar(
        r=values_closed,
        theta=labels_closed,
        fill="toself",
        fillcolor=fill_color,
        line=dict(color=color, width=2),
        hovertemplate="%{theta}: %{r:.0f}<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], gridcolor="#252b3b",
                           tickfont=dict(color="#8892a4", size=9), showticklabels=True,
                           tickvals=[25, 50, 75, 100]),
            angularaxis=dict(gridcolor="#252b3b", tickfont=dict(color="#e8eaf0", size=11)),
            bgcolor="rgba(0,0,0,0)",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8892a4", family="Inter, sans-serif"),
        margin=dict(l=50, r=50, t=30, b=30),
        height=320,
        showlegend=False,
    )
    return fig


def conviction_meter_breakdown(row) -> str:
    """Returns a short markdown text explaining the conviction meter."""
    factors = {
        "Värde": row.get("score_value", 50),
        "Kvalitet": row.get("score_quality", 50),
        "Momentum": row.get("score_momentum", 50),
        "Tillväxt": row.get("score_growth", 50),
        "Risk": row.get("score_risk", 50),
        "Sentiment": row.get("score_sentiment", 50),
    }
    valid = {k: float(v) for k, v in factors.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}
    if not valid:
        return ""
    top = sorted(valid.items(), key=lambda x: x[1], reverse=True)[:2]
    bot = sorted(valid.items(), key=lambda x: x[1])[:2]
    top_str = " · ".join(f"**{k}** ({v:.0f})" for k, v in top)
    bot_str = " · ".join(f"**{k}** ({v:.0f})" for k, v in bot)
    return f"Styrkor: {top_str}   Svagheter: {bot_str}"


@st.cache_data(ttl=86400)
def _build_sector_cache() -> dict:
    """Bygger ett sektorcache från ALLA tillgängliga scan-filer.
    Nyare scan-filer prioriteras. Returnerar {ticker: sector}."""
    cache: dict = {}
    scan_files = sorted(REPORT_DIR.glob("scored_universe_*.csv"))  # äldst -> nyast
    for f in scan_files:
        try:
            tmp = pd.read_csv(f, usecols=lambda c: c in ["ticker", "sector"])
            if "ticker" in tmp.columns and "sector" in tmp.columns:
                for _, r in tmp.dropna(subset=["sector"]).iterrows():
                    cache[str(r["ticker"]).upper()] = str(r["sector"])
        except Exception:
            pass
    return cache


def holdings_pie(df: pd.DataFrame, score_df: pd.DataFrame = None, mvs: dict = None) -> go.Figure:
    """Sektorpaj för innehav.

    Stödjer tre signaturer:
    - holdings_pie(df)                         - räknar antal per sektor (gammalt)
    - holdings_pie(holdings_df, score_df, mvs) - viktad på marknadsvärde, sektorer från score_df
    """
    # Ny signatur: holdings_df + score_df + mvs
    if score_df is not None and mvs is not None and "ticker" in df.columns:
        score_lu = {}
        if not score_df.empty and "ticker" in score_df.columns:
            score_lu = score_df.set_index("ticker").to_dict("index")
        # Bygg sektorcache från alla scans som fallback för aktier som saknas i senaste scan
        sector_fallback = _build_sector_cache()
        sector_mv: dict[str, float] = {}
        for _, row in df.iterrows():
            t = str(row["ticker"]).upper()
            sector = (score_lu.get(t, {}).get("sector")
                      or sector_fallback.get(t)
                      or "Okänd")
            mv = float(mvs.get(t, 0) or 0)
            sector_mv[sector] = sector_mv.get(sector, 0) + mv
        if not sector_mv:
            return go.Figure()
        labels = list(sector_mv.keys())
        values = list(sector_mv.values())
        fig = px.pie(
            names=labels, values=values,
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

    # Gammal signatur: sektor-kolumn i df
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


# ══════════════════════════════════════════════════════════════════════════════
# PORTFÖLJVÄRDE-HISTORIK
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fund_nav(fund_name: str) -> float | None:
    """
    Hämtar aktuellt NAV för en fond via Yahoo Finance-sökning.
    Söker på fondnamnet, returnerar priset i fondens valuta (SEK för svenska fonder).
    Cachas 1 timme. Returnerar None om fonden inte hittas.
    """
    import requests
    query = fund_name.strip()
    if not query:
        return None
    try:
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        r = requests.get(
            url,
            params={"q": query, "quotesCount": 6, "newsCount": 0},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code != 200:
            return None
        for quote in r.json().get("quotes", []):
            if quote.get("quoteType") not in ("MUTUALFUND", "ETF"):
                continue
            sym = quote.get("symbol", "")
            if not sym:
                continue
            info = yf.Ticker(sym).info
            price = (info.get("regularMarketPrice")
                     or info.get("navPrice")
                     or info.get("previousClose"))
            if price and float(price) > 0:
                return float(price)
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_price_history(tickers: tuple, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Hämtar kurshistorik för alla tickers. Returnerar DataFrame med datum/tid som index."""
    if not tickers:
        return pd.DataFrame()
    try:
        data = yf.download(list(tickers), period=period, interval=interval,
                           auto_adjust=True, progress=False)
        close = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
        if close.index.tz is not None:
            close.index = close.index.tz_localize(None)
        return close
    except Exception:
        return pd.DataFrame()


def portfolio_value_chart(holdings: pd.DataFrame, period: str = "1y",
                          fund_constant: float = 0.0,
                          benchmark: str = "") -> go.Figure:
    """
    Portföljvärde historik-chart.
    - Line chart (area fill) av portföljvärdet per dag
    - Scatter-markeringar (▲) vid buy_date för varje holding
    - fund_constant: fondernas aktuella marknadsvärde som konstant offset
    - benchmark: yfinance-ticker att jämföra mot (t.ex. "SPY", "^OMX")
    - period: "1mo" / "3mo" / "6mo" / "1y" / "2y"
    """
    if holdings.empty and fund_constant == 0:
        return go.Figure()

    tickers = tuple(holdings["ticker"].str.upper().tolist()) if not holdings.empty else ()
    price_hist = _fetch_price_history(tickers, period=period) if tickers else pd.DataFrame()

    if price_hist.empty:
        return go.Figure()

    def _calc_portfolio_series(ph: pd.DataFrame) -> pd.Series:
        """Summera portföljvärde per tidpunkt. Varje aktie räknas från sin buy_date."""
        pv = pd.Series(0.0, index=ph.index)
        for _, row in holdings.iterrows():
            t = row["ticker"].upper()
            s = float(row.get("shares", 0) or 0)
            if t not in ph.columns or s <= 0:
                continue
            ser = ph[t].ffill() * s
            bd = str(row.get("buy_date", "")).strip()
            if bd:
                try:
                    buy_ts = pd.Timestamp(bd).normalize()
                    ser = ser.where(ser.index >= buy_ts, 0.0)
                except Exception:
                    pass
            pv = pv + ser
        # Klipp till första dagen då något innehav faktiskt ägdes
        first_nz = pv[pv > 0].index.min() if (pv > 0).any() else None
        if first_nz is not None:
            pv = pv[pv.index >= first_nz]
        return pv[pv > 0]

    portfolio_values = _calc_portfolio_series(price_hist)
    _intraday = False

    # Om perioden gav för få punkter, utöka price_hist med längre datahämtning
    if len(portfolio_values) < 5 and tickers:
        ph_long = _fetch_price_history(tickers, period="max")
        if not ph_long.empty:
            pv_long = _calc_portfolio_series(ph_long)
            if not pv_long.empty:
                price_hist = ph_long
                portfolio_values = pv_long

    if fund_constant > 0:
        if portfolio_values.empty:
            idx = pd.date_range(end=pd.Timestamp.now(), periods=30, freq="D")
            portfolio_values = pd.Series(fund_constant, index=idx)
        else:
            portfolio_values = portfolio_values + fund_constant

    if portfolio_values.empty:
        return go.Figure()

    fig = go.Figure()
    show_legend = False

    # Area fill -- portföljvärde
    fig.add_trace(go.Scatter(
        x=portfolio_values.index,
        y=portfolio_values.values,
        mode="lines",
        name="Portföljvärde",
        line=dict(color="#4c9be8", width=2),
        fill="tozeroy",
        fillcolor="rgba(76,155,232,0.12)",
        hovertemplate="%{x|%d %b %Y}<br><b>%{y:,.0f} kr</b><extra></extra>",
    ))

    # Benchmark-linje (normaliserad till portföljens startvärde)
    if benchmark:
        _bperiod = "5d" if _intraday else period
        _binterval = "1h" if _intraday else "1d"
        bench_hist = _fetch_price_history((benchmark,), period=_bperiod, interval=_binterval)
        if not bench_hist.empty:
            bench_col = benchmark if benchmark in bench_hist.columns else bench_hist.columns[0]
            bench_s = bench_hist[bench_col].ffill()
            start_idx = portfolio_values.index[0]
            pos = bench_s.index.searchsorted(start_idx)
            if pos < len(bench_s):
                bench_start = bench_s.iloc[pos]
                port_start  = portfolio_values.iloc[0]
                if bench_start > 0:
                    bench_norm = bench_s * (port_start / bench_start)
                    bench_norm = bench_norm[bench_norm.index >= start_idx]
                    fig.add_trace(go.Scatter(
                        x=bench_norm.index,
                        y=bench_norm.values,
                        mode="lines",
                        name=benchmark,
                        line=dict(color="#f59e0b", width=1.5, dash="dot"),
                        hovertemplate="%{x|%d %b %Y}<br><b>%{y:,.0f} kr</b> (" + benchmark + ")<extra></extra>",
                    ))
                    show_legend = True

    # Köp-markeringar (▲)
    _dt_fmt = "%d %b %H:%M" if _intraday else "%d %b %Y"
    buy_markers_x, buy_markers_y, buy_markers_text = [], [], []
    for _, row in holdings.iterrows():
        bd = str(row.get("buy_date", "")).strip()
        if not bd:
            continue
        try:
            buy_dt = pd.Timestamp(bd)
            idx = portfolio_values.index.searchsorted(buy_dt)
            if idx < len(portfolio_values):
                buy_markers_x.append(portfolio_values.index[idx])
                buy_markers_y.append(portfolio_values.iloc[idx])
                buy_markers_text.append(f"Köp: {row['ticker']}")
        except Exception:
            pass

    if buy_markers_x:
        fig.add_trace(go.Scatter(
            x=buy_markers_x, y=buy_markers_y,
            mode="markers", name="Köp",
            marker=dict(symbol="triangle-up", size=10, color="#4caf50", line=dict(width=1, color="#fff")),
            text=buy_markers_text,
            hovertemplate="%{text}<br>%{x|" + _dt_fmt + "}<extra></extra>",
        ))

    layout_extra = {}
    if fund_constant > 0:
        layout_extra["annotations"] = [dict(
            text=f"🏦 +{fund_constant:,.0f} kr fonder (aktuellt värde, ej historik)",
            xref="paper", yref="paper", x=0.01, y=0.97,
            showarrow=False, font=dict(size=11, color="#f59e0b"), align="left",
        )]

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=8 if not fund_constant else 28, b=0),
        showlegend=show_legend,
        hovermode="x unified",
        title={"text": ""},
        yaxis_title="",
        **layout_extra,
    )
    return _apply_chart_style(fig)


def calc_period_returns(holdings: pd.DataFrame) -> dict:
    """
    Beräknar portföljens avkastning för standardperioder.
    För holdings köpta efter periodens start används cost_basis som referenspris
    (visar verklig avkastning sedan köp, inte hypotetisk historik).
    Returnerar: {"1D": (kr, pct), "1V": ..., "1M": ..., "3M": ..., "ÅTD": ..., "1Å": ...}
    """
    if holdings.empty:
        return {}

    # Bara aktieposter med yfinance-tickers (fonder med namn-som-ticker hoppas över)
    stock_h = holdings[~holdings["ticker"].str.upper().str.contains(r"\s", na=False)].copy()
    if stock_h.empty:
        return {}

    tickers = tuple(stock_h["ticker"].str.upper().tolist())
    price_hist = _fetch_price_history(tickers, period="1y")
    if price_hist.empty:
        return {}

    def _ref_value_at(dt: pd.Timestamp) -> float:
        """
        Portföljvärde vid datum dt.
        Om ett innehav köptes EFTER dt -> använd cost_basis som referens
        (vi hade inte positionen vid dt, men tar hänsyn till inköpspriset).
        """
        try:
            idx = price_hist.index.searchsorted(dt)
            if idx >= len(price_hist.index):
                idx = len(price_hist.index) - 1
            actual = price_hist.index[idx]
            total = 0.0
            for _, row in stock_h.iterrows():
                t = row["ticker"].upper()
                s = float(row.get("shares", 0) or 0)
                cost = float(row.get("cost_basis", 0) or 0)
                if t not in price_hist.columns or s <= 0:
                    continue
                buy_date_str = str(row.get("buy_date", "")).strip()
                bought_after = False
                if buy_date_str:
                    try:
                        bought_after = pd.Timestamp(buy_date_str) > dt
                    except Exception:
                        pass
                if bought_after:
                    # Inte ägd vid dt -- referens = vad vi betalade
                    total += cost * s
                else:
                    p = price_hist[t].iloc[idx]
                    if pd.notna(p):
                        total += float(p) * s
            return total if total > 0 else 0.0
        except Exception:
            return 0.0

    today = price_hist.index[-1]

    # Nuvarande värde (sista tillgängliga kurs)
    today_val = 0.0
    for _, row in stock_h.iterrows():
        t = row["ticker"].upper()
        s = float(row.get("shares", 0) or 0)
        if t in price_hist.columns and s > 0:
            _series = price_hist[t].dropna()
            if _series.empty:
                continue
            today_val += float(_series.iloc[-1]) * s

    if today_val <= 0:
        return {}

    periods = {
        "1D":  today - pd.Timedelta(days=1),
        "1V":  today - pd.Timedelta(weeks=1),
        "1M":  today - pd.DateOffset(months=1),
        "3M":  today - pd.DateOffset(months=3),
        "ÅTD": pd.Timestamp(today.year, 1, 1),
        "1Å":  today - pd.DateOffset(years=1),
    }

    result = {}
    for label, past_dt in periods.items():
        past_val = _ref_value_at(past_dt)
        if past_val > 0:
            kr_diff  = today_val - past_val
            pct_diff = (kr_diff / past_val) * 100
            result[label] = (round(kr_diff), round(pct_diff, 1))

    return result


def save_portfolio_snapshot(total_value: float, invested: float) -> None:
    """Sparar en daglig portfölj-snapshot om dagens datum saknas."""
    import datetime as _dt
    snap_path = DATA_DIR / "portfolio_snapshots.json"
    today = _dt.date.today().isoformat()
    try:
        snaps = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else []
    except Exception:
        snaps = []
    if any(s.get("date") == today for s in snaps):
        return
    pnl_pct = round((total_value / invested - 1) * 100, 2) if invested > 0 else 0.0
    snaps.append({"date": today, "value": round(total_value, 2),
                  "invested": round(invested, 2), "pnl_pct": pnl_pct})
    snaps = snaps[-365:]
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(snaps, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Landfilter (anvands av weekly_scan, smallcap, technical) ──────────────────
# Centraliserad for att undvika duplicering. Anvander suffix fran suffix_map.

def apply_country_filter(df: pd.DataFrame, selected_countries: list[str]) -> pd.DataFrame:
    """
    Filtrera en DataFrame baserat pa valda lander (med emoji-prefix).
    Overensstammer med filter-formatet fran sidebar: "🇸🇪 Sverige" etc.

    Args:
        df: DataFrame med ticker-kolumn.
        selected_countries: Lista av land-namn med emoji (tom lista = visa alla).

    Returns:
        Filtrerad DataFrame.
    """
    if df.empty or "ticker" not in df.columns or not selected_countries:
        return df

    from core.suffix_map import COUNTRY_SUFFIXES
    all_non_us = set(COUNTRY_SUFFIXES.values())
    us_selected = any(c.startswith("🇺🇸") for c in selected_countries)

    selected_suffixes = set()
    for c in selected_countries:
        if c in COUNTRY_SUFFIXES:
            selected_suffixes.add(COUNTRY_SUFFIXES[c])

    def _match(ticker: str) -> bool:
        t = str(ticker)
        if any(t.endswith(s) for s in selected_suffixes):
            return True
        if us_selected and not any(t.endswith(s) for s in all_non_us):
            return True
        return False

    return df[df["ticker"].apply(_match)].reset_index(drop=True)
