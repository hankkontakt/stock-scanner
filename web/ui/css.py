"""
css.py -- Centralized CSS Design System for MarketScan.

All global styling is injected once at app start via inject_global_css().
Uses CSS custom properties (design tokens) derived from tokens.py.
Overrides the old inline CSS block in streamlit_app.py (lines 116-253).

Built with Streamlit [data-testid] selectors for reliable targeting.
Mobile-first responsive design with breakpoints at 768px and 1024px.
"""
from __future__ import annotations

import streamlit as st

from web.ui import tokens as t


def _stylesheet() -> str:
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ═══════════════════════════════════════════════════════════════════════════
   DESIGN TOKENS (CSS Custom Properties)
   ═══════════════════════════════════════════════════════════════════════════ */
:root {{
    --bg-primary:    {t.BG};
    --bg-secondary:  #1a1f2e;
    --bg-card:       {t.SURFACE};
    --text-primary:  {t.TEXT};
    --text-secondary:#8892a4;
    --accent:        {t.PRIMARY};
    --success:       {t.POS};
    --warning:       {t.WARN};
    --danger:        {t.NEG};
    --border:        {t.BORDER};
    --border-hi:     {t.BORDER_HI};

    --font:          {t.FONT};
    --radius-card:   {t.RADIUS}px;
    --radius-sm:     {t.RADIUS_SM}px;
    --radius-lg:     {t.RADIUS_LG}px;

    --shadow-card:   {t.SHADOW_CARD};
    --shadow-hover:  {t.SHADOW_HOVER};

    --space-xs:  {t.SPACE_XS}px;
    --space-sm:  {t.SPACE_SM}px;
    --space-md:  {t.SPACE_MD}px;
    --space-lg:  {t.SPACE_LG}px;
    --space-xl:  {t.SPACE_XL}px;
    --space-2xl: {t.SPACE_2XL}px;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   BASE / TYPOGRAPHY
   ═══════════════════════════════════════════════════════════════════════════ */
html, body, [class*="css"], .stApp {{
    font-family: var(--font);
    color: var(--text-primary);
}}

.stApp {{
    background: var(--bg-primary);
}}

/* Typographic hierarchy */
h1, h2, h3 {{ font-weight: 700 !important; letter-spacing: -0.02em !important; }}
h1 {{ font-size: {t.TYPE_TITLE}px !important; }}
h2 {{ font-size: {t.TYPE_H2}px !important; }}
h3 {{ font-size: {t.TYPE_BODY}px !important; color: var(--text-secondary) !important;
      text-transform: uppercase; letter-spacing: 0.05em; }}

.block-container {{
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    max-width: 1280px;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   CARD COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    padding: 20px;
    box-shadow: var(--shadow-card);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}}
.ms-card:hover {{
    border-color: var(--border-hi);
    box-shadow: var(--shadow-hover);
}}

/* Streamlit bordered containers -> card look */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: var(--bg-card);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-card);
}}

/* ═══════════════════════════════════════════════════════════════════════════
   METRIC CARDS
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-metric {{
    display: flex;
    flex-direction: column;
    gap: 4px;
}}
.ms-metric .label {{
    font-size: {t.TYPE_LABEL}px;
    color: var(--text-secondary);
    font-weight: {t.WEIGHT_MED};
    text-transform: uppercase;
    letter-spacing: 0.04em;
    display: flex;
    align-items: center;
    gap: 4px;
}}
.ms-metric .value {{
    font-size: {t.TYPE_HERO}px;
    font-weight: {t.WEIGHT_SEMI};
    line-height: 1.1;
    color: var(--text-primary);
}}
.ms-metric .value.sm {{
    font-size: {t.TYPE_H2}px;
}}
.ms-metric .delta {{
    font-size: {t.TYPE_LABEL}px;
    font-weight: {t.WEIGHT_MED};
}}

/* ═══════════════════════════════════════════════════════════════════════════
   STATUS TAGS / CHIPS
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-tag {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 9px;
    border-radius: var(--radius-sm);
    font-size: {t.TYPE_MICRO}px;
    font-weight: {t.WEIGHT_SEMI};
    border: 1px solid transparent;
    line-height: 1.6;
}}
.ms-tag.pos {{ background: {t.POS}1f; color: {t.POS}; border-color: {t.POS}55; }}
.ms-tag.neg {{ background: {t.NEG}1f; color: {t.NEG}; border-color: {t.NEG}55; }}
.ms-tag.warn {{ background: {t.WARN}1f; color: {t.WARN}; border-color: {t.WARN}55; }}
.ms-tag.neutral {{ background: {t.SURFACE_2}; color: {t.TEXT_DIM}; border-color: {t.BORDER}; }}

/* Legacy tag classes (for backward compat) */
.tag-green  {{ background:#1a3a2a; color:#4caf50; border:1px solid #4caf50;
              border-radius:4px; padding:1px 7px; font-size:11px; }}
