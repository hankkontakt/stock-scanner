"""admin/scans.py – Starta scan tab for admin page."""
import streamlit as st

from web.pages.admin import _trigger_gh_workflow


_WORKFLOW_DISPATCH = {
    "morning": "morning",
    "evening": "evening",
    "weekly": "weekly",
    "smallcap": "smallcap",
    "targeted": "targeted",
    "refresh_missing": "refresh_missing",
}


def render():
    st.subheader("Starta scan via GitHub Actions")

    scan_mode = st.selectbox(
            "Valj scanlage",
            list(_WORKFLOW_DISPATCH.keys()),
            format_func=lambda k: {
                "morning": "Morgonbrief",
                "evening": "Kvallsrapport",
                "weekly": "Veckoscan (full)",
                "smallcap": "Smabolagsscan",
                "targeted": "Targeted refresh (specifika tickers)",
                "refresh_missing": "Refresh missing data",
            }.get(k, k),
    )

    targeted_tickers = ""
    if scan_mode == "targeted":
        targeted_tickers = st.text_input(
            "Tickers (kommaseparerade, t.ex. AAPL,MSFT,NVDA)",
            placeholder="t.ex. VOLV-B.ST,ERIC-B.ST",
        )

    if st.button("Starta scan", type="primary", use_container_width=True):
        with st.spinner("Startar workflow..."):
            ok = _trigger_gh_workflow(scan_mode, tickers=targeted_tickers)
            if ok:
                st.success(f"Workflow `{scan_mode}` startat! Se status i GitHub Actions.")
            else:
                st.error("Kunde inte starta workflow. Kontrollera GITHUB_TOKEN.")
