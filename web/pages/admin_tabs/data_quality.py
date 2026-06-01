"""admin_tabs/data_quality.py — Datakvalitets-tab i admin-sidan.

Visar täckning per faktor per ticker baserat på senaste scored_universe.
Hjälper till att hitta tickers som tyst straffas p.g.a. saknade nyckeltal.
"""
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import REPORT_DIR

# Kolumner som varje faktor kräver (primär + fallback).
# Källa: core/scoring.py calc_*_score()-funktioner.
FACTOR_COLUMNS: dict[str, list[str]] = {
    "value":         ["free_cash_flow", "enterprise_value", "pe_forward", "pe_trailing",
                       "price_to_book", "price_to_sales"],
    "quality":       ["roe", "roa", "profit_margin", "operating_margin", "gross_margin"],
    "momentum":      ["return_12m", "return_6m", "return_3m", "pct_from_52w_high"],
    "growth":        ["revenue_growth", "earnings_growth", "earnings_quarterly_growth"],
    "risk":          ["debt_to_equity", "current_ratio", "volatility", "beta"],
    "size":          ["market_cap"],
    "dividend":      ["dividend_yield", "payout_ratio"],
    "sentiment":     ["sentiment_raw"],
    "short_interest": ["short_pct_float", "short_ratio"],
    "options_flow":  ["options_flow_signal"],
}

# Minst en kolumn måste finnas för att faktorn ska kunna beräknas
FACTOR_PRIMARY: dict[str, list[str]] = {
    "value":         ["free_cash_flow", "pe_forward", "pe_trailing", "price_to_book"],
    "quality":       ["roe", "profit_margin"],
    "momentum":      ["return_12m", "return_6m"],
    "growth":        ["revenue_growth", "earnings_growth"],
    "risk":          ["debt_to_equity", "volatility"],
    "size":          ["market_cap"],
    "dividend":      ["dividend_yield"],
    "sentiment":     ["sentiment_raw"],
    "short_interest": ["short_pct_float", "short_ratio"],
    "options_flow":  ["options_flow_signal"],
}


def _load_latest_scored() -> pd.DataFrame | None:
    """Laddar senaste scored_universe_*.parquet (fallback: *.csv)."""
    parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
    if parquets:
        try:
            return pd.read_parquet(parquets[0])
        except Exception:
            pass
    csvs = sorted(REPORT_DIR.glob("scored_universe_*.csv"), reverse=True)
    if csvs:
        try:
            return pd.read_csv(csvs[0])
        except Exception:
            pass
    return None


