"""web/pages/paper_trading_page.py – Sida 13: Paper Trading"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def page_paper_trading():
    """Paper Trading Dashboard – track record, equity-kurva och positioner."""
    from portfolio.paper_trading import (
        _load, TRADES_FILE, PORTFOLIO_FILE,
        update_prices, calc_statistics,
        STOP_LOSS_PCT, TAKE_PROFIT_PCT, PARTIAL_PROFIT_PCT,
        TRAILING_DISTANCE, CLOSE_AFTER_WEEKS,
    )

    st.title("📄 Paper Trading – Track Record")

    trades = _load(TRADES_FILE)
    portfolio = _load(PORTFOLIO_FILE)

    if not trades:
        st.info("Inga trades registrerade ännu. Kör en scan för att generera köpsignaler.")
        return

    open_t  = [t for t in trades if t["status"] == "OPEN"]
    closed_t = [t for t in trades if t["status"] == "CLOSED"]

    # ── Uppdatera priser ────────────────────────────────────────────────────
    col_refresh, col_status = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Uppdatera priser", key="pt_refresh", type="primary", use_container_width=True):
            with st.spinner("Uppdaterar priser & kontrollerar stop-loss..."):
                result = update_prices(verbose=False)
                st.success(f"✅ {result['updated']} uppdaterade, {result['closed']} stängda")
                st.rerun()
    with col_status:
        st.caption(f"Öppna: {len(open_t)} · Stängda: {len(closed_t)} · Totalt: {len(trades)}")

    stats   = calc_statistics()
    closed  = [t for t in trades if t["status"] == "CLOSED" and t.get("pnl_pct") is not None]
    open_pos = [t for t in trades if t["status"] == "OPEN"]

    # ══════════════════════════════════════════════════════════════════════════
    # KPI-METRICS (same style as AI Paper Trading)
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")

    if "n_trades" in stats:
        avg_pnl    = stats.get("avg_return_pct", 0) or 0
        win_rate   = stats.get("win_rate_pct", 0) or 0
        sharpe     = stats.get("sharpe")
        median_pnl = stats.get("median_return_pct", 0) or 0
        best       = stats.get("best_trade", {})
        worst      = stats.get("worst_trade", {})

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric(
                "Snitt/trade", f"{avg_pnl:+.1f}%",
                help="Genomsnittlig avkastning per stängd trade.",
            )
        with c2:
            st.metric("Median", f"{median_pnl:+.1f}%")
        with c3:
            st.metric(
                "Win rate", f"{win_rate:.0f}%",
                help="Andel vinnande trades av alla stängda.",
            )
        with c4:
            st.metric("Sharpe (år)", f"{sharpe:.2f}" if sharpe else "—")
        with c5:
            st.metric("Stängda trades", stats["n_trades"])

        # Bästa / sämsta
        c6, c7, c8 = st.columns(3)
        with c6:
            best_t = best.get("ticker", "—")
            best_p = best.get("pnl_pct", 0)
            st.metric("🏆 Bästa trade", best_t, f"{best_p:+.1f}%")
        with c7:
            worst_t = worst.get("ticker", "—")
            worst_p = worst.get("pnl_pct", 0)
            st.metric("💀 Sämsta trade", worst_t, f"{worst_p:+.1f}%")
        with c8:
            dca_count = stats.get("dca_trades", 0)
            st.metric("DCA-köp", dca_count, help="Antal genomförda DCA-köp.")
    else:
        st.info("Inga stängda positioner ännu – statistik visas efter att positioner stängs.")

    # ══════════════════════════════════════════════════════════════════════════
    # EQUITY CURVE (prominent, top of page)
    # ══════════════════════════════════════════════════════════════════════════
    if "n_weeks" in stats and stats["n_weeks"] > 0:
        st.markdown("---")
        weekly_rets = stats.get("weekly_rets", [])
        if weekly_rets:
            equity = [100.0]
            for r in weekly_rets:
                equity.append(equity[-1] * (1 + r / 100))

            bench = [100.0 * (1.0013 ** i) for i in range(len(equity))]

            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=list(range(len(equity))),
                y=equity,
                mode="lines",
                name="Paper Trading",
                line=dict(color="#00d4aa", width=2.5),
                fill="tozeroy",
                fillcolor="rgba(0,212,170,0.1)",
            ))
            fig_eq.add_trace(go.Scatter(
                x=list(range(len(equity))),
                y=bench,
                mode="lines",
                name="7% år (benchmark)",
                line=dict(color="#64748b", width=1.5, dash="dash"),
            ))
            fig_eq.update_layout(
                title="Equity curve (100 = start)",
                template="plotly_dark",
                paper_bgcolor="#131722",
                plot_bgcolor="#1e2230",
                height=320,
                margin=dict(t=40, b=16, l=16, r=16),
                yaxis_title="Ackumulerad avkastning",
                hovermode="x unified",
                legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            )
            st.plotly_chart(fig_eq, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # ÖPPNA POSITIONER (expandable)
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander(f"📋 Öppna positioner ({len(open_pos)})", expanded=len(open_pos) > 0 and len(open_pos) <= 15):
        if not open_pos:
            st.caption("Inga öppna positioner.")
        else:
            rows = []
            for t in sorted(open_pos, key=lambda x: x.get("pnl_pct", 0) or 0, reverse=True):
                pnl  = t.get("pnl_pct", 0) or 0
                sl   = t.get("stop_loss", 0)
                tp   = t.get("take_profit", 0)
                trail = t.get("trailing_stop")
                rows.append({
                    "Ticker": t["ticker"],
                    "Vecka":  t.get("week", "—"),
                    "Köp":    f"{t['buy_price']:.2f}",
                    "Senast": f"{t.get('current_price', 0):.2f}",
                    "P&L %":  f"{pnl:+.1f}%",
                    "SL":     f"{sl:.2f}" if sl else "—",
                    "TP":     f"{tp:.2f}" if tp else "—",
                    "Trail":  f"{trail:.2f}" if trail else "—",
                    "DCA":    t.get("dca_count", 0),
                })
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                height=min(400, 60 + len(rows) * 36),
            )

    # ══════════════════════════════════════════════════════════════════════════
    # STÄNGDA POSITIONER (expandable)
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander(f"✅ Stängda positioner ({len(closed)})", expanded=False):
        if not closed:
            st.caption("Inga stängda positioner.")
        else:
            rows_c = []
            for t in sorted(closed, key=lambda x: x.get("sell_date", ""), reverse=True)[:50]:
                pnl    = t.get("pnl_pct", 0) or 0
                reason = t.get("exit_reason", "—") or "—"
                rows_c.append({
                    "Ticker": t["ticker"],
                    "Vecka":  t.get("week", "—"),
                    "Köp":    f"{t['buy_price']:.2f}",
                    "Sälj":   f"{t.get('sell_price', 0):.2f}",
                    "P&L %":  f"{pnl:+.1f}%",
                    "Exit":   reason.replace("_", " "),
                    "Datum":  t.get("sell_date", "—"),
                })
            st.dataframe(
                pd.DataFrame(rows_c),
                use_container_width=True,
                hide_index=True,
                height=min(400, 60 + len(rows_c) * 36),
            )

    # ══════════════════════════════════════════════════════════════════════════
    # DIAGRAM (sida vid sida)
    # ══════════════════════════════════════════════════════════════════════════
    if closed:
        st.markdown("---")
        col_chart1, col_chart2 = st.columns(2)

        # ── Exit-reason fördelning ──────────────────────────────────────────
        with col_chart1:
            exit_reasons = stats.get("exit_reasons", {})
            if exit_reasons:
                st.subheader("🧩 Exit-anledningar")
                labels_map = {
                    f"stop_loss_{STOP_LOSS_PCT:.0f}%":       f"🚫 Stop-loss ({STOP_LOSS_PCT:.0f}%)",
                    f"take_profit_{TAKE_PROFIT_PCT:.0f}%":   f"✅ Take-profit ({TAKE_PROFIT_PCT:.0f}%)",
                    f"partial_{PARTIAL_PROFIT_PCT:.0f}%":    f"🔶 Delvinst ({PARTIAL_PROFIT_PCT:.0f}%)",
                    f"trailing_stop_{TRAILING_DISTANCE:.0f}%": f"🔻 Trailing stop ({TRAILING_DISTANCE:.0f}%)",
                    "ai_stop_loss":                           "🤖 AI stop-loss",
                    f"time_{CLOSE_AFTER_WEEKS}w":             f"⏰ Tidsgräns ({CLOSE_AFTER_WEEKS}v)",
                    "manual_close_all":                       "👤 Manuell",
                }
                fig_pie = go.Figure(data=[go.Pie(
                    labels=[labels_map.get(k, k) for k in exit_reasons],
                    values=list(exit_reasons.values()),
                    hole=0.4,
                    marker=dict(colors=["#ef5350","#4caf50","#ffc107","#ff7043","#ab47bc","#42a5f5","#78909c"]),
                    textinfo="label+percent",
                    textposition="outside",
                )])
                fig_pie.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#131722",
                    plot_bgcolor="#1e2230",
                    height=320,
                    margin=dict(t=24, b=16, l=16, r=16),
                    showlegend=False,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        # ── P&L-histogram ──────────────────────────────────────────────────
        with col_chart2:
            rets = [t["pnl_pct"] for t in closed if t.get("pnl_pct") is not None]
            if rets:
                st.subheader("📊 P&L-fördelning")
                fig_hist = px.histogram(
                    x=rets, nbins=20,
                    color_discrete_sequence=["#42a5f5"],
                    labels={"x": "P&L %", "count": "Antal trades"},
                    template="plotly_dark",
                )
                fig_hist.add_vline(x=0, line_dash="dash", line_color="#ef5350")
                fig_hist.update_layout(
                    paper_bgcolor="#131722",
                    plot_bgcolor="#1e2230",
                    height=320,
                    margin=dict(t=24, b=16, l=16, r=16),
                )
                fig_hist.update_traces(
                    marker_color=["#4caf50" if v > 0 else "#ef5350" for v in rets]
                )
                st.plotly_chart(fig_hist, use_container_width=True)

    # ── Exit per vecka (staplad) ─────────────────────────────────────────────
    if closed and len(closed) >= 5:
        st.markdown("---")
        st.subheader("📊 Exit-anledning per vecka")
        weekly_exits: dict = {}
        for t in closed:
            w = t.get("week", "?")
            reason = t.get("exit_reason", "unknown") or "unknown"
            if "profit" in reason:
                cat = "✅ Vinst"
            elif "stop" in reason or "loss" in reason:
                cat = "🚫 Stop-loss"
            elif "partial" in reason:
                cat = "🔶 Delvinst"
            elif "time" in reason:
                cat = "⏰ Tidsgräns"
            else:
                cat = "📋 Övrigt"
            weekly_exits.setdefault(w, {})
            weekly_exits[w][cat] = weekly_exits[w].get(cat, 0) + 1

        if weekly_exits:
            df_weekly = pd.DataFrame(weekly_exits).fillna(0).T
            colors_map = {
                "✅ Vinst":     "#4caf50",
                "🚫 Stop-loss": "#ef5350",
                "🔶 Delvinst":  "#ffc107",
                "⏰ Tidsgräns": "#42a5f5",
                "📋 Övrigt":   "#78909c",
            }
            fig_w = go.Figure()
            for cat in df_weekly.columns:
                fig_w.add_trace(go.Bar(
                    name=cat,
                    x=df_weekly.index,
                    y=df_weekly[cat],
                    marker_color=colors_map.get(cat, "#78909c"),
                ))
            fig_w.update_layout(
                barmode="stack",
                template="plotly_dark",
                paper_bgcolor="#131722",
                plot_bgcolor="#1e2230",
                height=320,
                margin=dict(t=24, b=16, l=16, r=16),
                legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
            )
            st.plotly_chart(fig_w, use_container_width=True)

    # ── DCA-statistik ────────────────────────────────────────────────────────
    dca_count = stats.get("dca_trades", 0)
    dca_avg   = stats.get("dca_avg_pnl")
    if dca_count > 0:
        st.markdown("---")
        st.subheader("💰 DCA-statistik")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.metric("DCA-köp utförda", dca_count)
        with col_d2:
            st.metric("Snitt P&L efter DCA", f"{dca_avg:+.1f}%" if dca_avg else "—")
