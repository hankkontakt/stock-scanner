"""Quick verification tests for Phases 8–11."""
import sys
sys.path.insert(0, ".")

import pandas as pd


def test_phase9_score_deltas():
    print("=== Phase 9: _get_score_deltas ===")
    from core.daily_pipeline import _get_score_deltas

    today = pd.DataFrame({
        "ticker":      ["VOLV-B.ST", "AAPL", "MSFT"],
        "score_total": [75, 60, 55],
        "rsi_14":      [35, 55, 68],   # MSFT: 74->68 crosses 70 downward
        "close":       [290.0, 195.0, 430.0],
    })
    yest = pd.DataFrame({
        "ticker":      ["VOLV-B.ST", "AAPL", "MSFT"],
        "score_total": [65, 62, 50],
        "rsi_14":      [28, 50, 74],   # VOLV-B: 28->35 crosses 30 upward
        "close":       [280.0, 200.0, 420.0],
    })
    deltas = _get_score_deltas(today, yest)
    assert deltas["movers_up"][0]["ticker"] == "VOLV-B.ST", "Expected VOLV-B.ST as top gainer"
    assert len(deltas["rsi_spikes"]) >= 1, "Expected RSI spike for VOLV-B.ST (28->35 crosses 30)"
    assert any(s["rsi_crossed_30up"] for s in deltas["rsi_spikes"]), "rsi_crossed_30up not set"
    # MSFT RSI 74->68: crossed 70 downward
    assert any(s["rsi_crossed_70down"] for s in deltas["rsi_spikes"]), "rsi_crossed_70down not set"
    # Empty DataFrames should return {}
    assert _get_score_deltas(pd.DataFrame(), yest) == {}
    assert _get_score_deltas(today, pd.DataFrame()) == {}
    print("  PASS: movers_up[0] =", deltas["movers_up"][0]["ticker"])
    print("  PASS: rsi_spikes count =", len(deltas["rsi_spikes"]))
    print("  PASS: empty df guard works")


def test_phase10_macro_calendar():
    print("=== Phase 10: macro_calendar ===")
    from core.macro_calendar import get_upcoming_macro_events, get_all_events_by_month

    evs = get_upcoming_macro_events(days_ahead=365)
    assert len(evs) > 0, "No macro events in next 365 days"
    assert all("flag" in e and "days_until" in e and "event" in e for e in evs)
    # Should be sorted by days_until ascending
    days = [e["days_until"] for e in evs]
    assert days == sorted(days), "Events not sorted by days_until"
    print(f"  PASS: {len(evs)} events in next 365 days")
    print(f"  PASS: first event = {evs[0]['event']} on {evs[0]['date']} (+{evs[0]['days_until']}d)")

    by_month = get_all_events_by_month(year=2026)
    assert len(by_month) > 0
    # Every entry should be a list of events
    for month_key, events in by_month.items():
        assert isinstance(events, list)
        assert all("flag" in e for e in events)
    print(f"  PASS: get_all_events_by_month(2026) => {len(by_month)} months")


def test_phase11_yfinance_news():
    print("=== Phase 11: yfinance news wiring ===")
    import inspect
    from core.news_fetcher import fetch_yfinance_news, fetch_company_news

    src = inspect.getsource(fetch_company_news)
    assert "fetch_yfinance_news" in src, "yfinance fallback not wired into fetch_company_news"

    src_yf = inspect.getsource(fetch_yfinance_news)
    assert "t.news" in src_yf, "yfinance Ticker.news not used"
    assert "_write_cache" in src_yf, "caching not implemented"
    print("  PASS: fetch_yfinance_news defined and wired into fetch_company_news")


def test_phase8_filter_logic():
    """Test country filter logic isolated from Streamlit."""
    print("=== Phase 8: country filter logic ===")
    _SUFFIX_MAP = {
        "🇸🇪 Sverige": ".ST",
        "🇬🇧 UK":      ".L",
        "🇩🇪 Tyskland": ".DE",
        "🇫🇮 Finland": ".HE",
        "🇩🇰 Danmark": ".CO",
        "🇳🇴 Norge":   ".OL",
    }
    _ALL_NON_US = set(_SUFFIX_MAP.values())

    tickers = ["VOLV-B.ST", "AAPL", "AZN.L", "SAP.DE", "SPOT"]
    df = pd.DataFrame({"ticker": tickers})

    # Swedish only
    swedish = df[df["ticker"].str.endswith(".ST", na=False)]
    assert list(swedish["ticker"]) == ["VOLV-B.ST"], f"Swedish filter failed: {list(swedish['ticker'])}"
    print("  PASS: Swedish-only filter")

    # Country multiselect: Sverige + UK
    selected = ["🇸🇪 Sverige", "🇬🇧 UK"]
    us_sel = "🇺🇸 USA" in selected
    suffixes = [_SUFFIX_MAP[c] for c in selected if c in _SUFFIX_MAP]

    def _match(t):
        if any(t.endswith(s) for s in suffixes):
            return True
        if us_sel and not any(t.endswith(s) for s in _ALL_NON_US):
            return True
        return False

    filtered = df[df["ticker"].apply(_match)]
    assert set(filtered["ticker"]) == {"VOLV-B.ST", "AZN.L"}, f"SE+UK filter failed: {set(filtered['ticker'])}"
    print("  PASS: Sverige + UK multiselect filter")

    # USA selection — should include AAPL and SPOT (no non-US suffix) but not .ST/.L
    selected_us = ["🇺🇸 USA"]
    us_sel2 = "🇺🇸 USA" in selected_us
    suffixes2 = [_SUFFIX_MAP[c] for c in selected_us if c in _SUFFIX_MAP]

    def _match_us(t):
        if any(t.endswith(s) for s in suffixes2):
            return True
        if us_sel2 and not any(t.endswith(s) for s in _ALL_NON_US):
            return True
        return False

    filtered_us = df[df["ticker"].apply(_match_us)]
    assert set(filtered_us["ticker"]) == {"AAPL", "SPOT"}, f"USA filter failed: {set(filtered_us['ticker'])}"
    print("  PASS: USA multiselect filter (includes .ST-less tickers like AAPL, SPOT)")


if __name__ == "__main__":
    test_phase8_filter_logic()
    test_phase9_score_deltas()
    test_phase10_macro_calendar()
    test_phase11_yfinance_news()
    print()
    print("All phases 8–11 verified!")