.tag-yellow {{ background:#3a3010; color:#ffc107; border:1px solid #ffc107;
              border-radius:4px; padding:1px 7px; font-size:11px; }}
.tag-red    {{ background:#3a1010; color:#ef5350; border:1px solid #ef5350;
              border-radius:4px; padding:1px 7px; font-size:11px; }}
.tag-blue   {{ background:#0d2137; color:#42a5f5; border:1px solid #42a5f5;
              border-radius:4px; padding:1px 7px; font-size:11px; }}
.tag-grey   {{ background:var(--bg-card); color:var(--text-secondary); border:1px solid #4a5568;
              border-radius:4px; padding:1px 7px; font-size:11px; }}

/* ═══════════════════════════════════════════════════════════════════════════
   TABLES
   ═══════════════════════════════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {{
    border-radius: var(--radius-card);
}}
thead tr th {{
    text-transform: uppercase;
    font-size: {t.TYPE_MICRO}px !important;
    letter-spacing: 0.05em;
    color: var(--text-secondary) !important;
}}
.stDataFrame thead th {{
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-secondary) !important;
    background: #1a1f2e !important;
    border-bottom: 2px solid var(--border) !important;
}}
.stDataFrame tbody td {{ font-size: 13px !important; }}
.stDataFrame tbody tr:hover td {{
    background: rgba(76,155,232,0.04) !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   DIVIDER
   ═══════════════════════════════════════════════════════════════════════════ */
