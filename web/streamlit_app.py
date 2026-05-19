"""
MarketScan Dashboard – Interaktiv börsanalys
============================================
Läser utdata från scan.py, smallcap/scanner.py och portfolio.py.

Kör lokalt : streamlit run streamlit_app.py
Deploya    : anslut GitHub-repo till streamlit.io/cloud
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# ── Sökvägar – MÅSTE komma INNAN projekt-importer ────────────────────────────
# Streamlit Cloud kör filen från web/-mappen; projektroten måste läggas till
# explicit annars hittas inte core/, data_management/, portfolio/.
ROOT       = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
DATA_DIR   = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from core import config
from web.utils import (
    load_scan_reports, load_smallcap_reports, load_portfolio, load_watchlist,
    _get_provider, _get_depth,
)
from web.pages.overview        import page_overview
from web.pages.weekly_scan     import page_weekly_scan
from web.pages.smallcap        import page_smallcap
from web.pages.portfolio       import page_portfolio
from web.pages.technical       import page_technical
from web.pages.ai_page         import page_ai
from web.pages.admin           import page_admin, _search_ticker_yfinance
from web.pages.guide           import page_guide
from web.pages.backtesting_page import page_backtesting
from web.pages.sector_rotation import page_sector_rotation
from web.pages.global_markets  import page_global_markets
from web.pages.alerts          import page_alerts_notices
from web.pages.paper_trading_page import page_paper_trading
from web.pages.ml_paper_trading   import page_ml_paper_trading
from web.pages.stock_search    import page_stock_search
from web.pages.watchlist_detail import page_watchlist_detail
from web.pages.ai_journal       import page_ai_journal

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
  /* ── Typsnitt: Inter ──────────────────────────────────────────────────────── */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

  /* Sätt Inter på body — ärver till all text.
     Vi undviker att sätta !important på span/div så att Streamlits
     ikonfonter (Material Symbols Rounded) i span-element inte krockar. */
  body,
  .stApp,
  [data-testid="stAppViewContainer"],
  [data-testid="stSidebarContent"],
  [data-testid="stHeader"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  }

  /* Explicit override på semantiska textelement (ej span — ikoner bor i span) */
  p, h1, h2, h3, h4, h5, h6,
  button, input, textarea, select, a, td, th, label, li {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  }
  h1, h2, h3 { font-weight: 700 !important; letter-spacing: -0.02em !important; }

  /* ── Sidövergång – döljer ghosting vid rerun ─────────────────────────────── */
  /* Fade + subtil slide-up varje gång huvudinnehållet renderas om */
  [data-testid="stMainBlockContainer"] > div:first-child,
  [data-testid="block-container"] {
    animation: pageIn 0.22s ease-out both;
  }
  @keyframes pageIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* Sidebar-filter: mjuk höjd-transition när filter-expander läggs till/tas bort */
  div[data-testid="stSidebarContent"] .streamlit-expander {
    transition: opacity 0.15s ease;
  }

  /* ── Tabeller ────────────────────────────────────────────────────────────── */
  .stDataFrame thead th {
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #8892a4 !important;
    background: #1a1f2e !important;
    border-bottom: 2px solid #2d3250 !important;
  }
  .stDataFrame tbody td { font-size: 13px !important; }
  .stDataFrame tbody tr:hover td {
    background: rgba(76,155,232,0.04) !important;
  }

  /* ── Avdelare (st.markdown("---")) ──────────────────────────────────────── */
  hr {
    border: none !important;
    height: 1px !important;
    background: linear-gradient(to right, transparent, #2d3250 20%, #2d3250 80%, transparent) !important;
    margin: 28px 0 20px 0 !important;
  }

  /* ── Taggar ──────────────────────────────────────────────────────────────── */
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

  /* ── Sidebar ─────────────────────────────────────────────────────────────── */
  div[data-testid="stSidebarContent"] { background: #131722; }

  /* Nav-knappar: transparent bakgrund, vänsterkant hover */
  div[data-testid="stSidebarContent"] .stButton button {
    background: transparent !important;
    border: none !important;
    border-left: 3px solid transparent !important;
    border-radius: 0 6px 6px 0 !important;
    text-align: left !important;
    font-weight: 400 !important;
    font-size: 13px !important;
    color: #8892a4 !important;
    padding: 7px 12px !important;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
    width: 100% !important;
  }
  div[data-testid="stSidebarContent"] .stButton button:hover {
    background: rgba(76,155,232,0.08) !important;
    border-left-color: #4c9be8 !important;
    color: #e8eaf0 !important;
  }
  /* Expander-rubriker i sidebar */
  div[data-testid="stSidebarContent"] .streamlit-expanderHeader {
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #4a5568 !important;
  }

  /* ── Mobil (max-width: 768px) ────────────────────────────────────────────── */
  @media (max-width: 768px) {
    /* Mer luft under titlar */
    h1 { font-size: 22px !important; margin-bottom: 12px !important; }
    h2 { font-size: 18px !important; }
    h3 { font-size: 16px !important; }

    /* Tabeller: horisontell scroll i stället för klämda kolumner */
    .stDataFrame { overflow-x: auto !important; }
    .stDataFrame table { min-width: 480px !important; }
    .stDataFrame tbody td,
    .stDataFrame thead th { font-size: 12px !important; padding: 6px 8px !important; }

    /* Knappar: tillräcklig tryckkänsla på pekskärm */
    .stButton button { min-height: 44px !important; font-size: 14px !important; }

    /* KPI-kort: 2 per rad på mobil i stället för 4 */
    [data-testid="column"] { min-width: 45% !important; }

    /* Formulärfält: läsbar textstorlek på iOS (förhindrar auto-zoom) */
    input, select, textarea { font-size: 16px !important; }

    /* Plotly-grafer: ingen horisontell overflow */
    .js-plotly-plot, .plotly { max-width: 100% !important; }

    /* Metrics / info-boxar: mer luft */
    [data-testid="stMetric"] { padding: 12px !important; }

    /* Göm onödiga padding-spacers på mobil */
    [data-testid="stVerticalBlock"] > div[style*="gap"] { gap: 8px !important; }
  }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def build_sidebar(scan_dates: list, sc_dates: list) -> tuple:
    """Bygger sidebar och returnerar (page, scan_date, sc_date, filters)."""
    with st.sidebar:
        # ── Wordmark ────────────────────────────────────────────────────────
        st.markdown("""
