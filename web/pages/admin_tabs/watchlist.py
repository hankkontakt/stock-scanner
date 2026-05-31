"""admin/watchlist.py – Bevakningslista tab for admin page."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import load_watchlist, DATA_DIR
from web.pages.admin import (
    _search_ticker_yfinance, _save_watchlist_data,
)


def render():
    st.subheader("⭐ Bevakningslista")

    items = load_watchlist()

    if items:
        wl_df = pd.DataFrame(items)
        st.dataframe(wl_df, use_container_width=True, hide_index=True)

        remove_ticker = st.selectbox(
            "Ta bort ticker", [""] + [i["ticker"] for i in items],
            key="wl_remove",
        )
        if remove_ticker and st.button("Ta bort", key="btn_wl_remove"):
            items = [i for i in items if i["ticker"] != remove_ticker]
            _save_watchlist_data(items)
            st.success(f"`{remove_ticker}` borttagen ur bevakningslistan!")
            st.rerun()
    else:
        st.info("Bevakningslistan ar tom.")

    st.markdown("---")
    st.markdown("### Lagg till ny ticker")

    search_q = st.text_input("Sok aktie (ticker eller namn)", key="wl_search",
                             placeholder="t.ex. AAPL, VOLV-B.ST, Investor")
    if search_q:
        hits = _search_ticker_yfinance(search_q)
        if hits:
            options = {f"{h['ticker']} -- {h['name'][:40]}": h for h in hits}
            selected = st.selectbox("Valj fran sokresultat", list(options.keys()),
                                    key="wl_hit")
            if selected:
                h = options[selected]
                col1, col2 = st.columns([2, 1])
                if col1.button("Lagg till i bevakningslistan", key="btn_wl_add"):
                    new_ticker = h["ticker"]
                    exists = any(i["ticker"] == new_ticker for i in items)
                    if not exists:
                        items.append({
                            "ticker": new_ticker,
                            "name": h["name"],
                            "added": str(date.today()),
                        })
                        _save_watchlist_data(items)
                        st.success(f"`{new_ticker}` tillagd i bevakningslistan!")
                        st.rerun()
                    else:
                        st.info(f"`{new_ticker}` finns redan i bevakningslistan.")
        else:
            st.caption("Inga sokresultat. Prova med annat sokeord.")

    with st.expander("Eller lagg till manuellt (ticker)"):
        manual_ticker = st.text_input("Ticker (t.ex. AAPL)", key="wl_manual", max_chars=15)
        manual_name = st.text_input("Namn (valfritt)", key="wl_name")

        if st.button("Lagg till", key="btn_wl_add_manual"):
            mt = manual_ticker.strip().upper()
            if mt:
                exists = any(i["ticker"] == mt for i in items)
                if not exists:
                    items.append({
                        "ticker": mt,
                        "name": manual_name.strip() or mt,
                        "added": str(date.today()),
                    })
                    _save_watchlist_data(items)
                    st.success(f"`{mt}` tillagd i bevakningslistan!")
                    st.rerun()
                else:
                    st.info(f"`{mt}` finns redan.")
            else:
                st.warning("Ange en ticker.")
