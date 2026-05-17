"""Replace page_stock_search function with improved version."""
path = 'web/streamlit_app.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

s = content.find('def page_stock_search')
e = content.find('def page_watchlist_detail')

new_func = '''def page_stock_search():
    """🔍 Aktie-sök – sök på VILKEN aktie som helst.
    Förbättrad: linjegraf, AI-chatt, yfinance news, add to watchlist/portfolio."""
    st.title("🔍 Aktie-sök")
    st.caption("Sök på vilken aktie som helst (även utanför ditt universum) och få prisgraf, AI-analys, nyheter.")

    default_ticker = st.session_state.get("search_ticker", "")
    if default_ticker:
        st.session_state["search_ticker"] = ""

    items = load_watchlist()
    hlds = load_portfolio()

    col_s, col_go = st.columns([4, 1])
    with col_s:
        search_q = st.text_input(
            "Sök ticker eller bolagsnamn",
            value=default_ticker,
            key="stock_search_input",
            placeholder="t.ex. TSLA, AAPL, VOLV-B.ST, Investor...",
            label_visibility="collapsed",
        )
    with col_go:
        st.button("🔍 Sök", key="btn_stock_search", use_container_width=True, type="primary")

    if not search_q:
        st.info("Skriv en ticker eller ett bolagsnamn ovan för att söka.")
        st.markdown("---")
        st.caption("Tips: Använd sökfältet i sidebaren för att snabbt söka efter aktier!")
        return

    with st.spinner("Söker efter aktie..."):
        hits = _search_ticker_yfinance(search_q.strip())
        if not hits:
            try:
                t = yf.Ticker(search_q.strip().upper())
                info = t.info or {}
                if info.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND", "INDEX"):
                    hits = [{"ticker": search_q.strip().upper(),
                              "name": info.get("shortName") or info.get("longName", search_q),
                              "exchange": info.get("exchange", "")}]
            except Exception:
                pass

        if not hits:
            st.info("Inga sökresultat. Försök med en ticker-symbol som TSLA eller AAPL.")
            return

    ticker_options = {f"{h['ticker']} - {h['name'][:50]} ({h.get('exchange', '?')})": h for h in hits}
    selected_label = st.selectbox("Välj från sökresultat", list(ticker_options.keys()), key="stock_search_result")
    selected = ticker_options[selected_label]
    ticker = selected["ticker"]
    name = selected["name"]

    st.markdown(f"## 📈 {ticker} - {name}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ Lägg till i bevakning", key=f"add_wl_{ticker}", use_container_width=True):
            if not any(i["ticker"] == ticker for i in items):
                items.append({"ticker": ticker, "name": name, "added": str(date.today())})
                _save_watchlist_data(items)
                st.success(f"{ticker} tillagd i bevakningslistan!")
                st.rerun()
            else:
                st.info(f"{ticker} finns redan i bevakningslistan.")
    with col2:
        if st.button("➕ Lägg till i portfölj", key=f"add_pt_{ticker}", use_container_width=True):
            hlds = load_portfolio()
            if ticker not in hlds["ticker"].values:
                new_row = pd.DataFrame([{"ticker": ticker, "shares": 0, "cost_basis": 0}])
                hlds = pd.concat([hlds, new_row], ignore_index=True)
                _save_holdings_df(hlds)
                st.success(f"{ticker} tillagd i portföljen!")
                st.rerun()
            else:
                st.info(f"{ticker} finns redan i portföljen.")

    try:
        yf_ticker = yf.Ticker(ticker)
        info = yf_ticker.info or {}
    except Exception as e:
        st.error(f"Kunde inte hämta data för {ticker}: {e}")
        return

    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    sector = info.get("sector", "—")
    industry = info.get("industry", "—")
    pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    market_cap = info.get("marketCap")
    div_yield = info.get("dividendYield")
    beta = info.get("beta")
    high_52w = info.get("fiftyTwoWeekHigh")
    low_52w = info.get("fiftyTwoWeekLow")
    volume = info.get("volume")
    avg_volume = info.get("averageVolume")
    revenue = info.get("totalRevenue")
    ebitda = info.get("ebitda")
    debt = info.get("totalDebt")
    cash = info.get("totalCash")
    roe = info.get("returnOnEquity")
    profit_margin = info.get("profitMargins")

    kpi_row([
        ("Pris", f"{price:.2f}" if price else "—", None),
        ("Sektor", sector[:20] if sector else "—", None),
        ("P/E", f"{pe:.1f}" if pe else "—", None),
        ("Marknadsvärde", f"{market_cap/1e9:.1f}B" if market_cap else "—", None),
    ])

    # Linjegraf (stilren, ingen candlestick)
    try:
        hist = yf_ticker.history(period="1y", auto_adjust=True)
        if not hist.empty:
            close = hist["Close"] if isinstance(hist["Close"], pd.Series) else hist["Close"].iloc[:, 0]
            ma50 = close.rolling(50).mean() if len(close) >= 50 else None
            ma200 = close.rolling(200).mean() if len(close) >= 200 else None
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=close.index, y=close, mode="lines", name="Pris",
                line=dict(color="#42a5f5", width=2.5), fill="tozeroy", fillcolor="rgba(66,165,245,0.08)"))
            if ma50 is not None:
                fig.add_trace(go.Scatter(x=close.index, y=ma50, mode="lines", name="MA50",
                    line=dict(color="#ffd600", width=1.2, dash="dash")))
            if ma200 is not None:
                fig.add_trace(go.Scatter(x=close.index, y=ma200, mode="lines", name="MA200",
                    line=dict(color="#e040fb", width=1.2, dash="dash")))
            fig.update_layout(template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                height=400, margin=dict(t=40, b=16, l=16, r=16), hovermode="x unified",
                legend=dict(orientation="h", y=1.1, x=0.5, xanchor="center", font=dict(size=10)))
            fig.update_yaxes(title_text="Pris", color="#8892a4")
            fig.update_xaxes(color="#8892a4")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Prisdata saknas.")
    except Exception:
        st.info("Prisgraf kunde inte laddas.")

    # Detaljerad info
    with st.expander("📋 Detaljerad info", expanded=False):
        info_data = {
            "Bolag": name, "Ticker": ticker, "Sektor": sector,
            "Industri": industry, "Pris": f"{price:.2f}" if price else "—",
            "P/E (trailing)": f"{pe:.1f}" if pe else "—",
            "P/E (forward)": f"{forward_pe:.1f}" if forward_pe else "—",
            "Beta": f"{beta:.2f}" if beta else "—",
            "ROE": f"{roe*100:.1f}%" if roe else "—",
            "Vinstmarginal": f"{profit_margin*100:.1f}%" if profit_margin else "—",
            "Utdelningsyield": f"{div_yield*100:.2f}%" if div_yield else "—",
            "52v High": f"{high_52w:.2f}" if high_52w else "—",
            "52v Low": f"{low_52w:.2f}" if low_52w else "—",
            "Volym": f"{volume:,}" if volume else "—",
            "Intäkter": f"{revenue/1e9:.1f}B" if revenue else "—",
            "EBITDA": f"{ebitda/1e9:.1f}B" if ebitda else "—",
            "Skuld": f"{debt/1e9:.1f}B" if debt else "—",
            "Kassa": f"{cash/1e9:.1f}B" if cash else "—",
        }
        st.dataframe(pd.DataFrame(info_data.items(), columns=["Egenskap", "Värde"]),
            use_container_width=True, hide_index=True)

    # Nyheter via yfinance (gratis)
    st.markdown("---")
    st.subheader("📰 Nyheter")
    try:
        news = yf_ticker.news
        if news:
            for n in news[:7]:
                c = n.get("content", {})
                title = c.get("title", "—")
                pub = c.get("pubDate", "")[:10]
                summary = c.get("summary", "")
                st.markdown(f"- **{title}** ({pub})")
                if summary:
                    st.caption(summary[:200])
        else:
            st.caption("Inga nyheter hittade.")
    except Exception:
        st.caption("Nyheter ej tillgängliga.")

    # AI-chatt med live-data-kontext
    st.markdown("---")
    st.subheader("🤖 AI-analys & chatt")
    provider = _get_provider()

    if "stock_chat" not in st.session_state:
        st.session_state["stock_chat"] = []

    # Visa historik
    for msg in st.session_state["stock_chat"][-10:]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"][:500])

    prompt = st.chat_input(f"Fråga om {ticker}...")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner(f"AI tänker om {ticker}..."):
                try:
                    context_lines = []
                    if price: context_lines.append(f"Pris: {price:.2f}")
                    if sector: context_lines.append(f"Sektor: {sector}")
                    if industry: context_lines.append(f"Industri: {industry}")
                    if pe: context_lines.append(f"P/E: {pe:.1f}")
                    if forward_pe: context_lines.append(f"P/E forward: {forward_pe:.1f}")
                    if market_cap: context_lines.append(f"Marknadsvärde: {market_cap/1e9:.1f}B")
                    if beta: context_lines.append(f"Beta: {beta:.2f}")
                    if roe: context_lines.append(f"ROE: {roe*100:.1f}%")
                    if profit_margin: context_lines.append(f"Vinstmarginal: {profit_margin*100:.1f}%")
                    if high_52w and low_52w: context_lines.append(f"52v span: {low_52w:.2f} - {high_52w:.2f}")
                    if revenue: context_lines.append(f"Intäkter: {revenue/1e9:.1f}B")
                    if ebitda: context_lines.append(f"EBITDA: {ebitda/1e9:.1f}B")
                    if div_yield: context_lines.append(f"Utdelningsyield: {div_yield*100:.2f}%")
                    context_str = "\n".join(context_lines)

                    full_prompt = f"""Du är en professionell aktieanalytiker. Här är live-data för {ticker} ({name}):

{context_str}

Användaren frågar: {prompt}

Svara detaljerat med siffror från datan ovan. Ge investeringsrekommendation om möjligt."""

                    result = ai_analysis.ai_chat(
                        full_prompt, context="",
                        history=st.session_state["stock_chat"],
                        provider=provider, depth=_get_depth())
                    st.markdown(result)
                except Exception as e:
                    st.error(f"Fel: {e}")
                    result = f"Kunde inte analysera: {e}"

        st.session_state["stock_chat"].append({"role": "user", "content": prompt})
        st.session_state["stock_chat"].append({"role": "assistant", "content": result})
        if len(st.session_state["stock_chat"]) > 20:
            st.session_state["stock_chat"] = st.session_state["stock_chat"][-20:]
        st.rerun()

    if st.session_state.get("stock_chat"):
        if st.button("🗑️ Rensa chatt-historik", key="clear_stock_chat", use_container_width=True):
            st.session_state["stock_chat"] = []
            st.rerun()

    st.markdown("---")
    st.caption("Tips: Använd sökfältet i sidebaren för att snabbt söka efter aktier!")
'''

content = content[:s] + new_func + content[e:]
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'OK! Replaced function. New: {len(new_func)} chars.')
print('Done!')