<div style="padding:16px 0 12px 0;border-bottom:1px solid #2d3250;margin-bottom:14px;">
  <div style="font-size:22px;font-weight:800;letter-spacing:-0.03em;line-height:1;">
    <span style="color:#e8eaf0;">Market</span><span style="color:#4c9be8;">Scan</span>
  </div>
  <div style="font-size:10px;color:#4a5568;letter-spacing:0.14em;margin-top:4px;text-transform:uppercase;">
    Aktieanalys &amp; Portfölj
  </div>
</div>
""", unsafe_allow_html=True)

        # ── Global sökning (ALLTID synlig) ──────────────────────────────────
        st.markdown('<div style="font-size:10px;font-weight:600;color:#4a5568;letter-spacing:0.12em;text-transform:uppercase;margin-bottom:6px;">Sök</div>', unsafe_allow_html=True)
        _search_q = st.text_input("", placeholder="Ticker eller bolag...", key="global_search", label_visibility="collapsed")
        _search_val = st.session_state.get("global_search", "").strip()
        if len(_search_val) >= 2:
            _hits = _search_ticker_yfinance(_search_val)
            if _hits:
                for _h in _hits[:6]:
                    if st.button(f"{_h['ticker']} — {_h['name'][:40]}", key=f"gs_{_h['ticker']}", use_container_width=True):
                        st.session_state["nav_page"] = "🔍 Aktie-sök"
                        st.session_state["search_ticker"] = _h["ticker"]; st.session_state["selected_stock_ticker"] = ""; st.session_state["selected_stock_name"] = ""
                        try:
                            st.query_params["p"] = "stock-search"
                        except Exception:
                            pass
                        st.rerun()
        st.markdown('<div style="height:1px;background:linear-gradient(to right,transparent,#2d3250 30%,#2d3250 70%,transparent);margin:6px 0 12px 0;"></div>', unsafe_allow_html=True)

        # ── Navigation (st.query_params för historikstöd) ───────────────────
        # Synkar nav_page med URL-query-parametern "p" så att webbläsarens
        # tillbaka-knapp (historik) fungerar. När query_params ändras (av
        # användarens tillbaka-knapp) uppdateras session_state i nästa rerun.

        # Kända sidor och deras URL-nycklar
        _known_pages = {
            "overview":       "📊 Översikt",
            "guide":          "📚 Guide & Hjälp",
            "weekly-scan":    "🔍 Veckoscanner",
            "smallcap":       "🏦 Småbolag",
            "stock-search":   "🔍 Aktie-sök",
            "watchlist":      "⭐ Bevakningar",
            "global-markets": "🌍 Globala marknader",
            "sector-rotation":"🏭 Sektorrotation",
            "backtesting":    "📈 Backtesting",
            "portfolio":      "💼 Portfölj",
            "paper-trading":  "📄 Paper Trading",
            "ai-paper-trading":"🤖 AI Paper Trading",
            "alerts":         "🚨 Larm & Notiser",
            "settings":       "⚙️ Inställningar",
            "technical":      "📈 Teknisk analys",
            "ai":             "🤖 AI",
            "admin":          "🔧 Admin",
            "ai-journal":     "📓 AI Journal",
        }
        _reverse_map = {v: k for k, v in _known_pages.items()}

        # Läs query_param "p" från URL:en.
        # st.query_params["p"] = key  i _navigate_to() sätter URL:en via pushState
        # (Streamlit ≥1.31). Streamlit lyssnar på popstate och kör om scriptet med
        # de nya query_params → tillbaka/framåt-knappen fungerar utan extra JS.
        _qp = st.query_params.get_all("p")
        _qp_page = _qp[0] if _qp else None
        if _qp_page and _qp_page in _known_pages:
            st.session_state["nav_page"] = _known_pages[_qp_page]
        elif "nav_page" not in st.session_state:
            st.session_state["nav_page"] = "📊 Översikt"

        def _navigate_to(page_title: str):
            """Navigera till en sida – query_params skapar automatiskt
            en historikentry i webbläsaren → tillbaka-knappen fungerar."""
            st.session_state["nav_page"] = page_title
            qp_key = _reverse_map.get(page_title, "overview")
            st.query_params["p"] = qp_key
            st.rerun()

        # Översikt & Guide – alltid synliga
        if st.button("Översikt", key="nav_overview", use_container_width=True):
            _navigate_to("📊 Översikt")
        if st.button("Guide & Hjälp", key="nav_guide", use_container_width=True):
            _navigate_to("📚 Guide & Hjälp")

        # MARKNAD / PORTFÖLJ / ANALYS – enkla knappar (inga radio/on_change) för att
        # undvika att st.rerun() från andra widgets ändrar nav_page.
        _MARKNAD_PAGES = [
            ("🔍 Veckoscanner",    "Veckoscanner"),
            ("🏦 Småbolag",        "Småbolag"),
            ("🔍 Aktie-sök",       "Aktie-sök"),
            ("⭐ Bevakningar",     "Bevakningar"),
            ("🌍 Globala marknader","Globala marknader"),
            ("🏭 Sektorrotation",  "Sektorrotation"),
            ("📈 Backtesting",     "Backtesting"),
        ]
        _PORTFÖLJ_PAGES = [
            ("💼 Portfölj",        "Portfölj"),
            ("📄 Paper Trading",   "Paper Trading"),
            ("🤖 AI Paper Trading","AI Paper Trading"),
            ("🚨 Larm & Notiser",  "Larm & Notiser"),
            ("⚙️ Inställningar",   "Inställningar"),
        ]
        _ANALYS_PAGES = [
            ("📈 Teknisk analys",  "Teknisk analys"),
            ("🤖 AI",              "AI-analys"),
            ("📓 AI Journal",      "AI Journal"),
        ]

        with st.expander("MARKNAD", expanded=True):
            for nav_key, display in _MARKNAD_PAGES:
                if st.button(display, key=f"sb_{nav_key}", use_container_width=True):
                    _navigate_to(nav_key)

        with st.expander("PORTFÖLJ", expanded=True):
            for nav_key, display in _PORTFÖLJ_PAGES:
                if st.button(display, key=f"sb_{nav_key}", use_container_width=True):
                    _navigate_to(nav_key)

        with st.expander("ANALYS", expanded=False):
            for nav_key, display in _ANALYS_PAGES:
                if st.button(display, key=f"sb_{nav_key}", use_container_width=True):
                    _navigate_to(nav_key)

        # Admin – bara synlig för admin-användaren
        if st.session_state.get("username", "admin") == "admin":
            if st.button("Admin", key="nav_admin", use_container_width=True):
                _navigate_to("🔧 Admin")

        page = st.session_state["nav_page"]

        # ── Datumval (alltid synligt) ───────────────────────────────────────
        st.markdown('<div style="height:1px;background:linear-gradient(to right,transparent,#2d3250 30%,#2d3250 70%,transparent);margin:10px 0;"></div>', unsafe_allow_html=True)
        with st.expander("Datum", expanded=False):
            scan_date = st.selectbox("Scan", scan_dates if scan_dates else ["Ingen data"], key="scan_date", label_visibility="collapsed")
            sc_date = st.selectbox("Småbolag", sc_dates if sc_dates else ["Ingen data"], key="sc_date", label_visibility="collapsed")

        # ── Filters per page ────────────────────────────────────────────────
        filters = {}
        _show_filters = page in ("🔍 Veckoscanner", "🏦 Småbolag", "📈 Teknisk analys")

        if _show_filters:
            with st.expander("🎛️ Filter", expanded=False):
                if page == "🔍 Veckoscanner":
                    filters["score_min"] = st.slider("Min score", 0, 100, 40, 5, key="ws_min")
                    filters["score_max"] = st.slider("Max score", 0, 100, 100, 5, key="ws_max")
                    filters["sector"]    = st.multiselect("Sektor", [], placeholder="Välj sektorer…", key="ws_sector")
                    filters["entry"]     = st.multiselect("Entry", ["STARK","OK","VÄNTA","EJ AKTUELL"], default=["STARK","OK"], key="ws_entry")
                    filters["confidence"] = st.multiselect("Konfidens", ["HÖG","MEDEL","LÅG"], placeholder="Alla...", key="ws_conf")
                    filters["trend"] = st.selectbox("Trend", ["Alla","UPPTREND","NEDTREND","SIDLED"], key="ws_trend")
                    filters["piotroski_min"] = st.slider("Min Piotroski", 0, 9, 0, key="ws_pio")
                    filters["show_holdings"] = st.checkbox("Bara mina innehav", key="ws_hold")
                    filters["show_watchlist"] = st.checkbox("Inkludera bevakning", key="ws_wl")
                    filters["hide_illiquid"] = st.checkbox(
                        "Dölj illikvida",
                        value=False,
                        key="ws_hide_illiquid",
                        help="Döljer aktier med uppskattad dagsomsättning under $50k/dag (avg_volume × kurs × FX).",
                    )
                    st.markdown("---")
                    filters["only_swedish"] = st.checkbox(
                        "🇸🇪 Visa endast svenska aktier",
                        value=False,
                        key="ws_only_swedish",
                        help="Filtrera till enbart aktier på Stockholmsbörsen (.ST)",
                    )
                    if not filters["only_swedish"]:
                        filters["countries"] = st.multiselect(
                            "🌍 Länder",
                            options=["🇸🇪 Sverige", "🇺🇸 USA", "🇬🇧 UK", "🇩🇪 Tyskland",
                                     "🇫🇮 Finland", "🇩🇰 Danmark", "🇳🇴 Norge",
                                     "🇨🇳 Kina", "🇯🇵 Japan"],
                            default=[],
                            key="ws_countries",
                            help="Lämna tomt för att visa alla länder.",
                        )
                    else:
                        filters["countries"] = []

                elif page == "🏦 Småbolag":
                    filters["sc_score_min"] = st.slider("Min poäng", 0, 100, 30, 5, key="sc_min")
                    filters["sc_stars"] = st.multiselect("⭐ Betyg", ["★★★★★","★★★★","★★★","★★","★"], placeholder="Alla...", key="sc_stars")
                    filters["sc_sector"] = st.multiselect("Sektor", [], placeholder="Välj...", key="sc_sector")
                    filters["sc_insider"] = st.selectbox("Insider", ["Alla","BUY","NEUTRAL","SELL","N/A"], key="sc_insider")
                    filters["sc_fcf"] = st.checkbox("Positivt FCF", key="sc_fcf")
                    filters["sc_max_de"] = st.slider("Max D/E %", 0, 500, 300, 25, key="sc_de")
                    st.markdown("---")
                    filters["sc_only_swedish"] = st.checkbox(
                        "🇸🇪 Visa endast svenska aktier",
                        value=False, key="sc_only_swedish",
                        help="Filtrera till enbart aktier på Stockholmsbörsen (.ST)",
                    )
                    if not filters["sc_only_swedish"]:
                        filters["sc_countries"] = st.multiselect(
                            "🌍 Länder",
                            options=["🇸🇪 Sverige", "🇺🇸 USA", "🇬🇧 UK", "🇩🇪 Tyskland",
                                     "🇫🇮 Finland", "🇩🇰 Danmark", "🇳🇴 Norge",
                                     "🇨🇳 Kina", "🇯🇵 Japan"],
                            default=[], key="sc_countries",
                            help="Lämna tomt för att visa alla länder.",
                        )
                    else:
                        filters["sc_countries"] = []

                elif page == "📈 Teknisk analys":
                    filters["rsi_min"] = st.slider("Min RSI", 0, 100, 0, 5, key="tech_rsi_min")
                    filters["rsi_max"] = st.slider("Max RSI", 0, 100, 100, 5, key="tech_rsi_max")
                    filters["ma200"] = st.selectbox("MA200", ["Alla","Över MA200 (bull)","Under MA200 (bear)"], key="tech_ma200")
                    filters["t_sector"] = st.multiselect("Sektor", [], placeholder="Välj...", key="tech_sector")
                    filters["t_entry"] = st.multiselect("Entry", ["STARK","OK","VÄNTA","EJ AKTUELL"], placeholder="Alla...", key="tech_entry")
                    filters["trend_tech"] = st.selectbox("Trend", ["Alla","UPPTREND","Övriga"], key="tech_trend")
                    st.markdown("---")
                    filters["t_only_swedish"] = st.checkbox(
                        "🇸🇪 Visa endast svenska aktier",
                        value=False, key="t_only_swedish",
                        help="Filtrera till enbart aktier på Stockholmsbörsen (.ST)",
                    )
                    if not filters["t_only_swedish"]:
                        filters["t_countries"] = st.multiselect(
                            "🌍 Länder",
                            options=["🇸🇪 Sverige", "🇺🇸 USA", "🇬🇧 UK", "🇩🇪 Tyskland",
                                     "🇫🇮 Finland", "🇩🇰 Danmark", "🇳🇴 Norge",
                                     "🇨🇳 Kina", "🇯🇵 Japan"],
                            default=[], key="t_countries",
                            help="Lämna tomt för att visa alla länder.",
                        )
                    else:
                        filters["t_countries"] = []

        # ── AI-inställningar (alltid) ────────────────────────────────────────
        with st.expander("🤖 AI-inställningar", expanded=False):
            ai_provider = st.selectbox("Tjänst", ["auto","deepseek","gemini"], format_func=lambda k: {"auto": f"Auto ({config.AI_PROVIDER})","deepseek":"DeepSeek","gemini":"Gemini"}.get(k,k), key="sidebar_ai_provider")
            st.session_state["selected_provider"] = ai_provider
            ai_depth = st.selectbox("Djup", ["Snabb","Normal","Djup","Extra djup"], index=1, key="sidebar_ai_depth")
            st.session_state["selected_depth"] = ai_depth

        # ── Statusfot med exakt klockslag ────────────────────────────────────
        st.markdown("---")
        _latest_scan_file = None
        if scan_dates:
            _latest_scan_file = None
            # Prioritera .parquet, fallback till .csv
            parquet_files = list(REPORT_DIR.glob("scored_universe_*.parquet"))
            csv_files = list(REPORT_DIR.glob("scored_universe_*.csv"))
            if parquet_files:
                _latest_scan_file = max(parquet_files, key=lambda f: f.stat().st_mtime)
            elif csv_files:
                _latest_scan_file = max(csv_files, key=lambda f: f.stat().st_mtime)
        _time_str = "—"
        if _latest_scan_file:
            _mt = datetime.fromtimestamp(_latest_scan_file.stat().st_mtime)
            _tz = datetime.now().astimezone().tzinfo
            _time_str = _mt.astimezone(_tz).strftime("%Y-%m-%d %H:%M")
        st.caption(f"🟢 {len(scan_dates) if scan_dates else 0} datum · Senast: {max(scan_dates) if scan_dates else '—'} [{_time_str}]")

    return page, scan_date, sc_date, filters


# ══════════════════════════════════════════════════════════════════════════════
# ÅTKOMSTKONTROLL
# ══════════════════════════════════════════════════════════════════════════════

def _has_credentials_configured() -> bool:
    """Returnerar True om credentials-sektionen finns i Streamlit Secrets."""
    try:
        return bool(st.secrets.get("credentials"))
    except Exception:
        return False


# ── Lösenordsåterställning via e-post ────────────────────────────────────────

_RESET_TOKENS_PATH = DATA_DIR / "password_reset_tokens.json"


def _load_reset_tokens() -> dict:
    try:
        import json as _j
        if _RESET_TOKENS_PATH.exists():
            return _j.loads(_RESET_TOKENS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_reset_tokens(tokens: dict):
    import json as _j
    _RESET_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _RESET_TOKENS_PATH.write_text(_j.dumps(tokens, indent=2, ensure_ascii=False),
                                  encoding="utf-8")


def _find_user_by_email(email: str) -> tuple[str, dict] | tuple[None, None]:
    """Hitta användarnamn + userdata för en given e-postadress.
    Söker i users_config.json OCH Streamlit Secrets (för admin-kontot)."""
    email_lower = email.strip().lower()
    # 1. Sök i users_config.json (vanliga användare)
    try:
        import json as _j
        data = _j.loads((DATA_DIR / "users_config.json").read_text(encoding="utf-8"))
        for user in data.get("users", []):
            if user.get("email", "").strip().lower() == email_lower:
                return user.get("username"), user
    except Exception:
        pass
    # 2. Sök i Streamlit Secrets (admin och andra credential-baserade konton)
    try:
        raw_creds = st.secrets.get("credentials", {})
        for uname, udata in raw_creds.get("usernames", {}).items():
            if str(udata.get("email", "")).strip().lower() == email_lower:
                return uname, {
                    "username": uname,
                    "email": email_lower,
                    "name": udata.get("name", uname),
                }
    except Exception:
        pass
    return None, None


def _send_reset_email(to_email: str, username: str, token: str) -> bool:
    """Skickar återställningslänk via e-post. Returnerar True vid lyckat utskick."""
    try:
        from core.email_template import send_email
        # Hämta app-URL från secrets om den är konfigurerad, annars fallback
        try:
            app_url = str(st.secrets.get("APP_URL", "https://marketscan.streamlit.app")).rstrip("/")
        except Exception:
            app_url = "https://marketscan.streamlit.app"
        reset_url = f"{app_url}?reset_token={token}"
        body = f"""# 🔐 Återställ ditt lösenord

