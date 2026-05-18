"""web/pages/ai_page.py – Sida 6: AI Dashboard"""

import re
from datetime import datetime, date

import pandas as pd
import streamlit as st

from web.utils import (
    load_watchlist, load_portfolio, _get_provider, _get_depth,
)
from core import ai_analysis, config


def _save_watchlist_data(items):
    from web.pages.admin import _save_watchlist_data as _swd
    _swd(items)


def _save_holdings_df(df):
    from web.pages.admin import _save_holdings_df as _shd
    _shd(df)


def _search_ticker_yfinance(query: str):
    from web.pages.admin import _search_ticker_yfinance as _stf
    return _stf(query)


def _ai_section_header():
    """Gemensam rubrik för AI-sektioner."""
    return '<div style="background:#1a2332;border:1px solid #2d3250;border-radius:8px;padding:12px 18px;margin-bottom:16px">'


def _ai_section_footer():
    return '</div>'


def page_ai(df: pd.DataFrame, sc_df: pd.DataFrame, holdings: pd.DataFrame):
    """AI Dashboard – alla AI-funktioner samlade."""
    st.title("🤖 AI – MarketScan Intelligence")

    provider = _get_provider()
    api_key = config.DEEPSEEK_API_KEY or config.GEMINI_API_KEY
    if not api_key:
        st.warning("⚠️ Ingen AI API-nyckel konfigurerad. Ställ in DEEPSEEK_API_KEY eller GEMINI_API_KEY i .env.")
        return

    status = ai_analysis.test_api_key(provider=provider)
    if status.get("status") == "ok":
        st.caption(f"✅ {status['message']}")
    else:
        st.warning(f"⚠️ {status['message']}")
        if "saknas" in status.get("message", "").lower():
            return

    tab_market, tab_stock, tab_compare, tab_sector, tab_chat, tab_portfolio, tab_news = st.tabs([
        "📊 Marknad", "📈 Aktieanalys", "🔄 Jämför", "🏭 Sektor",
        "💬 Chat", "💼 Portfölj", "📰 Nyheter"
    ])

    # ── Flik 1: Market Dashboard Summary (Feature 8) ────────────────────────
    with tab_market:
        st.subheader("📊 AI-marknadssammanfattning")
        st.caption("Få en snabb AI-genererad överblick över dagens marknad baserat på senaste scandata.")

        refresh_market = st.checkbox("Hoppa över cache", key="ai_market_refresh")

        if st.button("🤖 Generera marknadssammanfattning", key="btn_market_summary",
                     type="primary", use_container_width=True):
            with st.spinner("Analyserar marknaden..."):
                try:
                    depth = _get_depth()
                    result = ai_analysis.generate_market_summary(
                        df=df if not df.empty else None,
                        sc_df=sc_df if not sc_df.empty else None,
                        force_refresh=refresh_market,
                        provider=provider,
                        depth=depth,
                    )
                    st.markdown(_ai_section_header(), unsafe_allow_html=True)
                    st.markdown(result)
                    st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"❌ Kunde inte generera sammanfattning: {e}")

        if not df.empty:
            st.markdown("---")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Bolag i scan", len(df))
            with c2:
                if "score_total" in df.columns:
                    st.metric("Snittpoäng", f"{df['score_total'].mean():.1f}")
            with c3:
                if "entry_signal" in df.columns:
                    n_stark = int((df["entry_signal"] == "STARK").sum())
                    st.metric("STARK entry", n_stark)
            with c4:
                if not df.empty and "score_total" in df.columns:
                    top = df.nlargest(1, "score_total").iloc[0]
                    st.metric("Topp", f"{top['ticker']} ({top['score_total']:.0f}p)")

        st.markdown("---")
        st.subheader("🔍 Sök och lägg till aktie")
        st.caption("Sök efter ticker/bolag via yfinance och lägg till i bevakningslista eller portfölj med ett klick.")

        col_search, col_target = st.columns([3, 1])
        with col_search:
            ai_search_q = st.text_input(
                "Sök ticker eller bolagsnamn",
                key="ai_market_ticker_search",
                placeholder="t.ex. AAPL, TSLA, NVDA...",
            )
        with col_target:
            target = st.selectbox(
                "Lägg till i",
                ["Bevakningslista", "Portfölj"],
                key="ai_market_add_target",
            )

        if ai_search_q:
            hits = _search_ticker_yfinance(ai_search_q.upper().strip())
            if hits:
                st.success(f"Hittade {len(hits)} träffar")
                for h in hits:
                    cols = st.columns([2, 3, 1, 1])
                    with cols[0]:
                        st.markdown(f"**{h['ticker']}**")
                    with cols[1]:
                        st.markdown(f"{h['name'][:50]}")
                    with cols[2]:
                        st.markdown(f"`{h.get('exchange', '?')}`")
                    with cols[3]:
                        if st.button("➕ Lägg till", key=f"ai_mkt_add_{h['ticker']}"):
                            if target == "Bevakningslista":
                                items = load_watchlist()
                                if not any(i["ticker"] == h["ticker"] for i in items):
                                    items.append({
                                        "ticker": h["ticker"],
                                        "name": h["name"],
                                        "added": str(date.today()),
                                    })
                                    _save_watchlist_data(items)
                                    st.success(f"`{h['ticker']}` tillagd i bevakningslistan!")
                                    st.rerun()
                                else:
                                    st.info(f"`{h['ticker']}` finns redan i bevakningslistan.")
                            else:  # Portfölj
                                holdings = load_portfolio()
                                if h["ticker"] not in holdings["ticker"].values:
                                    new_row = pd.DataFrame([{
                                        "ticker": h["ticker"],
                                        "shares": 0,
                                        "cost_basis": 0,
                                    }])
                                    holdings = pd.concat([holdings, new_row], ignore_index=True)
                                    _save_holdings_df(holdings)
                                    st.success(f"`{h['ticker']}` tillagd i portföljen! Fyll i antal och pris i Admin.")
                                    st.rerun()
                                else:
                                    st.info(f"`{h['ticker']}` finns redan i portföljen.")
            else:
                st.caption("Inga sökresultat. Prova med annat sökord.")

    # ── Flik 2: One-click Stock Analysis (Feature 2b) ───────────────────────
    with tab_stock:
        st.subheader("📈 AI-aktieanalys")
        st.caption("Välj en aktie för djupgående AI-analys av alla faktorer – inklusive färska nyheter.")

        if not df.empty and "ticker" in df.columns:
            tickers = sorted(df["ticker"].tolist())
            col1, col2 = st.columns([3, 1])
            with col1:
                sel_ticker = st.selectbox("Välj aktie", tickers, key="ai_stock_ticker")
            with col2:
                force_refresh = st.checkbox("Hoppa över cache", key="ai_stock_refresh")

            if st.button("🤖 Analysera aktie", key="btn_stock_analysis",
                         type="primary", use_container_width=True):
                with st.spinner(f"Hämtar nyheter och analyserar {sel_ticker}..."):
                    try:
                        # Fetch live news first
                        fetched_news = []
                        try:
                            from core.news_fetcher import fetch_company_news
                            fetched_news = fetch_company_news(sel_ticker, days_back=7) or []
                        except Exception:
                            pass

                        depth = _get_depth()
                        result = ai_analysis.analyze_stock(
                            sel_ticker, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )

                        # If we have news, append a news analysis below the stock analysis
                        if fetched_news:
                            news_items = [
                                {"title": n.get("headline", n.get("title", "")),
                                 "summary": n.get("summary", n.get("description", "")),
                                 "source": n.get("source", ""),
                                 "date": n.get("datetime", n.get("datetime_str", ""))}
                                for n in fetched_news[:8]
                            ]
                            news_result = ai_analysis.analyze_news(
                                sel_ticker, news_items=news_items,
                                force_refresh=force_refresh,
                                provider=provider,
                                depth=depth,
                            )
                            full_result = result + "\n\n---\n\n### 📰 Nyhetsläget\n\n" + news_result
                        else:
                            full_result = result

                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(full_result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)

                        if fetched_news:
                            with st.expander(f"📋 Källnyheter ({len(fetched_news)} artiklar)", expanded=False):
                                for n in fetched_news[:8]:
                                    title = n.get("headline", n.get("title", "—"))
                                    src = n.get("source", "?")
                                    age = n.get("age_hours")
                                    age_str = f" · {age:.0f}h sedan" if age is not None else ""
                                    st.markdown(f"- **{title}** — *{src}*{age_str}")
                    except Exception as e:
                        st.error(f"❌ Analys misslyckades: {e}")

            if sel_ticker:
                row = df[df["ticker"] == sel_ticker]
                if not row.empty:
                    r = row.iloc[0]
                    st.markdown("---")
                    st.caption("📋 Snabbdata")
                    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
                    with cc1:
                        st.metric("Score", f"{r.get('score_total', '—'):.0f}/100" if not pd.isna(r.get('score_total')) else "—")
                    with cc2:
                        st.metric("Entry", r.get("entry_signal", "—"))
                    with cc3:
                        st.metric("Trend", r.get("trend_signal", "—"))
                    with cc4:
                        st.metric("RSI", f"{r.get('rsi_14', '—'):.0f}" if not pd.isna(r.get('rsi_14', '—')) else "—")
                    with cc5:
                        st.metric("Piotroski", f"{r.get('piotroski_f', '—')}/9" if not pd.isna(r.get('piotroski_f', '—')) else "—")
        else:
            st.info("Ingen scandata tillgänglig för aktieval.")

    # ── Flik 3: Compare Two Stocks (Feature 2c) ────────────────────────────
    with tab_compare:
        st.subheader("🔄 AI-jämförelse – två aktier")
        st.caption("Jämför två aktier sida vid sida med AI-analys.")

        if not df.empty and "ticker" in df.columns:
            tickers = sorted(df["ticker"].tolist())
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                 ticker_a = st.selectbox("Aktie A", tickers, key="ai_cmp_a")
            with col2:
                 ticker_b = st.selectbox("Aktie B", tickers, index=min(1, len(tickers)-1), key="ai_cmp_b")
            with col3:
                 force_refresh = st.checkbox("Hoppa över cache", key="ai_cmp_refresh")

            if st.button("🤖 Jämför aktier", key="btn_compare",
                         type="primary", use_container_width=True):
                with st.spinner(f"Jämför {ticker_a} vs {ticker_b}..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.compare_stocks(
                            ticker_a, ticker_b, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Jämförelse misslyckades: {e}")

            if ticker_a and ticker_b and ticker_a != ticker_b:
                row_a = df[df["ticker"] == ticker_a].iloc[0] if not df[df["ticker"] == ticker_a].empty else None
                row_b = df[df["ticker"] == ticker_b].iloc[0] if not df[df["ticker"] == ticker_b].empty else None
                if row_a is not None and row_b is not None:
                    st.markdown("---")
                    st.caption("📋 Snabbjämförelse")
                    cmp_data = []
                    for field, label in [("score_total", "Total Score"), ("score_momentum", "Momentum"),
                                         ("score_value", "Värdering"), ("score_quality", "Kvalitet"),
                                         ("score_growth", "Tillväxt"), ("rsi_14", "RSI"),
                                         ("pe_trailing", "P/E"), ("roe", "ROE"),
                                         ("return_12m", "12m-avkastning"), ("price_vs_ma200", "vs MA200")]:
                        va = row_a.get(field)
                        vb = row_b.get(field)
                        if va is not None and not pd.isna(va):
                            va = f"{va:.1f}" if isinstance(va, float) else va
                        if vb is not None and not pd.isna(vb):
                            vb = f"{vb:.1f}" if isinstance(vb, float) else vb
                        cmp_data.append({"Mått": label, ticker_a: va if va is not None else "—", ticker_b: vb if vb is not None else "—"})
                    st.dataframe(pd.DataFrame(cmp_data), use_container_width=True, hide_index=True)
        else:
            st.info("Ingen scandata tillgänglig för jämförelse.")

    # ── Flik 4: Sector Analysis (Feature 2d) ───────────────────────────────
    with tab_sector:
        st.subheader("🏭 AI-sektoranalys")
        st.caption("Få en AI-genererad analys av en hel sektor.")

        if not df.empty and "sector" in df.columns:
            sectors = sorted(df["sector"].dropna().unique().tolist())
            col1, col2 = st.columns([3, 1])
            with col1:
                sel_sector = st.selectbox("Välj sektor", sectors, key="ai_sector")
            with col2:
                force_refresh = st.checkbox("Hoppa över cache", key="ai_sector_refresh")

            if st.button("🤖 Analysera sektor", key="btn_sector_analysis",
                         type="primary", use_container_width=True):
                with st.spinner(f"Analyserar sektorn {sel_sector}..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.analyze_sector(
                            sel_sector, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Sektoranalys misslyckades: {e}")

            if sel_sector:
                st.markdown("---")
                sec_df = df[df["sector"] == sel_sector].copy()
                st.caption(f"📋 Bolag i sektorn ({len(sec_df)} st)")
                show_cols = [c for c in ["ticker", "name", "score_total", "entry_signal",
                                         "trend_signal", "rsi_14"] if c in sec_df.columns]
                if show_cols:
                    st.dataframe(sec_df[show_cols].reset_index(drop=True), use_container_width=True, height=300)
        else:
            st.info("Ingen sektordata tillgänglig.")

    # ── Flik 5: AI Chat (adaptiv med historik) ─────────────────────────────
    with tab_chat:
        st.subheader("AI-chatt – fraga MarketScan AI")
        st.caption("Stall fragor om marknaden, aktier, strategier. Skriv t.ex. 'sok bland 50 basta' for att fa mer data.",
                   unsafe_allow_html=True)

        if "chat_history" not in st.session_state:
            st.session_state["chat_history"] = []

        col_clear, col_refresh = st.columns([1, 3])
        with col_clear:
            if st.button("Rensa historik", key="btn_clear_chat"):
                st.session_state["chat_history"] = []
                st.rerun()
        with col_refresh:
            force_refresh = st.checkbox("Hoppa over cache", key="ai_chat_refresh2")

        for msg in st.session_state["chat_history"][-20:]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        prompt = st.chat_input("Stall en fraga om marknaden...")

        if prompt:
            with st.chat_message("user"):
                st.markdown(prompt)

            context_parts = []

            match_num = re.search(r"(\d+)", prompt)
            top_n = int(match_num.group(1)) if match_num else 10
            top_n = max(3, min(top_n, 200))

            if not df.empty:
                context_parts.append(f"Global scan: {len(df)} bolag scannade")
                if "score_total" in df.columns:
                    context_parts.append(f"snittscore {df['score_total'].mean():.1f}")
                if "entry_signal" in df.columns:
                    n_stark = int((df["entry_signal"] == "STARK").sum())
                    context_parts.append(f"STARK-signaler: {n_stark}")

                score_col = "score_total"
                if score_col in df.columns:
                    top_df = df.nlargest(top_n, score_col)
                    topp_lista = "; ".join(
                        f"{r['ticker']} ({r[score_col]:.0f}p)"
                        for _, r in top_df.iterrows()
                    )
                    context_parts.append(f"Topp {top_n}: {topp_lista}")

            if not sc_df.empty:
                sc_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
                context_parts.append(f"Smabolag: {len(sc_df)} bolag")
                if sc_col in sc_df.columns:
                    context_parts.append(f"smabolagssnitt: {sc_df[sc_col].mean():.1f}")
                    sc_top = sc_df.nlargest(top_n, sc_col)
                    sc_lista = "; ".join(
                        f"{r['ticker']} ({r[sc_col]:.0f}p)"
                        for _, r in sc_top.iterrows()
                    )
                    context_parts.append(f"Topp {top_n} smabolag: {sc_lista}")

            now = datetime.now()
            days = ["måndag","tisdag","onsdag","torsdag","fredag","lördag","söndag"]
            day_name = days[now.weekday()]
            is_weekend = "HELG" if now.weekday() >= 5 else "BÖRSDAG"
            context_parts.append(f"Datum: {now.strftime('%Y-%m-%d')} ({day_name}, {is_weekend})")

            # ── Auto-detect ticker mention in prompt → fetch live news ──────
            news_context_parts = []
            prompt_upper = prompt.upper()
            # Look for known tickers from df/sc_df, or anything that looks like a ticker
            all_known = set()
            if not df.empty and "ticker" in df.columns:
                all_known.update(df["ticker"].tolist())
            if not sc_df.empty and "ticker" in sc_df.columns:
                all_known.update(sc_df["ticker"].tolist())

            mentioned_tickers = [t for t in all_known if t.upper() in prompt_upper or
                                  t.split(".")[0].upper() in prompt_upper]

            # Also look for patterns like nyheter/news + word, and explicit ".ST" suffixes
            ticker_pattern = re.findall(r'\b([A-ZÅÄÖ]{2,6}(?:-[A-Z])?(?:\.ST|\.OL|\.CO|\.HE)?)\b', prompt_upper)
            for tp in ticker_pattern:
                if tp not in mentioned_tickers and len(tp) >= 3:
                    # Validate: is it in all_known or ends with exchange suffix?
                    if tp in all_known or any(tp.endswith(s) for s in [".ST", ".OL", ".CO", ".HE"]):
                        mentioned_tickers.append(tp)

            mentioned_tickers = list(dict.fromkeys(mentioned_tickers))[:3]  # max 3

            if mentioned_tickers:
                try:
                    from core.news_fetcher import fetch_company_news
                    for mt in mentioned_tickers:
                        news_list = fetch_company_news(mt, days_back=5) or []
                        if news_list:
                            lines = []
                            for n in news_list[:6]:
                                title = n.get("headline", n.get("title", "")).strip()
                                src = n.get("source", "")
                                age = n.get("age_hours")
                                age_str = f" ({age:.0f}h sedan)" if age is not None else ""
                                if title:
                                    lines.append(f"- {title} [{src}]{age_str}")
                            if lines:
                                news_context_parts.append(
                                    f"{mt}:\n" + "\n".join(lines)
                                )
                except Exception:
                    pass

            context_str = ". ".join(context_parts) + "." if context_parts else ""
            if news_context_parts:
                # Use the special separator that ai_chat recognises for plain-text news
                context_str += "\n\nFärska nyheter:\n" + "\n\n".join(news_context_parts)

            full_context = context_str

            with st.chat_message("assistant"):
                with st.spinner("AI tanker..."):
                    try:
                        depth = _get_depth()
                        history_data = st.session_state.get("chat_history", [])
                        result = ai_analysis.ai_chat(
                            prompt,
                            context=full_context,
                            history=history_data,
                            force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(result)
                    except Exception as e:
                        st.error(f"Chatten misslyckades: {e}")
                        result = f"Fel: {e}"

            st.session_state["chat_history"].append({"role": "user", "content": prompt})
            st.session_state["chat_history"].append({"role": "assistant", "content": result})

            if len(st.session_state["chat_history"]) > 20:
                st.session_state["chat_history"] = st.session_state["chat_history"][-20:]

            st.rerun()

    # ── Flik 6: Portfolio Optimizer (Feature 4) ────────────────────────────
    with tab_portfolio:
        st.subheader("💼 AI-portföljoptimering")
        st.caption("Få AI-analys av din portfölj med förslag på förbättringar.")

        if not holdings.empty:
            if st.button("🤖 Analysera portfölj", key="btn_portfolio_ai_tab",
                         type="primary", use_container_width=True):
                with st.spinner("Analyserar portfölj..."):
                    try:
                        depth = _get_depth()
                        result = ai_analysis.analyze_portfolio(
                            holdings, df=df if not df.empty else None,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"❌ Portföljanalys misslyckades: {e}")

            st.markdown("---")
            st.caption(f"📋 Dina {len(holdings)} innehav")
            if not df.empty and "ticker" in df.columns:
                score_lu = df.set_index("ticker").to_dict("index")
            else:
                score_lu = {}
            rows = []
            for _, h in holdings.iterrows():
                t = h["ticker"]
                sc = score_lu.get(t, {})
                rows.append({
                    "Ticker": t,
                    "Score": sc.get("score_total", "—"),
                    "Entry": sc.get("entry_signal", "—"),
                    "Trend": sc.get("trend_signal", "—"),
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Inga portföljinnehav hittade. Lägg till innehav i Admin-fliken först.")

    # ── Flik 7: News Analysis (Feature 5) ──────────────────────────────────
    with tab_news:
        st.subheader("📰 AI-nyhetsanalys")
        st.caption("Sök och analysera nyheter för en specifik aktie.")

        news_search = st.text_input("Sök aktie (ticker eller bolagsnamn)", "",
                                    key="news_search_input",
                                    placeholder="t.ex. TSLA, AAPL, Investor, Volvo...")
        news_ticker = ""

        if news_search.strip():
            news_hits = _search_ticker_yfinance(news_search.strip())
            if news_hits:
                news_options = {f"{h['ticker']} — {h['name'][:50]}": h for h in news_hits}
                news_label = st.selectbox("Välj från sökresultat", list(news_options.keys()),
                                          key="ai_news_ticker_select")
                news_ticker = news_options[news_label]["ticker"]

        if not news_ticker and not df.empty and "ticker" in df.columns and df["ticker"].nunique() > 0:
            tickers = sorted(df["ticker"].dropna().unique().tolist())
            news_ticker = st.selectbox("Eller välj från senaste scan", tickers, key="ai_news_ticker_fallback")
        elif not news_ticker:
            st.info("Sök på en aktie ovan för att komma igång.")

        col_info, col_opt = st.columns([3, 1])
        with col_info:
            if news_ticker:
                st.markdown(f"**Vald aktie:** `{news_ticker}`")
        with col_opt:
            force_refresh = st.checkbox("Hoppa över cache", key="ai_news_refresh")

        if news_ticker:
            if st.button("📰 Hämta och analysera nyheter", key="btn_news_analysis",
                         type="primary", use_container_width=True):
                with st.spinner(f"Hämtar nyheter för {news_ticker}..."):
                    try:
                        fetched = []
                        try:
                            from core.news_fetcher import fetch_company_news
                            fetched = fetch_company_news(news_ticker, days_back=7) or []
                        except Exception:
                            pass

                        if fetched:
                            news_items = [
                                {"title": n.get("headline", n.get("title", "")),
                                 "summary": n.get("summary", n.get("description", "")),
                                 "source": n.get("source", ""),
                                 "date": n.get("datetime", n.get("datetime_str", ""))}
                                for n in fetched[:10]
                            ]
                        else:
                            news_items = None

                        depth = _get_depth()
                        result = ai_analysis.analyze_news(
                            news_ticker, news_items=news_items, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                        )
                        st.markdown(_ai_section_header(), unsafe_allow_html=True)
                        st.markdown(result)
                        st.markdown(_ai_section_footer(), unsafe_allow_html=True)

                        if fetched:
                            st.markdown("---")
                            st.caption(f"📋 {len(fetched)} nyheter hämtade (senaste 7 dagar)")
                            for n in fetched[:10]:
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
                            st.warning(
                                f"⚠️ Inga nyheter hittades för **{news_ticker}**. "
                                "Kontrollera att FINNHUB_API_KEY är satt i .env, "
                                "eller prova med ett annat sökord."
                            )
                    except Exception as e:
                        st.error(f"❌ Nyhetsanalys misslyckades: {e}")

            with st.expander("🔍 Visa råa nyheter (utan AI)", expanded=False):
                try:
                    from core.news_fetcher import fetch_company_news
                    raw_news = fetch_company_news(news_ticker, days_back=3) or []
                    if raw_news:
                        for n in raw_news[:8]:
                            title = n.get("headline", n.get("title", "—"))
                            src = n.get("source", "?")
                            url = n.get("url", "")
                            if url:
                                st.markdown(f"- [{title}]({url}) — *{src}*")
                            else:
                                st.markdown(f"- {title} — *{src}*")
                    else:
                        st.caption("Inga nyheter hittade för senaste 3 dagar.")
                except Exception:
                    st.caption("Kunde inte hämta nyheter.")