def _coverage_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Returnerar en rad per faktor med täckningststatistik."""
    rows = []
    n = len(df)
    for factor, cols in FACTOR_COLUMNS.items():
        present_cols = [c for c in cols if c in df.columns]
        missing_cols = [c for c in cols if c not in df.columns]
        if not present_cols:
            rows.append({
                "Faktor": factor,
                "Kolumner saknas i df": ", ".join(missing_cols),
                "Tickers med data": 0,
                "Tickers saknar data": n,
                "Täckning %": 0.0,
            })
            continue
        # Ticker har "data" om minst en primärkolumn är icke-null
        prim = [c for c in FACTOR_PRIMARY.get(factor, present_cols) if c in df.columns]
        if not prim:
            prim = present_cols
        has_data = df[prim].notna().any(axis=1).sum()
        rows.append({
            "Faktor": factor,
            "Kolumner saknas i df": ", ".join(missing_cols) if missing_cols else "–",
            "Tickers med data": int(has_data),
            "Tickers saknar data": int(n - has_data),
            "Täckning %": round(100 * has_data / n, 1) if n else 0.0,
        })
    return pd.DataFrame(rows)


def _missing_detail(df: pd.DataFrame, factor: str) -> pd.DataFrame:
    """Returnerar tickers som saknar primärkolumner för en given faktor."""
    prim = [c for c in FACTOR_PRIMARY.get(factor, []) if c in df.columns]
    all_cols = [c for c in FACTOR_COLUMNS.get(factor, []) if c in df.columns]
    if not prim:
        return pd.DataFrame()
    missing_mask = ~df[prim].notna().any(axis=1)
    subset = df[missing_mask].copy()
    if subset.empty:
        return pd.DataFrame()
    display_cols = ["ticker"]
    if "name" in subset.columns:
        display_cols.append("name")
    if "sector" in subset.columns:
        display_cols.append("sector")
    display_cols += all_cols
    return subset[[c for c in display_cols if c in subset.columns]].head(50)


def render():
    st.subheader("📊 Datakvalitet")
    st.caption("Täckning per faktor baserat på senaste scored_universe. Tickers med saknade nyckeltal får automatisk neutral poäng (50) i berörda faktorer.")

    df = _load_latest_scored()
    if df is None:
        st.warning("Ingen scored_universe-fil hittades i reports/. Kör en scan först.")
        return

    # Metadata
    parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
    file_label = parquets[0].name if parquets else "scored_universe (CSV)"
    st.info(f"Fil: **{file_label}** — {len(df)} tickers")

    # ── Täckningsöversikt ─────────────────────────────────────────────────────
    st.markdown("### Faktoröversikt")
    summary = _coverage_summary(df)

    # Färgkodning: <70% = röd, 70-90% = gul, ≥90% = grön
    def _color_coverage(val):
        if isinstance(val, float):
            if val < 70:
                return "background-color: #fee2e2"
            elif val < 90:
                return "background-color: #fef9c3"
            else:
                return "background-color: #dcfce7"
        return ""

    styled = summary.style.applymap(_color_coverage, subset=["Täckning %"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Kolumntäckning per faktor ─────────────────────────────────────────────
    st.markdown("### Kolumntäckning per faktor")
    st.caption("Andel tickers med icke-null värde för varje enskild kolumn.")
    n = len(df)
    col_rows = []
    for factor, cols in FACTOR_COLUMNS.items():
        for col in cols:
            if col in df.columns:
                filled = int(df[col].notna().sum())
                col_rows.append({
                    "Faktor": factor,
                    "Kolumn": col,
                    "Filled": filled,
                    "Missing": n - filled,
                    "Täckning %": round(100 * filled / n, 1) if n else 0.0,
                })
            else:
                col_rows.append({
                    "Faktor": factor,
                    "Kolumn": col,
                    "Filled": 0,
                    "Missing": n,
                    "Täckning %": 0.0,
                })
    col_df = pd.DataFrame(col_rows)

    factor_filter = st.selectbox(
        "Filtrera på faktor",
        ["Alla"] + list(FACTOR_COLUMNS.keys()),
        key="dq_factor_filter",
    )
    if factor_filter != "Alla":
        col_df = col_df[col_df["Faktor"] == factor_filter]

    st.dataframe(
        col_df.style.applymap(_color_coverage, subset=["Täckning %"]),
        use_container_width=True,
        hide_index=True,
    )

    # ── Drilldown: tickers som saknar data ────────────────────────────────────
    st.markdown("### Drilldown — tickers utan data")
    st.caption("Välj en faktor för att se vilka tickers som saknar primärkolumner.")

    drill_factor = st.selectbox(
        "Faktor att granska",
        list(FACTOR_COLUMNS.keys()),
        key="dq_drill_factor",
    )
    detail_df = _missing_detail(df, drill_factor)
    if detail_df.empty:
        st.success(f"Alla tickers har data för faktorn **{drill_factor}**.")
    else:
        st.warning(f"{len(detail_df)} tickers saknar primärkolumner för **{drill_factor}** (visar max 50):")
        try:
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
        except Exception:
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

    # ── Övergripande datakvalitetspoäng ───────────────────────────────────────
    if "data_quality" in df.columns:
        st.markdown("### data_quality-score (befintlig)")
        st.caption("Befintligt data_quality-fält från scoring.py (0–1). Lägre = fler saknade fält.")
        dq = df["data_quality"].dropna()
        c1, c2, c3 = st.columns(3)
        c1.metric("Median", f"{dq.median():.2f}")
        c2.metric("Min", f"{dq.min():.2f}")
        c3.metric("< 0.5 (låg kvalitet)", int((dq < 0.5).sum()))
        st.bar_chart(
            dq.value_counts(bins=10, sort=False).sort_index(),
            use_container_width=True,
        )
