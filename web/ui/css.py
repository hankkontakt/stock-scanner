"""
css.py — Global CSS byggd från designtokens.

EN källa för all global styling (ersätter det spridda CSS-blocket i
streamlit_app.py + inline-styles i sidorna). Injiceras en gång i appstart via
inject_global_css(). Allt härleds från tokens.py så färg/spacing/radius är
konsekvent och ändras på ett ställe.
"""
import streamlit as st

from web.ui import tokens as t


def _stylesheet() -> str:
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Bas ─────────────────────────────────────────────────────────────── */
html, body, [class*="css"], .stApp {{
    font-family: {t.FONT};
    color: {t.TEXT};
}}
.stApp {{ background: {t.BG}; }}

/* Bredare, luftigare innehållsyta */
.block-container {{
    padding-top: 2.2rem;
    padding-bottom: 3rem;
    max-width: 1280px;
}}

/* ── Typografisk hierarki ────────────────────────────────────────────── */
h1 {{ font-size: {t.TYPE_TITLE}px !important; font-weight: {t.WEIGHT_SEMI} !important;
      letter-spacing: -0.01em; }}
h2 {{ font-size: {t.TYPE_H2}px !important;   font-weight: {t.WEIGHT_SEMI} !important; }}
h3 {{ font-size: {t.TYPE_BODY}px !important; font-weight: {t.WEIGHT_SEMI} !important;
      color: {t.TEXT_DIM} !important; text-transform: uppercase; letter-spacing: 0.05em; }}

/* ── Kort / paneler ──────────────────────────────────────────────────── */
.ms-card {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: {t.RADIUS}px;
    padding: {t.SPACE_LG}px {t.SPACE_XL}px;
    box-shadow: {t.SHADOW_CARD};
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}}
.ms-card:hover {{ border-color: {t.BORDER_HI}; box-shadow: {t.SHADOW_HOVER}; }}

/* Streamlits bordered container → samma kortlook */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {t.SURFACE};
    border-radius: {t.RADIUS}px;
    box-shadow: {t.SHADOW_CARD};
}}

/* ── Metric-kort ─────────────────────────────────────────────────────── */
.ms-metric {{ display: flex; flex-direction: column; gap: 4px; }}
.ms-metric .label {{
    font-size: {t.TYPE_LABEL}px; color: {t.TEXT_DIM};
    font-weight: {t.WEIGHT_MED}; text-transform: uppercase; letter-spacing: 0.04em;
    display: flex; align-items: center; gap: 4px;
}}
.ms-metric .value {{ font-size: {t.TYPE_HERO}px; font-weight: {t.WEIGHT_SEMI};
                     line-height: 1.1; color: {t.TEXT}; }}
.ms-metric .value.sm {{ font-size: {t.TYPE_H2}px; }}
.ms-metric .delta {{ font-size: {t.TYPE_LABEL}px; font-weight: {t.WEIGHT_MED}; }}

/* ── Status-taggar ───────────────────────────────────────────────────── */
.ms-tag {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 9px; border-radius: {t.RADIUS_SM}px;
    font-size: {t.TYPE_MICRO}px; font-weight: {t.WEIGHT_SEMI};
    border: 1px solid transparent; line-height: 1.6;
}}
.ms-tag.pos {{ background: {t.POS}1f; color: {t.POS}; border-color: {t.POS}55; }}
.ms-tag.neg {{ background: {t.NEG}1f; color: {t.NEG}; border-color: {t.NEG}55; }}
.ms-tag.warn {{ background: {t.WARN}1f; color: {t.WARN}; border-color: {t.WARN}55; }}
.ms-tag.neutral {{ background: {t.SURFACE_2}; color: {t.TEXT_DIM}; border-color: {t.BORDER}; }}

/* ── Tabeller ────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {{ border-radius: {t.RADIUS}px; }}
thead tr th {{
    text-transform: uppercase; font-size: {t.TYPE_MICRO}px !important;
    letter-spacing: 0.05em; color: {t.TEXT_DIM} !important;
}}

/* ── Avdelare (sparsamt, bara mellan stora zoner) ────────────────────── */
hr {{ border: none; border-top: 1px solid {t.BORDER}; margin: {t.SPACE_XL}px 0; }}

/* ── Knappar ─────────────────────────────────────────────────────────── */
.stButton > button {{
    border-radius: {t.RADIUS_SM}px; font-weight: {t.WEIGHT_MED};
    border: 1px solid {t.BORDER};
}}
.stButton > button:hover {{ border-color: {t.PRIMARY}; color: {t.PRIMARY}; }}

/* ── Sidofält / navigation ───────────────────────────────────────────── */
section[data-testid="stSidebar"] {{ background: {t.SURFACE}; border-right: 1px solid {t.BORDER}; }}

/* ── Subtil sidövergång ──────────────────────────────────────────────── */
.main .block-container {{ animation: msfade 0.25s ease; }}
@keyframes msfade {{ from {{ opacity: 0; transform: translateY(4px); }}
                     to {{ opacity: 1; transform: none; }} }}

/* ── Mobil ───────────────────────────────────────────────────────────── */
@media (max-width: 640px) {{
    .block-container {{ padding-top: 1.2rem; }}
    .ms-metric .value {{ font-size: {t.TYPE_TITLE}px; }}
    .stButton > button {{ min-height: 44px; }}
}}
"""


def inject_global_css() -> None:
    """Injicera den globala stilmallen. Anropas en gång vid appstart."""
    st.markdown(f"<style>{_stylesheet()}</style>", unsafe_allow_html=True)
