"""web/pages/portfolio.py – Sida 4: Portfölj"""

import os
import tempfile

import pandas as pd
import streamlit as st

from web.utils import (
    kpi_row, holdings_pie, num_fmt, pct_fmt,
    load_portfolio, load_watchlist, _get_provider, _get_depth,
    _active_data_dir,
)
from core import ai_analysis


def _save_watchlist_data(items):
    from web.pages.admin import _save_watchlist_data as _swd
    _swd(items)


def _save_holdings_user(df: pd.DataFrame):
    """Sparar holdings.csv i användarens datakatalog.
    För admin synkas till GitHub. För andra användare sparas lokalt OCH till GitHub
    (så att pipeline kan läsa data för personliga e-postutskick)."""
    username = st.session_state.get("username", "admin")
    if username == "admin":
        from web.pages.admin import _save_holdings_df
        _save_holdings_df(df)
    else:
        user_dir = _active_data_dir()
        user_dir.mkdir(parents=True, exist_ok=True)
        csv_content = df.to_csv(index=False)
        (user_dir / "holdings.csv").write_text(csv_content, encoding="utf-8")
        # Commit till GitHub så pipeline kan läsa data för personliga e-postutskick
        try:
            from web.pages.admin import _get_github_token, _github_commit_file
            token = _get_github_token()
            if token:
                _github_commit_file(
                    f"data/users/{username}/holdings.csv",
                    csv_content,
                    token,
                    message=f"Update portfolio for {username}",
                )
        except Exception:
            pass  # GitHub-sync misslyckades, men lokal sparning lyckades


def _upsert_holding(holdings: pd.DataFrame, ticker: str,
                    shares: float, cost_basis: float) -> pd.DataFrame:
    """Lägg till eller uppdatera en aktie i portföljen.
    Om tickern är ny läggs den automatiskt till i nästa scan (custom_universe)."""
    h = holdings.copy() if not holdings.empty else pd.DataFrame(
        columns=["ticker", "shares", "cost_basis"]
    )
    is_new = ticker not in (h["ticker"].values if not h.empty else [])
    if ticker in h["ticker"].values:
        h.loc[h["ticker"] == ticker, "shares"]     = shares
        h.loc[h["ticker"] == ticker, "cost_basis"] = cost_basis
    else:
        h = pd.concat([h, pd.DataFrame([{
            "ticker": ticker, "shares": shares, "cost_basis": cost_basis
        }])], ignore_index=True)
    # Auto-lägg till i scan-universum om det är en ny ticker
    if is_new:
        try:
            from core.config import add_custom_to_universe
            added = add_custom_to_universe(ticker)
            if added:
                st.session_state[f"scan_pending_{ticker}"] = True
        except Exception:
            pass
    return h


def _show_scan_pending_notifications():
    """Visar en blå infobox för tickers som lagts till i nästa scan."""
    pending = [
        k.replace("scan_pending_", "")
        for k, v in st.session_state.items()
        if k.startswith("scan_pending_") and v
    ]
    if pending:
        tickers_str = ", ".join(f"**{t}**" for t in pending)
        n = len(pending)
        st.info(
            f"⏳ {tickers_str} {'har lagts' if n == 1 else 'har lagts'} till i din portfölj! "
            "Detaljerad analys — som rekommendationer, score och signaler — "
            "uppdateras automatiskt inom några dagar när systemet kör sin nästa analys. "
            "Pris och grundläggande information visas redan nu."
        )


