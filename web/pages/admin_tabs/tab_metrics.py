"""
web/pages/admin_tabs/tab_metrics.py
=====================================
Admin — Flik 5: Metrics

Sektioner:
  - Pipeline-prestanda (körningstid över tid)
  - AI-användning (tokens, anrop)
  - Score-distribution (histogram, percentiler)
  - Datahämtning (fetch-fel, rate-limiting)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import DATA_DIR


# ── Hjälpfunktioner ───────────────────────────────────────────────────────────

def _load_ai_usage_log() -> list:
    path = DATA_DIR / "ai_usage_log.json"
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _load_fetch_errors() -> list:
    path = DATA_DIR / "fetch_errors.json"
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _load_scoring_distribution() -> pd.DataFrame | None:
    path = DATA_DIR / "metrics" / "scoring_distribution"
    if path.exists():
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    # Fallback: beräkna från senaste scored_universe
    from web.utils import REPORT_DIR
    parquets = sorted(REPORT_DIR.glob("scored_universe_*.parquet"), reverse=True)
    if parquets:
        try:
            df = pd.read_parquet(parquets[0])
            if "score_total" in df.columns:
                return df[["score_total"]]
        except Exception:
            pass
    return None


# ── Render ────────────────────────────────────────────────────────────────────

def render():
    st.markdown('<div class="section-header">Metrics & Prestanda</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-desc">Prestanda, AI-förbrukning och trender över tid.</div>',
        unsafe_allow_html=True,
    )

    # ── A: Pipeline-prestanda ─────────────────────────────────────────────────
    st.markdown("#### Pipeline-prestanda")
    try:
        from core.metrics import get_recent_metrics, get_metric_summary

        perf_metrics = [
            ("pipeline_duration_s", "Körtid (sekunder)", "mode"),
            ("n_tickers_scored", "Antal tickers", "mode"),
            ("pipeline_fetch_duration_s", "Datahämtning (sek)", None),
            ("pipeline_scoring_duration_s", "Scoring (sek)", None),
        ]
        for metric_name, label, tag_key in perf_metrics:
            entries = get_recent_metrics(metric_name, limit=100)
            if entries:
                df = pd.DataFrame(entries)
                if "ts" in df.columns and "v" in df.columns:
                    df["ts"] = pd.to_datetime(df["ts"])
                    df = df.sort_values("ts")
                    df["label"] = label
                    st.line_chart(df.set_index("ts")["v"])
                    summary = get_metric_summary(metric_name, last_n=100)
                    if summary:
                        cols = st.columns(4)
                        cols[0].metric("Senaste", f"{summary.get('last', '--'):.1f}" if summary.get('last') else "--")
                        cols[1].metric("Medel", f"{summary.get('mean', '--'):.1f}" if summary.get('mean') else "--")
                        cols[2].metric("Min", f"{summary.get('min', '--'):.1f}" if summary.get('min') else "--")
                        cols[3].metric("Max", f"{summary.get('max', '--'):.1f}" if summary.get('max') else "--")
                    st.caption(f"{label} över tid. Noll = pipeline-data saknas.")
            else:
                st.caption(f"Inga data för {label} ännu — pipeline-data samlas in efter varje körning.")

        if not any(get_recent_metrics(m, limit=1) for m, _, _ in perf_metrics):
            st.info("Inga pipeline-metrics registrerade ännu. Metrics skapas automatiskt när pipeline körs.")
    except ImportError:
        st.info("core.metrics ej tillgänglig — pipeline-metrics visas när modulen är installerad.")
    except Exception:
        st.info("Kunde inte hämta pipeline-metrics.")

    # ── B: AI-användning ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### AI-användning")
    ai_usage = _load_ai_usage_log()
    if ai_usage:
        df_ai = pd.DataFrame(ai_usage)
        cols = st.columns(3)
        cols[0].metric("Totalt anrop", len(ai_usage))
        if "tokens" in df_ai.columns or "input_tokens" in df_ai.columns:
            tok_col = "tokens" if "tokens" in df_ai.columns else "input_tokens"
            total_tokens = int(df_ai[tok_col].sum()) if tok_col in df_ai.columns else 0
            cols[1].metric("Total tokens", f"{total_tokens:,}")
        if "cost" in df_ai.columns:
            total_cost = df_ai["cost"].sum()
            cols[2].metric("Ungefärlig kostnad", f"${total_cost:.2f}")
        else:
            # Uppskattning baserat på DeepSeek-priser
            cols[2].metric("Kostnadsestimat", "Se AI-logg")

        with st.expander("Senaste AI-anrop"):
            st.dataframe(df_ai.tail(20), use_container_width=True, hide_index=True)
    else:
        st.info("Ingen AI-användning loggad ännu.")

    # ── C: Score-distribution ─────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Score-distribution")
    score_df = _load_scoring_distribution()
    if score_df is not None and "score_total" in score_df.columns:
        scores = score_df["score_total"].dropna()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Median (P50)", f"{scores.median():.1f}")
        c2.metric("P75", f"{scores.quantile(0.75):.1f}")
        c3.metric("P90", f"{scores.quantile(0.90):.1f}")
        c4.metric("P95", f"{scores.quantile(0.95):.1f}")

        # Histogram
        bins = list(range(0, 101, 10))
        hist = pd.cut(scores, bins=bins, include_lowest=True).value_counts().sort_index()
        hist.index = [f"{int(i.left)}–{int(i.right)}" for i in hist.index]
        st.bar_chart(hist)
        st.caption(
            f"Fördelning av total score ({len(scores)} tickers). "
            "Poängen är relativ — en tickers score beror på hur den rankas inom universumet."
        )
    else:
        st.info("Ingen score-data tillgänglig. Kör en pipeline först.")

    # ── D: Datahämtning ──────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Datahämtning")
    fetch_data = _load_fetch_errors()
    if fetch_data:
        latest = fetch_data[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("Hämtade OK", latest.get("n_ok", 0))
        c2.metric("Misslyckade", latest.get("n_failed", 0))
        c3.metric("Rate-limited", latest.get("n_rate_limited", 0))

        if len(fetch_data) > 1:
            trend_rows = []
            for entry in fetch_data[-20:]:
                ts = entry.get("timestamp", "?")[:10]
                trend_rows.append({
                    "Datum": ts,
                    "OK": entry.get("n_ok", 0),
                    "Misslyckade": entry.get("n_failed", 0),
                    "Rate-limited": entry.get("n_rate_limited", 0),
                })
            st.markdown("##### Trend (senaste 20 körningarna)")
            st.dataframe(pd.DataFrame(trend_rows), use_container_width=True, hide_index=True)
            st.caption(
                "Misslyckade hämtningar beror ofta på Yahoo Finance rate-limiting. "
                "Systemet försöker automatiskt igen vid nästa schemalagda körning."
            )
    else:
        st.info("Ingen fetch-data ännu. Informationen samlas in under pipeline-körningar.")
