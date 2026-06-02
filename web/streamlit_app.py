"""
MarketScan Dashboard - Interaktiv börsanalys
============================================
Läser utdata från scan.py, smallcap/scanner.py och portfolio.py.

Kör lokalt : streamlit run streamlit_app.py
Deploya    : anslut GitHub-repo till streamlit.io/cloud
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# ── Sökvägar - MÅSTE komma INNAN projekt-importer ────────────────────────────
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

# ── i18n: Locale Detection ───────────────────────────────────────────────────────
# Prioritet: st.query_params > session_state > browser > default "sv"
def detect_locale() -> str:
    """Detektera anvandarens locale fran query_params, session_state eller default."""
    # 1. Query param (hogst prioritet - for url-based val)
    try:
        locale_qp = st.query_params.get("locale")
        if locale_qp in ("sv", "en", "de"):
            return locale_qp
    except Exception:
        pass

    # 2. Session state
    locale_ss = st.session_state.get("locale", "")
    if locale_ss in ("sv", "en", "de"):
        return locale_ss

    # 3. Default
    return "sv"


# Initiera TranslationManager
from core.i18n import TranslationManager
T = TranslationManager(detect_locale())
st.session_state.setdefault("locale", T.locale)
from web.utils import (
    load_scan_reports, load_smallcap_reports, load_portfolio, load_watchlist,
    _get_provider, _get_depth,
)
from web.pages.overview        import page_overview
from web.pages.weekly_scan     import page_weekly_scan
from web.pages.smallcap        import page_smallcap
try:
    from web.pages.portfolio   import (
        page_portfolio, page_portfolio_holdings, page_portfolio_analysis,
        page_portfolio_rebalance, page_portfolio_manage,
    )
except Exception as _pf_err:
    # Defensiv: en enskild sidas import-fel får aldrig krascha HELA appen.
    # Visar tydligt fel på portföljsidorna istället, resten av appen fungerar.
    import streamlit as _st_pf
    _PF_IMPORT_ERR = _pf_err
    def _pf_stub(*_a, **_k):
        _st_pf.error(f"Portföljsidan kunde inte laddas: {_PF_IMPORT_ERR}")
        _st_pf.caption("Övriga delar av appen fungerar. Kontakta admin / kolla loggar.")
    page_portfolio = page_portfolio_holdings = page_portfolio_analysis = \
        page_portfolio_rebalance = page_portfolio_manage = _pf_stub
from web.pages.technical       import page_technical
from web.pages.ai_page         import page_ai
from web.pages.admin           import _search_ticker_yfinance
from web.pages.admin_page      import page_admin
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
from web.pages.universe_explorer import page_universe_explorer
from web.pages.options_dashboard import page_options_dashboard
from web.pages.strategy_builder import page_strategy_builder
import traceback

# ── P

def _safe_render(page_name: str, fn, *args, **kwargs):
    """Rensa en sida med felisolering. Om sidan kraschar visas felmeddelandet
    och resten av appen fungerar."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        st.error(f"Sidan {page_name} kunde inte laddas: {e}")
        st.caption("Ovriga delar av appen fungerar som vanligt.")
        with st.expander("Visa tekniska detaljer", expanded=False):
            st.code(traceback.format_exc())


def _validate_api_keys():
    """Visar varningsbanners for saknade API-nycklar utan att blockera appen."""
    import os
    missing = []
    provider = os.getenv("AI_PROVIDER", "auto") or "auto"
    if provider in ("auto", "deepseek"):
        if not os.getenv("DEEPSEEK_API_KEY"):
            missing.append("DEEPSEEK_API_KEY")
    if provider in ("auto", "gemini"):
        if not os.getenv("GEMINI_API_KEY"):
            missing.append("GEMINI_API_KEY")
    if not os.getenv("FINNHUB_API_KEY"):
        missing.append("FINNHUB_API_KEY (sentimentdata)")
    if missing:
        st.warning(
            "Foljande API-nycklar saknas: "
            + ", ".join(f"**{k}**" for k in missing)
            + ". Funktioner som kravver dessa kommer att misslyckas eller anvanda fallback."
        )
    # Check for old env var names that won't be picked up
    if os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_API_KEY").startswith("sk-or-"):
        st.warning(
            "GEMINI_API_KEY ser ut att vara en OpenRouter-nyckel (börjar med sk-or-). "
            "Gemini API-nycklar börjar med AIza. Kontrollera din konfiguration."
        )

