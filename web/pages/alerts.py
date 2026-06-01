"""web/pages/alerts.py - Sida 12: Larm & Notiser (ombyggd)"""

import pandas as pd
import streamlit as st

from web.utils import kpi_row, load_portfolio, load_watchlist, _load_nth_latest_scored
from web.ui.components import clickable_stock_table


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fetch_news_for(ticker: str, days_back: int = 3) -> list:
    try:
        from core.news_fetcher import fetch_company_news
        return fetch_company_news(ticker, days_back=days_back) or []
    except Exception:
        return []


def _collect_mover_news(tickers: list[str], days_back: int = 2, max_per_ticker: int = 3) -> dict[str, list]:
    """
    Fetch news for a list of tickers in parallel.
    Returns {ticker: [news_items]} -- skips empties.
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
                lines.append(f"[{ticker}] {title} - {src}{age_str}")
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

def _watchlist_health_check(watchlist: list, df_today: pd.DataFrame, df_yesterday: pd.DataFrame) -> list:
    """
    For each watchlist item, check:
    - Score change vs yesterday
    - Entry signal change
    - Entered STARK / left STARK
    Returns list of alert dicts.
    """
    alerts = []
    if not watchlist or df_today.empty:
        return []

    wl_tickers = [w.get("ticker", "") for w in watchlist if w.get("ticker")]
    today_wl = df_today[df_today["ticker"].isin(wl_tickers)].set_index("ticker")
    yest_wl = df_yesterday[df_yesterday["ticker"].isin(wl_tickers)].set_index("ticker") if not df_yesterday.empty else pd.DataFrame()

    for ticker in wl_tickers:
        if ticker not in today_wl.index:
            continue
        today_row = today_wl.loc[ticker]
        alert = {"ticker": ticker, "changes": []}

        score_today = today_row.get("score_total")
        entry_today = today_row.get("entry_signal", "")

        if not yest_wl.empty and ticker in yest_wl.index:
            yest_row = yest_wl.loc[ticker]
            score_yest = yest_row.get("score_total")
            entry_yest = yest_row.get("entry_signal", "")

            # Score delta
            if pd.notna(score_today) and pd.notna(score_yest):
                delta = float(score_today) - float(score_yest)
                if abs(delta) >= 10:
                    direction = "Upp" if delta > 0 else "Ned"
                    alert["changes"].append(f"{direction} {abs(delta):.0f}p (score: {score_yest:.0f}->{score_today:.0f})")
                    alert["delta"] = delta

            # Signal change
            if entry_today != entry_yest and entry_today and entry_yest:
                if entry_today == "STARK":
                    alert["changes"].append(f"Ny STARK-signal! (från {entry_yest})")
                    alert["priority"] = "high"
                elif entry_yest == "STARK" and entry_today != "STARK":
                    alert["changes"].append(f"Lämnat STARK (nu: {entry_today})")
                    alert["priority"] = "medium"
                else:
                    alert["changes"].append(f"Signal: {entry_yest}->{entry_today}")

        # Current state info
        alert["score"] = float(score_today) if pd.notna(score_today) else None
        alert["entry_signal"] = entry_today
        alert["name"] = today_row.get("name", ticker)

        alerts.append(alert)

    return alerts


def _get_insider_alerts(df: pd.DataFrame) -> pd.DataFrame:
    """Get stocks with recent insider buying signals from scored universe."""
    if df.empty:
        return pd.DataFrame()

    conditions = []

    # Executive buy signal
    if "insider_executive_buy" in df.columns:
        exec_buy = df["insider_executive_buy"].fillna(False).astype(bool)
        conditions.append(exec_buy)

    # Insider cluster (3+ insiders buying)
    if "insider_cluster" in df.columns:
        cluster = df["insider_cluster"].fillna(False).astype(bool)
        conditions.append(cluster)

    # High insider ownership + recent activity
    if "insider_pct" in df.columns:
        high_pct = df["insider_pct"].fillna(0) > 0.15  # >15% owned by insiders
        conditions.append(high_pct)

    if not conditions:
        return pd.DataFrame()

    # Any condition triggers
    mask = conditions[0].copy()
    for cond in conditions[1:]:
        mask = mask | cond

    result = df[mask].copy()
    if result.empty:
        return pd.DataFrame()

    # Add signal type column
    def _signal_type(row):
        types = []
        if row.get("insider_executive_buy"):
            types.append("VD/CFO köp")
        if row.get("insider_cluster"):
            types.append("Kluster (3+ insiders)")
        if (row.get("insider_pct") or 0) > 0.15:
            types.append(f"Högt ägande ({row.get('insider_pct', 0) * 100:.0f}%)")
        return " * ".join(types) if types else "Insynsägande"

    result["Insynssignal"] = result.apply(_signal_type, axis=1)

    show_cols = ["ticker", "name", "Insynssignal", "score_total", "entry_signal",
                 "insider_pct", "return_1m", "return_3m"]
    available = [c for c in show_cols if c in result.columns or c == "Insynssignal"]
    if "score_total" in result.columns:
        return result[available].sort_values("score_total", ascending=False)
    return result[available]


def page_alerts_notices(df: pd.DataFrame):
    """Larm & Notiser - ombyggd för bättre läsbarhet."""
    st.title("🚨 Larm & Notiser")

    holdings = load_portfolio()
    watchlist = load_watchlist()

    # ── KPI-rad ────────────────────────────────────────────────────────────
    kpi_row([
        ("⭐ Bevakade aktier", len(watchlist), None,
         "Antal aktier på din bevakningslista."),
        ("💼 Portföljinnehav", len(holdings) if not holdings.empty else 0, None,
         "Antal aktier i din portfölj."),
    ])

    st.markdown("---")

    # Load yesterday's data for watchlist health check
    df_yesterday = _load_nth_latest_scored(n=2)

    tab_pos, tab_movers, tab_events, tab_watchlist, tab_insider = st.tabs([
        "⚡ Signaler & Larm",
        "🔥 Vad stack ut idag?",
        "📅 Kommande händelser",
        "⭐ Bevakningslista",
        "👔 Insynsköp",
    ])

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 -- Signaler & Larm (f.d. Positioner & Prislarm)
    # ══════════════════════════════════════════════════════════════════════
    with tab_pos:
        with st.expander("ℹ️ Vad är det här? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
**Den här fliken visar automatiska larm baserade på systemets analys av dina bevakade aktier.**

### ⚡ STARK köpsignal
Det starkaste larmet i systemet. Det innebär att aktien uppfyller *flera* positiva kriterier samtidigt:
- **Hög totalpoäng** (>= 60 av 100)
- **STARK entry-signal** = tekniska indikatorer pekar uppåt (momentum, RSI, trend)

Det betyder *inte* att aktien garanterat stiger -- men det är systemets starkaste köprekommendation.
**Gör alltid din egen research** och kolla nyheter innan du köper.

### ⚠️ Prislarm
Aktier på din bevakningslista som rört sig mer än 3% på en dag -- kan vara köp- eller säljsignal
beroende på riktning och nyhetsbakgrund.

### 📋 Övriga aktier
Resten av bevakningslistan med nuvarande status. Grön entry = positivt, röd = negativt.
""")

        # ── STARK-signaler från bevakningslista ────────────────────────────
        st.subheader("⚡ Köpsignaler - bevakningslista")

        if watchlist and not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")
            stark_hits, alarms, normal = [], [], []

            for item in watchlist:
                t     = item["ticker"]
                sc    = score_lu.get(t, {})
                price = sc.get("current_price") or sc.get("close")
                change = sc.get("change_pct") or sc.get("day_change_pct")
                entry  = sc.get("entry_signal", "--")
                score  = sc.get("score_total", 0) or 0
                trend  = sc.get("trend_signal", "--")
                conf   = sc.get("confidence_label", "--")

                if entry == "STARK" and score >= 60:
                    stark_hits.append({
                        "Ticker": t,
                        "Bolag":  item.get("name", t)[:30],
                        "Score":  f"{score:.0f}",
                        "Trend":  trend,
                        "Konfidens": conf,
                        "Pris":   f"{price:.2f}" if price else "--",
                        "Dag":    f"{change:+.1f}%" if change is not None else "--",
                    })
                elif change is not None and abs(change) >= 3:
                    alarms.append({
                        "Ticker":      t,
                        "Bolag":       item.get("name", t)[:30],
                        "Pris":        f"{price:.2f}" if price else "--",
                        "Dag":         f"{change:+.1f}%",
                        "Entry":       entry,
                        "Status":      "🔴 Stor rörelse" if abs(change) >= 5 else "🟡 Rörelse",
                    })
                else:
                    normal.append({
                        "Ticker": t,
                        "Bolag":  item.get("name", t)[:30],
                        "Pris":   f"{price:.2f}" if price else "--",
                        "Dag":    f"{change:+.1f}%" if change is not None else "--",
                        "Entry":  entry,
                        "Score":  f"{score:.0f}" if score else "--",
                    })

            # STARK-signaler -- framhäv tydligt
            if stark_hits:
                st.markdown(
                    f'<div style="background:#0d2a1a;border:2px solid #4caf50;border-radius:10px;'
                    f'padding:14px 18px;margin-bottom:12px;">'
                    f'<div style="font-size:14px;font-weight:700;color:#4caf50;margin-bottom:8px;">'
                    f'⚡ {len(stark_hits)} aktie(r) på din bevakning har STARK köpsignal nu!</div>'
                    f'<div style="font-size:12px;color:#a0c4a0;">Score >= 60 + STARK-signal = systemets starkaste köprekommendation. '
                    f'Kontrollera alltid trend och nyheter innan du agerar.</div></div>',
                    unsafe_allow_html=True,
                )
                clickable_stock_table(
                    pd.DataFrame(stark_hits), ticker_col="Ticker", context_df=df,
                    key="alerts_stark_table",
                    column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%.0f")},
                    caption="Klicka på en aktie för full analys.",
                )
            else:
                st.info("Inga STARK-signaler på bevakningslistan just nu -- systemet bevakar åt dig.")

            # Prislarm
            if alarms:
                st.markdown("---")
                st.markdown(f"**⚠️ Prislarm -- {len(alarms)} aktie(r) med stor rörelse idag**")
                clickable_stock_table(pd.DataFrame(alarms), ticker_col="Ticker", context_df=df,
                                      key="alerts_prislarm_table", caption="Klicka på en aktie för full analys.")

            # Alla övriga
            if normal:
                with st.expander(f"📋 Resten av bevakningslistan ({len(normal)} aktier)", expanded=False):
                    clickable_stock_table(pd.DataFrame(normal), ticker_col="Ticker", context_df=df,
                                         key="alerts_normal_table", caption="Klicka på en aktie för full analys.")
        else:
            st.info("Lägg till aktier i bevakningslistan (⭐ Bevakningar) för att få signaler och larm här.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 -- Vad stack ut idag?
    # ══════════════════════════════════════════════════════════════════════
    with tab_movers:
        with st.expander("ℹ️ Vad är det här? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
**Den här fliken visar aktier som stuckit ut jämfört med föregående dag.**

### ⬆️ / ⬇️ Score-förändringar
Systemet beräknar en **totalpoäng (0-100)** för varje aktie baserat på 10 faktorer.
En stor poängökning (+) betyder att aktien förbättrats på flera faktorer -- t.ex. bättre momentum,
tekniska signaler, eller förbättrad fundamenta. Stor poängnedgång (-) är varningssignal.

### 📈 RSI-korsningar (30↑ / 70↓)
**RSI (Relative Strength Index)** mäter om en aktie är överköpt eller översåld:
- **RSI korsade 30 uppåt (30↑):** Aktien var tidigare "översåld" (nedtryckt) och börjar studsa -- potentiell köpsignal
- **RSI korsade 70 nedåt (70↓):** Aktien var "överköpt" (dyr tekniskt) och börjar falla -- potentiell säljsignal

### 💥 Stora kursrörelser (>4%)
Aktier som rört sig mer än 4% på en enda dag. Kan bero på kvartalsrapport, nyhet,
eller generell marknadsrörelse. Kolla alltid nyheter för att förstå varför!
""")
        st.subheader("🔥 Vad stack ut de senaste 24 timmarna?")

        today_scored   = _load_nth_latest_scored(n=1)
        yest_scored    = _load_nth_latest_scored(n=2)

        if today_scored.empty:
            st.info("Aktiedata saknas ännu -- systemet uppdateras automatiskt varje vecka. Kom tillbaka snart.")
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
                                    f"{r['ticker']} (RSI {r.get('rsi_yesterday', 0):.0f}->{r.get('rsi_14', 0):.0f})"
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

                            # Bygg prompt - tvinga nyhetsanvändning om sådana finns
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
                                            _title = _n.get("headline", _n.get("title", "--")).strip()
                                            _src   = _n.get("source", "?")
                                            _age   = _n.get("age_hours")
                                            _url   = _n.get("url", "")
                                            _age_s = f" * {_age:.0f}h sedan" if _age is not None else ""
                                            if _url:
                                                st.markdown(f"  - [{_title}]({_url}) -- *{_src}*{_age_s}")
                                            else:
                                                st.markdown(f"  - {_title} -- *{_src}*{_age_s}")
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
                        clickable_stock_table(pd.DataFrame(rows), ticker_col="Ticker", context_df=today_scored,
                                             key="alerts_movers_up_table", caption="Klicka för analys.")
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
                        clickable_stock_table(pd.DataFrame(rows), ticker_col="Ticker", context_df=today_scored,
                                             key="alerts_movers_dn_table", caption="Klicka för analys.")
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
                            clickable_stock_table(pd.DataFrame(rsi_rows), ticker_col="Ticker", context_df=today_scored,
                                                 key="alerts_rsi_table", caption="Klicka för analys.")

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
                            clickable_stock_table(pd.DataFrame(big_rows), ticker_col="Ticker", context_df=today_scored,
                                                 key="alerts_big_table", caption="Klicka för analys.")

                # ── Nyheter för noterbara aktier (lazy expanders) ────────────
                if notable_tickers:
                    st.markdown("---")
                    st.markdown("##### 📰 Nyheter - aktier som stack ut idag")
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
                                        _t2 = _nn.get("headline", _nn.get("title", "--")).strip()
                                        _s2 = _nn.get("source", "?")
                                        _a2 = _nn.get("age_hours")
                                        _u2 = _nn.get("url", "")
                                        _as2 = f" * {_a2:.0f}h" if _a2 is not None else ""
                                        if _u2:
                                            st.markdown(f"[{_t2}]({_u2})  \n*{_s2}*{_as2}")
                                        else:
                                            st.markdown(f"{_t2}  \n*{_s2}*{_as2}")
                                        st.divider()
                                else:
                                    st.caption("Inga nyheter hittade.")

        st.markdown("---")

        # ── Nyheter för bevakningslistan ──────────────────────────────────
        st.subheader("📰 Senaste nyheter - bevakningslistan")
        if watchlist:
            watch_tickers = [item["ticker"] for item in watchlist[:8]]
            for item in watchlist[:6]:
                t = item["ticker"]
                name = item.get("name", t)[:40]
                with st.expander(f"📰 {t} -- {name}", expanded=False):
                    news = _fetch_news_for(t, days_back=3)
                    if news:
                        for n in news[:4]:
                            title = n.get("headline", n.get("title", "--"))
                            src = n.get("source", "?")
                            age = n.get("age_hours")
                            age_str = f" * {age:.0f}h sedan" if age is not None else ""
                            url = n.get("url", "")
                            if url:
                                st.markdown(f"- [{title}]({url}) -- *{src}*{age_str}")
                            else:
                                st.markdown(f"- **{title}** -- *{src}*{age_str}")
                    else:
                        st.caption("Inga nyheter hittade de senaste 3 dagarna.")
        else:
            st.info("Lägg till aktier i bevakningslistan för att se nyheter.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 -- Kommande händelser
    # ══════════════════════════════════════════════════════════════════════
    with tab_events:
        st.subheader("📅 Kommande händelser")

        _scored_for_cal = df if not df.empty else _load_nth_latest_scored(n=1)
        _holdings_for_cal = holdings

        # ── Rapporter ─────────────────────────────────────────────────────
        col_port, col_top = st.columns(2)

        with col_port:
            st.markdown("##### 📊 Rapporter - innehav (30 dagar)")
            try:
                from core.earnings_calendar import upcoming_in_portfolio
                if not _holdings_for_cal.empty and not _scored_for_cal.empty:
                    port_cal = upcoming_in_portfolio(_holdings_for_cal, _scored_for_cal, days_ahead=30)
                    if not port_cal.empty:
                        _pc = port_cal[["ticker", "earnings_date", "days_until"]].copy()
                        _pc.columns = ["Ticker", "Datum", "Dagar kvar"]
                        clickable_stock_table(_pc, ticker_col="Ticker", context_df=_scored_for_cal,
                                             key="alerts_port_cal_table", caption="Klicka för analys.")
                        st.caption("⚠️ Var försiktig med köp precis innan rapport (gap-risk)")
                    else:
                        st.info("Inga rapporter de närmsta 30 dagarna.")
                else:
                    st.info("Lägg till innehav för att se kommande rapporter.")
            except Exception as _e:
                st.caption(f"Rapportkalender ej tillgänglig: {_e}")

        with col_top:
            st.markdown("##### 📊 Rapporter - topp-20 (14 dagar)")
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
                        clickable_stock_table(_tc, ticker_col="Ticker", context_df=_scored_for_cal,
                                             key="alerts_top_cal_table", caption="Klicka för analys.")
                    else:
                        st.info("Inga rapporter de närmsta 14 dagarna.")
                else:
                    st.info("Rapportkalendern uppdateras automatiskt när ny aktiedata finns tillgänglig.")
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
        st.markdown("##### 💰 Kommande utdelningar - innehav (60 dagar)")
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
                    clickable_stock_table(_dc, ticker_col="Ticker", context_df=_scored_for_cal,
                                         key="alerts_div_cal_table", caption="Klicka för analys.")
                else:
                    st.info("Inga utdelningar de närmsta 60 dagarna.")
            else:
                st.info("Lägg till innehav för att se kommande utdelningar.")
        except Exception as _e:
            st.caption(f"Utdelningskalender ej tillgänglig: {_e}")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 4 -- Bevakningslista Hälsokoll (Feature 3)
    # ══════════════════════════════════════════════════════════════════════
    with tab_watchlist:
        st.subheader("⭐ Bevakningslista - Hälsokoll")

        if not watchlist:
            st.info("Din bevakningslista är tom. Lägg till aktier via Bevakningslistan.")
        else:
            wl_alerts = _watchlist_health_check(watchlist, df, df_yesterday)

            # Highlight high-priority first
            high = [a for a in wl_alerts if a.get("priority") == "high"]
            medium = [a for a in wl_alerts if a.get("priority") == "medium"]

            if high:
                st.markdown("**Nya köpsignaler**")
                for a in high:
                    score_val = a.get("score") or 0
                    st.success(f"**{a['ticker']}** -- {a['name']} | Score: {score_val:.0f} | " + " | ".join(a["changes"]))

            if medium:
                st.markdown("**Förändrade signaler**")
                for a in medium:
                    score_val = a.get("score") or 0
                    st.warning(f"**{a['ticker']}** -- {a['name']} | Score: {score_val:.0f} | " + " | ".join(a["changes"]))

            # Full overview table
            st.markdown("---")
            st.markdown("**Alla bevakade aktier**")
            wl_tickers_list = [w.get("ticker", "") for w in watchlist]
            wl_data = df[df["ticker"].isin(wl_tickers_list)].copy() if not df.empty else pd.DataFrame()
            if not wl_data.empty:
                show_cols_wl = [c for c in ["ticker", "name", "score_total", "entry_signal", "trend_signal",
                                            "return_1m", "return_3m", "confidence_label"]
                                if c in wl_data.columns]
                if "score_total" in wl_data.columns:
                    wl_data = wl_data.sort_values("score_total", ascending=False)
                clickable_stock_table(wl_data[show_cols_wl].rename(columns={"ticker": "Ticker"}),
                                     ticker_col="Ticker", context_df=df,
                                     key="alerts_wl_health_table", caption="Klicka för analys.")
            else:
                st.info("Inga av dina bevakade aktier hittades i nuvarande scan.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 5 -- Insynsköp (Feature 7)
    # ══════════════════════════════════════════════════════════════════════
    with tab_insider:
        st.subheader("👔 Insynsköp - Signaler")
        st.caption("Aktier där insiders (VD, CFO, styrelse) nyligen köpt aktier eller har högt ägande.")
        with st.expander("ℹ️ Vad är insynsköp och varför spelar det roll? -- Förklaring för nybörjare", expanded=False):
            st.markdown("""
### 👔 Vad är ett insynsköp?
**Insiders** är personer med tillgång till icke-offentlig information om ett bolag --
t.ex. VD, CFO, styrelseledamöter och storägare (>=10% av aktierna).

När dessa personer **köper aktier i det egna bolaget** med egna pengar kallas det **insynsköp**.
Det måste rapporteras till Finansinspektionen (FI) inom 3 dagar.

### Varför är det intressant?
Insiders känner bolaget bättre än någon annan. Om VD:n köper aktier för egna pengar
är det ett starkt signalvärde att han/hon tror på bolagets framtid.

**Forskning visar** att aktier med stora insynsköp tenderar att prestera bättre
på 6-12 månaders sikt jämfört med börsen som helhet.

### ⚠️ Tolka med försiktighet
- **VD/CFO-köp** väger tyngre än passivt ägarskap
- **Klusterköp** (3+ insiders köper samtidigt) är starkaste signalen
- Insyns**sälj** är svagare signal -- de säljer av många skäl (skatt, privatekonomin)
- Kolla alltid bolaget i övrigt -- insynsköp är ett av flera verktyg

### 🩳 Hög blankningsandel (Short Squeeze)
**Blankning** = någon lånar aktier och säljer dem, hoppas köpa tillbaka billigare.
Hög blankningsandel (>10%) innebär att många satsar *mot* aktien.
Om aktien sedan stiger tvingas blankarna köpa tillbaka -> **short squeeze** -> kurs rusar ännu mer.
""")

        insider_df = _get_insider_alerts(df)
        if insider_df.empty:
            st.info("Inga insynssignaler hittades i nuvarande scan. Data uppdateras varje vecka.")
        else:
            n_exec = int((df.get("insider_executive_buy", pd.Series(dtype=bool)).fillna(False)).sum()) if "insider_executive_buy" in df.columns else 0
            n_cluster = int((df.get("insider_cluster", pd.Series(dtype=bool)).fillna(False)).sum()) if "insider_cluster" in df.columns else 0

            col1, col2, col3 = st.columns(3)
            col1.metric("VD/CFO-köp", n_exec)
            col2.metric("Klusterköp (3+)", n_cluster)
            col3.metric("Totalt insynssignaler", len(insider_df))

            st.markdown("---")
            clickable_stock_table(insider_df.rename(columns={"ticker": "Ticker"}),
                                  ticker_col="Ticker", context_df=df,
                                  key="alerts_insider_table", caption="Klicka på en aktie för full analys.")

            # Link to Finansinspektionen
            st.markdown("[Finansinspektionens Insynsregister](https://www.fi.se/sv/vara-register/insynsregistret/) -- officiell källa för svenska insynsaffärer")

        st.markdown("---")
        # Short squeeze opportunities
        st.markdown("**Hög blankningsandel (Short Squeeze-risk)**")
        if "short_pct_float" in df.columns:
            high_short = df[df["short_pct_float"].fillna(0) > 0.05].copy()  # >5% float shorted
            if not high_short.empty:
                show_short = [c for c in ["ticker", "name", "short_pct_float", "short_ratio", "score_total", "return_1m"]
                              if c in high_short.columns]
                high_short = high_short.copy()
                high_short["short_pct_float"] = (high_short["short_pct_float"] * 100).round(1)
                _hs_display = high_short[show_short].rename(columns={
                    "short_pct_float": "Blankat % av float",
                    "short_ratio": "Days to cover",
                    "ticker": "Ticker",
                }).sort_values("Blankat % av float", ascending=False).head(15)
                clickable_stock_table(_hs_display, ticker_col="Ticker", context_df=df,
                                      key="alerts_short_table", caption="Klicka för analys.")
            else:
                st.info("Inga aktier med hög blankningsandel (>5%) i nuvarande scan")
        else:
            st.info("Short-data ej tillgänglig i nuvarande scan")
