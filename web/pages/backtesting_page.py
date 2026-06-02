"""web/pages/backtesting_page.py - Sida 9: Backtesting"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime

from web.utils import kpi_row, _get_provider, _get_depth
from core import ai_analysis
from web.ui.components import clickable_stock_table


def page_backtesting():
    from web.ui.components import page_header
    page_header("Backtesting", "backtest", subtitle="Historisk simulering av momentum-strategin mot index.")

    with st.expander("ℹ️ Hur funkar backtesting? (klicka för att läsa)", expanded=False):
        st.markdown("""
### Vad är backtesting?

Backtesting är ett sätt att se hur en strategi *hade* fungerat historiskt --
vi reser "tillbaka i tid" och låtsas att vi handlade enligt modellens regler
för varje månad under den valda perioden.

### Hur fungerar den här modellen?

Varje månad gör systemet följande:

1. **Hämtar historisk prisdata** för alla aktier i universum (via Yahoo Finance)
2. **Beräknar teknisk momentum-score** för varje aktie baserat på data som *faktiskt
   var tillgänglig den dagen* -- ingen fusk med framtida data
   - 12-månaders momentum -- 40 %
   - 6-månaders momentum -- 30 %
   - 3-månaders momentum -- 20 %
   - Avstånd från 52-veckors-high -- 10 %
3. **Väljer topp-N aktier** (du styr antalet) och köper likaviktat
4. **Mäter avkastningen** tills nästa månadsskifte, sedan rebalanseras portföljen
5. **Jämför mot benchmark** (SPY = S&P 500, ^OMXS30 = svenska börsen)

### Varför ser siffrorna "för bra" ut?

Det finns tre inbyggda problem som blåser upp resultaten:

| Problem | Förklaring | Effekt |
|---------|------------|--------|
| **Survivorship bias** | Bara aktier som *finns kvar idag* ingår. Aktier som gick i konkurs eller avnoterades saknas. | Kan blåsa upp +5-15 % per år |
| **Momentum-only modell** | Scoringen bygger bara på pris -- inte fundamenta, insider, sentiment m.m. | Underpresterar jämfört med fulla modellen |
| **Transaktionskostnader** | 0,2 % per omsatt position är inkluderat, men spread, slippage och skatt saknas | Kan kosta ytterligare 0,5-1 % per år |

**Tumregel:** Ta det visade resultatet och dra av ~10-15 % per år för att få en
mer realistisk uppskattning av faktisk prestanda.

### Vad är de viktigaste nyckeltalen?

- **Sharpe ratio > 1.0** -- bra riskjusterad avkastning
- **Hit rate > 55 %** -- strategin slog index mer än hälften av månaderna
- **Max drawdown** -- hur mycket portföljen gick ned som värst (ju lägre desto bättre)
- **Alpha** -- meravkastning utöver benchmark (kan vara positiv av survivorship bias)

### Hur ska jag använda resultaten?