def _manage_portfolio_section(holdings: pd.DataFrame):
    """Tabbar för att hantera portföljen: Avanza-import | Sök & lägg till | Manuell | Ta bort."""
    from data_management import avanza_import
    from web.pages.admin import _search_ticker_yfinance

    label = "➕ Hantera portfölj" if not holdings.empty else "➕ Kom igång – lägg till dina aktier"
    with st.expander(label, expanded=holdings.empty):

        tab_avanza, tab_search, tab_manual, tab_remove = st.tabs([
            "📥 Importera från Avanza",
            "🔍 Sök & lägg till",
            "✏️ Lägg till manuellt",
            "🗑️ Ta bort aktie",
        ])

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 1 – AVANZA IMPORT
        # ══════════════════════════════════════════════════════════════════════
        with tab_avanza:
            st.markdown("""
<div style="background:#1a2235;border:1px solid #2d3250;border-radius:10px;
     padding:14px 18px;margin-bottom:14px;">
<div style="font-size:13px;font-weight:600;color:#e8eaf0;margin-bottom:8px;">
  Så här laddar du ner din portfölj från Avanza
</div>
<ol style="font-size:13px;color:#a0aec0;margin:0;padding-left:18px;line-height:2.1;">
  <li>Logga in på <strong style="color:#e8eaf0;">avanza.se</strong></li>
  <li>Gå till <strong style="color:#e8eaf0;">Konto → din depå/ISK</strong></li>
  <li>Klicka på fliken <strong style="color:#e8eaf0;">Innehav</strong></li>
  <li>Scrolla längst ner → klicka <strong style="color:#4c9be8;">Exportera</strong></li>
  <li>Spara filen och ladda upp den nedan</li>
</ol>
</div>
""", unsafe_allow_html=True)

            uploaded = st.file_uploader(
                "Välj Avanza-filen (CSV)",
                type=["csv"],
                key="avanza_csv_user",
                help="Filen laddas inte upp till någon server – den läses direkt i din webbläsare.",
            )
            if uploaded is not None:
                try:
                    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                        tmp.write(uploaded.getvalue())
                        tmp_path = tmp.name
                    try:
                        df_az = avanza_import.parse_avanza_csv(tmp_path)
                    finally:
                        os.unlink(tmp_path)

                    if df_az.empty:
                        st.error("Kunde inte läsa filen. Är det en Avanza-export?")
                    else:
                        st.success(f"Hittade **{len(df_az)} innehav**. Granska och bekräfta:")
                        import_data = []
                        for i, r in df_az.iterrows():
                            hits      = _search_ticker_yfinance(r.get("name", ""))
                            suggested = hits[0]["ticker"] if hits else ""
                            with st.container(border=True):
                                c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 2, 1])
                                c1.markdown(f"**{r.get('name','?')}**")
                                c2.caption(f"Antal: {r.get('shares',0)}")
                                c3.caption(f"Pris: {r.get('cost_basis',0)}")
                                ticker_val = c4.text_input(
                                    "Ticker", value=suggested, key=f"az_t_{i}",
                                    label_visibility="collapsed",
                                    placeholder="t.ex. VOLV-B.ST",
                                ).upper().strip()
                                do_it = c5.checkbox("Ta med", value=bool(suggested), key=f"az_ok_{i}")
                            import_data.append({"row": r, "ticker": ticker_val, "import": do_it})

                        if st.button("💾 Importera markerade", key="btn_az_save",
                                     type="primary", use_container_width=True):
                            h = holdings.copy() if not holdings.empty else pd.DataFrame(
                                columns=["ticker", "shares", "cost_basis"])
                            n_add = n_upd = 0
                            for item in import_data:
                                if not item["import"] or not item["ticker"]:
                                    continue
                                t = item["ticker"]
                                s = float(item["row"].get("shares", 0))
                                c = float(item["row"].get("cost_basis", 0))
                                was_new = t not in h["ticker"].values
                                h = _upsert_holding(h, t, s, c)  # hanterar scan_pending internt
                                if was_new: n_add += 1
                                else:       n_upd += 1
                            _save_holdings_user(h)
                            st.success(f"✅ Klart! {n_add} nya, {n_upd} uppdaterade.")
                            st.rerun()
                except Exception as e:
                    st.error(f"Fel: {e}")

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 2 – SÖK & LÄGG TILL
        # ══════════════════════════════════════════════════════════════════════
        with tab_search:
            st.caption("Sök på aktiens namn eller ticker och fyll i hur många du köpt och till vilket pris.")
            search_q = st.text_input(
                "Sök aktie",
                key="port_search_q",
                placeholder="t.ex. Volvo, AAPL, Investor...",
            )
            if search_q:
                with st.spinner("Söker..."):
                    hits = _search_ticker_yfinance(search_q)
                if hits:
                    options = {
                        f"{h['ticker']}  —  {h.get('name','')[:35]}  ({h.get('exchange','')})": h
                        for h in hits
                    }
                    chosen_label = st.selectbox("Välj aktie", list(options.keys()),
                                                key="port_search_sel")
                    chosen = options[chosen_label]

                    with st.container(border=True):
                        st.markdown(
                            f"**{chosen.get('name', chosen['ticker'])}**  "
                            f"`{chosen['ticker']}`  ·  {chosen.get('exchange','')}"
                        )
                        col_s, col_p, col_d = st.columns(3)
                        with col_s:
                            antal = st.number_input(
                                "Antal aktier",
                                min_value=0.0, value=0.0, step=1.0,
                                key="port_add_shares",
                                help="Hur många aktier du äger totalt av detta bolag.",
                            )
                        with col_p:
                            pris = st.number_input(
                                "Genomsnittligt inköpspris (kr/st)",
                                min_value=0.0, value=0.0, step=0.01,
                                key="port_add_price",
                                help="Ditt genomsnittliga inköpspris per aktie, inklusive courtage.",
                            )
                        with col_d:
                            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                            if st.button("➕ Lägg till i portfölj", key="btn_port_add_search",
                                         type="primary", use_container_width=True):
                                if antal <= 0:
                                    st.error("Ange antal aktier.")
                                elif pris <= 0:
                                    st.error("Ange inköpspris.")
                                else:
                                    h = _upsert_holding(holdings, chosen["ticker"], antal, pris)
                                    _save_holdings_user(h)
                                    st.success(
                                        f"✅ **{chosen['ticker']}** tillagd "
                                        f"({antal:.0f} st à {pris:.2f} kr)!"
                                    )
                                    st.rerun()
                else:
                    st.info("Inga resultat. Försök med tickern direkt, t.ex. `VOLV-B.ST`.")

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 3 – MANUELL INMATNING
        # ══════════════════════════════════════════════════════════════════════
        with tab_manual:
            st.caption("Vet du tickern? Fyll i direkt utan att söka.")
            with st.form("form_manual_add", clear_on_submit=True):
                c1, c2, c3 = st.columns([2, 2, 2])
                with c1:
                    m_ticker = st.text_input(
                        "Ticker *",
                        placeholder="t.ex. VOLV-B.ST",
                        help="Yahoo Finance-ticker. Svenska aktier slutar på .ST",
                    ).upper().strip()
                with c2:
                    m_shares = st.number_input(
                        "Antal aktier *",
                        min_value=0.0, value=0.0, step=1.0,
                    )
                with c3:
                    m_price = st.number_input(
                        "Inköpspris per aktie (kr) *",
                        min_value=0.0, value=0.0, step=0.01,
                    )
                if st.form_submit_button("➕ Lägg till", type="primary", use_container_width=True):
                    if not m_ticker:
                        st.error("Ange ticker.")
                    elif m_shares <= 0:
                        st.error("Ange antal.")
                    elif m_price <= 0:
                        st.error("Ange inköpspris.")
                    else:
                        h = _upsert_holding(holdings, m_ticker, m_shares, m_price)
                        _save_holdings_user(h)
                        st.success(f"✅ **{m_ticker}** tillagd ({m_shares:.0f} st à {m_price:.2f} kr)!")
                        st.rerun()

        # ══════════════════════════════════════════════════════════════════════
        # FLIK 4 – TA BORT / REDIGERA
        # ══════════════════════════════════════════════════════════════════════
        with tab_remove:
            if holdings.empty:
                st.info("Portföljen är tom – ingenting att ta bort.")
            else:
                tickers = holdings["ticker"].tolist()
                sel = st.selectbox("Välj aktie att hantera", tickers, key="port_remove_sel")
                row = holdings[holdings["ticker"] == sel].iloc[0]

                with st.container(border=True):
                    st.markdown(f"**{sel}** · {float(row['shares']):.0f} st · inköp {float(row['cost_basis']):.2f} kr/st")
                    col_edit, col_del = st.columns(2)

                    with col_edit:
                        with st.expander("✏️ Ändra antal / pris"):
                            with st.form(f"form_edit_{sel}"):
                                e_shares = st.number_input(
                                    "Antal", value=float(row["shares"]),
                                    min_value=0.0, step=1.0, key=f"e_s_{sel}",
                                )
                                e_price = st.number_input(
                                    "Inköpspris (kr/st)", value=float(row["cost_basis"]),
                                    min_value=0.0, step=0.01, key=f"e_p_{sel}",
                                )
                                if st.form_submit_button("💾 Spara", use_container_width=True):
                                    h = _upsert_holding(holdings, sel, e_shares, e_price)
                                    _save_holdings_user(h)
                                    st.success(f"✅ {sel} uppdaterad.")
                                    st.rerun()

                    with col_del:
                        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                        if st.button(f"🗑️ Ta bort {sel}", key=f"btn_del_{sel}",
                                     use_container_width=True):
                            h = holdings[holdings["ticker"] != sel].reset_index(drop=True)
                            _save_holdings_user(h)
                            st.success(f"✅ {sel} borttagen.")
                            st.rerun()


def page_portfolio(df: pd.DataFrame, holdings: pd.DataFrame, watchlist: list,
                   sc_df: pd.DataFrame = None):
    st.title("💼 Portfölj & Bevakningslista")

    # ── Notiser för nyligen tillagda tickers som inväntar nästa scan ──────────
    _show_scan_pending_notifications()

    # ── Portföljhantering (synlig för alla användare) ─────────────────────────
    _manage_portfolio_section(holdings)
    # Ladda om portföljen om den just sparades
    holdings = load_portfolio()

    if holdings.empty:
        st.info("Portföljen är tom. Importera dina innehav från Avanza ovan ↑")
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
                st.markdown(f"⚪ **`{t}`** — Data uppdateras automatiskt inom kort (veckovis analys pågår)")
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
        st.info("Bevakningslistan är tom. Sök efter aktier på 🔍 Aktie-sök och klicka 'Lägg till i bevakningslista'.")
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