Hej **{username}**,

Du (eller någon annan) begärde att återställa lösenordet för ditt MarketScan-konto.

**[Klicka här för att välja nytt lösenord]({reset_url})**

Länken är giltig i **1 timme**. Om du inte begärde detta kan du ignorera detta mail —
ditt konto är oförändrat.

---
*MarketScan · Automatiskt utskick*
"""
        return send_email(
            subject="🔐 MarketScan – återställ lösenord",
            body_markdown=body,
            recipients=[to_email],
        )
    except Exception:
        return False


def _update_user_password(username: str, new_hashed: str) -> bool:
    """Uppdaterar lösenord i users_config.json. Returnerar True vid lyckat sparande.

    Fungerar även för admin-kontot: skriver in en override-post i filen som
    sedan läses av _load_managed_users() och slås samman över secrets-lösenordet.
    """
    try:
        import json as _j
        from datetime import datetime as _dt
        path = DATA_DIR / "users_config.json"
        # Ladda befintlig fil eller skapa tom struktur
        try:
            data = _j.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {"users": []}
        uname_lower = username.strip().lower()
        updated = False
        for user in data.get("users", []):
            if user.get("username", "").strip().lower() == uname_lower:
                user["password"] = new_hashed
                user["active"] = True
                updated = True
                break
        if not updated:
            # Användaren finns inte i filen (t.ex. admin som normalt är i secrets)
            # – lägg till som override-post
            data.setdefault("users", []).append({
                "username": uname_lower,
                "name": username,
                "email": "",
                "password": new_hashed,
                "active": True,
                "added": _dt.now().strftime("%Y-%m-%d"),
                "password_reset": True,
            })
        path.write_text(_j.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        pass
    return False


def _handle_password_reset_flow() -> bool:
    """
    Kontrollerar om URL:en innehåller en reset_token och hanterar i så fall
    hela lösenordsåterställningssidan.

    Returnerar True om sidan tas över (token hittades i URL) → anroparen ska stopa appen.
    Returnerar False om ingen token finns i URL → normal inloggning fortsätter.
    """
    from datetime import datetime, timezone

    try:
        token_from_url = st.query_params.get("reset_token", "")
    except Exception:
        token_from_url = ""

    if not token_from_url:
        return False

    # ── Lösenordsåterställning via länk ───────────────────────────────────────
    st.markdown("""
    <style>
    [data-testid="stForm"] {
        max-width: 380px; margin: 80px auto 0 auto;
        background: #1e2230; border: 1px solid #2d3250;
        border-radius: 12px; padding: 40px 36px 32px;
    }
    </style>
    <div style="text-align:center; padding:60px 0 0 0;">
      <div style="font-size:24px;font-weight:800;letter-spacing:3px;color:#e8eaf0;">
        MARKET<span style="color:#00d4aa;">SCAN</span>
      </div>
      <div style="font-size:11px;color:#64748b;letter-spacing:2px;
                  text-transform:uppercase;margin-top:4px;margin-bottom:32px;">
        Välj nytt lösenord
      </div>
    </div>
    """, unsafe_allow_html=True)

    tokens = _load_reset_tokens()
    token_data = tokens.get(token_from_url)

    if not token_data:
        st.error("❌ Ogiltig eller redan använd återställningslänk.")
        if st.button("↩ Gå till inloggning"):
            st.query_params.clear()
            st.rerun()
        return True

    expires_str = token_data["expires"]
    try:
        expires = datetime.fromisoformat(expires_str)
        # Hantera både naive (gamla tokens) och timezone-aware format
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except Exception:
        expires = datetime.now(timezone.utc)  # Behandla ogiltigt datum som utgånget
    if datetime.now(timezone.utc) > expires:
        st.error("⌛ Länken har gått ut (giltig 1 timme). Begär en ny nedan.")
        if st.button("↩ Gå till inloggning"):
            st.query_params.clear()
            st.rerun()
        return True

    username = token_data["username"]
    with st.form("reset_pw_form", clear_on_submit=True):
        st.markdown(f"**Välj ett nytt lösenord för kontot `{username}`**")
        pw1 = st.text_input("Nytt lösenord", type="password", placeholder="Minst 8 tecken")
        pw2 = st.text_input("Upprepa lösenord", type="password")
        submitted = st.form_submit_button("💾 Spara nytt lösenord",
                                          use_container_width=True, type="primary")
        if submitted:
            if len(pw1) < 8:
                st.error("Lösenordet måste vara minst 8 tecken.")
            elif pw1 != pw2:
                st.error("Lösenorden matchar inte.")
            else:
                # Hasha lösenordet — prova olika API-varianter beroende på version
                new_hash = None
                try:
                    import streamlit_authenticator as stauth
                    # Ny API (>=0.3.3): Hasher.hash(password)
                    new_hash = stauth.Hasher.hash(pw1)
                except Exception:
                    pass
                if not new_hash:
                    try:
                        import streamlit_authenticator as stauth
                        # Gammal API (<0.3): Hasher([password]).generate()[0]
                        new_hash = stauth.Hasher([pw1]).generate()[0]
                    except Exception:
                        pass
                if not new_hash:
                    try:
                        import bcrypt
                        new_hash = bcrypt.hashpw(pw1.encode(), bcrypt.gensalt()).decode()
                    except Exception:
                        new_hash = None
                if not new_hash:
                    st.error("❌ Kunde inte hasha lösenordet. Kontakta administratören.")
                elif _update_user_password(username, new_hash):
                    tokens.pop(token_from_url, None)
                    _save_reset_tokens(tokens)
                    st.success("✅ Lösenordet har uppdaterats! Du kan nu logga in.")
                    st.query_params.clear()
                    st.balloons()
                else:
                    st.error("❌ Kunde inte spara lösenordet. Kontakta administratören.")
    return True


def _show_forgot_password_form():
    """Visar 'Glömt lösenord?'-expander under inloggningsformuläret."""
    import uuid
    from datetime import datetime, timedelta, timezone

    with st.expander("🔑 Glömt lösenord?", expanded=False):
        st.caption("Ange din e-postadress så skickar vi en länk för att välja nytt lösenord.")
        with st.form("forgot_pw_form", clear_on_submit=True):
            reset_email = st.text_input("E-postadress", placeholder="din@email.se")
            send_btn = st.form_submit_button("📧 Skicka återställningslänk",
                                             use_container_width=True)
            if send_btn:
                if not reset_email.strip():
                    st.warning("Ange din e-postadress.")
                else:
                    uname, _ = _find_user_by_email(reset_email)
                    # Alltid samma meddelande (undviker user enumeration)
                    st.success("Om e-postadressen finns registrerad skickar vi en länk inom kort.")
                    if uname is not None:
                        token = str(uuid.uuid4())
                        now_utc = datetime.now(timezone.utc)
                        expires = (now_utc + timedelta(hours=1)).isoformat()
                        tokens = _load_reset_tokens()
                        # Rensa gamla tokens för denna användare
                        def _is_valid_token(v: dict) -> bool:
                            try:
                                exp = datetime.fromisoformat(v["expires"])
                                if exp.tzinfo is None:
                                    exp = exp.replace(tzinfo=timezone.utc)
                                return v.get("username") != uname or exp > now_utc
                            except Exception:
                                return False
                        tokens = {k: v for k, v in tokens.items() if _is_valid_token(v)}
                        tokens[token] = {"username": uname, "expires": expires}
                        _save_reset_tokens(tokens)
                        _send_reset_email(reset_email.strip(), uname, token)


def _load_managed_users() -> dict:
    """Laddar användare som skapats via admin-sidan (data/users_config.json).

    Returnerar dict på formatet:
        {"username": {"name": ..., "email": ..., "password": "<bcrypt>"}}
    Ignorerar inaktiva användare.

    OBS: Admin-posten i filen (om den finns) används som lösenords-override
    efter en lysenordsåterställning — den slås samman ÖVER secrets-värdet.
    """
    try:
        import json as _json
        path = DATA_DIR / "users_config.json"
        data = _json.loads(path.read_text(encoding="utf-8"))
        result = {}
        for user in data.get("users", []):
            uname = user.get("username", "").strip().lower()
            if not uname:
                continue
            if not user.get("active", True):
                continue
            # Admin-posten inkluderas bara om den har ett lösenord (reset-override)
            if uname == "admin" and not user.get("password"):
                continue
            result[uname] = {
                "name":     user.get("name", uname),
                "email":    user.get("email", ""),
                "password": user.get("password", ""),
            }
        return result
    except Exception:
        return {}


def _run_auth() -> bool:
    """Hanterar inloggning med streamlit-authenticator (cookie-baserade sessioner).

    Flöde:
    1. Om credentials INTE är konfigurerade i secrets → öppen åtkomst (lokal körning)
    2. Admin-credentials läses från Streamlit Secrets
    3. Övriga användare läses från data/users_config.json (hanteras via admin-sidan)
    4. Om redan inloggad via cookie → True direkt
    5. Annars → visa inloggningsformulär

    Sätter session_state["username"] efter lyckad inloggning.
    """
    if not _has_credentials_configured():
        # Lokal körning utan secrets – öppen åtkomst, sätt admin som default-användare
        if not st.session_state.get("username"):
            st.session_state["username"] = "admin"
        return True

    try:
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("❌ streamlit-authenticator saknas. Kör: pip install streamlit-authenticator")
        return False

    # Bygg credentials-dict: admin från secrets + övriga från users_config.json
    try:
        raw_creds = st.secrets["credentials"]
        credentials = {
            "usernames": {
                uname: dict(udata)
                for uname, udata in raw_creds.get("usernames", {}).items()
            }
        }
    except Exception as e:
        st.error(f"❌ Fel vid läsning av credentials från secrets: {e}")
        return False

    # Slå samman med admin-hanterade användare (läses från data/users_config.json)
    managed = _load_managed_users()
    credentials["usernames"].update(managed)

    cookie_cfg = {}
    try:
        cookie_cfg = dict(st.secrets.get("cookie", {}))
    except Exception:
        pass

    authenticator = stauth.Authenticate(
        credentials=credentials,
        cookie_name=cookie_cfg.get("name", "marketscan_auth"),
        key=cookie_cfg.get("key", "marketscan_default_key_change_me"),
        cookie_expiry_days=int(cookie_cfg.get("expiry_days", 30)),
    )

    # Om URL har reset_token → visa lösenordsåterställning istället för inloggning
    if _handle_password_reset_flow():
        return False

    # Visa inloggningsformulär centrerat med varumärkeslogotyp
    if st.session_state.get("authentication_status") is not True:
        st.markdown("""
        <style>
        [data-testid="stForm"] {
            max-width: 380px;
            margin: 80px auto 0 auto;
            background: #1e2230;
            border: 1px solid #2d3250;
            border-radius: 12px;
            padding: 40px 36px 32px;
        }
        </style>
        <div style="text-align:center; padding: 60px 0 0 0;">
          <div style="font-size:24px; font-weight:800; letter-spacing:3px; color:#e8eaf0;">
            MARKET<span style="color:#00d4aa;">SCAN</span>
          </div>
          <div style="font-size:11px; color:#64748b; letter-spacing:2px;
                      text-transform:uppercase; margin-top:4px; margin-bottom:32px;">
            Aktieanalys & Portfölj
          </div>
        </div>
        """, unsafe_allow_html=True)

    authenticator.login(location="main")

    status = st.session_state.get("authentication_status")

    # Visa kontaktinfo + "Glömt lösenord?" under inloggningsformuläret (ej inloggad)
    if status is not True:
        st.markdown("""
        <div style="text-align:center; margin-top:24px; padding: 0 20px;">
          <div style="font-size:12px; color:#64748b; line-height:1.9;">
            Inget konto? Kontakta
            <a href="mailto:h.thurner@hotmail.com"
               style="color:#4c9be8; text-decoration:none;">
              h.thurner@hotmail.com
            </a>
            för att få tillgång.
          </div>
        </div>
        <div style="max-width:380px; margin:16px auto 0 auto; padding:0 20px;">
        </div>
        """, unsafe_allow_html=True)
        _show_forgot_password_form()

    if status is True:
        username = st.session_state.get("username", "admin")
        # Logga inloggning (en gång per session via session_state-flagga)
        if not st.session_state.get("_login_logged"):
            _log_activity(username, "login")
            st.session_state["_login_logged"] = True
        # Lägg till utloggningsknapp i sidofältet
        with st.sidebar:
            st.markdown(
                f"<div style='font-size:12px;color:#8892a4;padding:4px 0 8px;'>"
                f"Inloggad som <b style='color:#e8eaf0;'>{username}</b></div>",
                unsafe_allow_html=True,
            )
            authenticator.logout("🚪 Logga ut", location="sidebar")
        return True
    elif status is False:
        st.error("❌ Fel användarnamn eller lösenord")
    # status is None → väntar på input
    return False


def _log_activity(username: str, action: str, detail: str = ""):
    """Log user activity to data/activity_log.json (last 500 entries)."""
    try:
        import json as _j
        log_path = DATA_DIR / "activity_log.json"
        try:
            log = _j.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
        except Exception:
            log = []
        log = log[-499:]
        log.append({
            "timestamp": datetime.now().isoformat()[:19],
            "username": username,
            "action": action,
            "detail": detail,
        })
        log_path.write_text(_j.dumps(log, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _init_session_state():
    """Initialiserar session_state med säkra default-värden vid första laddning."""
    defaults = {
        "nav_page": "📊 Översikt",
        "selected_provider": "auto",
        "selected_depth": "Normal",
        "global_search": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():

    # Initiera session_state med defaults
    _init_session_state()

    # Global inloggning – körs innan allt annat
    if not _run_auth():
        st.stop()

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

    # ── Anti-ghosting: rensa förra sidans DOM helt innan nya sidan ritas ─────
    # st.empty() skapar en slot vars innehåll Streamlit garanterat byter ut
    # mellan rerendringar. Utan denna kan widgets från föregående sida ligga
    # kvar i DOM:en under sidbyten ("ghosting").
    _page_slot = st.empty()
    with _page_slot.container():
        if page == "📚 Guide & Hjälp":
            page_guide()

        elif page == "📊 Översikt":
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

        elif page == "🔍 Aktie-sök":
            page_stock_search()

        elif page == "⭐ Bevakningar":
            page_watchlist_detail(df, watchlist)

        elif page == "🌍 Globala marknader":
            page_global_markets()

        elif page == "💼 Portfölj":
            page_portfolio(df, holdings, watchlist, sc_df=sc_df)

        elif page == "📄 Paper Trading":
            page_paper_trading()

        elif page == "🤖 AI Paper Trading":
            page_ml_paper_trading()

        elif page == "🏭 Sektorrotation":
            page_sector_rotation(df)

        elif page == "🚨 Larm & Notiser":
            page_alerts_notices(df)

        elif page == "📈 Backtesting":
            page_backtesting()

        elif page == "📈 Teknisk analys":
            if not df.empty and "sector" in df.columns:
                secs = sorted(df["sector"].dropna().unique().tolist())
            page_technical(df, filters)

        elif page == "🤖 AI":
            page_ai(df, sc_df, holdings)

        elif page == "📓 AI Journal":
            page_ai_journal(df)

        elif page == "⚙️ Inställningar":
            from web.pages.settings_page import page_settings
            page_settings()

        elif page == "🔧 Admin":
            page_admin()


if __name__ == "__main__":
    main()
