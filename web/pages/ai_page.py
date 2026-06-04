"""web/pages/ai_page.py - Sida 6: AI Dashboard"""

import json
import re
from datetime import datetime, date

import pandas as pd
import streamlit as st

from web.utils import (
    load_watchlist, load_portfolio, _get_provider, _get_depth,
)
from core import ai_analysis, config
from core.ai_ensemble import AiEnsemble
from web.ui.components import clickable_stock_table


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


def _consensus_badge(agreement: str) -> str:
    """Returnera HTML för consensus-badge."""
    if agreement == "full":
        return '<span style="background:#00c85320;color:#00c853;padding:2px 10px;border-radius:12px;font-size:0.8rem">🟢 Konsensus</span>'
    elif agreement == "conflict":
        return '<span style="background:#ff174420;color:#ff1744;padding:2px 10px;border-radius:12px;font-size:0.8rem">🔴 Konflikt</span>'
    else:
        return '<span style="background:#ffd60020;color:#ffd600;padding:2px 10px;border-radius:12px;font-size:0.8rem">🟡 Delade meningar</span>'


def _confidence_bar(confidence: float) -> str:
    """Returnera en enkel CSS-confidence bar."""
    pct = min(int(confidence * 100), 100)
    color = "#00c853" if pct >= 80 else "#ffd600" if pct >= 50 else "#ff1744"
    return f'''
    <div style="background:#2d3250;border-radius:4px;height:8px;width:100%;margin:4px 0">
        <div style="background:{color};width:{pct}%;height:8px;border-radius:4px"></div>
    </div>
    <span style="font-size:0.8rem">{pct}%</span>
    '''


