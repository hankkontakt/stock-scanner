"""admin_tabs/strikes_health.py — Strike-lista och ticker-halsa med bulk-borttagning.

Visar:
  - Strike-lista (ticker + antal strikes + datum)
  - Blacklist (redan borttagna)
  - Mjlighet att ta bort tickers fran universe eller blacklist med bulk-selection
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"


def _load_json(rel_path: str) -> dict:
    p = DATA_DIR / rel_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(rel_path: str, data: dict):
    p = DATA_DIR / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_universe_json() -> dict:
    p = DATA_DIR / "universe.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_universe_json(data: dict):
    p = DATA_DIR / "universe.json"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def remove_ticker_from_universe_json(ticker: str, data: dict) -> bool:
    """Tar bort en ticker fran universe.json (bade tickers och markets)."""
    ticker = ticker.upper().strip()
    found = False
    for cat, val in data.items():
        if isinstance(val, dict):
            if "tickers" in val:
                before = len(val["tickers"])
                val["tickers"] = [t for t in val["tickers"] if t.upper().strip() != ticker]
                if len(val["tickers"]) < before:
                    found = True
            if "markets" in val:
                for mkt_name in list(val["markets"].keys()):
                    mkt_list = val["markets"][mkt_name]
                    if isinstance(mkt_list, list):
                        before = len(mkt_list)
                        val["markets"][mkt_name] = [t for t in mkt_list if t.upper().strip() != ticker]
                        if len(val["markets"][mkt_name]) < before:
                            found = True
    return found


def render():
    st.subheader("Strikes & Ticker-halsa")
    st.caption(
        "Tickers som misslyckats att hamta data flera ganger "
        "(3 strikes = auto-blacklist). Har kan du aven ta bort tickers manuellt."
    )

    strikes = _load_json("strike_list.json")
    blacklist = _load_json("blacklist.json")
    universe_data = load_universe_json()

    tab_strikes, tab_blacklist, tab_universe = st.tabs([
        "Strikes (pagar)",
        "Blacklist (borttagna)",
        "Ta bort fran universe",
    ])

    # ── STRIKES ──────────────────────────────────────────────────────────────
    with tab_strikes:
        if not strikes:
            st.success("Inga pagende strikes. Alla tickers fungerar!")
        else:
            strike_rows = []
            for ticker, info in sorted(strikes.items()):
                if isinstance(info, dict):
                    cnt = info.get("count", 1)
                    dt = info.get("date", "?")
                else:
                    cnt = int(info)
                    dt = "?"
                strike_rows.append({"Ticker": ticker, "Strikes": cnt, "Senaste": dt})

            sdf = pd.DataFrame(strike_rows)
            st.dataframe(sdf, use_container_width=True, hide_index=True)

            st.markdown("#### Bulk-atgarder")
            select_all_strikes = st.checkbox("Valj alla strikes", key="sel_all_strikes")
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                clear_strikes = st.button("Rensa strikes for valda", key="btn_clear_strikes")
            with col_b2:
                blacklist_from_strikes = st.button("Blacklista valda (ta bort ur universe)", key="btn_blacklist_strikes")

            selected_for_strike = []
            for _, row in sdf.iterrows():
                default = select_all_strikes
                if st.checkbox(
                    f"{row['Ticker']} ({row['Strikes']} strikes, senast {row['Senaste']})",
                    key=f"strike_sel_{row['Ticker']}",
                    value=default,
                ):
                    selected_for_strike.append(row["Ticker"])

            if clear_strikes and selected_for_strike:
                for t in selected_for_strike:
                    strikes.pop(t, None)
                _save_json("strike_list.json", strikes)
                blacklisted_now = []
                for t in selected_for_strike:
                    if t not in blacklist:
                        blacklist[t] = {"reason": "Manuellt borttagen fran strikes", "date": "?"}
                        blacklisted_now.append(t)
                if blacklisted_now:
                    _save_json("blacklist.json", blacklist)
                    for t in blacklisted_now:
                        remove_ticker_from_universe_json(t, universe_data)
                    save_universe_json(universe_data)
                st.success(f"Rensade strikes for {len(selected_for_strike)} tickers. Blacklistade {len(blacklisted_now)}.")
                st.rerun()

            if blacklist_from_strikes and selected_for_strike:
                for t in selected_for_strike:
                    strikes.pop(t, None)
                    if t not in blacklist:
                        blacklist[t] = {"reason": "Blacklistad fran strike-lista", "date": "?"}
                _save_json("strike_list.json", strikes)
                _save_json("blacklist.json", blacklist)
                for t in selected_for_strike:
                    remove_ticker_from_universe_json(t, universe_data)
                save_universe_json(universe_data)
                st.success(f"Blacklistade {len(selected_for_strike)} tickers och tog bort ur universe.")
                st.rerun()

    # ── BLACKLIST ─────────────────────────────────────────────────────────────
    with tab_blacklist:
        if not blacklist:
            st.success("Blacklisten ar tom.")
        else:
            bl_rows = []
            for ticker, info in sorted(blacklist.items()):
                if isinstance(info, dict):
                    reason = info.get("reason", "")[:60]
                    dt = info.get("date", "?")
                else:
                    reason = str(info)[:60]
                    dt = "?"
                bl_rows.append({"Ticker": ticker, "Anledning": reason, "Datum": dt})

            bdf = pd.DataFrame(bl_rows)
            st.dataframe(bdf, use_container_width=True, hide_index=True)

            st.markdown("#### Bulk-atgarder")
            select_all_bl = st.checkbox("Valj alla blacklistade", key="sel_all_bl")

            if st.button("Ta bort ur blacklist for valda (aterstall)", key="btn_restore_bl"):
                to_restore = []
                for _, row in bdf.iterrows():
                    cb_key = f"bl_sel_{row['Ticker']}"
                    cb_val = st.session_state.get(cb_key, False) or select_all_bl
                    if cb_val:
                        to_restore.append(row["Ticker"])
                if to_restore:
                    for t in to_restore:
                        blacklist.pop(t, None)
                    _save_json("blacklist.json", blacklist)
                    st.success(f"Aterstallde {len(to_restore)} tickers fran blacklist.")
                    st.rerun()
                else:
                    st.warning("Inga tickers valda.")

            for _, row in bdf.iterrows():
                default = select_all_bl
                st.checkbox(
                    f"{row['Ticker']} - {row['Anledning']} ({row['Datum']})",
                    key=f"bl_sel_{row['Ticker']}",
                    value=default,
                )

    # ── TA BORT FRAN UNIVERSE ─────────────────────────────────────────────────
    with tab_universe:
        st.info(
            "Har kan du soka upp tickers i universumet och ta bort dem. "
            "Anvandbart for aktier som ar delistade eller inte langre intressanta."
        )

        all_tickers = []
        for cat, val in universe_data.items():
            if isinstance(val, dict):
                if "tickers" in val:
                    for t in val["tickers"]:
                        all_tickers.append({"ticker": t, "category": cat, "location": "tickers"})
                if "markets" in val:
                    for mkt_name, mkt_list in val["markets"].items():
                        if isinstance(mkt_list, list):
                            for t in mkt_list:
                                all_tickers.append({"ticker": t, "category": f"{cat}.{mkt_name}", "location": "markets"})

        search_q = st.text_input("Sok ticker (lamna tomt for att visa alla)", key="universe_rm_search")
        if search_q:
            filtered = [t for t in all_tickers if search_q.upper() in t["ticker"].upper()]
        else:
            filtered = all_tickers

        if filtered:
            st.caption(f"Visar {len(filtered)} tickers.")
            select_all_rm = st.checkbox("Valj alla", key="sel_all_rm")

            selected_rm = []
            for t_info in filtered:
                ck = f"rm_sel_{t_info['ticker']}_{t_info['category'].replace('.', '_')}"
                if st.checkbox(
                    f"{t_info['ticker']} ({t_info['category']})",
                    key=ck,
                    value=select_all_rm,
                ):
                    selected_rm.append(t_info["ticker"])

            if selected_rm:
                if st.button(f"Ta bort {len(set(selected_rm))} markerade tickers", key="btn_rm_selected", type="primary"):
                    for t in set(selected_rm):
                        remove_ticker_from_universe_json(t, universe_data)
                    save_universe_json(universe_data)
                    st.success(f"Borttagna {len(set(selected_rm))} tickers ur universe.")
                    st.rerun()
        else:
            st.caption("Inga tickers hittades.")

        st.markdown("---")
        st.markdown("#### Blacklista ticker manuellt")
        manual_ticker = st.text_input("Ticker att blacklista:", key="manual_blacklist_ticker").upper().strip()
        manual_reason = st.text_input("Anledning (valfritt):", key="manual_blacklist_reason")
        if st.button("Blacklista", key="btn_manual_blacklist") and manual_ticker:
            bl = _load_json("blacklist.json")
            if manual_ticker not in bl:
                bl[manual_ticker] = {"reason": manual_reason or "Manuellt blacklistad", "date": "?"}
                _save_json("blacklist.json", bl)
                remove_ticker_from_universe_json(manual_ticker, universe_data)
                save_universe_json(universe_data)
                st.success(f"{manual_ticker} blacklistad och borttagen ur universe.")
                st.rerun()
            else:
                st.warning(f"{manual_ticker} finns redan i blacklist.")
