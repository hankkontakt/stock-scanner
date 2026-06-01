"""web/pages/ml_paper_trading.py – Sida 14: AI Paper Trading"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from web.ui.components import clickable_stock_table


def page_ml_paper_trading():
    """Dashboard för ML-modellens paper trading (parallellt spår mot klassisk)."""
    from core import ml_paper_trading as mlpt
    try:
        from core.ml_predictor import load_model
    except Exception:
        load_model = lambda *_a, **_k: None  # noqa: E731

    st.title("🤖 AI Paper Trading")
    st.caption(
        "Separat track record för ML-modellens topp-10 prediktioner per dag. "
        "Klassisk paper trading körs orört parallellt — jämför dem för att se "
        "vilken som faktiskt levererar."
    )

    # ── Modellstatus ────────────────────────────────────────────────────────
    col_u, col_s = st.columns(2)
    for col, universe, label in [(col_u, "universe", "Universum (stora aktier)"),
                                 (col_s, "smallcap", "Småbolag (svenska)")]:
        with col:
            st.markdown(f"### {label}")
            m = load_model(universe) if callable(load_model) else None
            if m is None:
                st.warning(
                    f"Ingen modell tränad ännu för **{universe}**.\n\n"
                    "Träna via GitHub Actions: workflow **🤖 Train ML** (manuell trigger)."
                )
            else:
                mt = getattr(m, "test_metrics", {})
                st.success(
                    f"Modell tränad: **{getattr(m, 'trained_at', '?')[:10]}** · "
                    f"{getattr(m, 'n_rows', 0):,} rader · "
                    f"IC={mt.get('ic', '?')} · hit-rate={mt.get('hit_rate', '?')}"
                )

    st.markdown("---")

    # ── Sammanfattning + Equity-kurva per universum ─────────────────────────
    for universe, label in [("universe", "🌍 Universum"),
                            ("smallcap", "🇸🇪 Småbolag")]:
        st.markdown(f"## {label}")
        summary = mlpt.get_summary(universe)

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("Equity", f"{summary['equity']:,.0f} kr",
                      help="Simulerat kapital startande på 100 000 kr. Ökar/minskar baserat på AI-modellens predikterade köp och faktiska kursrörelser.")
        with c2:
            st.metric("Avkastning", f"{summary['total_return_pct']:+.2f}%",
                      help="Total avkastning sedan AI paper trading startade. Jämför med klassisk paper trading för att se om ML-modellen tillför värde.")
        with c3:
            st.metric("Trades", f"{summary['n_trades']}",
                      help="Totalt antal affärer (öppna + stängda) som AI-modellen har genererat sedan start.")
        with c4:
            st.metric("Öppna", f"{summary['n_open']}",
                      help="Antal aktiva positioner som fortfarande är öppna. Varje position stängs automatiskt efter 30 dagar.")
        with c5:
            hr = summary.get("hit_rate")
            st.metric("Hit-rate", f"{hr:.1f}%" if hr is not None else "—",
                      help="Andel stängda positioner med positiv avkastning. >50% = modellen prickar rätt mer än hälften av gångerna. >60% = utmärkt.")

        eq_df = mlpt.get_equity_curve_df(universe)
        if not eq_df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=eq_df["date"], y=eq_df["equity"],
                mode="lines+markers", name="ML equity",
                line=dict(color="#42a5f5", width=2),
                fill="tozeroy", fillcolor="rgba(66,165,245,0.1)",
            ))
            fig.update_layout(
                title=f"Equity curve – {label}",
                template="plotly_dark", paper_bgcolor="#131722",
                plot_bgcolor="#1e2230", height=300,
                margin=dict(t=40, b=16, l=16, r=16),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Ingen historik ännu — systemet börjar automatiskt registrera positioner varje vecka. Kom tillbaka om några dagar för att se hur det går.")

        # Öppna positioner
        open_df = mlpt.get_trades_df(universe, only_open=True)
        with st.expander(f"📋 Öppna positioner ({len(open_df)})", expanded=False):
            if open_df.empty:
                st.caption("Inga öppna positioner just nu.")
            else:
                clickable_stock_table(open_df, ticker_col="ticker",
                                      context_df=st.session_state.get("scored_df"),
                                      key=f"mlpt_open_{universe}", height=300)

        # Stängda
        all_df = mlpt.get_trades_df(universe, only_open=False)
        closed_df = all_df[all_df["exit_date"].notna()] if not all_df.empty and "exit_date" in all_df.columns else pd.DataFrame()
        with st.expander(f"✅ Stängda positioner ({len(closed_df)})", expanded=False):
            if closed_df.empty:
                st.caption("Inga stängda positioner ännu — positioner hålls i upp till 30 dagar innan de stängs automatiskt.")
            else:
                show = closed_df.copy()
                if "realized_return" in show.columns:
                    show["realized_return"] = (show["realized_return"] * 100).round(2)
                clickable_stock_table(show, ticker_col="ticker",
                                      context_df=st.session_state.get("scored_df"),
                                      key=f"mlpt_closed_{universe}", height=300)

        st.markdown("---")
