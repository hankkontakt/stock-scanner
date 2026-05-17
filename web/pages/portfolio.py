"""web/pages/portfolio.py – Sida 4: Portfölj"""

import pandas as pd
import streamlit as st

from web.utils import (
    kpi_row, holdings_pie, num_fmt, pct_fmt,
    load_portfolio, load_watchlist, _get_provider, _get_depth,
)
from core import ai_analysis


def _save_watchlist_data(items):
    from web.pages.admin import _save_watchlist_data as _swd
    _swd(items)


def page_portfolio(df: pd.DataFrame, holdings: pd.DataFrame, watchlist: list,
                   sc_df: pd.DataFrame = None):
    st.title("💼 Portfölj & Bevakningslista")

    if holdings.empty:
        st.info("Ingen portföljdata. Lägg till innehav i `data/holdings.csv`.")
    else:
        frames = [f for f in [df, sc_df] if f is not None and not f.empty and "ticker" in f.columns]
        if frames:
            combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ticker", keep="first")
            score_data = combined.set_index("ticker").to_dict("index")
        else:
            score_data = {}

        rows = []
        for _, h in holdings.iterrows():
            t     = str(h["ticker"]).upper()
            sc    = score_data.get(t, {})
            price = sc.get("current_price")
            cost  = h.get("cost_basis")
            shares = h.get("shares", 0)
            pnl_pct = ((price / float(cost)) - 1) * 100 \
                if price and cost and float(cost) > 0 else None
            mv = price * float(shares) if price and shares else None
            rows.append({
                "Ticker":    t,
                "Bolag":     sc.get("name", t)[:30],
                "Sektor":    sc.get("sector", "—"),
                "Antal":     shares,
                "Inköpspris": cost,
                "Pris nu":   f"{price:.2f}" if price else "—",
                "P&L %":     f"{pnl_pct:+.1f}%" if pnl_pct is not None else "—",
                "Marknadsvärde": f"{mv:,.0f}" if mv else "—",
                "Score":     sc.get("score_total"),
                "Entry":     sc.get("entry_signal", "—"),
                "Trend":     sc.get("trend_signal", "—"),
                "Piotroski": sc.get("piotroski_f"),
                "RS":        sc.get("rs_label", "—"),
            })

        port_df = pd.DataFrame(rows)

        total_mv   = sum(float(r["Marknadsvärde"].replace(",", "").replace(" ", ""))
                        for r in rows if isinstance(r["Marknadsvärde"], str)
                        and r["Marknadsvärde"] != "—") if rows else 0
        pnl_vals   = [float(r["P&L %"].replace("%", "").replace("+", ""))
                      for r in rows if r["P&L %"] not in ("—", None)]
        avg_pnl    = sum(pnl_vals) / len(pnl_vals) if pnl_vals else 0
        best       = max(pnl_vals) if pnl_vals else 0
        worst      = min(pnl_vals) if pnl_vals else 0

        kpi_row([
            ("Positioner",       f"{len(rows)}",            None,
             "Antal aktier du för närvarande äger i din portfölj."),
            ("Totalt värde",     f"{total_mv:,.0f} kr",     None,
             "Totalt marknadsvärde av alla dina innehav baserat på senaste kurs."),
            ("Snitt P&L",        f"{avg_pnl:+.1f}%",        None,
             "Genomsnittlig vinst/förlust (Profit & Loss) för alla positioner sedan inköp. Positivt = portföljen är på plus totalt."),
            ("Bäst / Sämst",     f"+{best:.1f}% / {worst:.1f}%", None,
             "Din bästa respektive sämsta position i procent. Bra för att identifiera vinnare och förlorare i portföljen."),
        ])

        col_cfg = {}
        if "Score" in port_df.columns:
            col_cfg["Score"] = st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f"
            )
        st.dataframe(port_df, use_container_width=True, hide_index=True,
                     column_config=col_cfg)

        st.markdown("---")
        st.subheader("💡 Rekommendationer (baserat på senaste scan)")
        for r in sorted(rows, key=lambda x: x.get("Score") or 0, reverse=True):
            t  = r["Ticker"]
            sc = score_data.get(t, {})
            if not sc:
                st.markdown(f"⚪ **`{t}`** — Ej i senaste scan (kör en ny scanning för att få rekommendation)")
                continue
            entry = sc.get("entry_signal", "—")
            score = sc.get("score_total", 0) or 0
            if score >= 70 and entry == "STARK":
                icon = "🟢"; rec = "BEHÅLL STARKT / KÖP MER"
            elif score >= 55:
                icon = "🔵"; rec = "BEHÅLL"
            elif score >= 40:
                icon = "🟡"; rec = "BEVAKA"
            else:
                icon = "🔴"; rec = "MINSKA / SÄLJ"
            st.markdown(f"{icon} **`{t}`** — {rec} (score {score:.0f})")

        if len(rows) > 1:
            st.markdown("---")
            st.plotly_chart(holdings_pie(pd.DataFrame(rows).rename(columns={"Sektor": "sector"})),
                            use_container_width=True)

    # ── AI Portfolio Optimizer button (Feature 4) ──────────────────────────
    if not holdings.empty:
        st.markdown("---")
        st.subheader("🤖 AI-portföljoptimering")
        st.caption("Få AI-analys av din portfölj med förslag")
        if st.button("🤖 Analysera portfölj med AI", key="btn_portfolio_ai",
                     use_container_width=True, type="primary"):
            provider = _get_provider()
            depth = _get_depth()
            with st.spinner("Analyserar portfölj..."):
                try:
                    result = ai_analysis.analyze_portfolio(
                        holdings, df=df if not df.empty else None,
                        provider=provider,
                        depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")

    # ── Dividend-kalender ───────────────────────────────────────────────────
    if not holdings.empty and "ticker" in holdings.columns:
        st.markdown("---")
        st.subheader("💰 Kommande utdelningar")
        st.caption("Estimerade nästa utdelningsdatum för dina innehav (baseras på historisk frekvens).")
        _div_days = st.slider("Visa inom (dagar)", 30, 180, 90, 30, key="div_days")
        if st.button("🔄 Hämta utdelningsdata", key="btn_div_cal", use_container_width=True):
            with st.spinner("Hämtar utdelningshistorik..."):
                try:
                    from core.dividend_calendar import get_upcoming_dividends
                    _tickers = holdings["ticker"].str.strip().str.upper().tolist()
                    _div_df = get_upcoming_dividends(_tickers, days_ahead=_div_days)
                    st.session_state["div_cal"] = _div_df
                except Exception as e:
                    st.error(f"Kunde inte hämta utdelningsdata: {e}")

        _div_result = st.session_state.get("div_cal")
        if _div_result is not None:
            if _div_result.empty:
                st.info(f"Inga förväntade utdelningar inom {_div_days} dagar.")
            else:
                def _urgency(d):
                    if d <= 7:   return "🔴"
                    if d <= 21:  return "🟡"
                    return "🟢"
                _div_result = _div_result.copy()
                _div_result["Kvar"] = _div_result["days_until"].apply(
                    lambda d: f"{_urgency(d)} {d}d")
                _div_result["Yield"] = _div_result["yield_pct"].apply(
                    lambda v: f"{v:.1f}%" if v and not pd.isna(v) else "—")
                _div_show = _div_result[["ticker", "name", "next_div", "Kvar",
                                         "amount", "Yield", "frequency"]].copy()
                _div_show.columns = ["Ticker", "Bolag", "Datum", "Kvar",
                                     "Belopp", "Årsyield", "Frekvens"]
                st.dataframe(_div_show, use_container_width=True, hide_index=True)
                st.caption("⚠️ Datum är estimat baserade på historisk frekvens — inte bekräftade.")

    # Bevakningslista
    st.markdown("---")
    st.subheader("⭐ Bevakningslista")
    if not watchlist:
        st.info("Bevakningslistan är tom. Redigera `data/watchlist.json`.")
    else:
        if not df.empty and "ticker" in df.columns:
            score_lu = df.set_index("ticker").to_dict("index")
        else:
            score_lu = {}

        wl_rows = []
        for item in watchlist:
            t  = item["ticker"]
            sc = score_lu.get(t, {})
            wl_rows.append({
                "Ticker":  t,
                "Bolag":   item.get("name", sc.get("name", t))[:28],
                "Sektor":  sc.get("sector", "—"),
                "Tillagd": item.get("added", "—"),
                "Score":   sc.get("score_total"),
                "Entry":   sc.get("entry_signal", "Ej scannad"),
                "Konf.":   sc.get("confidence_label", "—"),
                "Trend":   sc.get("trend_signal", "—"),
                "P/E":     num_fmt(sc.get("pe_trailing")),
                "P/B":     num_fmt(sc.get("price_to_book")),
                "ROE":     pct_fmt(sc.get("roe")),
            })

        wl_df   = pd.DataFrame(wl_rows)
        col_cfg = {}
        if "Score" in wl_df.columns:
            col_cfg["Score"] = st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f"
            )
        st.dataframe(wl_df, use_container_width=True, hide_index=True,
                     column_config=col_cfg)
