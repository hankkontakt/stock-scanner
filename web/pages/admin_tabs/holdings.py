"""admin/holdings.py - Portfolj tab for admin page."""
import json
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from web.utils import load_portfolio, DATA_DIR
from web.pages.admin import (
    _save_holdings_df,
)


def render():
    st.subheader("Portfolj (holdings.csv)")
    holdings = load_portfolio()

    if not holdings.empty:
        col_order = [c for c in ["ticker", "shares", "cost_basis", "konto", "typ", "buy_date", "market_value"]
                     if c in holdings.columns]
        st.dataframe(holdings[col_order], use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### Redigera innehav")

        selected = st.selectbox(
            "Valj ticker att redigera",
            [""] + sorted(holdings["ticker"].unique()),
            key="hold_edit_ticker",
        )

        if selected:
            row = holdings[holdings["ticker"] == selected].iloc[0]
            col_s, col_p, col_b = st.columns(3)
            with col_s:
                new_shares = st.number_input("Antal", value=float(row.get("shares", 0)),
                                              step=1.0, format="%.2f", key="hold_shares")
            with col_p:
                new_price = st.number_input("Kurs", value=float(row.get("cost_basis", 0)),
                                             step=1.0, format="%.2f", key="hold_price")
            with col_b:
                new_buy = st.text_input("Kopdatum (YYYY-MM-DD)",
                                         value=str(row.get("buy_date", "")),
                                         key="hold_buy")

            if st.button("Spara andringar", key="btn_hold_save", type="primary"):
                holdings.loc[holdings["ticker"] == selected, "shares"] = new_shares
                holdings.loc[holdings["ticker"] == selected, "cost_basis"] = new_price
                if "buy_date" in holdings.columns and new_buy:
                    holdings.loc[holdings["ticker"] == selected, "buy_date"] = new_buy
                csv_content = holdings.to_csv(index=False)
                ok = _save_holdings_df(holdings)
                if ok:
                    st.success(f"Andringar sparade for `{selected}`!")
                    st.rerun()
                else:
                    st.warning("Andringar sparade lokalt men GitHub-commit misslyckades.")

            if st.button("Ta bort innehav", key="btn_hold_remove"):
                holdings = holdings[holdings["ticker"] != selected]
                _save_holdings_df(holdings)
                st.success(f"`{selected}` borttaget ur portfoljen!")
                st.rerun()

        st.markdown("---")
        st.markdown("### Lagg till nytt innehav")

        with st.form("form_add_holding"):
            c1, c2, c3 = st.columns(3)
            with c1:
                add_t = st.text_input("Ticker *", placeholder="AAPL", max_chars=15).strip().upper()
            with c2:
                add_s = st.number_input("Antal *", min_value=0.0, step=1.0, format="%.2f")
            with c3:
                add_p = st.number_input("Kopkurs *", min_value=0.0, step=10.0, format="%.2f")

            c4, c5, c6 = st.columns(3)
            with c4:
                add_k = st.selectbox("Konto", ["Huvud", "ISK", "Depa", "Kant", "Pension"], key="hold_konto")
            with c5:
                add_typ = st.selectbox("Typ", ["", "aktier", "fond", "etf", "certificate"], key="hold_typ")
            with c6:
                add_buy = st.text_input("Kopdatum (YYYY-MM-DD)", key="hold_date",
                                         placeholder="2025-01-15")

            submitted = st.form_submit_button("Lagg till", type="primary", use_container_width=True)
            if submitted:
                if not add_t or add_s <= 0:
                    st.error("Ticker och antal maste anges.")
                else:
                    new_row = {"ticker": add_t, "shares": add_s, "cost_basis": add_p,
                                "konto": add_k, "typ": add_typ, "buy_date": add_buy}
                    new_df = pd.DataFrame([new_row])
                    combined = pd.concat([holdings, new_df], ignore_index=True)
                    _save_holdings_df(combined)
                    st.success(f"`{add_t}` tillagt i portfoljen!")
                    st.rerun()
    else:
        st.info("Inga innehav i portfoljen.")
