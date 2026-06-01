"""
components.py -- Återanvändbara UI-byggblock för MarketScan.

Professionella komponenter som ersätter ad-hoc inline-HTML utspritt i sidorna.
Alla härleder utseende från tokens + glossary, så stil och hjälptexter är
konsekventa. Byggda för "zoner, inte ström": metric_card/kpi_grid/panel skapar
visuella kort som grupperas i st.columns istället för staplade fullbreddselement.
"""
from __future__ import annotations

import html as _html
from typing import Iterable

import pandas as pd
import streamlit as st

from web.ui import tokens as t
from web.ui.icons import ic
from web.ui.glossary import help_for, label_for


# ── Sidhuvud & sektioner ─────────────────────────────────────────────────────

def page_header(title: str, icon: str = "", subtitle: str = "") -> None:
    """Enhetlig sidrubrik med valfri Material-ikon + underrubrik."""
    icon_md = f"{ic(icon)} " if icon else ""
    st.markdown(f"# {icon_md}{title}")
    if subtitle:
        st.caption(subtitle)


def section(title: str, icon: str = "", help: str | None = None) -> None:
    """Sektionsrubrik (h3) med valfri ikon + info-bubbla.

    OBS: Streamlit har inget native help= på markdown-rubriker, så info läggs som
    en liten caption-rad under vid behov. För tyngre fall, använd `info_dot`.
    """
    icon_md = f"{ic(icon)} " if icon else ""
    st.markdown(f"### {icon_md}{title}")
    if help:
        st.caption(help)


# ── Metric-kort ──────────────────────────────────────────────────────────────

def metric_card(label: str, value: str, *, delta: str | None = None,
                delta_kind: str = "pos", help: str | None = None,
                value_color: str | None = None, small: bool = False) -> None:
    """Ett KPI-kort. Använd inuti en kolumn/container för zon-layout.

    delta_kind: 'pos' (grön) | 'neg' (röd) | 'neutral'.
    value_color: tvinga värdefärg (annars temaets textfärg).
    """
    delta_html = ""
    if delta is not None:
        dcol = {"pos": t.POS, "neg": t.NEG}.get(delta_kind, t.TEXT_DIM)
        delta_html = f'<div class="delta" style="color:{dcol}">{_html.escape(str(delta))}</div>'
    vcls = "value sm" if small else "value"
    vstyle = f"color:{value_color}" if value_color else ""
    # Info-titel via title=-attribut (native hover-tooltip)
    label_attr = f' title="{_html.escape(help)}"' if help else ""
    info_mark = " ⓘ" if help else ""
    st.markdown(
        f'<div class="ms-card ms-metric">'
        f'<div class="label"{label_attr}>{_html.escape(label)}{info_mark}</div>'
        f'<div class="{vcls}" style="{vstyle}">{_html.escape(str(value))}</div>'
        f'{delta_html}</div>',
        unsafe_allow_html=True,
    )


def kpi_grid(metrics: list[dict], cols: int = 4) -> None:
    """Responsivt rutnät av metric_card.

    metrics: lista av dicts med nycklar som matchar metric_card-argument:
        {"label","value","delta","delta_kind","help","value_color","small"}
    """
    if not metrics:
        return
    columns = st.columns(min(cols, len(metrics)))
    for i, m in enumerate(metrics):
        with columns[i % len(columns)]:
            metric_card(
                m.get("label", ""), m.get("value", "--"),
                delta=m.get("delta"), delta_kind=m.get("delta_kind", "pos"),
                help=m.get("help"), value_color=m.get("value_color"),
                small=m.get("small", False),
            )


# ── Taggar ───────────────────────────────────────────────────────────────────

def tag(text: str, kind: str = "neutral") -> str:
    """Returnerar HTML för ett status-chip (pos/neg/warn/neutral). Rendera via
    st.markdown(..., unsafe_allow_html=True) eller bädda in i annan HTML."""
    kind = kind if kind in ("pos", "neg", "warn", "neutral") else "neutral"
    return f'<span class="ms-tag {kind}">{_html.escape(str(text))}</span>'


