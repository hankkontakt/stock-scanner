"""
screener_utils.py -- Shared enhanced screener utilities.

Provides column selectors, quick filter presets, pagination, export,
and change detection for all screener pages (weekly_scan, technical, smallcap).
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Callable

import pandas as pd
import streamlit as st

from web.ui.components import data_table
from web.ui.icons import ic
from web.ui.experience_mode import InvestorExperience


# ══════════════════════════════════════════════════════════════════════════════
# PRESET QUICK FILTERS
# ══════════════════════════════════════════════════════════════════════════════

QUICK_FILTERS: dict[str, dict[str, Any]] = {
    "Value": {
        "icon": "💰",
        "description": "Low valuation, high FCF yield",
        "filters": {
            "pe_trailing": (0, 15),
            "fcf_yield": (0.05, None),
            "price_to_book": (0, 1.5),
        },
    },
    "Growth": {
        "icon": "🚀",
        "description": "High revenue and earnings growth",
        "filters": {
            "revenue_growth": (0.10, None),
            "earnings_growth": (0.10, None),
            "pe_trailing": (0, 40),
        },
    },
    "High Quality": {
        "icon": "💎",
        "description": "Strong profitability and low debt",
        "filters": {
            "roe": (0.15, None),
            "roa": (0.05, None),
            "debt_to_equity": (0, 1.0),
            "profit_margin": (0.10, None),
        },
    },
    "Technically Strong": {
        "icon": "📈",
        "description": "Uptrend, strong momentum, healthy RSI",
        "filters": {
            "trend_signal": ("UPPTREND",),
            "rsi_14": (40, 80),
            "price_vs_ma200": (0, None),
            "price_vs_ma50": (0, None),
        },
    },
}

TECHNICAL_QUICK_FILTERS: dict[str, dict[str, Any]] = {
    "Oversold": {
        "icon": "📉",
        "description": "RSI below 35 - potential bounce candidates",
        "filters": {
            "rsi_14": (0, 35),
        },
    },
    "Momentum": {
        "icon": "⚡",
        "description": "Strong uptrend with MACD buy signal",
        "filters": {
            "trend_signal": ("UPPTREND",),
            "macd_above_signal": (True,),
        },
    },
    "Low Volatility": {
        "icon": "🛡️",
        "description": "Low beta and volatility",
        "filters": {
            "beta": (0, 1.0),
            "volatility": (0, 0.3),
        },
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# COLUMN SELECTOR
# ══════════════════════════════════════════════════════════════════════════════

def render_column_selector(
    available_columns: dict[str, str],
    default_columns: list[str] | None = None,
    key: str = "col_selector",
) -> list[str]:
    """Multi-select column picker with save per user.

    Args:
        available_columns: Dict of {column_key: display_name}.
        default_columns: Default selected column keys. If None, uses first 8.
        key: Streamlit key prefix.

    Returns:
        List of selected column keys.
    """
    # Determine defaults
    if default_columns is None:
        default_columns = list(available_columns.keys())[:8]

    # Check session state for saved selection
    session_key = f"{key}_selected"
    if session_key not in st.session_state:
        st.session_state[session_key] = default_columns

    # Render multiselect
    options = list(available_columns.keys())
    display_map = available_columns

    selected = st.multiselect(
        f"{ic('view')} Columns",
        options=options,
        default=st.session_state.get(session_key, default_columns),
        format_func=lambda k: display_map.get(k, k),
        key=f"{key}_ms",
        placeholder="Select columns to display...",
    )

    # Save to session state
    st.session_state[session_key] = selected

    if not selected:
        st.info("Select at least one column.")
        return default_columns

    return selected


def apply_selected_columns(
    df: pd.DataFrame,
    selected_columns: list[str],
    column_display: dict[str, str],
) -> pd.DataFrame:
    """Filter and rename DataFrame to show only selected columns.

    Args:
        df: Source DataFrame.
        selected_columns: List of column keys to include.
        column_display: Dict of {column_key: display_name}.

    Returns:
        Filtered and renamed DataFrame.
    """
    available = [c for c in selected_columns if c in df.columns]
    if not available:
        return df

    display = df[available].copy()
    rename_map = {k: v for k, v in column_display.items() if k in available}
    display = display.rename(columns=rename_map)
    return display


# ══════════════════════════════════════════════════════════════════════════════
# QUICK FILTER PRESETS
# ══════════════════════════════════════════════════════════════════════════════

def render_quick_filters(
    filter_presets: dict[str, dict[str, Any]],
    key: str = "qf",
) -> str | None:
    """Render quick filter preset buttons.

    Args:
        filter_presets: Dict of preset name -> {icon, description, filters}.
        key: Streamlit key prefix.

    Returns:
        Selected preset name, or None.
    """
    st.markdown(f"### {ic('filter')} Quick Filters")

    cols = st.columns(len(filter_presets))
    selected = None

    for i, (preset_name, preset) in enumerate(filter_presets.items()):
        with cols[i]:
            if st.button(
                f"{preset['icon']} {preset_name}",
                key=f"{key}_{preset_name}",
                use_container_width=True,
                help=preset.get("description", ""),
            ):
                selected = preset_name

    return selected


def apply_quick_filters(
    df: pd.DataFrame,
    preset_name: str,
    filter_presets: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """Apply a quick filter preset to the DataFrame.

    Args:
        df: Source DataFrame.
        preset_name: Name of the filter preset.
        filter_presets: Dict of presets.

    Returns:
        Filtered DataFrame.
    """
    preset = filter_presets.get(preset_name)
    if not preset:
        return df

    out = df.copy()
    for col, condition in preset["filters"].items():
        if col not in out.columns:
            continue

        if isinstance(condition, tuple) and len(condition) == 2:
            lo, hi = condition
            if lo is not None:
                out = out[out[col] >= lo] if lo is not None else out
            if hi is not None:
                out = out[out[col] <= hi] if hi is not None else out
        elif isinstance(condition, tuple) and len(condition) == 1:
            out = out[out[col] == condition[0]]
        elif isinstance(condition, bool):
            out = out[out[col] == condition]
        else:
            out = out[out[col] == condition]

    return out.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGINATION
# ══════════════════════════════════════════════════════════════════════════════

def render_pagination(
    total: int,
    key: str = "pag",
) -> tuple[int, int]:
    """Render pagination controls.

    Args:
        total: Total number of items.
        key: Streamlit key prefix.

    Returns:
        (page_size, current_page) tuple.
    """
    PAGE_SIZES = [25, 50, 100, 0]  # 0 = All

    # Page size selector
    page_size_key = f"{key}_page_size"
    if page_size_key not in st.session_state:
        st.session_state[page_size_key] = 50

    col_pages, col_info = st.columns([1, 2])

    with col_pages:
        page_size = st.selectbox(
            "Rows per page",
            options=PAGE_SIZES,
            format_func=lambda x: "All" if x == 0 else str(x),
            index=PAGE_SIZES.index(st.session_state.get(page_size_key, 50)),
            key=f"{key}_size",
        )
        st.session_state[page_size_key] = page_size

    # Calculate pages
    effective_size = total if page_size == 0 else page_size
    num_pages = max(1, (total + effective_size - 1) // effective_size) if page_size > 0 else 1

    # Current page
    page_key = f"{key}_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    # Ensure page is valid
    if st.session_state[page_key] >= num_pages:
        st.session_state[page_key] = 0

    current_page = st.session_state[page_key]

    with col_pages:
        if num_pages > 1:
            cols = st.columns([1, 2, 1])
            with cols[0]:
                if st.button("◀", key=f"{key}_prev", disabled=(current_page <= 0)):
                    st.session_state[page_key] = max(0, current_page - 1)
            with cols[1]:
                st.markdown(
                    f"<div style='text-align:center;font-size:13px;color:#8892a4;'>"
                    f"Page {current_page + 1} / {num_pages}</div>",
                    unsafe_allow_html=True,
                )
            with cols[2]:
                if st.button("▶", key=f"{key}_next", disabled=(current_page >= num_pages - 1)):
                    st.session_state[page_key] = min(num_pages - 1, current_page + 1)

    # Slice the data
    start = current_page * effective_size
    end = min(start + effective_size, total) if page_size > 0 else total

    with col_info:
        st.caption(f"Showing {start + 1}-{end} of {total}")

    return effective_size, current_page


def paginate_dataframe(df: pd.DataFrame, page_size: int, current_page: int) -> pd.DataFrame:
    """Slice DataFrame to current page.

    Returns empty DataFrame if page_size is 0 (show all).
    """
    if page_size == 0:
        return df
    start = current_page * page_size
    end = start + page_size
    return df.iloc[start:end].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def render_export_buttons(
    df: pd.DataFrame,
    filename_prefix: str = "export",
    key: str = "export",
) -> None:
    """Render CSV, Excel, and Print export buttons.

    Args:
        df: DataFrame to export.
        filename_prefix: Prefix for the filename.
        key: Streamlit key prefix.
    """
    if df.empty:
        return

    now = datetime.now().strftime("%Y-%m-%d")
    base_filename = f"{filename_prefix}_{now}"

    col_csv, col_xls, col_print = st.columns(3)

    # CSV export
    with col_csv:
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            f"{ic('download')} CSV",
            data=csv_data,
            file_name=f"{base_filename}.csv",
            mime="text/csv",
            key=f"{key}_csv",
            use_container_width=True,
        )

    # Excel export
    with col_xls:
        try:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Data")
            xlsx_data = buffer.getvalue()
            st.download_button(
                f"{ic('download')} Excel",
                data=xlsx_data,
                file_name=f"{base_filename}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{key}_xlsx",
                use_container_width=True,
            )
        except Exception:
            st.button("Excel (install openpyxl)", disabled=True, use_container_width=True, key=f"{key}_xlsx_disabled")

    # Print
    with col_print:
        st.markdown(
            f"<button onclick=\"window.print()\" "
            f"style=\"background:#1e2230;color:#e8eaf0;border:1px solid #2d3250;"
            f"border-radius:6px;padding:6px 14px;cursor:pointer;width:100%;"
            f"font-size:13px;\">"
            f"{ic('link')} Print / PDF</button>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# CHANGE DETECTION TOGGLE
# ══════════════════════════════════════════════════════════════════════════════

def render_changes_toggle(key: str = "changes") -> bool:
    """Toggle to show only changed rows since last scan.

    Returns:
        True if "show changes only" is enabled.
    """
    return st.checkbox(
        f"{ic('refresh')} Show changes only",
        value=False,
        key=f"{key}_toggle",
        help="When enabled, only shows rows that have changed since the last scan.",
    )


def filter_changed_rows(df: pd.DataFrame, delta_col: str = "delta_flag") -> pd.DataFrame:
    """Filter to rows that have changed.

    Args:
        df: Source DataFrame.
        delta_col: Column name indicating change status.

    Returns:
        DataFrame with only changed rows.
    """
    if delta_col not in df.columns:
        return df
    return df[df[delta_col].notna() & (df[delta_col] != "")].reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# ENHANCED SCREENER WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def render_enhanced_screener_bar(
    available_columns: dict[str, str],
    default_columns: list[str] | None = None,
    filter_presets: dict[str, dict[str, Any]] | None = None,
    key: str = "screener",
) -> dict[str, Any]:
    """Render the enhanced screener toolbar (columns, quick filters, export).

    Args:
        available_columns: Dict of {column_key: display_name}.
        default_columns: Default selected columns.
        filter_presets: Optional dict of quick filter presets.
        key: Streamlit key prefix.

    Returns:
        Dict with "columns" and "quick_filter" keys.
    """
    result: dict[str, Any] = {
        "columns": default_columns or list(available_columns.keys())[:8],
        "quick_filter": None,
        "show_changes_only": False,
    }

    with st.expander(f"{ic('tune')} View Options", expanded=False):
        # Quick filters (if provided)
        if filter_presets:
            selected_preset = render_quick_filters(filter_presets, key=f"{key}_qf")
            if selected_preset:
                result["quick_filter"] = selected_preset

        # Column selector
        result["columns"] = render_column_selector(
            available_columns,
            default_columns=default_columns,
            key=f"{key}_cols",
        )

        # Change detection toggle
        result["show_changes_only"] = render_changes_toggle(key=f"{key}_chg")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# NATURSPRAKLIG SCREENER-FRAGA
# ══════════════════════════════════════════════════════════════════════════════

_NL_SECTORS = [
    "Technology", "Healthcare", "Financials", "Energy", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Materials",
    "Real Estate", "Utilities", "Communication Services",
]

_NL_SYSTEM_PROMPT = (
    "Du är ett filterparsningssystem för en aktie-screener. "
    "Din uppgift: konvertera en naturspråksfråga om aktier till exakta filterparametrar i JSON. "
    "Svara ENBART med ett JSON-objekt — inga förklaringar, ingen text utanför JSON. "
    "\n\nTillgängliga filterparametrar (sätt null om okänt/ej nämnt):"
    "\n- score_min (number 0-100): minsta poäng"
    "\n- score_max (number 0-100): högsta poäng"
    "\n- sector (array of strings): en eller flera av: " + ", ".join(_NL_SECTORS)
    + "\n- entry (array): en eller flera av [STARK, OK, VÄNTA, EJ AKTUELL]"
    "\n- trend (string eller null): UPPTREND / SIDLED / NEDTREND"
    "\n- piotroski_min (integer 0-9): minsta Piotroski F-Score"
    "\n- only_swedish (boolean): bara svenska (.ST) aktier"
    "\n- only_improving (boolean): bara aktier med förbättrad score (+5p)"
    "\n- preset_used (string eller null): vilket av [Value, Growth, High Quality, Technically Strong, Oversold, Momentum, Low Volatility] som matchade bäst"
    "\n\nTolkningsregler:"
    "\n- 'undervärderade' → score_min: 55, preset_used: 'Value'"
    "\n- 'tillväxt' → preset_used: 'Growth'"
    "\n- 'momentum' / 'stark trend' → entry: ['STARK'], trend: 'UPPTREND'"
    "\n- 'köpsignal' → entry: ['STARK', 'OK']"
    "\n- 'låg risk' → score_min: 60 (high quality)"
    "\n- 'svenska' / 'Stockholm' / 'nordiska' → only_swedish: true"
    "\n- 'förbättrande' → only_improving: true"
    "\nOm frågan är för vag, returnera tomt objekt {}."
)


def parse_nl_filter_query(query: str) -> dict:
    """
    Konverterar en naturspråksfråga till filterparametrar för weekly_scan.

    Args:
        query: Naturspråksfråga, t.ex. "undervärderade svenska techbolag med starkt momentum"

    Returns:
        dict med filterparametrar (null-värden utelämnade).
        Tomt dict vid fel eller för vag fråga.
    """
    if not query or len(query.strip()) < 3:
        return {}

    try:
        import json
        from core import ai_analysis
        from core.ai_prompts import SYSTEM_PROMPT_FILTER_PARSER

        raw = ai_analysis.ai_chat(
            question=query,
            context="",
            system_prompt_override=SYSTEM_PROMPT_FILTER_PARSER,
            depth="Snabb",
        )

        # Rensa eventuell markdown-formattering runt JSON
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        parsed = json.loads(raw)

        # Rensa null-värden och returnera bara satta parametrar
        return {k: v for k, v in parsed.items() if v is not None}

    except Exception:
        return {}


def render_nl_filter_bar(key: str = "nl") -> dict:
    """
    Renderar naturspråksfält + knapp. Returnerar parsade filterparametrar
    om en fråga ställts, annars tomt dict.
    """
    col_input, col_btn = st.columns([5, 1])
    with col_input:
        query = st.text_input(
            "Beskriv vad du letar efter",
            placeholder="t.ex. 'undervärderade svenska techbolag med starkt momentum'",
            label_visibility="collapsed",
            key=f"{key}_nl_query",
        )
    with col_btn:
        search = st.button("🔍 Sök", key=f"{key}_nl_btn", use_container_width=True)

    if search and query.strip():
        with st.spinner("Tolkar frågan med AI..."):
            result = parse_nl_filter_query(query.strip())

        if result:
            # Visa tolkad filter som caption
            parts = []
            if result.get("score_min"):
                parts.append(f"poäng ≥ {result['score_min']}")
            if result.get("sector"):
                parts.append(f"sektor: {', '.join(result['sector'])}")
            if result.get("entry"):
                parts.append(f"entry: {', '.join(result['entry'])}")
            if result.get("trend"):
                parts.append(f"trend: {result['trend']}")
            if result.get("only_swedish"):
                parts.append("bara svenska")
            if result.get("only_improving"):
                parts.append("förbättrande")
            if result.get("preset_used"):
                parts.append(f"preset: {result['preset_used']}")
            if parts:
                st.caption(f"↳ Tolkad som: {' · '.join(parts)}")
            return result
        else:
            st.caption("↳ Kunde inte tolka frågan — prova att vara mer specifik.")

    return {}