def page_ai(df: pd.DataFrame, sc_df: pd.DataFrame, holdings: pd.DataFrame):
    """AI Dashboard - alla AI-funktioner samlade."""
    st.title("🤖 AI - MarketScan Intelligence")

    provider = _get_provider()
    api_key = config.DEEPSEEK_API_KEY or config.GEMINI_API_KEY or config.CLAUDE_API_KEY
    if not api_key:
        st.warning("⚠️ Ingen AI API-nyckel konfigurerad. Ställ in DEEPSEEK_API_KEY, GEMINI_API_KEY eller CLAUDE_API_KEY i .env.")
        return

    status = ai_analysis.test_api_key(provider=provider)
    if status.get("status") == "ok":
        st.caption(f"✅ {status['message']}")
    else:
        st.warning(f"⚠️ {status['message']}")
        if "saknas" in status.get("message", "").lower():
            # Visa bara varning, blockera inte hela sidan
            pass

    tab_market, tab_stock, tab_compare, tab_sector, tab_chat, tab_portfolio, tab_news, tab_multi = st.tabs([
        "📊 Marknad", "📈 Aktieanalys", "🔄 Jämför", "🏭 Sektor",
        "💬 Chat", "💼 Portfölj", "📰 Nyheter", "🔀 Multi-AI"
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
        st.caption("Välj en aktie för djupgående AI-analys av alla faktorer - inklusive färska nyheter.")

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
                        # Fetch live news first (look up company name for better search)
                        fetched_news = []
                        try:
                            from core.news_fetcher import fetch_company_news
                            _cname_row = df[df["ticker"] == sel_ticker]
                            _cname = str(_cname_row.iloc[0]["name"]) if not _cname_row.empty and "name" in _cname_row.columns else None
                            fetched_news = fetch_company_news(sel_ticker, days_back=7, company_name=_cname) or []
                        except Exception:
                            pass

                        depth = _get_depth()
                        # Kolla om användaren äger tickern - skicka i så fall position till AI
                        user_pos = None
                        if holdings is not None and not holdings.empty and sel_ticker in holdings["ticker"].values:
                            h_row = holdings[holdings["ticker"] == sel_ticker].iloc[0]
                            cur_p = None
                            if df is not None and not df.empty and "ticker" in df.columns:
                                price_rows = df[df["ticker"] == sel_ticker]
                                if not price_rows.empty:
                                    cur_p = price_rows.iloc[0].get("current_price") or price_rows.iloc[0].get("close")
                            user_pos = {
                                "shares":        float(h_row.get("shares", 0)),
                                "cost_basis":    float(h_row.get("cost_basis", 0)),
                                "current_price": float(cur_p) if cur_p is not None else None,
                            }
                        result = ai_analysis.analyze_stock(
                            sel_ticker, df=df, force_refresh=force_refresh,
                            provider=provider,
                            depth=depth,
                            user_position=user_pos,
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

                        # Log to AI trade journal
                        try:
                            from web.pages.ai_journal import log_ai_recommendation
                            rec_text = result.upper()
                            if "STARKT KÖP" in rec_text or "STARK KÖP" in rec_text:
                                rec = "STARKT KÖP"
                            elif "KÖP" in rec_text:
                                rec = "KÖP"
                            elif "SÄLJ" in rec_text:
                                rec = "SÄLJ"
                            elif "VÄNTA" in rec_text:
                                rec = "VÄNTA"
                            else:
                                rec = "NEUTRAL"
                            _ticker_rows = df[df["ticker"] == sel_ticker]
                            _cur_price = float(_ticker_rows.iloc[0].get("current_price") or _ticker_rows.iloc[0].get("close") or 0) if not _ticker_rows.empty else 0
                            _score = float(_ticker_rows.iloc[0].get("score_total") or 0) if not _ticker_rows.empty else 0
                            _sector = str(_ticker_rows.iloc[0].get("sector") or "") if not _ticker_rows.empty else ""
                            log_ai_recommendation(sel_ticker, rec, _score, _cur_price, result[:300],
                                                  provider=provider, sector=_sector)
                        except Exception:
                            pass

                        if fetched_news:
                            with st.expander(f"📋 Källnyheter ({len(fetched_news)} artiklar)", expanded=False):
                                for n in fetched_news[:8]:
                                    title = n.get("headline", n.get("title", "--"))
                                    src = n.get("source", "?")
                                    age = n.get("age_hours")
                                    age_str = f" * {age:.0f}h sedan" if age is not None else ""
                                    st.markdown(f"- **{title}** -- *{src}*{age_str}")
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
                        st.metric("Score", f"{r.get('score_total', '--'):.0f}/100" if not pd.isna(r.get('score_total')) else "--")
                    with cc2:
                        st.metric("Entry", r.get("entry_signal", "--"))
                    with cc3:
                        st.metric("Trend", r.get("trend_signal", "--"))
                    with cc4:
                        st.metric("RSI", f"{r.get('rsi_14', '--'):.0f}" if not pd.isna(r.get('rsi_14', '--')) else "--")
                    with cc5:
                        st.metric("Piotroski", f"{r.get('piotroski_f', '--')}/9" if not pd.isna(r.get('piotroski_f', '--')) else "--")
        else:
            st.info("Ingen scandata tillgänglig för aktieval.")

    # ── Flik 3: Compare Two Stocks (Feature 2c) ────────────────────────────
    with tab_compare:
        st.subheader("🔄 AI-jämförelse - två aktier")
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
                        cmp_data.append({"Mått": label, ticker_a: va if va is not None else "--", ticker_b: vb if vb is not None else "--"})
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
                    _sec_disp = sec_df[show_cols].reset_index(drop=True).rename(columns={"ticker": "Ticker"})
                    clickable_stock_table(_sec_disp, ticker_col="Ticker", context_df=df,
                                         key="ai_sector_stocks_table", height=300,
                                         caption="Klicka för full analys.")
        else:
            st.info("Ingen sektordata tillgänglig.")

    # ── Flik 5: AI Chat (adaptiv med historik) ─────────────────────────────
    with tab_chat:
        st.subheader("AI-chatt — fråga MarketScan AI")
        st.caption("Ställ frågor om marknaden, aktier, strategier. Skriv t.ex. 'sök bland 50 bästa' för att få mer data.",
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

            def _fmt_val(v, pct=False, decimals=1, prefix="", suffix=""):
                """Format a value cleanly; return '' if missing/NaN."""
                import math
                if v is None:
                    return ""
                try:
                    f = float(v)
                    if math.isnan(f) or math.isinf(f):
                        return ""
                    if pct:
                        return f"{prefix}{f*100:.{decimals}f}%{suffix}"
                    return f"{prefix}{f:.{decimals}f}{suffix}"
                except (TypeError, ValueError):
                    s = str(v).strip()
                    return f"{prefix}{s}{suffix}" if s and s not in ("nan", "None", "") else ""

            def _stock_card(r: dict, score_col: str) -> str:
                """Build a rich one-line data card for a stock row (dict)."""
                parts = []

                # Score + ticker
                import math as _math
                score = r.get(score_col)
                ticker = r.get("ticker", "")
                try:
                    score_s = f"({float(score):.0f}p)" if score is not None and not _math.isnan(float(score)) else ""
                except (TypeError, ValueError):
                    score_s = ""
                parts.append(f"{ticker} {score_s}".strip())

                # Name (truncated)
                name = str(r.get("name") or "").strip()
                if name and name != "nan":
                    parts.append(name[:28])

                # Sector (short)
                sector = str(r.get("sector") or "").strip()
                if sector and sector not in ("nan", "Unknown", "N/A"):
                    parts.append(sector[:20])

                # Entry + Trend signals
                entry = str(r.get("entry_signal") or "").strip()
                trend = str(r.get("trend_signal") or "").strip()
                sig_parts = []
                if entry and entry not in ("nan", ""):
                    sig_parts.append(f"Entry:{entry}")
                if trend and trend not in ("nan", ""):
                    sig_parts.append(f"Trend:{trend}")
                if sig_parts:
                    parts.append(" ".join(sig_parts))

                # Price + Analyst target
                price = r.get("current_price")
                currency = str(r.get("currency") or "").strip()
                cur_sym = {"SEK": "kr", "USD": "$", "EUR": "€", "GBP": "£",
                           "NOK": "kr", "DKK": "kr"}.get(currency, currency)
                p_s = _fmt_val(price, decimals=1)
                if p_s:
                    parts.append(f"Kurs:{cur_sym}{p_s}")

                target = r.get("target_mean_price")
                t_s = _fmt_val(target, decimals=0)
                if t_s:
                    parts.append(f"Mål:{cur_sym}{t_s}")

                # Valuation
                pe = _fmt_val(r.get("pe_trailing"), decimals=1)
                if pe:
                    parts.append(f"PE:{pe}")

                ev_ebitda = _fmt_val(r.get("ev_to_ebitda"), decimals=1)
                if ev_ebitda:
                    parts.append(f"EV/EBITDA:{ev_ebitda}")

                # Quality
                roe = _fmt_val(r.get("roe"), pct=True, decimals=0)
                if roe:
                    parts.append(f"ROE:{roe}")

                # Growth
                rev_g = _fmt_val(r.get("revenue_growth"), pct=True, decimals=0)
                if rev_g:
                    parts.append(f"Rev:{rev_g}")

                # Momentum
                rsi = _fmt_val(r.get("rsi_14"), decimals=0)
                if rsi:
                    parts.append(f"RSI:{rsi}")

                ma200 = _fmt_val(r.get("price_vs_ma200"), pct=True, decimals=0)
                if ma200:
                    parts.append(f"MA200:{ma200}")

                def _ret_str(val, max_pct=150):
                    """Smart return formatter: auto-detects decimal vs % storage.
                    Values with abs < 1 are treated as decimals (x100).
                    Values with abs >= 1 are treated as already in %.
                    Clips anything beyond ±max_pct as likely corrupt data.
                    """
                    if val is None:
                        return ""
                    try:
                        f = float(val)
                        if _math.isnan(f) or _math.isinf(f):
                            return ""
                        pct = f * 100 if abs(f) < 1.0 else f
                        if abs(pct) > max_pct:
                            return ""   # discard corrupt/extreme data
                        sign = "+" if pct > 0 else ""
                        return f"{sign}{pct:.1f}%"
                    except (TypeError, ValueError):
                        return ""

                ret_1m = _ret_str(r.get("return_1m"))
                if ret_1m:
                    parts.append(f"1m:{ret_1m}")

                ret_3m = _ret_str(r.get("return_3m"))
                if ret_3m:
                    parts.append(f"3m:{ret_3m}")

                # Dividend (already stored as %, e.g. 2.68 = 2.68%)
                div_raw = r.get("dividend_yield")
                try:
                    div_f = float(div_raw) if div_raw is not None else None
                    if div_f is not None and not _math.isnan(div_f) and div_f > 0.05:
                        parts.append(f"Utd:{div_f:.1f}%")
                except (TypeError, ValueError):
                    pass

                # Piotroski
                pio = r.get("piotroski_f")
                if pio is not None:
                    try:
                        if not __import__("math").isnan(float(pio)):
                            parts.append(f"Pio:{int(float(pio))}/9")
                    except Exception:
                        pass

                return " | ".join(parts)

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
                    cards = [_stock_card(r.to_dict(), score_col) for _, r in top_df.iterrows()]
                    context_parts.append(f"Topp {top_n} aktier (ticker | score | namn | sektor | signaler | kurs | mål | PE | EV/EBITDA | ROE | rev-tillväxt | RSI | MA200 | 1m | 3m | utd | Piotroski):\n" + "\n".join(cards))

            if not sc_df.empty:
                sc_col = "sc_total" if "sc_total" in sc_df.columns else "score_total"
                context_parts.append(f"Småbolag: {len(sc_df)} bolag")
                if sc_col in sc_df.columns:
                    context_parts.append(f"smabolagssnitt: {sc_df[sc_col].mean():.1f}")
                    sc_top = sc_df.nlargest(top_n, sc_col)
                    sc_cards = [_stock_card(r.to_dict(), sc_col) for _, r in sc_top.iterrows()]
                    context_parts.append(f"Topp {top_n} småbolag:\n" + "\n".join(sc_cards))

            # ── Portfölj ────────────────────────────────────────────────────
            if holdings is not None and not holdings.empty:
                owned = holdings["ticker"].tolist()

                # Build lookup from both scan universes
                df_lu = df.set_index("ticker") if not df.empty and "ticker" in df.columns else None
                sc_lu = sc_df.set_index("ticker") if not sc_df.empty and "ticker" in sc_df.columns else None
                sc_score_col = "sc_total" if sc_lu is not None and "sc_total" in sc_df.columns else "score_total"

                def _live_card_fallback(ticker: str) -> str:
                    """Fetch basic data from yfinance for tickers not in the scan."""
                    try:
                        import yfinance as yf
                        info = yf.Ticker(ticker).info or {}
                        r = {
                            "ticker":           ticker,
                            "name":             info.get("longName") or info.get("shortName", ""),
                            "sector":           info.get("sector", ""),
                            "current_price":    info.get("currentPrice") or info.get("regularMarketPrice"),
                            "currency":         info.get("currency", ""),
                            "pe_trailing":      info.get("trailingPE"),
                            "roe":              info.get("returnOnEquity"),
                            "revenue_growth":   info.get("revenueGrowth"),
                            "rsi_14":           None,
                            "target_mean_price": info.get("targetMeanPrice"),
                            "dividend_yield":   info.get("dividendYield") or 0,  # yfinance returns as %, e.g. 1.49 = 1.49%
                            "market_cap":       info.get("marketCap"),
                            "entry_signal":     "ej scannad",
                            "trend_signal":     "",
                        }
                        return _stock_card(r, "score_total")
                    except Exception:
                        return ticker

                holding_cards = []
                for t in owned[:30]:
                    if df_lu is not None and t in df_lu.index:
                        holding_cards.append(_stock_card(df_lu.loc[t].to_dict(), "score_total"))
                    elif sc_lu is not None and t in sc_lu.index:
                        holding_cards.append(_stock_card(sc_lu.loc[t].to_dict(), sc_score_col))
                    else:
                        # Not in any scan -- fetch live from yfinance
                        holding_cards.append(_live_card_fallback(t))

                context_parts.append(
                    f"Användarens portfölj ({len(owned)} innehav):\n"
                    + "\n".join(holding_cards)
                )

            now = datetime.now()
            days = ["måndag","tisdag","onsdag","torsdag","fredag","lördag","söndag"]
            day_name = days[now.weekday()]
            is_weekend = "HELG" if now.weekday() >= 5 else "BÖRSDAG"
            context_parts.append(f"Datum: {now.strftime('%Y-%m-%d')} ({day_name}, {is_weekend})")

            # ── Auto-detect tickers -> fetch live news ──────────────────────
            news_context_parts = []
            prompt_upper = prompt.upper()

            # Build lookup of all known tickers from current scan
            all_known = set()
            if not df.empty and "ticker" in df.columns:
                all_known.update(df["ticker"].tolist())
            if not sc_df.empty and "ticker" in sc_df.columns:
                all_known.update(sc_df["ticker"].tolist())

            mentioned_tickers = []

            # 1. Explicit TICKER.EXCHANGE patterns (e.g. VOLV-B.ST, AAPL, ERIC-B.ST)
            suffix_re = re.compile(
                r'\b([A-ZÅÄÖ]{1,8}(?:-[A-Z0-9])?)'
                r'\.(ST|OL|CO|HE|L|DE|PA|AS|TO|AX)\b',
                re.IGNORECASE,
            )
            for base, suffix in suffix_re.findall(prompt):
                t = f"{base.upper()}.{suffix.upper()}"
                if t not in mentioned_tickers:
                    mentioned_tickers.append(t)

            # 2. Known tickers from scan (full ticker or base part).
            # Guard: only match if base is >=3 chars -- prevents single-letter tickers
            # like "V" (Visa), "D" (Dominion), "T" (AT&T) from matching as substrings
            # of common Swedish words ("VAD", "AKTIER", etc.)
            for t in all_known:
                base = t.split(".")[0].upper()
                if len(base) < 3:
                    continue  # skip 1-2 char tickers - too many false positives
                if t.upper() in prompt_upper or re.search(rf'\b{re.escape(base)}\b', prompt_upper):
                    if t not in mentioned_tickers:
                        mentioned_tickers.append(t)

            # 3. News keywords trigger -> also grab top-scored ticker if no specific one found
            news_keywords = {"NYHETER", "NYHET", "NYHETSLÄGE", "NEWS", "RUBRIK",
                             "RAPPORT", "VD", "CEO", "PRESSRELEASE", "FÖRVÄRV"}
            wants_news = bool(news_keywords & set(re.findall(r'\b\w+\b', prompt_upper)))

            mentioned_tickers = list(dict.fromkeys(mentioned_tickers))[:4]

            if mentioned_tickers or wants_news:
                fetch_for = mentioned_tickers or []
                # If no specific ticker but user asks about news -> use top scored ticker
                if not fetch_for and wants_news and not df.empty and "score_total" in df.columns:
                    fetch_for = [df.nlargest(1, "score_total").iloc[0]["ticker"]]

                # Build ticker -> company name lookup from both scored DataFrames
                name_lookup: dict[str, str] = {}
                for _sdf in (df, sc_df):
                    if not _sdf.empty and "ticker" in _sdf.columns and "name" in _sdf.columns:
                        for _, _row in _sdf[["ticker", "name"]].dropna().iterrows():
                            t_key = str(_row["ticker"]).upper()
                            if t_key not in name_lookup and _row["name"]:
                                name_lookup[t_key] = str(_row["name"])

                try:
                    from core.news_fetcher import fetch_company_news
                    for mt in fetch_for:
                        cname = name_lookup.get(mt.upper())
                        news_list = fetch_company_news(mt, days_back=7, company_name=cname) or []
                        if news_list:
                            lines = []
                            for n in news_list[:8]:
                                title = n.get("headline", n.get("title", "")).strip()
                                src   = n.get("source", "")
                                age   = n.get("age_hours")
                                age_s = f" ({age:.0f}h sedan)" if age is not None else ""
                                if title:
                                    lines.append(f"- {title} [{src}]{age_s}")
                            if lines:
                                news_context_parts.append(f"{mt}:\n" + "\n".join(lines))
                except Exception:
                    pass

            context_str = ". ".join(context_parts) + "." if context_parts else ""
            if news_context_parts:
                context_str += "\n\nFärska nyheter:\n" + "\n\n".join(news_context_parts)

            full_context = context_str

            with st.chat_message("assistant"):
                spinner_msg = "AI analyserar..."
                if news_context_parts:
                    tickers_fetched = ", ".join(p.split(":\n")[0] for p in news_context_parts)
                    spinner_msg = f"Hämtade nyheter för {tickers_fetched} - AI analyserar..."
                with st.spinner(spinner_msg):
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
                        # Show fetched news as collapsible source below the answer
                        if news_context_parts:
                            total_lines = sum(p.count("\n- ") for p in news_context_parts)
                            with st.expander(f"📰 {total_lines} nyheter hämtades live", expanded=False):
                                for block in news_context_parts:
                                    st.markdown(block)
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
                    "Score": sc.get("score_total", "--"),
                    "Entry": sc.get("entry_signal", "--"),
                    "Trend": sc.get("trend_signal", "--"),
                })
            if rows:
                clickable_stock_table(pd.DataFrame(rows), ticker_col="Ticker", context_df=df,
                                      key="ai_portfolio_overview_table", caption="Klicka för analys.")
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
                news_options = {f"{h['ticker']} -- {h['name'][:50]}": h for h in news_hits}
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
                            _nt_row = df[df["ticker"] == news_ticker] if not df.empty and "ticker" in df.columns else pd.DataFrame()
                            _nt_name = str(_nt_row.iloc[0]["name"]) if not _nt_row.empty and "name" in _nt_row.columns else None
                            # Also check news_options if ticker came from search
                            if not _nt_name and news_search.strip() and "news_options" in dir():
                                _selected_hit = news_options.get(news_label, {})
                                _nt_name = _selected_hit.get("name")
                            fetched = fetch_company_news(news_ticker, days_back=7, company_name=_nt_name) or []
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
                    _raw_row = df[df["ticker"] == news_ticker] if not df.empty and "ticker" in df.columns else pd.DataFrame()
                    _raw_name = str(_raw_row.iloc[0]["name"]) if not _raw_row.empty and "name" in _raw_row.columns else None
                    raw_news = fetch_company_news(news_ticker, days_back=3, company_name=_raw_name) or []
                    if raw_news:
                        for n in raw_news[:8]:
                            title = n.get("headline", n.get("title", "--"))
                            src = n.get("source", "?")
                            url = n.get("url", "")
                            if url:
                                st.markdown(f"- [{title}]({url}) -- *{src}*")
                            else:
                                st.markdown(f"- {title} -- *{src}*")
                    else:
                        st.caption("Inga nyheter hittade för senaste 3 dagar.")
                except Exception:
                    st.caption("Kunde inte hämta nyheter.")

    # ── Flik 8: Multi-AI Ensemble (Project 4) ──────────────────────────────
    with tab_multi:
        st.subheader("🔀 Multi-AI Ensemble")
        st.caption("Analysera en aktie med flera AI-modeller samtidigt och jämför svaren sida vid sida.")

        # Provider-selector
        ensemble_mode = st.selectbox(
            "Provider-läge",
            ["Auto (ensemble)", "DeepSeek + Gemini", "DeepSeek + Claude", "Gemini + Claude", "Alla tre"],
            index=0,
            key="ensemble_mode",
        )

        mode_to_providers = {
            "Auto (ensemble)": ["deepseek", "gemini"],
            "DeepSeek + Gemini": ["deepseek", "gemini"],
            "DeepSeek + Claude": ["deepseek", "claude"],
            "Gemini + Claude": ["gemini", "claude"],
            "Alla tre": ["deepseek", "gemini", "claude"],
        }

        if not df.empty and "ticker" in df.columns:
            tickers = sorted(df["ticker"].tolist())
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                sel_ticker = st.selectbox("Välj aktie", tickers, key="ensemble_ticker")
            with col2:
                ensemble_depth = st.selectbox("Djup", ["Snabb", "Normal", "Djup"], index=1, key="ensemble_depth")
            with col3:
                st.markdown("<br>", unsafe_allow_html=True)
                run_ensemble = st.button("🤖 Kör ensemble", type="primary", use_container_width=True, key="btn_ensemble")

            if run_ensemble:
                with st.spinner(f"Frågar {len(mode_to_providers[ensemble_mode])} AI-modeller parallellt..."):
                    try:
                        providers = mode_to_providers[ensemble_mode]
                        ensemble = AiEnsemble()

                        # Bygg stock_data från DataFrame
                        stock_data = {}
                        match = df[df["ticker"] == sel_ticker]
                        if not match.empty:
                            row = match.iloc[0]
                            factor_fields = {
                                "score_total": "Total Score",
                                "score_value": "Value", "score_quality": "Quality",
                                "score_momentum": "Momentum", "score_growth": "Growth",
                                "score_risk": "Risk", "score_size": "Size",
                                "score_dividend": "Dividend", "score_sentiment": "Sentiment",
                                "entry_signal": "Entry Signal", "confidence_label": "Confidence",
                                "trend_signal": "Trend", "pe_trailing": "P/E (trailing)",
                                "roe": "ROE", "revenue_growth": "Revenue Growth",
                                "price_to_book": "P/B", "rsi_14": "RSI (14)",
                                "price_vs_ma200": "vs MA200", "piotroski_f": "Piotroski F-Score",
                                "sector": "Sector", "name": "Company Name",
                                "current_price": "Price", "return_1m": "1m Return",
                                "return_3m": "3m Return", "return_6m": "6m Return",
                            }
                            for field, label in factor_fields.items():
                                val = row.get(field)
                                if val is not None and not pd.isna(val):
                                    stock_data[label] = round(val, 2) if isinstance(val, float) else val

                        result = ensemble.ensemble_analysis(
                            sel_ticker,
                            stock_data=stock_data,
                            providers=providers,
                            depth=ensemble_depth,
                        )

                        # ---- Show consensus summary ----
                        st.markdown("---")
                        st.markdown("### Ensemble-resultat")
                        st.markdown(f"**Ticker:** {result.ticker}")

                        # Consensus badge + confidence
                        badge = _consensus_badge(result.agreement_level)
                        st.markdown(f"{badge} | **Consensus:** {result.consensus} | "
                                    f"**Konfidens:** {result.consensus_confidence:.0%}",
                                    unsafe_allow_html=True)

                        st.markdown(_confidence_bar(result.consensus_confidence), unsafe_allow_html=True)

                        if result.error:
                            st.warning(f"⚠️ {result.error}")

                        # ---- Show provider responses side by side ----
                        st.markdown("---")
                        st.markdown("### Svar från varje AI-modell")

                        # Spara till journal
                        from web.pages.ai_journal import record_ai_signal

                        provider_tabs = st.tabs([p.capitalize() for p in result.responses.keys()])

                        for idx, (p_name, (text, conf, rec)) in enumerate(result.responses.items()):
                            with provider_tabs[idx]:
                                if text:
                                    weight = result.provider_weights.get(p_name, 1.0)
                                    st.markdown(
                                        f"**Rekommendation:** {rec} | "
                                        f"**Konfidens:** {conf:.0%} | "
                                        f"**Vikt:** {weight:.1f}x",
                                    )
                                    st.markdown(_confidence_bar(conf), unsafe_allow_html=True)
                                    st.markdown(text)

                                    # Verifiera-knapp
                                    col_a, col_b = st.columns([1, 3])
                                    with col_a:
                                        v_key = f"verify_{p_name}_{sel_ticker}"
                                        if st.button(f"✅ Verifiera {p_name}", key=v_key):
                                            # Hämta aktuellt pris
                                            cur_price = None
                                            if not df.empty and "ticker" in df.columns:
                                                price_row = df[df["ticker"] == sel_ticker]
                                                if not price_row.empty:
                                                    cur_price = price_row.iloc[0].get("current_price") or price_row.iloc[0].get("close")

                                            if cur_price:
                                                from web.pages.ai_journal import record_ai_verification
                                                entry_price = stock_data.get("Price", 0)
                                                if entry_price and entry_price > 0:
                                                    ret = (float(cur_price) / float(entry_price) - 1) * 100
                                                    record_ai_verification(sel_ticker, rec, ret)
                                                    st.success(f"Verifierad! {sel_ticker} gick {ret:+.1f}% sedan signalen.")
                                                else:
                                                    st.warning("Saknar ingångspris för verifiering.")
                                            else:
                                                st.warning("Saknar aktuellt pris för verifiering.")

                                    # Spara signal
                                    try:
                                        sector = stock_data.get("Sector", "")
                                        record_ai_signal(
                                            sel_ticker, rec, conf,
                                            provider=p_name,
                                            context={
                                                "price": stock_data.get("Price"),
                                                "score": stock_data.get("Total Score"),
                                                "sector": sector,
                                                "snippet": text[:200],
                                                "signal_type": "ensemble",
                                            },
                                        )
                                    except Exception:
                                        pass
                                else:
                                    st.error(f"❌ {p_name.capitalize()} svarade inte: {rec}")

                        # ---- Spara ensemble-signal ----
                        try:
                            sector = stock_data.get("Sector", "")
                            record_ai_signal(
                                sel_ticker, result.consensus, result.consensus_confidence,
                                provider="ensemble",
                                context={
                                    "price": stock_data.get("Price"),
                                    "score": stock_data.get("Total Score"),
                                    "sector": sector,
                                    "snippet": f"Ensemble consensus: {result.consensus} "
                                               f"(agreement: {result.agreement_level})",
                                    "signal_type": "ensemble_consensus",
                                },
                            )
                        except Exception:
                            pass

                        # ---- Provider comparison table ----
                        st.markdown("---")
                        st.markdown("### Provider-jämförelse")
                        cmp_rows = []
                        for p_name, (text, conf, rec) in result.responses.items():
                            cmp_rows.append({
                                "Provider": p_name.capitalize(),
                                "Rekommendation": rec,
                                "Konfidens": f"{conf:.0%}",
                                "Vikt": f"{result.provider_weights.get(p_name, 1.0):.1f}x",
                                "Svarade": "Ja" if text else "Nej",
                            })
                        st.dataframe(pd.DataFrame(cmp_rows), use_container_width=True, hide_index=True)

                        # ---- Provider accuracy comparison ----
                        try:
                            acc_data = ensemble._load_provider_accuracy()
                            if acc_data:
                                st.markdown("---")
                                st.markdown("### Historisk träffsäkerhet")
                                acc_rows = []
                                for p, acc in sorted(acc_data.items(), key=lambda x: x[1], reverse=True):
                                    acc_rows.append({
                                        "Provider": p.capitalize(),
                                        "Accuracy": f"{acc:.1%}",
                                    })
                                st.dataframe(pd.DataFrame(acc_rows), use_container_width=True, hide_index=True)
                        except Exception:
                            pass

                    except Exception as e:
                        st.error(f"❌ Ensemble-analys misslyckades: {e}")
                        import traceback
                        st.exception(e)

            # Visa snabbdata för vald ticker
            if sel_ticker:
                row = df[df["ticker"] == sel_ticker]
                if not row.empty:
                    r = row.iloc[0]
                    st.markdown("---")
                    st.caption("📋 Snabbdata")
                    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
                    with cc1:
                        st.metric("Score", f"{r.get('score_total', '--'):.0f}/100" if not pd.isna(r.get('score_total')) else "--")
                    with cc2:
                        st.metric("Entry", r.get("entry_signal", "--"))
                    with cc3:
                        st.metric("Trend", r.get("trend_signal", "--"))
                    with cc4:
                        st.metric("RSI", f"{r.get('rsi_14', '--'):.0f}" if not pd.isna(r.get('rsi_14', '--')) else "--")
                    with cc5:
                        st.metric("Piotroski", f"{r.get('piotroski_f', '--')}/9" if not pd.isna(r.get('piotroski_f', '--')) else "--")
        else:
            st.info("Ingen scandata tillgänglig för ensemble-analys.")
