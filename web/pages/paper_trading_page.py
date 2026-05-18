"""web/pages/paper_trading_page.py – Sida 13: Paper Trading"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from web.utils import kpi_row, _apply_chart_style


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _compute_equity_data(trades: list) -> "dict | None":
    """
    Compute portfolio equity from raw trades list.

    Returns:
        initial_capital  – total capital deployed (sum of trade capitals)
        current_equity   – current total value (unrealised + realised)
        total_return_pct – (current / initial - 1) × 100
        equity_curve     – list of {"week": str, "equity": float} sorted by week
    """
    if not trades:
        return None

    by_week: dict[str, dict] = {}
    total_invested = 0.0
    total_current  = 0.0

    for t in trades:
        capital  = float(t.get("capital", 0) or 0)
        pnl_pct  = float(t.get("pnl_pct",  0) or 0)
        week     = t.get("week", "?")
        current  = capital * (1 + pnl_pct / 100)

        if week not in by_week:
            by_week[week] = {"invested": 0.0, "current": 0.0}
        by_week[week]["invested"] += capital
        by_week[week]["current"]  += current

        total_invested += capital
        total_current  += current

    if total_invested == 0:
        return None

    # Build cumulative equity curve (one point per week, sorted)
    sorted_weeks = sorted(by_week.keys())
    cum_equity   = 0.0
    equity_curve = []
    for w in sorted_weeks:
        cum_equity += by_week[w]["current"]
        equity_curve.append({"week": w, "equity": round(cum_equity, 2)})

    return {
        "initial_capital":  round(total_invested, 2),
        "current_equity":   round(total_current, 2),
        "total_return_pct": round((total_current / total_invested - 1) * 100, 2),
        "equity_curve":     equity_curve,
        "n_weeks":          len(sorted_weeks),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────────────────────────

def page_paper_trading():
    """Paper Trading Dashboard – track record, equity-kurva och positioner."""
    from portfolio.paper_trading import (
        _load, TRADES_FILE,
        update_prices, calc_statistics,
        STOP_LOSS_PCT, TAKE_PROFIT_PCT, PARTIAL_PROFIT_PCT,
        TRAILING_DISTANCE, CLOSE_AFTER_WEEKS,
    )

    st.title("📄 Paper Trading – Track Record")

    trades   = _load(TRADES_FILE)

    if not trades:
        st.info("Inga trades registrerade ännu. Kör en scan för att generera köpsignaler.")
        return

    open_t   = [t for t in trades if t["status"] == "OPEN"]
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

    st.markdown("---")

    # ── Compute equity ───────────────────────────────────────────────────────
    equity_data = _compute_equity_data(trades)
    stats       = calc_statistics()
    closed      = [t for t in trades if t["status"] == "CLOSED" and t.get("pnl_pct") is not None]
    open_pos    = [t for t in trades if t["status"] == "OPEN"]

    # ══════════════════════════════════════════════════════════════════════════
    # TOP KPI ROW  (always visible as long as there are trades)
    # ══════════════════════════════════════════════════════════════════════════
    if equity_data:
        eq_kr  = equity_data["current_equity"]
        ret_pct = equity_data["total_return_pct"]
        hit_rate = stats.get("win_rate_pct")
        hit_str  = f"{hit_rate:.0f}%" if hit_rate is not None else "—"

        kpi_row([
            ("Equity",           f"{eq_kr:,.0f} kr",          f"Insatt: {equity_data['initial_capital']:,.0f} kr",
             "Simulerat totalt portföljvärde (insatt kapital + orealiserad/realiserad P&L)."),
            ("Avkastning",       f"{ret_pct:+.2f}%",           None,
             "Total avkastning sedan start, viktad över alla veckor och positioner."),
            ("Trades",           str(len(trades)),              f"Veckor: {equity_data['n_weeks']}",
             "Totalt antal registrerade positioner (öppna + stängda)."),
            ("Öppna",            str(len(open_pos)),            None,
             "Antal aktiva positioner som fortfarande är öppna."),
            ("Hit-rate",         hit_str,                       ">50% slår benchmark",
             "Andel stängda positioner med positiv avkastning. Beräknas när positioner börjar stängas."),
        ])

    # ══════════════════════════════════════════════════════════════════════════
    # EQUITY CURVE  (always visible)
    # ══════════════════════════════════════════════════════════════════════════
    if equity_data and equity_data["equity_curve"]:
        eq_curve = equity_data["equity_curve"]
        dates_x  = [p["week"] for p in eq_curve]
        vals_y   = [p["equity"] for p in eq_curve]

        # Append "Idag" point with live current equity (same as last point unless
        # intraday prices moved since the last week entry was recorded)
        import datetime
        today_str = datetime.date.today().isoformat()
        if dates_x[-1] != today_str:
            dates_x.append(today_str)
            vals_y.append(equity_data["current_equity"])

        # Benchmark line: 7 % per year flat
        n_pts   = len(vals_y)
        initial = equity_data["initial_capital"] / equity_data["n_weeks"]  # per-week capital
        bench   = [initial * (1.0 + 0.07 / 52) ** i for i in range(n_pts)]

        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=dates_x, y=vals_y,
            mode="lines+markers",
            name="Paper Trading",
            line=dict(color="#00d4aa", width=2.5),
            marker=dict(size=6),
            fill="tozeroy",
            fillcolor="rgba(0,212,170,0.10)",
        ))
        fig_eq.add_trace(go.Scatter(
            x=dates_x, y=bench,
            mode="lines",
            name="7 %/år (benchmark)",
            line=dict(color="#64748b", width=1.5, dash="dash"),
        ))
        fig_eq.update_layout(
            title="Equity curve – Paper Trading",
            template="plotly_dark",
            paper_bgcolor="#131722",
            plot_bgcolor="#1e2230",
            height=320,
            margin=dict(t=48, b=16, l=16, r=16),
            yaxis_title="Portföljvärde (kr)",
            hovermode="x unified",
            legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
        )
        _apply_chart_style(fig_eq)
        st.plotly_chart(fig_eq, use_container_width=True)

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # ÖPPNA POSITIONER – summary metrics + tabell
    # ══════════════════════════════════════════════════════════════════════════
    if open_pos:
        pnls        = [t.get("pnl_pct", 0) or 0 for t in open_pos]
        pnl_pos     = sum(1 for p in pnls if p > 0)
        pnl_neg     = sum(1 for p in pnls if p <= 0)
        avg_pnl_open = sum(pnls) / len(pnls) if pnls else 0

        kpi_row([
            ("Öppna positioner",   str(len(open_pos)),          None, None),
            ("Snitt P&L (öppna)", f"{avg_pnl_open:+.1f}%",     None,
             "Genomsnittlig orealiserad avkastning för öppna positioner just nu."),
            ("🟢 I vinst",         str(pnl_pos),                None, None),
            ("🔴 Med förlust",     str(pnl_neg),                None, None),
        ])
        st.markdown("")

    with st.expander(f"📋 Öppna positioner ({len(open_pos)})", expanded=len(open_pos) > 0 and len(closed) == 0):
        if not open_pos:
            st.caption("Inga öppna positioner.")
        else:
            rows = []
            for t in sorted(open_pos, key=lambda x: x.get("pnl_pct", 0) or 0, reverse=True):
                pnl   = t.get("pnl_pct", 0) or 0
                sl    = t.get("stop_loss")
                tp    = t.get("take_profit")
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
    # STÄNGDA POSITIONER
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander(f"✅ Stängda positioner ({len(closed)})", expanded=False):
        if not closed:
            st.caption("Inga stängda positioner ännu.")
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
    # STATISTIK OCH DIAGRAM – visas när det finns stängda positioner
    # ══════════════════════════════════════════════════════════════════════════
    if "n_trades" in stats:
        st.markdown("---")

        avg_pnl    = stats.get("avg_return_pct", 0) or 0
        win_rate   = stats.get("win_rate_pct", 0) or 0
        sharpe     = stats.get("sharpe")
        median_pnl = stats.get("median_return_pct", 0) or 0
        best       = stats.get("best_trade", {})
        worst      = stats.get("worst_trade", {})

        kpi_row([
            ("Snitt/trade",    f"{avg_pnl:+.1f}%",     None,
             "Genomsnittlig avkastning per stängd trade."),
            ("Median",         f"{median_pnl:+.1f}%",  None, None),
            ("Win rate",       f"{win_rate:.0f}%",      ">50% = lönsamt",
             "Andel vinnande trades av alla stängda."),
            ("Sharpe (år)",    f"{sharpe:.2f}" if sharpe else "—", None,
             "Riskjusterad årsavkastning. >1.0 = bra."),
            ("Stängda trades", str(stats["n_trades"]), None, None),
        ])

        st.markdown("")

        # Bästa / sämsta
        col_b, col_w, col_dca = st.columns(3)
        with col_b:
            best_t = best.get("ticker", "—")
            best_p = best.get("pnl_pct", 0)
            st.metric("🏆 Bästa trade", best_t, f"{best_p:+.1f}%")
        with col_w:
            worst_t = worst.get("ticker", "—")
            worst_p = worst.get("pnl_pct", 0)
            st.metric("💀 Sämsta trade", worst_t, f"{worst_p:+.1f}%")
        with col_dca:
            dca_count = stats.get("dca_trades", 0)
            st.metric("DCA-köp", dca_count, help="Antal genomförda DCA-köp.")

        st.markdown("---")

        # ── Diagram sida vid sida ────────────────────────────────────────────
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            exit_reasons = stats.get("exit_reasons", {})
            if exit_reasons:
                st.subheader("🧩 Exit-anledningar")
                labels_map = {
                    f"stop_loss_{STOP_LOSS_PCT:.0f}%":           f"🚫 Stop-loss ({STOP_LOSS_PCT:.0f}%)",
                    f"take_profit_{TAKE_PROFIT_PCT:.0f}%":       f"✅ Take-profit ({TAKE_PROFIT_PCT:.0f}%)",
                    f"partial_{PARTIAL_PROFIT_PCT:.0f}%":        f"🔶 Delvinst ({PARTIAL_PROFIT_PCT:.0f}%)",
                    f"trailing_stop_{TRAILING_DISTANCE:.0f}%":   f"🔻 Trailing stop ({TRAILING_DISTANCE:.0f}%)",
                    "ai_stop_loss":                              "🤖 AI stop-loss",
                    f"time_{CLOSE_AFTER_WEEKS}w":                f"⏰ Tidsgräns ({CLOSE_AFTER_WEEKS}v)",
                    "manual_close_all":                          "👤 Manuell",
                }
                fig_pie = go.Figure(data=[go.Pie(
                    labels=[labels_map.get(k, k) for k in exit_reasons],
                    values=list(exit_reasons.values()),
                    hole=0.4,
                    marker=dict(colors=["#ef5350", "#4caf50", "#ffc107", "#ff7043",
                                        "#ab47bc", "#42a5f5", "#78909c"]),
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
                _apply_chart_style(fig_pie)
                st.plotly_chart(fig_pie, use_container_width=True)

        with col_chart2:
            rets = [t["pnl_pct"] for t in closed if t.get("pnl_pct") is not None]
            if rets:
                st.subheader("📊 P&L-fördelning")
                colors_hist = ["#4caf50" if v >= 0 else "#ef5350" for v in rets]
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
                fig_hist.update_traces(marker_color=colors_hist)
                _apply_chart_style(fig_hist)
                st.plotly_chart(fig_hist, use_container_width=True)

    # ── Exit per vecka ───────────────────────────────────────────────────────
    if closed and len(closed) >= 5:
        st.markdown("---")
        st.subheader("📊 Exit-anledning per vecka")
        weekly_exits: dict = {}
        for t in closed:
            w      = t.get("week", "?")
            reason = t.get("exit_reason", "unknown") or "unknown"
            cat = ("✅ Vinst"     if "profit" in reason else
                   "🚫 Stop-loss" if ("stop" in reason or "loss" in reason) else
                   "🔶 Delvinst"  if "partial" in reason else
                   "⏰ Tidsgräns" if "time" in reason else
                   "📋 Övrigt")
            weekly_exits.setdefault(w, {})
            weekly_exits[w][cat] = weekly_exits[w].get(cat, 0) + 1

        if weekly_exits:
            df_weekly   = pd.DataFrame(weekly_exits).fillna(0).T
            colors_map  = {
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
            _apply_chart_style(fig_w)
            st.plotly_chart(fig_w, use_container_width=True)

    # ── DCA-statistik ────────────────────────────────────────────────────────
    dca_count = stats.get("dca_trades", 0)
    dca_avg   = stats.get("dca_avg_pnl")
    if dca_count and dca_count > 0:
        st.markdown("---")
        st.subheader("💰 DCA-statistik")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.metric("DCA-köp utförda", dca_count)
        with col_d2:
            st.metric("Snitt P&L efter DCA", f"{dca_avg:+.1f}%" if dca_avg else "—")
