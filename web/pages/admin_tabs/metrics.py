"""admin/metrics.py - Metrics & observability tab för admin page.

E3-integration: Visar pipeline-metrics (duration, tickers, errors)
från data/metrics/*.jsonl.
"""
import pandas as pd
import streamlit as st

from web.utils import DATA_DIR


def render():
    st.subheader("Pipeline-metrics")
    st.caption("Historiska mätpunkter för pipeline-körningar, API-anrop och systemhälsa.")

    try:
        from core.metrics import list_metrics, get_recent_metrics, get_metric_summary
    except ImportError:
        st.warning("core.metrics ej tillgänglig — kör `pip install marketscan` eller kontrollera installationen.")
        return

    available = list_metrics()
    if not available:
        st.info("Inga metrics registrerade ännu. Metrics skapas automatiskt när pipeline körs.")
        st.caption("Metrics sparas i: `data/metrics/`")
        return

    # ── Metric-väljare ────────────────────────────────────────────────────────
    selected = st.selectbox("Välj metric", available, key="metrics_select")

    if selected:
        summary = get_metric_summary(selected, last_n=500)
        entries = get_recent_metrics(selected, limit=200)

        if summary:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Antal mätningar", summary.get("count", "--"))
            c2.metric("Senaste värde", f"{summary.get('last', '--')}")
            c3.metric("Medel", f"{summary.get('mean', '--')}")
            c4.metric("Min/Max", f"{summary.get('min', '--')} / {summary.get('max', '--')}")
            c5.metric("P95", f"{summary.get('p95', '--')}")

        if entries:
            df = pd.DataFrame(entries)
            if "ts" in df.columns and "v" in df.columns:
                df["ts"] = pd.to_datetime(df["ts"])
                df = df.sort_values("ts")

                # Tidsserie-graf
                st.line_chart(df.set_index("ts")["v"])

                # Rådata (de senaste 50)
                with st.expander("Visa rådata (senaste 50)", expanded=False):
                    display = df.tail(50)[["ts", "v"]].copy()
                    display.columns = ["Tidpunkt", "Värde"]
                    display["Tidpunkt"] = display["Tidpunkt"].dt.strftime("%Y-%m-%d %H:%M")
                    st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.info(f"Inga data för metric '{selected}' ännu.")

    # ── Sammanfattning (alla metrics) ─────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Alla metrics (senaste värden)")
    rows = []
    from core.metrics import get_metric_summary as _gms
    for m in available:
        s = _gms(m, last_n=10)
        if s:
            rows.append({
                "Metric": m,
                "Senaste": round(s.get("last", 0), 2),
                "Medel (10)": round(s.get("mean", 0), 2),
                "Antal": s.get("count", 0),
                "Senast": s.get("last_ts", "")[:16] if s.get("last_ts") else "",
            })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
