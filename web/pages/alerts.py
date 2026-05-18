"""web/pages/alerts.py – Sida 12: Larm & Notiser (ombyggd)"""

import pandas as pd
import streamlit as st

from web.utils import kpi_row, load_portfolio, load_watchlist, _load_nth_latest_scored


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_trades():
    try:
        from portfolio.paper_trading import _load, TRADES_FILE
        return _load(TRADES_FILE)
    except Exception:
        return []


def _fetch_news_for(ticker: str, days_back: int = 3) -> list:
    try:
        from core.news_fetcher import fetch_company_news
        return fetch_company_news(ticker, days_back=days_back) or []
    except Exception:
        return []


def _collect_mover_news(tickers: list[str], days_back: int = 2, max_per_ticker: int = 3) -> dict[str, list]:
    """
    Fetch news for a list of tickers in parallel.
    Returns {ticker: [news_items]} — skips empties.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    result = {}
    if not tickers:
        return result
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch_news_for, t, days_back): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                news = fut.result(timeout=20)
                if news:
                    result[t] = news[:max_per_ticker]
            except Exception:
                pass
    return result


def _format_news_context(news_map: dict[str, list]) -> str:
    """
    Format {ticker: [news]} as a 'Färska nyheter:' context block for ai_chat().
    """
    if not news_map:
        return ""
    lines = ["Färska nyheter:"]
    for ticker, items in news_map.items():
        for n in items:
            title = n.get("headline", n.get("title", "")).strip()
            src = n.get("source", "")
            age = n.get("age_hours")
            age_str = f" ({age:.0f}h sedan)" if age is not None else ""
            if title:
                lines.append(f"[{ticker}] {title} – {src}{age_str}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _score_deltas(df_today: pd.DataFrame, df_yest: pd.DataFrame, top_n: int = 8) -> dict:
    """Compare today vs yesterday scored universe."""
    try:
        from core.daily_pipeline import _get_score_deltas
        return _get_score_deltas(df_today, df_yest, top_n=top_n)
    except Exception:
        return {}


def _pct_color(val: float) -> str:
    return "🟢" if val > 0 else ("🔴" if val < 0 else "⚪")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

def page_alerts_notices(df: pd.DataFrame):
    """Larm & Notiser – ombyggd för bättre läsbarhet."""
    st.title("🚨 Larm & Notiser")

    trades = _load_trades()
    holdings = load_portfolio()
    watchlist = load_watchlist()

    # ── KPI-rad ────────────────────────────────────────────────────────────
    n_open = sum(1 for t in trades if t["status"] == "OPEN")
    n_near_stop = sum(
        1 for t in trades
        if t["status"] == "OPEN"
        and t.get("stop_loss") and t.get("current_price")
        and t["current_price"] <= t["stop_loss"] * 1.1
    )
    n_near_tp = sum(
        1 for t in trades
        if t["status"] == "OPEN"
        and t.get("take_profit") and t.get("current_price")
        and t["current_price"] >= t["take_profit"] * 0.9
    )

    kpi_row([
        ("🟢 Öppna positioner", n_open, None,
         "Antal aktiva paper trading-positioner."),
        ("🔴 Nära stop-loss", n_near_stop, None,
         "Positioner vars kurs är inom 10 % av stop-loss-nivån."),
        ("🟢 Nära take-profit", n_near_tp, None,
         "Positioner vars kurs är inom 10 % av take-profit-nivån."),
        ("⭐ Bevakade", len(watchlist), None,
         "Antal aktier på bevakningslistan."),
    ])

    st.markdown("---")

    tab_pos, tab_movers, tab_events = st.tabs([
        "📊 Positioner & Prislarm",
        "🔥 Vad stack ut idag?",
        "📅 Kommande händelser",
    ])

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 — Positioner & Prislarm
    # ══════════════════════════════════════════════════════════════════════
    with tab_pos:

        # ── Stop-loss / Take-profit ────────────────────────────────────────
        st.subheader("🛡 Stop-loss & Take-profit (paper trading)")

        if not trades:
            st.info("Inga paper trading-positioner ännu.")
        else:
            open_t = [t for t in trades if t["status"] == "OPEN"]

            near_stop = [
                t for t in open_t
                if t.get("stop_loss") and t.get("current_price")
                and t["current_price"] <= t["stop_loss"] * 1.15
            ]
            near_tp = [
                t for t in open_t
                if t.get("take_profit") and t.get("current_price")
                and t["current_price"] >= t["take_profit"] * 0.85
            ]
            safe = [t for t in open_t if t not in near_stop and t not in near_tp]

            col_a, col_b, col_c = st.columns(3)

            with col_a:
                st.markdown(f"#### 🔴 Nära stop-loss ({len(near_stop)})")
                if near_stop:
                    for t in sorted(near_stop, key=lambda x: x.get("pnl_pct", 0) or 0):
                        pnl = t.get("pnl_pct", 0) or 0
                        sl = t.get("stop_loss", 0)
                        cur = t.get("current_price", 0)
                        dist = ((cur - sl) / sl * 100) if sl else 0
                        st.markdown(
                            f"**{t['ticker']}** &nbsp; {pnl:+.1f}%  \n"
                            f"Kurs: {cur:.2f} · SL: {sl:.2f} · "
                            f"Dist: {dist:.1f}%",
                            unsafe_allow_html=True,
                        )
                        st.divider()
                else:
                    st.caption("Inga positioner nära stop-loss.")

            with col_b:
                st.markdown(f"#### 🟢 Nära take-profit ({len(near_tp)})")
                if near_tp:
                    for t in sorted(near_tp, key=lambda x: -(x.get("pnl_pct", 0) or 0)):
                        pnl = t.get("pnl_pct", 0) or 0
                        tp = t.get("take_profit", 0)
                        cur = t.get("current_price", 0)
                        dist = ((tp - cur) / tp * 100) if tp else 0
                        st.markdown(
                            f"**{t['ticker']}** &nbsp; {pnl:+.1f}%  \n"
                            f"Kurs: {cur:.2f} · TP: {tp:.2f} · "
                            f"Kvar: {dist:.1f}%",
                            unsafe_allow_html=True,
                        )
                        st.divider()
                else:
                    st.caption("Inga positioner nära take-profit.")

            with col_c:
                trailing = [t for t in open_t if t.get("trailing_stop")]
                st.markdown(f"#### 🔻 Trailing stop ({len(trailing)})")
                if trailing:
                    for t in sorted(trailing, key=lambda x: -(x.get("pnl_pct", 0) or 0)):
                        ts = t.get("trailing_stop", 0)
                        cur = t.get("current_price", 0)
                        pnl = t.get("pnl_pct", 0) or 0
                        st.markdown(
                            f"**{t['ticker']}** &nbsp; {pnl:+.1f}%  \n"
                            f"Kurs: {cur:.2f} · Trail: {ts:.2f}",
                            unsafe_allow_html=True,
                        )
                        st.divider()
                else:
                    st.caption("Inga trailing stops aktiva.")

            # Senaste triggade
            triggered = [
                t for t in trades
                if t["status"] == "CLOSED"
                and "stop" in (t.get("exit_reason", "") or "")
            ]
            if triggered:
                st.markdown("---")
                st.markdown("#### 💀 Senast triggade stop-loss")
                for t in sorted(triggered, key=lambda x: x.get("sell_date", ""), reverse=True)[:5]:
                    st.markdown(
                        f"**{t['ticker']}** såldes {t.get('sell_date', '?')} · "
                        f"{t.get('pnl_pct', 0):+.1f}% · _{t.get('exit_reason', '?')}_"
                    )

        st.markdown("---")

        # ── Prislarm från bevakningslista ──────────────────────────────────
        st.subheader("🚨 Prislarm – bevakningslista")

        if watchlist and not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")
            alarms, normal = [], []
            for item in watchlist:
                t = item["ticker"]
                sc = score_lu.get(t, {})
                price = sc.get("current_price") or sc.get("close")
                change = sc.get("change_pct") or sc.get("day_change_pct")
                entry = sc.get("entry_signal", "—")
                if change is not None and abs(change) >= 3:
                    alarms.append({
                        "Ticker": t,
                        "Bolag": item.get("name", t)[:35],
                        "Pris": f"{price:.2f}" if price else "—",
                        "Förändring": f"{change:+.1f}%",
                        "Entry": entry,
                        "Status": "🔴 Stor rörelse" if abs(change) >= 5 else "🟡 Rörelse",
                    })
                else:
                    normal.append({
                        "Ticker": t,
                        "Bolag": item.get("name", t)[:35],
                        "Pris": f"{price:.2f}" if price else "—",
                        "Dag": f"{change:+.1f}%" if change is not None else "—",
                        "Entry": entry,
                    })

            if alarms:
                st.warning(f"⚠️ {len(alarms)} aktie(r) med prislarm idag!")
                st.dataframe(pd.DataFrame(alarms), use_container_width=True, hide_index=True)
            else:
                st.success("✅ Inga prislarm – lugnt på bevakningslistan idag.")

            if normal:
                with st.expander(f"📋 Alla bevakade ({len(normal)} aktier, inga larm)", expanded=False):
                    st.dataframe(pd.DataFrame(normal), use_container_width=True, hide_index=True)
        else:
            st.info("Lägg till aktier i bevakningslistan för att se prislarm.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 — Vad stack ut idag?
    # ══════════════════════════════════════════════════════════════════════
    with tab_movers:
        st.subheader("🔥 Vad stack ut de senaste 24 timmarna?")

        today_scored   = _load_nth_latest_scored(n=1)
        yest_scored    = _load_nth_latest_scored(n=2)

        if today_scored.empty:
            st.info("Ingen scandata tillgänglig. Kör en weekly scan för att generera data.")
            st.stop()

        if yest_scored.empty:
            st.info("Behöver minst 2 dagars scandata för att visa förändringar.")
        else:
            deltas = _score_deltas(today_scored, yest_scored, top_n=8)

            if not deltas:
                st.info("Inga delta-data tillgängliga.")
            else:
                # ── Samla noterbara tickers (används av AI + nyhetsexpander) ──
                up_tickers  = [r["ticker"] for r in deltas.get("movers_up", [])[:5]]
                rsi_tickers = [r["ticker"] for r in deltas.get("rsi_spikes", [])[:5]]
                big_tickers = [r["ticker"] for r in deltas.get("big_price", [])[:5]]
                # Deduplicera, bevara ordning
                _seen: set = set()
                notable_tickers: list = []
                for _t in up_tickers + rsi_tickers + big_tickers:
                    if _t not in _seen:
                        _seen.add(_t)
                        notable_tickers.append(_t)

                # ── AI-sammanfattning ──────────────────────────────────────
                try:
                    from core import ai_analysis, config
                    from web.utils import _get_provider, _get_depth
                    api_key = config.DEEPSEEK_API_KEY or config.GEMINI_API_KEY
                    if api_key and st.button("🤖 AI-sammanfattning av dagens rörelser", key="btn_movers_ai",
                                             type="primary"):
                        with st.spinner("Hämtar nyheter och analyserar..."):
                            summary_context = []
                            up   = deltas.get("movers_up", [])[:5]
                            dn   = deltas.get("movers_down", [])[:5]
                            rsi  = deltas.get("rsi_spikes", [])
                            big  = deltas.get("big_price", [])
                            if up:
                                ups = ", ".join(
                                    f"{r['ticker']} (+{r.get('score_delta', 0):.0f}p, {r.get('price_delta_pct', 0):+.1f}%)"
                                    for r in up
                                )
                                summary_context.append(f"Störst score-ökning: {ups}")
                            if dn:
                                dns = ", ".join(
                                    f"{r['ticker']} ({r.get('score_delta', 0):.0f}p, {r.get('price_delta_pct', 0):+.1f}%)"
                                    for r in dn
                                )
                                summary_context.append(f"Störst score-minskning: {dns}")
                            if rsi:
                                rsi_str = ", ".join(
                                    f"{r['ticker']} (RSI {r.get('rsi_yesterday', 0):.0f}→{r.get('rsi_14', 0):.0f})"
                                    for r in rsi[:5]
                                )
                                summary_context.append(f"RSI-korsningar: {rsi_str}")
                            if big:
                                big_str = ", ".join(
                                    f"{r['ticker']} ({r.get('price_delta_pct', 0):+.1f}%)"
                                    for r in big[:5]
                                )
                                summary_context.append(f"Stora kursrörelser: {big_str}")

                            # ── Hämta nyheter för noterbara tickers (parallellt) ─
                            news_map = _collect_mover_news(notable_tickers[:12], days_back=2)

                            # Komplettera med portfölj/bevakningslista (parallellt)
                            port_tickers = (
                                list(holdings["ticker"].tolist()) if not holdings.empty else []
                            )
                            watch_tickers_cached = [item["ticker"] for item in (watchlist or [])[:6]]
                            extra_tickers = [
                                t for t in port_tickers + watch_tickers_cached
                                if t not in news_map and t not in notable_tickers
                            ][:8]
                            if extra_tickers:
                                extra_map = _collect_mover_news(extra_tickers, days_back=7, max_per_ticker=2)
                                news_map.update(extra_map)

                            news_ctx = _format_news_context(news_map)
                            _n_articles = sum(len(v) for v in news_map.values())

                            # ── Bygg fullständigt context ─────────────────────
                            ctx_parts = ["\n".join(summary_context)]
                            if news_ctx:
                                ctx_parts.append(news_ctx)
                            ctx = "\n\n".join(ctx_parts)

                            # Bygg prompt – tvinga nyhetsanvändning om sådana finns
                            if news_ctx:
                                _user_prompt = (
                                    f"Sammanfatta vad som stack ut på börsen idag. "
                                    f"Du har fått {_n_articles} färska nyhetsartiklar "
                                    f"för {len(news_map)} bolag (se 'Färska nyheter:' nedan). "
                                    "VIKTIGT: Du MÅSTE referera till minst 3 specifika nyheter "
                                    "och koppla dem till respektive akties rörelse. "
                                    "Citera nyhetstitel eller källa när du nämner en nyhet. "
                                    "Struktur: 1) Översikt av rörelserna (2 meningar), "
                                    "2) Specifika nyhetshändelser och vilka aktier de påverkar, "
                                    "3) Kort slutsats. Totalt 6-10 meningar."
                                )
                            else:
                                _user_prompt = (
                                    "Sammanfatta vad som stack ut på börsen idag baserat på dessa data. "
                                    "Ge en kortfattad analys (4-6 meningar) av de viktigaste rörelserna "
                                    "och vad de kan signalera. OBS: Inga färska nyheter hittades, "
                                    "spekulera inte om nyhetshändelser."
                                )

                            result = ai_analysis.ai_chat(
                                _user_prompt,
                                context=ctx,
                                provider=_get_provider(),
                                depth="Snabb",
                                force_refresh=True,
                            )

                            # Status-rad om nyhetstillgång
                            if news_map:
                                st.success(
                                    f"📰 {_n_articles} nyheter från {len(news_map)} bolag inkluderades i analysen."
                                )
                            else:
                                st.warning(
                                    "⚠️ Inga nyheter kunde hämtas för dagens rörare. "
                                    "Analysen är baserad endast på score-/kursdata."
                                )

                            st.markdown(
                                '<div style="background:#1a2332;border:1px solid #2d3250;'
                                'border-radius:8px;padding:12px 18px;margin-bottom:16px">',
                                unsafe_allow_html=True,
                            )
                            st.markdown(result)
                            st.markdown("</div>", unsafe_allow_html=True)

                            # ── Visa hämtade nyheter i expander ──────────────
                            if news_map:
                                total_news = sum(len(v) for v in news_map.values())
                                with st.expander(
                                    f"📰 Nyheter som inkluderades i analysen ({total_news} artiklar, "
                                    f"{len(news_map)} bolag)",
                                    expanded=False,
                                ):
                                    for _ticker, _items in news_map.items():
                                        st.markdown(f"**{_ticker}**")
                                        for _n in _items:
                                            _title = _n.get("headline", _n.get("title", "—")).strip()
                                            _src   = _n.get("source", "?")
                                            _age   = _n.get("age_hours")
                                            _url   = _n.get("url", "")
                                            _age_s = f" · {_age:.0f}h sedan" if _age is not None else ""
                                            if _url:
                                                st.markdown(f"  - [{_title}]({_url}) — *{_src}*{_age_s}")
                                            else:
                                                st.markdown(f"  - {_title} — *{_src}*{_age_s}")
                                        st.markdown("")
                except Exception:
                    pass

                st.markdown("---")

                # ── Score-rörelser ──────────────────────────────────────────
                col_up, col_dn = st.columns(2)

                with col_up:
                    st.markdown("##### ⬆️ Störst score-ökning")
                    up_data = deltas.get("movers_up", [])
                    if up_data:
                        rows = []
                        for r in up_data:
                            ticker = r["ticker"]
                            delta = r.get("score_delta", 0)
                            price_d = r.get("price_delta_pct", 0)
                            score = r.get("score_total", 0)
                            rows.append({
                                "Ticker": ticker,
                                "Score": f"{score:.0f}",
                                "Δ Score": f"+{delta:.1f}",
                                "Δ Pris": f"{price_d:+.1f}%",
                            })
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    else:
                        st.caption("Inga data.")

                with col_dn:
                    st.markdown("##### ⬇️ Störst score-minskning")
                    dn_data = deltas.get("movers_down", [])
                    if dn_data:
                        rows = []
                        for r in dn_data:
                            ticker = r["ticker"]
                            delta = r.get("score_delta", 0)
                            price_d = r.get("price_delta_pct", 0)
                            score = r.get("score_total", 0)
                            rows.append({
                                "Ticker": ticker,
                                "Score": f"{score:.0f}",
                                "Δ Score": f"{delta:.1f}",
                                "Δ Pris": f"{price_d:+.1f}%",
                            })
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    else:
                        st.caption("Inga data.")

                # ── RSI-korsningar ──────────────────────────────────────────
                rsi_data = deltas.get("rsi_spikes", [])
                big_data = deltas.get("big_price", [])

                if rsi_data or big_data:
                    st.markdown("---")
                    col_rsi, col_big = st.columns(2)

                    with col_rsi:
                        if rsi_data:
                            st.markdown("##### 📈 RSI-korsningar (30↑ / 70↓)")
                            rsi_rows = []
                            for r in rsi_data:
                                crossed = ("30 ↑" if r.get("rsi_crossed_30up") else "70 ↓")
                                rsi_rows.append({
                                    "Ticker": r["ticker"],
                                    "RSI idag": f"{r.get('rsi_14', 0):.0f}",
                                    "RSI igår": f"{r.get('rsi_yesterday', 0):.0f}",
                                    "Signal": crossed,
                                })
                            st.dataframe(pd.DataFrame(rsi_rows), use_container_width=True, hide_index=True)

                    with col_big:
                        if big_data:
                            st.markdown("##### 💥 Stora kursrörelser (>4%)")
                            big_rows = []
                            for r in big_data[:8]:
                                d = r.get("price_delta_pct", 0)
                                big_rows.append({
                                    "Ticker": r["ticker"],
                                    "Score": f"{r.get('score_total', 0):.0f}",
                                    "Δ Pris": f"{d:+.1f}%",
                                    "Riktning": "🟢 Upp" if d > 0 else "🔴 Ned",
                                })
                            st.dataframe(pd.DataFrame(big_rows), use_container_width=True, hide_index=True)

                # ── Nyheter för noterbara aktier (lazy expanders) ────────────
                if notable_tickers:
                    st.markdown("---")
                    st.markdown("##### 📰 Nyheter – aktier som stack ut idag")
                    st.caption(
                        "Klicka på en aktie för att se senaste nyheter. "
                        "Nyheter hämtas ur cache (eller live om ingen cache finns)."
                    )
                    _n_cols = min(3, len(notable_tickers[:9]))
                    _cols = st.columns(_n_cols)
                    for _i, _nt in enumerate(notable_tickers[:9]):
                        with _cols[_i % _n_cols]:
                            with st.expander(f"📰 {_nt}", expanded=False):
                                _nt_news = _fetch_news_for(_nt, days_back=3)
                                if _nt_news:
                                    for _nn in _nt_news[:4]:
                                        _t2 = _nn.get("headline", _nn.get("title", "—")).strip()
                                        _s2 = _nn.get("source", "?")
                                        _a2 = _nn.get("age_hours")
                                        _u2 = _nn.get("url", "")
                                        _as2 = f" · {_a2:.0f}h" if _a2 is not None else ""
                                        if _u2:
                                            st.markdown(f"[{_t2}]({_u2})  \n*{_s2}*{_as2}")
                                        else:
                                            st.markdown(f"{_t2}  \n*{_s2}*{_as2}")
                                        st.divider()
                                else:
                                    st.caption("Inga nyheter hittade.")

        st.markdown("---")

        # ── Nyheter för bevakningslistan ──────────────────────────────────
        st.subheader("📰 Senaste nyheter – bevakningslistan")
        if watchlist:
            watch_tickers = [item["ticker"] for item in watchlist[:8]]
            for item in watchlist[:6]:
                t = item["ticker"]
                name = item.get("name", t)[:40]
                with st.expander(f"📰 {t} — {name}", expanded=False):
                    news = _fetch_news_for(t, days_back=3)
                    if news:
                        for n in news[:4]:
                            title = n.get("headline", n.get("title", "—"))
                            src = n.get("source", "?")
                            age = n.get("age_hours")
                            age_str = f" · {age:.0f}h sedan" if age is not None else ""
                            url = n.get("url", "")
                            if url:
                                st.markdown(f"- [{title}]({url}) — *{src}*{age_str}")
                            else:
                                st.markdown(f"- **{title}** — *{src}*{age_str}")
                    else:
                        st.caption("Inga nyheter hittade de senaste 3 dagarna.")
        else:
            st.info("Lägg till aktier i bevakningslistan för att se nyheter.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 — Kommande händelser
    # ══════════════════════════════════════════════════════════════════════
    with tab_events:
        st.subheader("📅 Kommande händelser")

        _scored_for_cal = df if not df.empty else _load_nth_latest_scored(n=1)
        _holdings_for_cal = holdings

        # ── Rapporter ─────────────────────────────────────────────────────
        col_port, col_top = st.columns(2)

        with col_port:
            st.markdown("##### 📊 Rapporter – innehav (30 dagar)")
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
            st.markdown("##### 📊 Rapporter – topp-20 (14 dagar)")
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

        st.markdown("---")

        # ── Centralbanksbeslut ────────────────────────────────────────────
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

        st.markdown("---")

        # ── Utdelningar ───────────────────────────────────────────────────
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
