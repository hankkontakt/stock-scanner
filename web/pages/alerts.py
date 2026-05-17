"""web/pages/alerts.py – Sida 12: Larm & Notiser"""

import pandas as pd
import streamlit as st

from web.utils import kpi_row, load_portfolio, load_watchlist, _load_nth_latest_scored


def page_alerts_notices(df: pd.DataFrame):
    """Larm & notiser – visa aktiva stop-loss, prisnivåer och nyhetslarm."""
    st.title("🚨 Larm & Notiser")
    st.caption("Översikt över aktiva stop-loss, take-profit, prisnivåer och larm baserat på din portfölj och bevakningslista.")

    # Ladda paper trading-data för stop-loss/take-profit-larm
    try:
        from portfolio.paper_trading import _load, TRADES_FILE
        trades = _load(TRADES_FILE)
    except Exception:
        trades = []

    # Ladda holdings/watchlist
    holdings = load_portfolio()
    watchlist = load_watchlist()

    # KPI-kort
    n_open = sum(1 for t in trades if t["status"] == "OPEN")
    n_near_stop = sum(1 for t in trades if t["status"] == "OPEN" and t.get("stop_loss") and t.get("current_price") and t["current_price"] <= t["stop_loss"] * 1.1)
    n_near_tp = sum(1 for t in trades if t["status"] == "OPEN" and t.get("take_profit") and t.get("current_price") and t["current_price"] >= t["take_profit"] * 0.9)

    kpi_row([
        ("🟢 Öppna positioner", n_open, None,
         "Antal aktiva paper trading-positioner som inte stängts ännu. Paper trading = simulerade affärer utan riktiga pengar, för att testa strategier."),
        ("🔴 Nära stop-loss", n_near_stop, None,
         "Antal positioner vars kurs är inom 10% av stop-loss-nivån. Stop-loss = en prisnivå där positionen automatiskt säljs för att begränsa förluster."),
        ("🟢 Nära take-profit", n_near_tp, None,
         "Antal positioner vars kurs är inom 10% av take-profit-nivån. Take-profit = en prisnivå där positionen säljs för att låsa in vinst."),
        ("⭐ Bevakade", len(watchlist), None,
         "Antal aktier på din bevakningslista. Du får nyheter och larm för dessa aktier utan att äga dem."),
    ])

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔴 Stop-loss/Take-profit", "🚨 Prislarm", "📰 Nyhetslarm",
        "📊 Stuckit ut (24h)", "📅 Värt att kolla",
    ])

    with tab1:
        if not trades:
            st.info("Inga paper trading-positioner. Starta en scan för att få trades.")
        else:
            # Trades nära stop-loss
            near_stop = [t for t in trades if t["status"] == "OPEN" and t.get("stop_loss") and t.get("current_price") and t["current_price"] <= t["stop_loss"] * 1.15]
            near_tp = [t for t in trades if t["status"] == "OPEN" and t.get("take_profit") and t.get("current_price") and t["current_price"] >= t["take_profit"] * 0.85]
            trailing = [t for t in trades if t["status"] == "OPEN" and t.get("trailing_stop")]

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.subheader(f"🔴 Stop-loss ({len(near_stop)})")
                for t in sorted(near_stop, key=lambda x: x.get("pnl_pct", 0)):
                    pnl = t.get("pnl_pct", 0) or 0
                    st.markdown(f"**{t['ticker']}** — {pnl:+.1f}% — SL: {t.get('stop_loss', 0):.2f}")
            with col_b:
                st.subheader(f"🟢 Take-profit ({len(near_tp)})")
                for t in sorted(near_tp, key=lambda x: -x.get("pnl_pct", 0)):
                    pnl = t.get("pnl_pct", 0) or 0
                    st.markdown(f"**{t['ticker']}** — {pnl:+.1f}% — TP: {t.get('take_profit', 0):.2f}")
            with col_c:
                st.subheader(f"🔻 Trailing ({len(trailing)})")
                for t in sorted(trailing, key=lambda x: -x.get("pnl_pct", 0)):
                    ts = t.get("trailing_stop", 0)
                    st.markdown(f"**{t['ticker']}** — Trail: {ts:.2f}")

            # Senaste triggade stop-loss
            triggered = [t for t in trades if t["status"] == "CLOSED" and "stop" in (t.get("exit_reason", "") or "")]
            if triggered:
                st.markdown("---")
                st.subheader(f"💀 Senaste triggade stop-loss ({len(triggered)})")
                for t in sorted(triggered, key=lambda x: x.get("sell_date", ""), reverse=True)[:5]:
                    st.markdown(f"**{t['ticker']}** — såldes {t.get('sell_date', '?')} — {t.get('pnl_pct', 0):+.1f}% (anledning: {t.get('exit_reason', '?')})")

    with tab2:
        st.subheader("🚨 Prislarm")
        st.caption("Här kan du skapa och se prislarm för dina bevakade aktier.")

        # Simpel prislarm-funktion: visa när bevakade aktier rör sig >5%
        if watchlist and not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")
            alarms = []
            for item in watchlist:
                t = item["ticker"]
                sc = score_lu.get(t, {})
                price = sc.get("current_price")
                change = sc.get("change_pct") or sc.get("day_change_pct")
                if change and abs(change) >= 3:
                    alarms.append({
                        "Ticker": t,
                        "Bolag": item.get("name", t),
                        "Pris": f"{price:.2f}" if price else "—",
                        "Förändring": f"{change:+.1f}%",
                        "Larm": "🔴 Stor rörelse" if abs(change) >= 5 else "🟡 Rörelse >3%",
                    })
            if alarms:
                st.warning(f"⚠️ {len(alarms)} aktier med prislarm!")
                st.dataframe(pd.DataFrame(alarms), use_container_width=True, hide_index=True)
            else:
                st.info("Inga aktiva prislarm just nu.")
        else:
            st.info("Lägg till bevakningslista för att se prislarm.")

    with tab3:
        st.subheader("📰 Nyhetslarm")
        st.caption("Se senaste nyheter för dina innehav.")
        if watchlist:
            for item in watchlist[:5]:
                t = item["ticker"]
                with st.expander(f"📰 {t} — {item.get('name', '')[:40]}", expanded=False):
                    try:
                        from core.news_fetcher import fetch_company_news
                        news = fetch_company_news(t, days_back=3)
                        if news:
                            for n in news[:3]:
                                st.markdown(f"- **{n.get('headline', '?')}** ({n.get('source', '?')})")
                        else:
                            st.caption("Inga nyheter hittade.")
                    except Exception:
                        st.caption("Nyhetshämtning ej tillgänglig.")
        else:
            st.info("Lägg till bevakningslista för att se nyheter.")

    with tab4:
        st.subheader("📊 Vad stack ut de senaste 24 timmarna?")
        st.caption("Jämför dagens ranking mot gårdagens — score-rörelser, RSI-korsningar och stora kursrörelser.")
        try:
            from core.daily_pipeline import _get_score_deltas
            today_scored   = _load_nth_latest_scored(n=1)
            yesterday_scored = _load_nth_latest_scored(n=2)
            deltas = _get_score_deltas(today_scored, yesterday_scored)
        except Exception as _e:
            deltas = {}
            st.warning(f"Kunde inte beräkna deltas: {_e}")

        if not deltas:
            st.info("Behöver minst 2 dagars scan-data för att visa förändringar.")
        else:
            col_up, col_dn = st.columns(2)
            with col_up:
                st.markdown("##### ⬆️ Störst score-ökning")
                up_data = deltas.get("movers_up", [])
                if up_data:
                    up_df = pd.DataFrame(up_data).rename(columns={
                        "ticker": "Ticker", "score_total": "Score idag",
                        "score_yesterday": "Score igår", "score_delta": "Δ Score",
                        "price_delta_pct": "Δ Pris %",
                    })
                    st.dataframe(up_df, use_container_width=True, hide_index=True)
                else:
                    st.caption("Inga data.")
            with col_dn:
                st.markdown("##### ⬇️ Störst score-minskning")
                dn_data = deltas.get("movers_down", [])
                if dn_data:
                    dn_df = pd.DataFrame(dn_data).rename(columns={
                        "ticker": "Ticker", "score_total": "Score idag",
                        "score_yesterday": "Score igår", "score_delta": "Δ Score",
                        "price_delta_pct": "Δ Pris %",
                    })
                    st.dataframe(dn_df, use_container_width=True, hide_index=True)
                else:
                    st.caption("Inga data.")

            rsi_data = deltas.get("rsi_spikes", [])
            if rsi_data:
                st.markdown("##### 📈 RSI-korsningar (30↑ / 70↓)")
                rsi_df = pd.DataFrame(rsi_data).rename(columns={
                    "ticker": "Ticker", "rsi_14": "RSI idag", "rsi_yesterday": "RSI igår",
                    "rsi_crossed_30up": "Korsade 30↑", "rsi_crossed_70down": "Korsade 70↓",
                })
                st.dataframe(rsi_df, use_container_width=True, hide_index=True)

            price_data = deltas.get("big_price", [])
            if price_data:
                st.markdown("##### 💥 Stora kursrörelser (>4%)")
                price_df = pd.DataFrame(price_data).rename(columns={
                    "ticker": "Ticker", "score_total": "Score",
                    "price_delta_pct": "Δ Pris %",
                })
                st.dataframe(price_df[["Ticker", "Score", "Δ Pris %"]],
                             use_container_width=True, hide_index=True)

    with tab5:
        st.subheader("📅 Kommande händelser")
        st.caption("Rapporter, centralbanksbeslut och utdelningar de närmaste veckorna.")

        # ── Rapporter ──────────────────────────────────────────────────────────
        col_port, col_top = st.columns(2)
        _scored_for_cal = df if not df.empty else _load_nth_latest_scored(n=1)
        _holdings_for_cal = holdings

        with col_port:
            st.markdown("##### 📊 Rapporter – innehav")
            try:
                from core.earnings_calendar import upcoming_in_portfolio
                if not _holdings_for_cal.empty and not _scored_for_cal.empty:
                    port_cal = upcoming_in_portfolio(_holdings_for_cal, _scored_for_cal, days_ahead=30)
                    if not port_cal.empty:
                        _pc = port_cal[["ticker", "earnings_date", "days_until"]].copy()
                        _pc.columns = ["Ticker", "Datum", "Dagar kvar"]
                        st.dataframe(_pc, use_container_width=True, hide_index=True)
                        st.caption("⚠️ Var försiktig med köp precis innan rapport (gap-risk)")
                    else:
                        st.info("Inga rapporter de närmsta 30 dagarna.")
                else:
                    st.info("Lägg till innehav för att se kommande rapporter.")
            except Exception as _e:
                st.caption(f"Rapportkalender ej tillgänglig: {_e}")

        with col_top:
            st.markdown("##### 📊 Rapporter – topp-20")
            try:
                from core.earnings_calendar import upcoming_in_top
                if not _scored_for_cal.empty:
                    top_cal = upcoming_in_top(_scored_for_cal, top_n=20, days_ahead=14)
                    if not top_cal.empty:
                        _tc_cols = [c for c in ["ticker", "earnings_date", "days_until", "rank"]
                                    if c in top_cal.columns]
                        _tc = top_cal[_tc_cols].copy()
                        _tc.columns = [{"ticker": "Ticker", "earnings_date": "Datum",
                                         "days_until": "Dagar kvar", "rank": "Rank"}.get(c, c)
                                        for c in _tc_cols]
                        st.dataframe(_tc, use_container_width=True, hide_index=True)
                    else:
                        st.info("Inga rapporter de närmsta 14 dagarna.")
                else:
                    st.info("Kör en scan för att se kommande rapporter.")
            except Exception as _e:
                st.caption(f"Rapportkalender ej tillgänglig: {_e}")

        # ── Centralbanksbeslut ─────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 🏦 Kommande centralbanksbeslut (30 dagar)")
        try:
            from core.macro_calendar import get_upcoming_macro_events
            macro_evs = get_upcoming_macro_events(days_ahead=30)
            if macro_evs:
                _mc_df = pd.DataFrame(macro_evs)[["flag", "event", "date", "days_until"]]
                _mc_df.columns = ["", "Händelse", "Datum", "Dagar kvar"]
                st.dataframe(_mc_df, use_container_width=True, hide_index=True)
            else:
                st.info("Inga centralbanksbeslut de närmsta 30 dagarna.")
        except Exception as _e:
            st.caption(f"Makrokalender ej tillgänglig: {_e}")

        # ── Utdelningar ────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("##### 💰 Kommande utdelningar – innehav (60 dagar)")
        try:
            from core.dividend_calendar import get_upcoming_dividends
            if not _holdings_for_cal.empty:
                div_cal = get_upcoming_dividends(
                    _holdings_for_cal["ticker"].tolist(), days_ahead=60
                )
                if not div_cal.empty:
                    _dc_cols = [c for c in ["ticker", "next_div_date", "amount", "yield_pct", "days_until"]
                                if c in div_cal.columns]
                    _dc = div_cal[_dc_cols].copy()
                    _dc.columns = [{"ticker": "Ticker", "next_div_date": "Ex-datum",
                                     "amount": "Belopp", "yield_pct": "Yield %",
                                     "days_until": "Dagar kvar"}.get(c, c) for c in _dc_cols]
                    st.dataframe(_dc, use_container_width=True, hide_index=True)
                else:
                    st.info("Inga utdelningar de närmsta 60 dagarna.")
            else:
                st.info("Lägg till innehav för att se kommande utdelningar.")
        except Exception as _e:
            st.caption(f"Utdelningskalender ej tillgänglig: {_e}")