def score_tag(score: float) -> str:
    """Tagg färgkodad efter score-band (stark/neutral/svag)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return tag("--", "neutral")
    kind = "pos" if s >= 70 else ("warn" if s >= 50 else "neg")
    return tag(f"{s:.0f}", kind)


# ── Paneler & tomtillstånd ───────────────────────────────────────────────────

def panel(title: str = "", icon: str = "", help: str | None = None):
    """Returnerar en bordered container (zon-kort) med valfri rubrikrad.
    Använd som: `with panel("Titel", "icon"): ...`."""
    box = st.container(border=True)
    if title:
        with box:
            section(title, icon, help)
    return box


def empty_state(message: str, icon: str = "info") -> None:
    """Vänligt tomtillstånd istället för en tom yta."""
    st.markdown(
        f'<div class="ms-card" style="text-align:center;color:{t.TEXT_DIM};padding:32px">'
        f'{ic(icon)} {_html.escape(message)}</div>',
        unsafe_allow_html=True,
    )


# ── Datatabell med kolumn-tooltips ───────────────────────────────────────────

def data_table(df: pd.DataFrame, *, column_help: dict | None = None,
               height: int | None = None, hide_index: bool = True) -> None:
    """Stylad tabell där kolumner får info-bubblor från glossary.

    column_help: {kolumnnamn: hjälptext}. Om None slås hjälp upp automatiskt via
    glossary för kolumner vars namn matchar en metric-nyckel.
    """
    if df is None or len(df) == 0:
        empty_state("Ingen data att visa.")
        return
    col_cfg = {}
    for col in df.columns:
        h = (column_help or {}).get(col) or help_for(str(col))
        if h:
            col_cfg[col] = st.column_config.Column(help=h)
    safe_height = None if height is None else max(height, 200)
    st.dataframe(df, use_container_width=True, hide_index=hide_index,
                 height=safe_height, column_config=col_cfg or None)


# ── Klickbar aktietabell (öppnar detaljvy vid klick) ─────────────────────────

def clickable_stock_table(df: pd.DataFrame, *, ticker_col: str = "ticker",
                          context_df: pd.DataFrame | None = None,
                          column_help: dict | None = None,
                          column_config: dict | None = None,
                          height: int | None = None, key: str = "cst",
                          detail_kwargs: dict | None = None,
                          caption: str = "Klicka på en rad för full analys.") -> None:
    """Visar en aktietabell där ett klick på en rad öppnar stock_detail-panelen.

    Återanvändbar överallt (teknisk analys, paper trading, småbolag, …) så att
    alla tabeller beter sig som ranking-tabellen.

    Args:
        df: tabellen att visa (måste ha en ticker-kolumn, ev. med flagg-prefix).
        ticker_col: kolumnnamn som innehåller tickern.
        context_df: scored_universe för att slå upp full rad + AI-kontext (valfritt).
        key: unik nyckel per tabell.
        detail_kwargs: extra argument till render_stock_detail (t.ex. show_news=False).
    """
    if df is None or len(df) == 0:
        empty_state("Ingen data att visa.")
        return
    if ticker_col not in df.columns:
        # Ingen ticker-kolumn -> vanlig tabell utan klick
        data_table(df, column_help=column_help, height=height)
        return

    st.caption(caption)
    col_cfg: dict = {}
    for col in df.columns:
        h = (column_help or {}).get(col) or help_for(str(col))
        if h:
            col_cfg[col] = st.column_config.Column(help=h)
    # Merge in caller-supplied column_config (overrides help-derived entries)
    if column_config:
        col_cfg.update(column_config)

    safe_height = None if height is None else max(height, 200)
    event = st.dataframe(
        df, use_container_width=True, hide_index=True, height=safe_height,
        column_config=col_cfg or None,
        on_select="rerun", selection_mode="single-row", key=key,
    )

    if event and getattr(event, "selection", None) and event.selection.get("rows"):
        idx = event.selection["rows"][0]
        raw = str(df.iloc[idx][ticker_col]).strip()
        # Hantera flagg-prefix som "🇸🇪 VOLV-B.ST" -> ta sista ordet
        ticker = raw.split()[-1] if " " in raw else raw
        row = None
        if context_df is not None and not context_df.empty and "ticker" in context_df.columns:
            m = context_df[context_df["ticker"].astype(str).str.upper() == ticker.upper()]
            if not m.empty:
                row = m.iloc[0]
        from web.stock_detail import render_stock_detail  # lat import -> undvik cirkulär
        with st.expander(f"Analys: {ticker}", expanded=True):
            render_stock_detail(ticker, row=row, df=context_df, **(detail_kwargs or {}))


# ── Genvägslänk (för dashboard "Visa allt ->") ────────────────────────────────

def shortcut(label: str, page_path: str, icon: str = "link") -> None:
    """Liten 'Visa allt ->'-länk till en annan sida (st.page_link)."""
    try:
        st.page_link(page_path, label=label, icon=None)
    except Exception:
        # Fallback om page_link ej stöds i kontexten
        st.caption(f"{label} ->")