# ── Page-konfiguration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MarketScan",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS (migrerad till web/ui/css.py) ──────────────────────────────────
# All global styling is in the centralized CSS design system (web/ui/css.py),
# which is injected below. The old inline CSS block (formerly lines 116-253)
# has been removed -- everything is now driven by design tokens from tokens.py
# with [data-testid] selectors, animations, card components, and responsive
# breakpoints at 768px and 1024px.

# ── Injicera designsystem (web/ui) -- kort, metrics, taggar, typografi ───────
try:
    from web.ui.css import inject_global_css
    from web.ui.icons import ic
    inject_global_css()
except Exception:
    def ic(_k):  # fallback om web.ui saknas
        return ""


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
                    if st.button(f"{_h['ticker']} -- {_h['name'][:40]}", key=f"gs_{_h['ticker']}", use_container_width=True):
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
            "options":        "📊 Options & Derivator",
            "portfolio":      "💼 Portfölj",
            "portfolio-analysis":  "💼 Portföljanalys",
            "portfolio-rebalance": "💼 Rebalansering",
            "portfolio-manage":    "💼 Hantera innehav",
            "paper-trading":  "📄 Paper Trading",
            "ai-paper-trading":"🤖 AI Paper Trading",
            "alerts":         "🚨 Larm & Notiser",
            "settings":       "⚙️ Inställningar",
            "technical":      "📈 Teknisk analys",
            "ai":             "🤖 AI",
            "admin":          "🔧 Admin",
            "ai-journal":     "📓 AI Journal",
            "universe":       "🔭 Universe Explorer",
            "strategy":       "🔧 Strategy Builder",
            "stock-compare":  "🔀 Stock Comparison",
        }
        _reverse_map = {v: k for k, v in _known_pages.items()}

        # Läs query_param "p" från URL:en.
        # st.query_params["p"] = key  i _navigate_to() sätter URL:en via pushState
        # (Streamlit >=1.31). Streamlit lyssnar på popstate och kör om scriptet med
        # de nya query_params -> tillbaka/framåt-knappen fungerar utan extra JS.
        _qp = st.query_params.get_all("p")
        _qp_page = _qp[0] if _qp else None
        if _qp_page and _qp_page in _known_pages:
            st.session_state["nav_page"] = _known_pages[_qp_page]
        elif "nav_page" not in st.session_state:
            st.session_state["nav_page"] = "📊 Översikt"

        def _navigate_to(page_title: str):
            """Navigera till en sida."""
            st.session_state["nav_page"] = page_title
            qp_key = _reverse_map.get(page_title, "overview")
            st.query_params["p"] = qp_key
            # Track recent pages
            _recent = st.session_state.setdefault("_recent_pages", [])
            if page_title in _recent:
                _recent.remove(page_title)
            _recent.insert(0, page_title)
            st.session_state["_recent_pages"] = _recent[:10]
            st.rerun()

        def _nav_button(nav_key: str, display: str, icon_key: str):
            """Nav-knapp med Material-ikon (ersätter emoji)."""
            if st.button(display, key=f"sb_{nav_key}", use_container_width=True,
                         icon=ic(icon_key) or None):
                _navigate_to(nav_key)

        # ── Searchable navigation filter ──────────────────────────────────────
        _nav_search = st.text_input(
            "\U0001f50d Filter pages...",
            placeholder="Type to filter...",
            key="nav_filter",
            label_visibility="collapsed",
        )
        _nav_q = _nav_search.strip().lower() if _nav_search else ""

        # ── Recent pages (show last 3 visited) ────────────────────────────────
        _recent = st.session_state.setdefault("_recent_pages", [])
        if _recent and not _nav_q:
            st.markdown("""
<div style="font-size:9px;font-weight:700;color:#4a5568;letter-spacing:0.12em;text-transform:uppercase;margin:8px 0 4px;">
  Senaste sidor
</div>
""", unsafe_allow_html=True)
            for _rp in _recent[:3]:
                if _rp in _reverse_map:
                    if st.button(f"• {_rp}", key=f"recent_{_reverse_map[_rp]}", use_container_width=True):
                        _navigate_to(_rp)
            st.markdown('<div style="height:1px;background:linear-gradient(to right,transparent,#2d3250 30%,#2d3250 70%,transparent);margin:6px 0;"></div>', unsafe_allow_html=True)

        # ── Pinned pages (⭐) ─────────────────────────────────────────────────
        _pinned = st.session_state.setdefault("_pinned_pages", ["\U0001f4ca Översikt", "\U0001f50d Veckoscanner"])
        if _pinned and not _nav_q:
            st.markdown("""
<div style="font-size:9px;font-weight:700;color:#4a5568;letter-spacing:0.12em;text-transform:uppercase;margin:8px 0 4px;">
  Favoriter
</div>
""", unsafe_allow_html=True)
            for _pp in _pinned[:5]:
                if _pp in _reverse_map:
                    _pk = _reverse_map[_pp]
                    if st.button(f"⭐ {_pp}", key=f"pin_{_pk}", use_container_width=True):
                        _navigate_to(_pp)
            st.markdown('<div style="height:1px;background:linear-gradient(to right,transparent,#2d3250 30%,#2d3250 70%,transparent);margin:6px 0;"></div>', unsafe_allow_html=True)

        # ── Pin/unpin current page toggle ─────────────────────────────────────
        _current_page = st.session_state.get("nav_page", "\U0001f4ca Översikt")
        _is_pinned = _current_page in _pinned
        if st.button(
            f"{'⭐' if _is_pinned else '☆'} {'Unpin' if _is_pinned else 'Pin'} current page",
            key="nav_toggle_pin",
            use_container_width=True,
            help="Pin this page to your favorites at the top of the sidebar.",
        ):
            if _is_pinned:
                _pinned.remove(_current_page)
            else:
                _pinned.insert(0, _current_page)
            st.session_state["_pinned_pages"] = _pinned[:10]

        # ── Sektioner med collapse state ──────────────────────────────────────
        # Collapse all sections by default (persist expand/collapse state)
        _has_filter = bool(_nav_q)
        _SECTIONS = [
            ("MARKNAD", True, [
                ("🔍 Veckoscanner",     "Veckoscanner",      "scanner"),
                ("🏦 Småbolag",         "Småbolag",          "smallcap"),
                ("🌍 Globala marknader","Globala marknader", "globe"),
                ("🏭 Sektorrotation",   "Sektorrotation",    "sector"),
                ("🔭 Universe Explorer","Universe Explorer", "explore"),
            ]),
            ("AKTIE", True, [
                ("📈 Teknisk analys",   "Teknisk analys",    "technical"),
                ("🔀 Stock Comparison","Stock Comparison",  "stock"),
                ("📊 Options & Derivator", "Options & Derivator", "chart"),
                ("⭐ Bevakningar",      "Bevakningar",       "watch"),
            ]),
            ("PORTFÖLJ", True, [
                ("💼 Portfölj",          "Innehav",           "holdings"),
                ("💼 Portföljanalys",    "Analys",            "analysis"),
                ("💼 Rebalansering",     "Rebalansering",     "rebalance"),
                ("💼 Hantera innehav",   "Hantera innehav",   "manage"),
            ]),
            ("SIMULERING", False, [
                ("📄 Paper Trading",    "Paper Trading",     "paper"),
                ("🤖 AI Paper Trading", "AI Paper Trading",  "simulation"),
                ("📈 Backtesting",      "Backtesting",       "backtest"),
                ("🔧 Strategy Builder", "Strategy Builder",   "strategy"),
            ]),
            ("AI & LARM", False, [
                ("🚨 Larm & Notiser",   "Larm & Notiser",    "alerts"),
                ("🤖 AI",               "AI-analys",         "ai"),
                ("📓 AI Journal",       "AI Journal",        "journal"),
            ]),
            ("KONTO", False, [
                ("⚙️ Inställningar",    "Inställningar",      "settings"),
                ("📚 Guide & Hjälp",    "Guide & Hjälp",     "guide"),
            ]),
        ]
        for sec_name, sec_open, pages in _SECTIONS:
            if _has_filter:
                filtered_pages = [
                    p for p in pages
                    if _nav_q in p[0].lower() or _nav_q in p[1].lower()
                ]
                if not filtered_pages:
                    continue
                display_pages = filtered_pages
                sec_expanded = True
            else:
                display_pages = pages
                _sec_key = f"_nav_sec_{sec_name}"
                if _sec_key not in st.session_state:
                    st.session_state[_sec_key] = sec_open
                sec_expanded = st.session_state[_sec_key]
            with st.expander(sec_name, expanded=sec_expanded):
                for nav_key, display, icon_key in display_pages:
                    _nav_button(nav_key, display, icon_key)

        # Admin - bara synlig för admin-användaren
        if st.session_state.get("username", "admin") == "admin":
            # Badge för pending HIGH-tier kandidater
            _pending_badge = ""
            try:
                from core.universe_manager import get_pending_candidates
                _pending = get_pending_candidates()
                _high = [c for c in _pending if c.get("quality_tier") == "HIGH"]
                if _high:
                    _pending_badge = f" 🔍 {len(_high)} nya"
            except Exception:
                pass

            if st.button(f"🔧 Admin{_pending_badge}", key="nav_admin", use_container_width=True):
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
                        help="Döljer aktier med uppskattad dagsomsättning under $50k/dag (avg_volume x kurs x FX).",
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

        # ── AI-tjänst (provider) ─────────────────────────────────────────────
        # AI-DJUP väljs inte längre globalt här -- det väljs vid varje AI-åtgärd
        # (se web/ui/ai_action.py). Bara providern är global.
        with st.expander("AI-tjänst", expanded=False):
            ai_provider = st.selectbox(
                "Tjänst", ["auto", "deepseek", "gemini"],
                format_func=lambda k: {"auto": f"Auto ({config.AI_PROVIDER})",
                                       "deepseek": "DeepSeek", "gemini": "Gemini"}.get(k, k),
                key="sidebar_ai_provider",
            )
            st.session_state["selected_provider"] = ai_provider

        # ── Sparade vyer ─────────────────────────────────────────────────────
        try:
            from web.ui.saved_views import render_saved_views_ui as _render_saved_views
            _current_view_config = {
                "page": page,
                "filters": filters,
                "date_selection": f"{scan_date} / {sc_date}",
            }
            _loaded_view = _render_saved_views(current_config=_current_view_config)
            if _loaded_view:
                # Apply loaded view config
                pass
        except Exception:
            pass

        # ── Experience mode toggle ────────────────────────────────────────────
        try:
            from web.ui.experience_mode import InvestorExperience as _ExpMgr
            _exp = _ExpMgr()
            _exp.render_toggle()
        except Exception:
            pass

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
        _time_str = "--"
        if _latest_scan_file:
            _mt = datetime.fromtimestamp(_latest_scan_file.stat().st_mtime)
            _tz = datetime.now().astimezone().tzinfo
            _time_str = _mt.astimezone(_tz).strftime("%Y-%m-%d %H:%M")
        st.caption(f"🟢 {len(scan_dates) if scan_dates else 0} datum * Senast: {max(scan_dates) if scan_dates else '--'} [{_time_str}]")

        # Data-färskhetsvarning: visa orange/röd banner om data är gammal
        if _latest_scan_file:
            from datetime import timedelta
            _age_hours = (datetime.now() - datetime.fromtimestamp(_latest_scan_file.stat().st_mtime)).total_seconds() / 3600
            if _age_hours > 72:
                st.warning(f"⚠️ Scandata är **{_age_hours/24:.0f} dagar** gammal -- senaste vecko­scan misslyckades troligen. Trigga manuellt via Admin -> Kör scan.", icon="⚠️")
            elif _age_hours > 48:
                st.info(f"ℹ️ Scandata är **{_age_hours:.0f}h** gammal. Nästa schema­lagda uppdatering sker snart.", icon="ℹ️")

        # ── Språkväljare i sidebar footer ─────────────────────────────────────
        _current_locale = T.locale
        _locale_labels = {"sv": "SV", "en": "EN", "de": "DE"}
        locale_cols = st.columns(3)
        for i, (loc, label) in enumerate(_locale_labels.items()):
            with locale_cols[i]:
                if st.button(
                    label,
                    key=f"locale_{loc}",
                    use_container_width=True,
                    type="secondary" if _current_locale != loc else "primary",
                    help=TranslationManager().get_locale_name(loc),
                ):
                    st.session_state["locale"] = loc
                    T.set_locale(loc)
                    try:
                        st.query_params["locale"] = loc
                    except Exception:
                        pass
                    st.rerun()

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

