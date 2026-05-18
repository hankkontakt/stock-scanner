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
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def build_sidebar(scan_dates: list, sc_dates: list) -> tuple:
    """Bygger sidebar och returnerar (page, scan_date, sc_date, filters)."""
    with st.sidebar:
        st.markdown("## 📊 MarketScan")
        st.markdown("---")

        # ── Global sökning (ALLTID synlig) ──────────────────────────────────
        st.markdown("### 🔍 Sök")
        _search_q = st.text_input("", placeholder="Ticker eller bolag...", key="global_search", label_visibility="collapsed")
        _search_val = st.session_state.get("global_search", "").strip()
        if len(_search_val) >= 2:
            _hits = _search_ticker_yfinance(_search_val)
            if _hits:
                for _h in _hits[:6]:
                    if st.button(f"{_h['ticker']} — {_h['name'][:40]}", key=f"gs_{_h['ticker']}", use_container_width=True):
                        st.session_state["nav_page"] = "🔍 Aktie-sök"
                        st.session_state["search_ticker"] = _h["ticker"]; st.session_state["selected_stock_ticker"] = ""; st.session_state["selected_stock_name"] = ""
                        st.rerun()
        st.markdown("---")

        # ── Navigation ──────────────────────────────────────────────────────
        if "nav_page" not in st.session_state:
            st.session_state["nav_page"] = "📊 Översikt"

        # Översikt – alltid synlig
        if st.button("📊 Översikt", key="nav_overview", use_container_width=True):
            st.session_state["nav_page"] = "📊 Översikt"
            st.rerun()

        if st.button("📚 Guide & Hjälp", key="nav_guide", use_container_width=True):
            st.session_state["nav_page"] = "📚 Guide & Hjälp"
            st.rerun()

        # MARKNAD / PORTFÖLJ / ANALYS – använder enkla knappar (inga radio/on_change) för att
        # undvika att st.rerun() från andra widgets ändrar nav_page.
        with st.expander("📈 MARKNAD", expanded=True):
            for label in ["🔍 Veckoscanner", "🏦 Småbolag", "🔍 Aktie-sök", "⭐ Bevakningar", "🌍 Globala marknader", "🏭 Sektorrotation", "📈 Backtesting"]:
                if st.button(label, key=f"sb_{label}", use_container_width=True):
                    st.session_state["nav_page"] = label
                    st.rerun()

        with st.expander("💼 PORTFÖLJ", expanded=True):
            for label in ["💼 Portfölj", "📄 Paper Trading", "🤖 AI Paper Trading", "🚨 Larm & Notiser"]:
                if st.button(label, key=f"sb_{label}", use_container_width=True):
                    st.session_state["nav_page"] = label
                    st.rerun()

        with st.expander("📈 ANALYS", expanded=False):
            for label in ["📈 Teknisk analys", "🤖 AI"]:
                if st.button(label, key=f"sb_{label}", use_container_width=True):
                    st.session_state["nav_page"] = label
                    st.rerun()

        # Admin – alltid synlig längst ner
        if st.button("🔧 Admin", key="nav_admin", use_container_width=True):
            st.session_state["nav_page"] = "🔧 Admin"
            st.rerun()

        page = st.session_state["nav_page"]

        # ── Datumval (alltid synligt) ───────────────────────────────────────
        st.markdown("---")
        with st.expander("📅 Datum", expanded=False):
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

def _check_site_access() -> bool:
    """Kräver lösenord för att överhuvudtaget komma in på sidan.

    Lösenordet hämtas från:
    1. Streamlit Secrets: SITE_PASSWORD (prioriteras)
    2. Miljövariabel: SITE_PASSWORD
    3. Fallback: STREAMLIT_APP_PASSWORD
    4. Om inget är satt → fri åtkomst (lokalt/utveckling)

    Användaren måste autentisera en gång per session.
    """
    # Hämta lösenord från secrets eller miljövariabel
    pw = ""
    try:
        import streamlit as st
        pw = st.secrets.get("SITE_PASSWORD", "") or \
             st.secrets.get("STREAMLIT_APP_PASSWORD", "")
    except Exception:
        pass
    if not pw:
        import os
        pw = os.getenv("SITE_PASSWORD", "") or \
             os.getenv("STREAMLIT_APP_PASSWORD", "")

    # Inget lösenord satt → öppen åtkomst (t.ex. lokalt eller om användaren
    # explicit vill ha öppen site)
    if not pw:
        return True

    # Kolla om redan autentiserad i denna session
    if st.session_state.get("site_authenticated", False):
        return True

    # Visa inloggningsruta
    st.markdown("""
    <style>
    .login-wrapper {
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 80vh;
    }
    .login-box {
        background: #1e2230;
        border: 1px solid #2d3250;
        border-radius: 12px;
        padding: 40px 36px;
        max-width: 380px;
        width: 100%;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .login-logo {
        text-align: center;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 4px;
        color: #e8eaf0;
        margin-bottom: 4px;
    }
    .login-logo span { color: #00d4aa; }
    .login-sub {
        text-align: center;
        font-size: 12px;
        color: #64748b;
        margin-bottom: 28px;
        letter-spacing: 1.5px;
        text-transform: uppercase;
    }
    </style>
    <div class="login-wrapper">
    <div class="login-box">
        <div class="login-logo">MARKET<span>SCAN</span></div>
        <div class="login-sub">Inloggning krävs</div>
    </div>
    </div>
    """, unsafe_allow_html=True)

    def _check_site_pw():
        pw_in = st.session_state.get("site_pw_input", "")
        if pw_in == pw:
            st.session_state["site_authenticated"] = True
        elif pw_in:
            st.session_state["site_pw_error"] = True
        else:
            st.session_state["site_pw_error"] = False

    pw_input = st.text_input(
        "Lösenord",
        type="password",
        key="site_pw_input",
        placeholder="Ange lösenord",
        label_visibility="collapsed",
        on_change=_check_site_pw,
    )

    if st.session_state.get("site_pw_error"):
        st.error("❌ Fel lösenord!")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔓 Lås upp", key="btn_site_unlock", use_container_width=True, type="primary"):
            if pw_input == pw:
                st.session_state["site_authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Fel lösenord!")

    return False


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

    # Global lösenordsskydd – körs innan allt annat
    if not _check_site_access():
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

        elif page == "🔧 Admin":
            page_admin()


if __name__ == "__main__":
    main()
