"""admin/scans.py - Starta scan tab for admin page."""
import streamlit as st

from web.pages.admin import _trigger_targeted_refresh, _get_github_token, _get_st_secret


_WORKFLOW_DISPATCH = {
    "morning":            "morning",
    "evening":            "evening",
    "weekly":             "weekly",
    "smallcap":           "smallcap",
    "targeted":           "targeted",
    "refresh_missing":    "refresh_missing",
    "retry_rate_limited": "retry_rate_limited",
}

_MODE_LABELS = {
    "morning":            "Morgonbrief (09:05 CEST)",
    "evening":            "Kvällsrapport (17:30 CEST)",
    "weekly":             "Veckoscan (full)",
    "smallcap":           "Småbolagsscan",
    "targeted":           "Targeted refresh (specifika tickers)",
    "refresh_missing":    "Refresh missing data",
    "retry_rate_limited": "Retry rate-limitade tickers",
}

_MODE_HELP = {
    "morning":            "Hämtar portföljpriser och skickar morgonbrevet.",
    "evening":            "Hämtar stängningspriser och skickar kvällsrapporten.",
    "weekly":             "Full universumscan med scoring, rotation och audit. Tar ~20-40 min.",
    "smallcap":           "Scan av nordiska och globala småbolag.",
    "targeted":           "Hämtar om specifika tickers du anger nedan.",
    "refresh_missing":    "Letar upp tickers med saknad data och hämtar dem.",
    "retry_rate_limited": "Kör om tickers som rate-limitades i senaste scan. Itererar tills alla klarar sig.",
}


def render():
    st.subheader("Starta scan via GitHub Actions")

    scan_mode = st.selectbox(
        "Välj scanlage",
        list(_WORKFLOW_DISPATCH.keys()),
        format_func=lambda k: _MODE_LABELS.get(k, k),
    )

    if scan_mode in _MODE_HELP:
        st.caption(_MODE_HELP[scan_mode])

    targeted_tickers = ""
    if scan_mode == "targeted":
        targeted_tickers = st.text_input(
            "Tickers (kommaseparerade, t.ex. AAPL,MSFT,NVDA)",
            placeholder="t.ex. VOLV-B.ST,ERIC-B.ST",
        ).strip()

    if st.button("Starta scan", type="primary", use_container_width=True):
        with st.spinner("Startar workflow..."):
            if scan_mode == "targeted":
                ticker_list = [t.strip().upper() for t in targeted_tickers.split(",") if t.strip()]
                if not ticker_list:
                    st.warning("Ange minst en ticker for targeted refresh.")
                    return
                ok = _trigger_targeted_refresh(ticker_list)
            else:
                ok = _trigger_scan(scan_mode)
            if ok:
                st.success(f"Workflow `{scan_mode}` startat! Se status i GitHub Actions.")
            else:
                st.error("Kunde inte starta workflow. Kontrollera GITHUB_TOKEN.")


def _trigger_scan(mode: str) -> bool:
    """Trigga en pipeline-scan via GitHub Actions workflow_dispatch."""
    token = _get_github_token()
    if not token:
        return False
    import requests as _req
    owner = "hankkontakt"
    repo = "stock-scanner"
    url = (f"https://api.github.com/repos/{owner}/{repo}"
           f"/actions/workflows/daily_scan.yml/dispatches")
    payload = {"ref": "main", "inputs": {"mode": mode, "tickers": ""}}
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        resp = _req.post(url, json=payload, headers=headers, timeout=15)
        return resp.status_code in (200, 201, 204)
    except Exception:
        return False