Länken är giltig i **1 timme**. Om du inte begärde detta kan du ignorera detta mail --
ditt konto är oförändrat.

---
*MarketScan * Automatiskt utskick*
"""
        return send_email(
            subject="🔐 MarketScan - återställ lösenord",
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
            # - lägg till som override-post
            data.setdefault("users", []).append({
                "username": uname_lower,
                "name": username,
                "email": "",
                "password": new_hashed,
                "active": True,
                "added": _dt.now().strftime("%Y-%m-%d"),
                "password_reset": True,
            })
        content = _j.dumps(data, indent=2, ensure_ascii=False)
        path.write_text(content, encoding="utf-8")
        # Committa till GitHub -- annars försvinner lösenordsbytet vid nästa
        # Streamlit Cloud-omstart och användaren låses ute / får tillbaka gammalt lösen.
        try:
            from web.pages.admin import _get_github_token, _github_commit_file
            token = _get_github_token()
            if token:
                _github_commit_file("data/users_config.json", content, token,
                                    message=f"Update password for {uname_lower}")
        except Exception:
            pass
        return True
    except Exception:
        pass
    return False


def _handle_password_reset_flow() -> bool:
    """
    Kontrollerar om URL:en innehåller en reset_token och hanterar i så fall
    hela lösenordsåterställningssidan.

    Returnerar True om sidan tas över (token hittades i URL) -> anroparen ska stopa appen.
    Returnerar False om ingen token finns i URL -> normal inloggning fortsätter.
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
                # Hasha lösenordet -- prova olika API-varianter beroende på version
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
    efter en lysenordsåterställning -- den slås samman ÖVER secrets-värdet.
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
    1. Om credentials INTE är konfigurerade i secrets -> öppen åtkomst (lokal körning)
    2. Admin-credentials läses från Streamlit Secrets
    3. Övriga användare läses från data/users_config.json (hanteras via admin-sidan)
    4. Om redan inloggad via cookie -> True direkt
    5. Annars -> visa inloggningsformulär

    Sätter session_state["username"] efter lyckad inloggning.
    """
    if not _has_credentials_configured():
        # Lokal körning utan secrets - öppen åtkomst, sätt admin som default-användare
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

    # Om URL har reset_token -> visa lösenordsåterställning istället för inloggning
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
    # status is None -> väntar på input
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

    # Global inloggning - körs innan allt annat
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
            _safe_render("Veckoscanner", page_weekly_scan, df, filters, holdings, watchlist)

        elif page == "🏦 Småbolag":
            if not sc_df.empty and "sector" in sc_df.columns:
                secs = sorted(sc_df["sector"].dropna().unique().tolist())
            _safe_render("Smabolag", page_smallcap, sc_df, filters)

        elif page == "🔍 Aktie-sök":
            _safe_render("Aktie-sok", page_stock_search)

        elif page == "⭐ Bevakningar":
            _safe_render("Bevakningar", page_watchlist_detail, df, watchlist)

        elif page == "🌍 Globala marknader":
            _safe_render("Globala marknader", page_global_markets)

        elif page == "💼 Portfölj":
            _safe_render("Portfolj", page_portfolio_holdings, df, holdings, watchlist, sc_df=sc_df)

        elif page == "💼 Portföljanalys":
            _safe_render("Portfoljanalys", page_portfolio_analysis, df, holdings, watchlist, sc_df=sc_df)

        elif page == "💼 Rebalansering":
            _safe_render("Rebalansering", page_portfolio_rebalance, df, holdings, watchlist, sc_df=sc_df)

        elif page == "💼 Hantera innehav":
            _safe_render("Hantera innehav", page_portfolio_manage, df, holdings, watchlist, sc_df=sc_df)

        elif page == "📄 Paper Trading":
            _safe_render("Paper Trading", page_paper_trading)

        elif page == "🤖 AI Paper Trading":
            _safe_render("AI Paper Trading", page_ml_paper_trading)

        elif page == "🏭 Sektorrotation":
            _safe_render("Sektorrotation", page_sector_rotation, df)

        elif page == "🚨 Larm & Notiser":
            _safe_render("Larm & Notiser", page_alerts_notices, df)

        elif page == "📈 Backtesting":
            _safe_render("Backtesting", page_backtesting)

        elif page == "📈 Teknisk analys":
            if not df.empty and "sector" in df.columns:
                secs = sorted(df["sector"].dropna().unique().tolist())
            _safe_render("Teknisk analys", page_technical, df, filters)

        elif page == "📊 Options & Derivator":
            _safe_render("Options & Derivator", page_options_dashboard)

        elif page == "🤖 AI":
            _safe_render("AI", page_ai, df, sc_df, holdings)

        elif page == "📓 AI Journal":
            _safe_render("AI Journal", page_ai_journal, df)

        elif page == "⚙️ Inställningar":
            from web.pages.settings_page import page_settings
            _safe_render("Installningar", page_settings)

        elif page == "🔭 Universe Explorer":
            _safe_render("Universe Explorer", page_universe_explorer, df)

        elif page == "🔀 Stock Comparison":
            from web.pages.stock_comparison import page_stock_comparison
            _safe_render("Stock Comparison", page_stock_comparison, df)

        elif page == "🔧 Strategy Builder":
            _safe_render("Strategy Builder", page_strategy_builder)

        elif page == "🔧 Admin":
            _safe_render("Admin", page_admin)

        elif page == "🔀 Stock Comparison":
            from web.pages.stock_comparison import page_stock_comparison
            _safe_render("Stock Comparison", page_stock_comparison, df)


if __name__ == "__main__":
    main()