hr {{
    border: none !important;
    height: 1px !important;
    background: linear-gradient(to right, transparent, var(--border) 20%, var(--border) 80%, transparent) !important;
    margin: 28px 0 20px 0 !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   BUTTONS
   ═══════════════════════════════════════════════════════════════════════════ */
.stButton > button {{
    border-radius: var(--radius-sm);
    font-weight: {t.WEIGHT_MED};
    border: 1px solid var(--border);
}}
.stButton > button:hover {{
    border-color: var(--accent);
    color: var(--accent);
}}

/* ═══════════════════════════════════════════════════════════════════════════
   SIDEBAR / NAVIGATION
   ═══════════════════════════════════════════════════════════════════════════ */
section[data-testid="stSidebar"] {{
    background: #131722;
    border-right: 1px solid var(--border);
}}
div[data-testid="stSidebarContent"] {{
    background: #131722;
}}

/* Nav buttons */
div[data-testid="stSidebarContent"] .stButton button {{
    background: transparent !important;
    border: none !important;
    border-left: 3px solid transparent !important;
    border-radius: 0 6px 6px 0 !important;
    text-align: left !important;
    font-weight: 400 !important;
    font-size: 13px !important;
    color: var(--text-secondary) !important;
    padding: 7px 12px !important;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease !important;
    width: 100% !important;
}}
div[data-testid="stSidebarContent"] .stButton button:hover {{
    background: rgba(76,155,232,0.08) !important;
    border-left-color: var(--accent) !important;
    color: var(--text-primary) !important;
}}
div[data-testid="stSidebarContent"] .streamlit-expanderHeader {{
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #4a5568 !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   ANIMATIONS
   ═══════════════════════════════════════════════════════════════════════════ */

/* Page fade-in transition */
.main .block-container,
[data-testid="stMainBlockContainer"] > div:first-child,
[data-testid="block-container"] {{
    animation: msPageIn 0.25s ease;
}}

@keyframes msPageIn {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}

/* Card fade-in */
.ms-card {{
    animation: msFadeIn 0.3s ease;
}}
@keyframes msFadeIn {{
    from {{ opacity: 0; transform: translateY(4px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}

/* Slide-up panels */
.ms-slide-up {{
    animation: msSlideUp 0.3s ease;
}}
@keyframes msSlideUp {{
    from {{ opacity: 0; transform: translateY(16px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
}}

/* Pulse for loading states */
.ms-pulse {{
    animation: msPulse 1.5s ease-in-out infinite;
}}
@keyframes msPulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
}}

/* ═══════════════════════════════════════════════════════════════════════════
   LOADING SKELETON
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-skeleton {{
    background: linear-gradient(
        90deg,
        var(--bg-card) 25%,
        #252b3b 50%,
        var(--bg-card) 75%
    );
    background-size: 200% 100%;
    animation: msShimmer 1.5s ease-in-out infinite;
    border-radius: var(--radius-sm);
}}
@keyframes msShimmer {{
    0% {{ background-position: 200% 0; }}
    100% {{ background-position: -200% 0; }}
}}

.ms-skeleton-line {{
    height: 14px;
    margin-bottom: 8px;
    border-radius: 4px;
    background: linear-gradient(
        90deg,
        var(--bg-card) 25%,
        #252b3b 50%,
        var(--bg-card) 75%
    );
    background-size: 200% 100%;
    animation: msShimmer 1.5s ease-in-out infinite;
}}

.ms-skeleton-line:last-child {{ width: 60%; }}
.ms-skeleton-line:nth-child(2) {{ width: 85%; }}
.ms-skeleton-line:nth-child(3) {{ width: 70%; }}
.ms-skeleton-line:nth-child(4) {{ width: 90%; }}

.ms-skeleton-block {{
    height: 200px;
    border-radius: var(--radius-card);
    background: linear-gradient(
        90deg,
        var(--bg-card) 25%,
        #252b3b 50%,
        var(--bg-card) 75%
    );
    background-size: 200% 100%;
    animation: msShimmer 1.5s ease-in-out infinite;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   PROGRESS BAR (AI Analysis)
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-progress {{
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
}}
.ms-progress-bar {{
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    overflow: hidden;
}}
.ms-progress-fill {{
    height: 100%;
    border-radius: 2px;
    background: var(--accent);
    transition: width 0.3s ease;
    animation: msProgressPulse 1.5s ease-in-out infinite;
}}
@keyframes msProgressPulse {{
    0%, 100% {{ opacity: 0.8; }}
    50% {{ opacity: 1; }}
}}
.ms-progress-label {{
    font-size: {t.TYPE_LABEL}px;
    color: var(--text-secondary);
}}

/* ═══════════════════════════════════════════════════════════════════════════
   PLOTLY OVERRIDES
   ═══════════════════════════════════════════════════════════════════════════ */
.js-plotly-plot, .plotly {{ max-width: 100% !important; }}
.js-plotly-plot .plotly .main-svg {{ border-radius: var(--radius-sm); }}

/* ═══════════════════════════════════════════════════════════════════════════
   SORT INDICATORS
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-sort-asc::after {{ content: " \\25B2"; font-size: 10px; }}
.ms-sort-desc::after {{ content: " \\25BC"; font-size: 10px; }}

/* ═══════════════════════════════════════════════════════════════════════════
   INLINE TOOLTIP
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-tooltip {{
    position: relative;
    cursor: help;
    border-bottom: 1px dashed var(--text-secondary);
}}
.ms-tooltip:hover::after {{
    content: attr(data-tip);
    position: absolute;
    bottom: 100%;
    left: 0;
    z-index: 1000;
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 8px 12px;
    font-size: {t.TYPE_MICRO}px;
    font-weight: {t.WEIGHT_REG};
    white-space: nowrap;
    box-shadow: var(--shadow-card);
    pointer-events: none;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   RESPONSIVE — TABLET (max-width: 1024px)
   ═══════════════════════════════════════════════════════════════════════════ */
@media (max-width: 1024px) {{
    .block-container {{
        padding-top: 1.8rem;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100%;
    }}
    [data-testid="column"] {{
        min-width: 28% !important;
    }}
    /* 4-kolumns KPI-rader → 2+2 på tablet */
    [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(n+3) {{
        margin-top: 0;
    }}
}}

/* ═══════════════════════════════════════════════════════════════════════════
   RESPONSIVE — MOBILE (max-width: 768px)
   ═══════════════════════════════════════════════════════════════════════════ */
@media (max-width: 768px) {{
    h1 {{ font-size: 20px !important; margin-bottom: 10px !important; }}
    h2 {{ font-size: 17px !important; }}
    h3 {{ font-size: 14px !important; }}

    /* Tabeller: horisontell scroll på mobil */
    .stDataFrame {{ overflow-x: auto !important; }}
    .stDataFrame table {{ min-width: 420px !important; }}
    .stDataFrame tbody td,
    .stDataFrame thead th {{ font-size: 12px !important; padding: 5px 7px !important; }}

    /* Touch-vänliga knappar */
    .stButton button {{ min-height: 44px !important; font-size: 14px !important; }}

    /* 4-kolumns KPI-grid → 2 per rad på mobil */
    [data-testid="column"] {{
        min-width: 44% !important;
        flex: 1 1 44% !important;
    }}
    [data-testid="stHorizontalBlock"] {{
        flex-wrap: wrap !important;
        gap: 8px !important;
    }}

    /* KPI-kort kompaktare på mobil */
    .ms-card.ms-metric {{ padding: 14px 16px !important; }}
    .ms-metric .value {{ font-size: {t.TYPE_TITLE}px !important; }}
    .ms-metric .value.sm {{ font-size: {t.TYPE_H2}px !important; }}
    .ms-metric .label {{ font-size: 10px !important; }}

    /* Plotly-grafer: full bredd */
    .js-plotly-plot {{ width: 100% !important; }}

    /* Formulär: förhindra zoom vid tap på iOS */
    input, select, textarea {{ font-size: 16px !important; }}

    /* Native Streamlit metric-kort */
    [data-testid="stMetric"] {{ padding: 10px !important; }}
    [data-testid="stMetricValue"] {{ font-size: 22px !important; }}

    /* Minska sidmarginaler för mer utrymme */
    .block-container {{
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
        padding-top: 1.2rem !important;
    }}
}}

/* ═══════════════════════════════════════════════════════════════════════════
   BEGINNER MODE — extra explanations, larger tooltips
   ═══════════════════════════════════════════════════════════════════════════ */
.ms-beginner .ms-card {{
    border-left: 3px solid var(--accent);
}}
.ms-beginner .ms-tooltip {{
    font-size: {t.TYPE_LABEL}px !important;
}}

/* ═══════════════════════════════════════════════════════════════════════════
   PRINT STYLES
   ═══════════════════════════════════════════════════════════════════════════ */
@media print {{
    section[data-testid="stSidebar"] {{ display: none !important; }}
    .main .block-container {{ max-width: 100% !important; padding: 0 !important; }}
    .stButton, .stDownloadButton {{ display: none !important; }}
}}
"""


def inject_global_css() -> None:
    """Inject the global stylesheet. Call once at app start."""
    st.markdown(f"<style>{_stylesheet()}</style>", unsafe_allow_html=True)