Använd backtestingen för att **jämföra varianter** (t.ex. topp-10 vs topp-20,
1 år vs 3 år) snarare än att ta de absoluta siffrorna bokstavligt.
Om modellen konsistent slår index i 60-70 % av perioderna är det ett bra tecken --
men garanterar ingenting om framtiden.
        """)

    st.warning("⚠️ **Tolkningsvarning:** Survivorship bias och förenklad scoring gör att siffrorna troligen är 10-15 %/år för höga. Se förklaringen ovan.")

    col_yr, col_top, col_bench, col_bench2, col_run = st.columns([1, 1, 1, 1, 1])
    with col_yr:
        years = st.number_input("År att testa", min_value=1, max_value=10, value=3, key="bt_years")
    with col_top:
        top_n = st.number_input("Top-N aktier", min_value=5, max_value=50, value=20, key="bt_top")
    with col_bench:
        bench = st.text_input("Benchmark 1", value="SPY", key="bt_bench", help="S&P 500 ETF (global referens)")
    with col_bench2:
        bench2 = st.text_input("Benchmark 2", value="^OMXS30", key="bt_bench2", help="Lämna tomt för att skippa. T.ex. ^OMXS30, QQQ")
    with col_run:
        run_bt = st.button("▶️ Kör backtest", type="primary", key="bt_run", use_container_width=True)

    if "bt_result" not in st.session_state:
        st.session_state["bt_result"] = None
    if "bt_result2" not in st.session_state:
        st.session_state["bt_result2"] = None

    if run_bt:
        with st.spinner(f"Kör backtest {int(years)} år, topp-{int(top_n)}... (kan ta 1-2 min)"):
            try:
                from backtesting.backtest import run_backtest
                from core import config
                tickers = config.UNIVERSE[:50]
                result = run_backtest(tickers=tickers, years=int(years), top_n=int(top_n), benchmark=str(bench), verbose=False)
                st.session_state["bt_result"] = result
                if bench2.strip() and bench2.strip() != bench.strip():
                    result2 = run_backtest(tickers=tickers, years=int(years), top_n=int(top_n), benchmark=str(bench2).strip(), verbose=False)
                    st.session_state["bt_result2"] = result2
                else:
                    st.session_state["bt_result2"] = None
            except Exception as e:
                st.error(f"Fel: {e}")

    result  = st.session_state.get("bt_result")
    result2 = st.session_state.get("bt_result2")
    b2_label = bench2.strip() if bench2.strip() else None

    if result and result.get("perioder", 0) > 0:
        kpi_row([
            ("📅 Perioder testade",  f"{result['perioder']} mån",                        f"{result['år_testat']} år",
             "Antal månader som backtestet täcker. Fler perioder ger mer statistisk säkerhet. Minst 24 perioder (2 år) rekommenderas för meningsfulla slutsatser."),
            ("📈 Kumulativ",          f"{result['kumulativ_avkastning']:+.1f}%",           f"{bench}: {result.get('kumulativ_benchmark', 0):+.1f}%",
             "Total avkastning under hela testperioden om du investerat 100 kr från start. OBS: Survivorship bias blåser upp siffran med +5-15 %/år -- ta den inte bokstavligt."),
            ("📊 Annualiserad",       f"{result['annualiserad_port']:+.1f}%/år",           f"Alpha: {result.get('alpha_annualiserad', 0) or 0:+.1f}%/år",
             "Genomsnittlig årsavkastning (geometriskt medelvärde). Alpha = meravkastning utöver benchmark. Högt alpha kan bero på survivorship bias snarare än riktig skicklighet."),
            ("🎯 Sharpe ratio",       f"{result['sharpe_ratio']:.2f}",                    ">1.0 = bra",
             "Riskjusterad avkastning: (avkastning − riskfri ränta) / volatilitet. >1.0 = bra, >1.5 = mycket bra, >2.0 = utmärkt. Beräknas mot riskfri ränta ~4 %/år. Tar inte hänsyn till survivorship bias."),
            ("✅ Hit rate",           f"{result.get('hit_rate_pct', 0):.0f}%",            ">50 % slår index",
             "Andel månader som modellen slog benchmark. 50 % = kasta krona/klave. >55 % = bra. >60 % = mycket bra. Det viktigaste nyckeltalet -- påverkas minst av survivorship bias."),
            ("💀 Max drawdown",       f"{result['max_drawdown_pct']:.1f}%",               None,
             "Värsta nedgång från toppnivå till bottennivå under testperioden. −20 % = portföljen tappade 20 % som värst innan den vände upp. Ju mer negativt, desto mer risk att du säljer i panik."),
        ])

        tab1, tab2, tab3 = st.tabs(["📈 Equity-kurva", "📋 Per period", "🤖 AI-analys"])

        with tab1:
            period_data = pd.DataFrame(result.get("period_details", []))
            if not period_data.empty:
                port_rets = period_data["portfolio_ret"].values / 100
                equity_port = [100.0]
                for r in port_rets:
                    equity_port.append(equity_port[-1] * (1 + r))
                labels = list(period_data["period"]) + [period_data["period"].iloc[-1]]

                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=labels, y=equity_port, mode="lines",
                    name="Modell (momentum top-N)",
                    line=dict(color="#00d4aa", width=2.5),
                    fill="tozeroy", fillcolor="rgba(0,212,170,0.08)",
                ))
                if "benchmark_ret" in period_data.columns:
                    bench_rets = period_data["benchmark_ret"].dropna().values / 100
                    if len(bench_rets) == len(port_rets):
                        eq_b = [100.0]
                        for r in bench_rets:
                            eq_b.append(eq_b[-1] * (1 + r))
                        fig_eq.add_trace(go.Scatter(
                            x=labels, y=eq_b, mode="lines", name=bench,
                            line=dict(color="#f59e0b", width=1.8, dash="dash"),
                        ))
                if result2 and result2.get("period_details"):
                    pd2 = pd.DataFrame(result2["period_details"])
                    if "benchmark_ret" in pd2.columns:
                        b2_rets = pd2["benchmark_ret"].dropna().values / 100
                        if len(b2_rets) > 0:
                            eq_b2 = [100.0]
                            for r in b2_rets:
                                eq_b2.append(eq_b2[-1] * (1 + r))
                            labels2 = list(pd2["period"]) + [pd2["period"].iloc[-1]]
                            fig_eq.add_trace(go.Scatter(
                                x=labels2, y=eq_b2, mode="lines",
                                name=b2_label or "Benchmark 2",
                                line=dict(color="#a78bfa", width=1.8, dash="dot"),
                            ))
                fig_eq.update_layout(
                    template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                    height=420, margin=dict(t=48, b=16, l=16, r=16),
                    hovermode="x unified",
                    legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center"),
                    title=dict(text="Kumulativ värdeutveckling (start = 100 kr)", font=dict(size=14)),
                    yaxis=dict(title="Portföljvärde (kr)"),
                    xaxis=dict(title="Period"),
                )
                st.plotly_chart(fig_eq, use_container_width=True)

                colors = ["#22c55e" if r >= 0 else "#ef4444" for r in period_data["portfolio_ret"]]
                fig_bar = go.Figure(go.Bar(
                    x=period_data["period"], y=period_data["portfolio_ret"],
                    marker_color=colors, name="Månadsavkastning %",
                ))
                if "benchmark_ret" in period_data.columns:
                    fig_bar.add_trace(go.Scatter(
                        x=period_data["period"], y=period_data["benchmark_ret"],
                        mode="lines", name=bench, line=dict(color="#f59e0b", width=1.5),
                    ))
                fig_bar.update_layout(
                    template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                    height=280, margin=dict(t=36, b=16, l=16, r=16),
                    title=dict(text="Månadsavkastning -- modell (staplar) vs benchmark (linje)", font=dict(size=13)),
                    yaxis=dict(title="%", zeroline=True, zerolinecolor="#64748b"),
                    legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center"),
                )
                st.plotly_chart(fig_bar, use_container_width=True)

                if result2 and result2.get("perioder", 0) > 0:
                    st.markdown("#### Jämförelse benchmarks")
                    cmp_data = {
                        "Metric": ["Kumulativ avkastning", "Annualiserad", "Sharpe", "Max drawdown"],
                        "Modell": [
                            f"{result['kumulativ_avkastning']:+.1f}%",
                            f"{result['annualiserad_port']:+.1f}%/år",
                            f"{result['sharpe_ratio']:.2f}",
                            f"{result['max_drawdown_pct']:.1f}%",
                        ],
                        bench: [
                            f"{result.get('kumulativ_benchmark', 0):+.1f}%",
                            f"{result.get('annualiserad_bench', 0) or 0:+.1f}%/år", "--", "--",
                        ],
                    }
                    if b2_label:
                        cmp_data[b2_label] = [
                            f"{result2.get('kumulativ_benchmark', 0):+.1f}%",
                            f"{result2.get('annualiserad_bench', 0) or 0:+.1f}%/år", "--", "--",
                        ]
                    st.dataframe(pd.DataFrame(cmp_data), use_container_width=True, hide_index=True)
            else:
                st.info("Inga perioder att visa. Kör backtestet igen.")

        with tab2:
            pd_data = pd.DataFrame(result.get("period_details", []))
            if not pd_data.empty:
                try:
                    st.dataframe(pd_data, use_container_width=True, hide_index=True, height=450)
                except Exception:
                    st.dataframe(pd_data, use_container_width=True, hide_index=True)
                st.caption("**portfolio_ret** = modellens månadsavkastning, **benchmark_ret** = benchmarkens, **alpha** = skillnaden")

        with tab3:
            pd_data = pd.DataFrame(result.get("period_details", []))
            if not pd_data.empty:
                st.download_button(
                    "📥 Ladda ner CSV",
                    data=pd_data.to_csv(index=False),
                    file_name=f"backtest_{datetime.now():%Y-%m-%d}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            st.markdown("---")
            st.subheader("🤖 AI-analys av backtestresultaten")

            _bt_context = {
                "annualiserad": result["annualiserad_port"],
                "sharpe": result["sharpe_ratio"],
                "hit_rate": result.get("hit_rate_pct"),
                "max_dd": result["max_drawdown_pct"],
                "alpha": result.get("alpha_annualiserad"),
                "benchmark": bench,
                "perioder": result.get("perioder"),
                "kumulativ": result.get("kumulativ_avkastning"),
                "top_n": int(top_n),
                "år": int(years),
            }

            _PRESET_QUESTIONS = [
                "Är den här strategin robust eller är siffrorna vilseledande?",
                "Vilka är de största riskerna med modellen?",
                "Hur ser Sharpe ratio och drawdown ut jämfört med indexfonder?",
                "Är hit rate och alpha statistiskt signifikanta eller kan det vara slump?",
                "Vad är det smartaste sättet att förbättra strategin?",
            ]

            if "bt_chat" not in st.session_state:
                st.session_state["bt_chat"] = []

            st.caption("Snabbfrågor -- klicka för att skicka:")
            _qcols = st.columns(3)
            for _qi, _qtext in enumerate(_PRESET_QUESTIONS):
                _qcol = _qcols[_qi % 3]
                _qlabel = (_qtext[:38] + "…") if len(_qtext) > 38 else _qtext
                if _qcol.button(_qlabel, key=f"bt_preset_{_qi}", use_container_width=True):
                    st.session_state["bt_chat_pending"] = _qtext

            _user_q = st.chat_input("Skriv en egen fråga om backtestresultaten…", key="bt_chat_input")
            if _user_q:
                st.session_state["bt_chat_pending"] = _user_q

            if "bt_chat_pending" in st.session_state:
                _q = st.session_state.pop("bt_chat_pending")
                st.session_state["bt_chat"].append({"role": "user", "content": _q})
                _system_note = "\n\nViktigt: Nämn begränsningarna (survivorship bias ~+5-15 %/år, momentum-only modell, transaktionskostnader). Svara kortfattat på svenska."
                with st.spinner("AI analyserar…"):
                    try:
                        _resp = ai_analysis.ai_chat(
                            _q + _system_note,
                            context=ai_analysis._safe_json(_bt_context, ensure_ascii=False),
                            provider=_get_provider(),
                            depth=_get_depth(),
                        )
                        st.session_state["bt_chat"].append({"role": "assistant", "content": _resp})
                    except Exception as _e:
                        st.session_state["bt_chat"].append({"role": "assistant", "content": f"❌ Fel: {_e}"})
                st.rerun()

            for _msg in st.session_state["bt_chat"]:
                with st.chat_message(_msg["role"]):
                    st.markdown(_msg["content"])

            if st.session_state.get("bt_chat"):
                if st.button("🗑️ Rensa chatt", key="bt_clear_chat"):
                    st.session_state["bt_chat"] = []
                    st.rerun()

    # ── Point-in-time backtest (snapshots) ──────────────────────────────────
    st.markdown("---")
    st.subheader("📸 Point-in-time Backtest (reella score-snapshots)")
    st.caption(
        "Backtestas mot de **faktiska score­rekommendationer** som systemet gav vid varje "
        "veckoscan -- ingen look-ahead bias eller rekonstruerad scoring. "
        "Historiken byggs upp löpande; ju fler vecko­scanningar som körts, desto mer data."
    )

    from backtesting.backtest_snapshots import list_snapshots, run_snapshot_backtest
    snaps = list_snapshots()
    st.metric("Tillgängliga snapshots", len(snaps),
              help=f"Senaste: {snaps[-1] if snaps else '--'}, Första: {snaps[0] if snaps else '--'}")

    if len(snaps) < 3:
        st.info(
            f"Bara {len(snaps)} snapshot(s) hittills. Backtesten byggs upp automatiskt varje gång "
            f"veckoscanen körs (varje lördag). Kom tillbaka om några veckor för meningsfull data."
        )
    else:
        col1, col2, col3 = st.columns(3)
        with col1:
            snap_top_n = st.number_input("Topp-N", min_value=3, max_value=30, value=10, key="snap_top_n")
        with col2:
            snap_hold = st.number_input("Hållperiod (dagar)", min_value=7, max_value=90, value=30, key="snap_hold")
        with col3:
            snap_bench = st.text_input("Benchmark", value="^OMXS30", key="snap_bench")

        if st.button("▶️ Kör point-in-time backtest", key="btn_snap_bt", type="primary"):
            with st.spinner("Hämtar priser och beräknar..."):
                snap_result = run_snapshot_backtest(
                    top_n=int(snap_top_n),
                    holding_days=int(snap_hold),
                    benchmark=snap_bench.strip(),
                    verbose=False,
                )

            if "error" in snap_result:
                st.error(snap_result["error"])
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Kumulativ avkastning", f"{snap_result['cum_return_pct']:+.1f}%")
                c2.metric("Sharpe (annualiserad)", f"{snap_result['sharpe']:.2f}")
                c3.metric("Max drawdown", f"{snap_result['max_drawdown']:.1f}%")
                c4.metric("Hit rate", f"{snap_result['hit_rate']:.0f}%",
                          help="% av perioder där portföljen slog benchmark")

                import plotly.graph_objects as go
                eq_df = pd.DataFrame(snap_result["equity_curve"])
                if not eq_df.empty:
                    fig = go.Figure(go.Scatter(
                        x=eq_df["date"], y=eq_df["equity"],
                        fill="toself", fillcolor="rgba(66,165,245,0.15)",
                        line=dict(color="#42a5f5", width=2),
                        name="Equity",
                    ))
                    fig.update_layout(
                        title="Equity-kurva (point-in-time backtest, 100k SEK start)",
                        template="plotly_dark",
                        paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                        height=320, margin=dict(t=44, b=16, l=16, r=16),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                per_df = pd.DataFrame(snap_result["periods"])
                if not per_df.empty:
                    with st.expander("📋 Per period"):
                        st.dataframe(per_df, use_container_width=True, hide_index=True)

    # ── A/B-test av faktorvikter ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚖️ A/B-test av faktorvikter")
    st.caption(
        "Jämför två viktuppsättningar mot historiska snapshots -- omviktar de lagrade "
        "faktorpoängen utan att hämta om data. Bra för att se om en viktändring hade lönat sig."
    )
    if len(snaps) < 3:
        st.info(f"Behöver >=3 snapshots för A/B-test (har {len(snaps)}).")
    else:
        from core.config import FACTOR_WEIGHTS as _FW
        _factor_keys = ["value", "quality", "momentum", "growth", "risk",
                        "dividend", "sentiment", "short_interest"]
        st.markdown("**Viktset B** (A = nuvarande config). Justera vikterna att testa mot:")
        cols = st.columns(4)
        weights_b = {}
        for i, k in enumerate(_factor_keys):
            with cols[i % 4]:
                weights_b[k] = st.number_input(
                    k, min_value=0.0, max_value=1.0,
                    value=float(round(_FW.get(k, 0.0), 3)), step=0.01,
                    key=f"ab_w_{k}",
                )
        _w_sum = sum(weights_b.values())
        _w_color = "green" if abs(_w_sum - 1.0) < 0.01 else "red"
        st.caption(f"Summa vikter B: :{_w_color}[{_w_sum:.3f}] (bör vara 1.0)")
        if st.button("⚖️ Kör A/B-test", key="btn_ab_test", type="primary"):
            from backtesting.backtest_snapshots import ab_test_weights
            with st.spinner("Backtestar båda viktseten..."):
                ab = ab_test_weights(
                    weights_a={k: float(_FW.get(k, 0.0)) for k in _factor_keys},
                    weights_b=weights_b,
                    top_n=10, holding_days=30,
                    label_a="Nuvarande", label_b="Test",
                )
            if "error" in ab:
                st.error(ab["error"])
            else:
                ca, cb = st.columns(2)
                for col, lbl in [(ca, "Nuvarande"), (cb, "Test")]:
                    r = ab.get(lbl, {})
                    with col:
                        st.markdown(f"**{lbl}**" + (" 🏆" if ab.get("winner") == lbl else ""))
                        st.metric("Kumulativ avk.", f"{r.get('cum_return_pct', 0):+.1f}%")
                        st.caption(f"Sharpe {r.get('sharpe', 0):.2f} * Win-rate {r.get('win_rate', 0):.0f}% * {r.get('n_periods', 0)} perioder")

    # ── Score-drift: top movers mellan senaste snapshots (P3.1) ──────────────
    st.markdown("---")
    st.subheader("📊 Score-rörelser (senaste två scans)")
    if len(snaps) < 2:
        st.info("Behöver >=2 snapshots för att visa score-rörelser.")
    else:
        from backtesting.backtest_snapshots import compare_snapshots
        diff = compare_snapshots(snaps[-2], snaps[-1], top_n=15, min_score_change=3.0)
        if "error" in diff:
            st.caption(diff["error"])
        else:
            st.caption(f"Jämför {snaps[-2]} -> {snaps[-1]}")
            cu, cd = st.columns(2)
            with cu:
                st.markdown("**⬆️ Största ökningar**")
                mu = pd.DataFrame(diff.get("movers_up", []))
                if not mu.empty:
                    _mu_disp = mu[["ticker", "score_total_a", "score_total_b", "score_delta"]].rename(columns={"ticker": "Ticker"})
                    clickable_stock_table(_mu_disp, ticker_col="Ticker", key="bt_movers_up_table",
                                         caption="Klicka för analys.")
            with cd:
                st.markdown("**⬇️ Största minskningar**")
                md = pd.DataFrame(diff.get("movers_down", []))
                if not md.empty:
                    _md_disp = md[["ticker", "score_total_a", "score_total_b", "score_delta"]].rename(columns={"ticker": "Ticker"})
                    clickable_stock_table(_md_disp, ticker_col="Ticker", key="bt_movers_dn_table",
                                         caption="Klicka för analys.")
            new_e = diff.get("new_entries", [])
            fallen = diff.get("fallen", [])
            if new_e:
                st.success("🆕 Nya i topp-15: " + ", ".join(f"{e['ticker']} ({e['score']:.0f})" for e in new_e[:10]))
            if fallen:
                st.warning("📉 Föll ur topp-15: " + ", ".join(f"{e['ticker']} ({e['score']:.0f})" for e in fallen[:10]))

    # ── Historisk replay: vad rekommenderade systemet då? (P3.2) ─────────────
    st.markdown("---")
    st.subheader("🕰️ Historisk replay -- vad rekommenderade systemet då?")
    if not snaps:
        st.info("Inga snapshots ännu.")
    else:
        from backtesting.backtest_snapshots import load_snapshot
        replay_date = st.selectbox("Välj datum", options=list(reversed(snaps)), key="replay_date")
        if replay_date:
            rsnap = load_snapshot(replay_date)
            if not rsnap.empty and "score_total" in rsnap.columns:
                top15 = rsnap.nlargest(15, "score_total")
                show_cols = [c for c in ["ticker", "name", "sector", "score_total", "entry_signal"]
                             if c in top15.columns]
                st.caption(f"Systemets topp-15 den {replay_date}:")
                _replay_disp = top15[show_cols].rename(columns={"ticker": "Ticker"})
                clickable_stock_table(_replay_disp, ticker_col="Ticker", key="bt_replay_table",
                                      caption="Klicka för analys.")
