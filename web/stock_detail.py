"""
stock_detail.py – MarketScan Stock Detail Panel
================================================
En återanvändbar Streamlit-komponent som visar detaljerad information
för en enskild aktie: prisgraf, nyckeltal, nyhetsflöde och AI-analys.

Användning:
    from web.stock_detail import render_stock_detail

    # I din Streamlit-sida:
    render_stock_detail(
        ticker="AAPL",
        row=scored_df[scored_df["ticker"] == "AAPL"].iloc[0],  # rad från scored_universe
        df=scored_df,                                           # hela datasetet (för kontext)
    )
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core import config, data_fetcher
from core import ai_analysis

try:
    from core.news_fetcher import fetch_company_news as _fetch_news
except ImportError:
    _fetch_news = None


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════

def _safe_val(val, fmt: str = "num", default: str = "—"):
    """Returnera formaterat värde eller default om None/NaN."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except Exception:
        pass
    if fmt == "pct":
        return f"{float(val):.1f}%"
    if fmt == "pct_plus":
        return f"{float(val):+.1f}%"
    if fmt == "dec2":
        return f"{float(val):.2f}"
    if fmt == "dec0":
        return f"{float(val):.0f}"
    if fmt == "ratio":
        return f"{float(val):.1f}/9"
    return str(val)


def _get_depth() -> str:
    """Hämta valt AI-djup från sidebar/session state."""
    return st.session_state.get("selected_depth", "Normal")


def _provider_selector(key: str = "provider_default") -> str:
    """Visa en provider-väljare i UI och returnera vald provider."""
    options = {
        "auto": f"Auto ({config.AI_PROVIDER})",
        "deepseek": "DeepSeek (komplex, kostar)",
        "gemini": "Gemini (enkel, gratis)",
    }
    default_key = f"provider_{key}"
    if default_key not in st.session_state:
        st.session_state[default_key] = "auto"
    return st.selectbox(
        "AI-provider",
        list(options.keys()),
        format_func=lambda k: options.get(k, k),
        key=default_key,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. PRISGRAF
# ══════════════════════════════════════════════════════════════════════════════

PERIOD_OPTIONS = {
    "1m":  "1 månad",
    "3m":  "3 månader",
    "6m":  "6 månader",
    "1y":  "1 år",
    "2y":  "2 år",
    "5y":  "5 år",
    "max": "Max",
}


def _price_chart(ticker: str, period: str = "1y") -> Optional[go.Figure]:
    """
    Skapa en prisgraf med volym och glidande medelvärden.
    Returnerar None om data saknas.
    """
    hist = data_fetcher.fetch_price_history(ticker, period=period)
    if hist.empty:
        return None

    # Beräkna glidande medelvärden
    hist["MA50"] = hist["Close"].rolling(50).mean() if len(hist) >= 50 else None
    hist["MA200"] = hist["Close"].rolling(200).mean() if len(hist) >= 200 else None

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.75, 0.25],
    )

    # ── Candlestick ──────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=hist.index,
        open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        name="Pris",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # ── Glidande medelvärden ─────────────────────────────────────────────
    if hist["MA50"] is not None and not hist["MA50"].isna().all():
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["MA50"],
            line=dict(color="#ffd600", width=1.2),
            name="MA50",
        ), row=1, col=1)

    if hist["MA200"] is not None and not hist["MA200"].isna().all():
        fig.add_trace(go.Scatter(
            x=hist.index, y=hist["MA200"],
            line=dict(color="#e040fb", width=1.2),
            name="MA200",
        ), row=1, col=1)

    # ── Volym ────────────────────────────────────────────────────────────
    colors = ["#26a69a" if hist["Close"].iloc[i] >= hist["Open"].iloc[i]
              else "#ef5350" for i in range(len(hist))]
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=colors,
        name="Volym",
        opacity=0.4,
    ), row=2, col=1)

    # ── Layout ───────────────────────────────────────────────────────────
    fig.update_layout(
        title=f"{ticker} – Prisutveckling ({PERIOD_OPTIONS.get(period, period)})",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        paper_bgcolor="#131722",
        plot_bgcolor="#1e2230",
        height=440,
        margin=dict(t=44, b=16, l=16, r=16),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
    )

    fig.update_yaxes(title_text="Pris (SEK)", row=1, col=1, color="#8892a4")
    fig.update_yaxes(title_text="Volym", row=2, col=1, color="#8892a4")
    fig.update_xaxes(color="#8892a4")

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 2. DATA-KORT (snabbvy)
# ══════════════════════════════════════════════════════════════════════════════

_QUICK_CARD_HELP = {
    "Score":     "Totalpoäng 0–100 från 8 faktorer: värdering, kvalitet, momentum, tillväxt, risk och storlek. 70+ = stark. 50–69 = neutral. Under 50 = svag.",
    "Entry":     "Köpsignal: STARK = tydlig uppåtrörelse med stöd av volym. OK = måttlig signal. — = ingen signal. Klicka på aktien för mer detaljer.",
    "Trend":     "Teknisk trend: UPPTREND = aktien är över MA50 och MA200 (glidande medelvärden). NEDTREND = under MA200. Viktig för tajming.",
    "RSI":       "Relative Strength Index (0–100). Mäter om aktien är överköpt eller översåld. Under 30 = översåld (möjligt köpläge). Över 70 = överköpt (försiktig).",
    "P/E":       "Pris/Vinst (trailing). Hur många kronor du betalar per vinstkrona. Lägre = billigare relativt vinst. Normalt 10–20. Negativt = bolaget går med förlust.",
    "ROE":       "Return on Equity — avkastning på eget kapital. Visar hur effektivt bolaget använder ägarnas pengar. Över 15% = bra. Över 25% = utmärkt.",
    "Piotroski": "Piotroski F-Score (0–9). Nio nyckeltal för lönsamhet, skuldsättning och effektivitet. 7–9 = stark fundamenta. 4–6 = godkänd. 0–3 = svag.",
}

def _quick_data_cards(row: pd.Series):
    """Visa en rad med metrik-kort för aktuell aktie."""
    cols = st.columns(7)

    metrics = [
        ("Score", row.get("score_total"), "dec0", "🎯"),
        ("Entry", row.get("entry_signal"), None, "⚡"),
        ("Trend", row.get("trend_signal"), None, "📈"),
        ("RSI", row.get("rsi_14"), "dec0", "🌡️"),
        ("P/E", row.get("pe_trailing"), "dec1", "💰"),
        ("ROE", row.get("roe"), "pct", "📊"),
        ("Piotroski", row.get("piotroski_f"), "ratio", "🔬"),
    ]

    for col, (label, val, fmt, icon) in zip(cols, metrics):
        with col:
            formatted = _safe_val(val, fmt if fmt else "num")
            st.metric(f"{icon} {label}", formatted, help=_QUICK_CARD_HELP.get(label))


# ══════════════════════════════════════════════════════════════════════════════
# UTDELNINGSANALYS
# ══════════════════════════════════════════════════════════════════════════════

def _render_dividend_analysis(row: pd.Series):
    """Visar utdelningsanalys med historik, nyckeltal och säkerhetsbedömning."""
    import yfinance as yf
    import plotly.graph_objects as go

    ticker = str(row.get("ticker", ""))
    yld    = row.get("dividend_yield")
    pr     = row.get("payout_ratio")
    fcf    = row.get("free_cash_flow")
    div_rate  = row.get("dividend_rate")
    yld_5y    = row.get("div_yield_5y_avg")
    score_div = row.get("score_dividend")

    # ── Ingen utdelning → kort info ───────────────────────────────────────────
    no_div = (yld is None or pd.isna(yld) or float(yld) == 0)
    if no_div and (div_rate is None or pd.isna(div_rate)):
        st.info("📭 Bolaget betalar ingen utdelning.")
        misc = {
            "Utdelningsscore": _safe_val(score_div, "dec0"),
            "Sektor": str(row.get("sector", "—")),
            "Industri": str(row.get("industry", "—")),
            "Land": str(row.get("country", "—")),
        }
        st.dataframe(pd.DataFrame(misc.items(), columns=["Mått", "Värde"]),
                     use_container_width=True, hide_index=True)
        return

    # ── KPI-kort ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Direktavkastning", f"{float(yld)*100:.2f}%" if yld and not pd.isna(yld) else "—",
              help="Årlig utdelning ÷ aktiekurs. 2–4% = normalt för stabila bolag. Mycket hög yield (>6–7%) kan vara en varningssignal om att kursen rasat eller utdelningen snart sänks.")
    c2.metric("📊 5Y snittyield",    f"{float(yld_5y):.2f}%" if yld_5y and not pd.isna(yld_5y) else "—",
              help="Genomsnittlig direktavkastning de senaste 5 åren. Jämför med dagens yield — om dagens är mycket högre kan det tyda på att aktien är nedtryckt eller utdelningen är hotad.")
    c3.metric("💵 Utd/aktie (årl.)", f"{float(div_rate):.2f}" if div_rate and not pd.isna(div_rate) else "—",
              help="Total utdelning per aktie per år i bolagets rapportvaluta. Används för att beräkna din faktiska inkomst per aktie du äger.")
    c4.metric("🎯 Utdelningsscore",  f"{float(score_div):.0f}/100" if score_div and not pd.isna(score_div) else "—",
              help="Sammanvägt poäng för utdelningskvalitet: direktavkastning, payout ratio, FCF-täckning och historisk stabilitet. 70+ = hög kvalitet. Under 40 = försiktig.")

    # ── Säkerhetsbedömning ────────────────────────────────────────────────────
    st.markdown("#### 🔒 Utdelningens säkerhet")
    safety_rows = []

    # Payout ratio
    if pr and not pd.isna(pr):
        pr_f = float(pr) * 100
        if pr_f > 100:
            pr_icon, pr_label = "🔴", f"{pr_f:.0f}% — Utdelningen överstiger vinsten! Hög risk."
        elif pr_f > 80:
            pr_icon, pr_label = "🟡", f"{pr_f:.0f}% — Ansträngd utdelningsandel, bevaka."
        elif pr_f > 0:
            pr_icon, pr_label = "🟢", f"{pr_f:.0f}% — Hållbar utdelningsandel."
        else:
            pr_icon, pr_label = "⚪", "—"
        safety_rows.append(("Payout Ratio (vinst)", f"{pr_icon} {pr_label}"))

    # FCF coverage
    if fcf and not pd.isna(fcf) and div_rate and not pd.isna(div_rate):
        try:
            shares = row.get("sharesOutstanding") or row.get("shares_outstanding")
            if shares and not pd.isna(shares):
                total_div = float(div_rate) * float(shares)
                fcf_cov = float(fcf) / total_div if total_div > 0 else None
                if fcf_cov is not None:
                    if fcf_cov < 1.0:
                        fcf_icon, fcf_label = "🔴", f"{fcf_cov:.1f}× — Fritt kassaflöde täcker EJ utdelningen."
                    elif fcf_cov < 1.5:
                        fcf_icon, fcf_label = "🟡", f"{fcf_cov:.1f}× — Liten marginal i kassaflödet."
                    else:
                        fcf_icon, fcf_label = "🟢", f"{fcf_cov:.1f}× — Utdelningen täcks väl av fritt kassaflöde."
                    safety_rows.append(("FCF-täckning", f"{fcf_icon} {fcf_label}"))
        except Exception:
            pass

    # Yield vs 5Y average
    if yld and not pd.isna(yld) and yld_5y and not pd.isna(yld_5y):
        try:
            diff = (float(yld) * 100) - float(yld_5y)
            if diff > 1.5:
                y_icon, y_label = "🟡", f"Yield {diff:+.1f}pp över 5-årssnitt — kan vara utdelningstrap eller pressad aktiekurs."
            elif diff < -1.5:
                y_icon, y_label = "🟢", f"Yield {diff:+.1f}pp under 5-årssnitt — aktien värderas relativt högt."
            else:
                y_icon, y_label = "🟢", f"Yield nära 5-årssnitt ({float(yld_5y):.1f}%) — normalt historiskt läge."
            safety_rows.append(("Yield vs historik", f"{y_icon} {y_label}"))
        except Exception:
            pass

    if safety_rows:
        st.dataframe(pd.DataFrame(safety_rows, columns=["Mått", "Bedömning"]),
                     use_container_width=True, hide_index=True)

    # ── Utdelningshistorik ────────────────────────────────────────────────────
    st.markdown("#### 📅 Utdelningshistorik (senaste 7 åren)")
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is not None and not divs.empty:
            # Aggregera till årsvis
            divs.index = pd.to_datetime(divs.index).tz_localize(None)
            annual = divs.resample("YE").sum()
            annual = annual[annual > 0].tail(7)

            if not annual.empty:
                years = [str(d.year) for d in annual.index]
                amounts = annual.values.tolist()

                # Beräkna tillväxttakt
                if len(amounts) >= 2:
                    cagr_1y = (amounts[-1] / amounts[-2] - 1) * 100 if amounts[-2] > 0 else None
                    if len(amounts) >= 4:
                        cagr_3y = ((amounts[-1] / amounts[-4]) ** (1/3) - 1) * 100 if amounts[-4] > 0 else None
                    else:
                        cagr_3y = None
                    if len(amounts) >= 6:
                        cagr_5y = ((amounts[-1] / amounts[-6]) ** (1/5) - 1) * 100 if amounts[-6] > 0 else None
                    else:
                        cagr_5y = None
                else:
                    cagr_1y = cagr_3y = cagr_5y = None

                # Färgkoda staplar — grön = tillväxt, röd = minskning
                bar_colors = []
                for i, a in enumerate(amounts):
                    if i == 0 or amounts[i-1] == 0:
                        bar_colors.append("#42a5f5")
                    elif a >= amounts[i-1]:
                        bar_colors.append("#22c55e")
                    else:
                        bar_colors.append("#ef4444")

                fig = go.Figure(go.Bar(
                    x=years, y=amounts,
                    marker_color=bar_colors,
                    text=[f"{a:.2f}" for a in amounts],
                    textposition="outside",
                ))
                fig.update_layout(
                    template="plotly_dark", paper_bgcolor="#131722", plot_bgcolor="#1e2230",
                    height=260, margin=dict(t=24, b=16, l=16, r=16),
                    yaxis=dict(title="Utdelning per aktie"),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

                # Tillväxttakter
                gr_cols = st.columns(3)
                gr_cols[0].metric("Tillväxt 1Y",
                    f"{cagr_1y:+.1f}%" if cagr_1y is not None else "—",
                    delta_color="normal",
                    help="Förändring i utdelning per aktie det senaste året. Positiv = utdelningen höjdes. 5–10% tillväxt per år = utmärkt utdelningsbolag.")
                gr_cols[1].metric("Tillväxt 3Y (CAGR)",
                    f"{cagr_3y:+.1f}%" if cagr_3y is not None else "—",
                    delta_color="normal",
                    help="Genomsnittlig årlig utdelningstillväxt de senaste 3 åren (CAGR). Visar om bolaget konsekvent höjer utdelningen eller om det är ojämnt.")
                gr_cols[2].metric("Tillväxt 5Y (CAGR)",
                    f"{cagr_5y:+.1f}%" if cagr_5y is not None else "—",
                    delta_color="normal",
                    help="Genomsnittlig årlig utdelningstillväxt de senaste 5 åren. Långsiktig trend — utdelningsbolag med 5%+ CAGR under 5 år är attraktiva för passiv inkomst.")

                # Konsistens
                n_years = len(amounts)
                n_growing = sum(1 for i in range(1, len(amounts)) if amounts[i] >= amounts[i-1])
                consistency = n_growing / (n_years - 1) * 100 if n_years > 1 else 0
                if consistency >= 80:
                    st.success(f"✅ Konsistent utdelningstillväxt {n_growing}/{n_years-1} år ({consistency:.0f}%)")
                elif consistency >= 50:
                    st.info(f"📊 Blandad utdelningshistorik {n_growing}/{n_years-1} år med tillväxt ({consistency:.0f}%)")
                else:
                    st.warning(f"⚠️ Ojämn utdelningshistorik — minskade {n_years-1-n_growing} av {n_years-1} år")
            else:
                st.info("Ingen utdelningshistorik tillgänglig.")
        else:
            st.info("Ingen utdelningshistorik hittades via yfinance.")
    except Exception as e:
        st.caption(f"Kunde inte hämta utdelningshistorik: {e}")

    # ── Övrigt ────────────────────────────────────────────────────────────────
    misc_data = {
        "Sektor":  str(row.get("sector", "—")),
        "Industri": str(row.get("industry", "—")),
        "Land":    str(row.get("country", "—")),
    }
    st.dataframe(pd.DataFrame(misc_data.items(), columns=["Mått", "Värde"]),
                 use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# 3. DETALJERAD DATA-TABELL
# ══════════════════════════════════════════════════════════════════════════════

def _detail_table(row: pd.Series):
    """Visa detaljerad data i expanderbara sektioner."""
    with st.expander("📋 All data", expanded=False):
        tab_val, tab_qual, tab_mom, tab_risk, tab_div = st.tabs([
            "Värdering", "Kvalitet", "Momentum", "Risk", "Övrigt"
        ])

        with tab_val:
            val_rows = [
                ("P/E (trailing)", _safe_val(row.get("pe_trailing"), "dec1"),
                 "Pris ÷ vinst per aktie (historisk). Lägre = billigare. 10–20 = normalt. Negativt = bolaget förlorar pengar."),
                ("P/E (forward)", _safe_val(row.get("pe_forward"), "dec1"),
                 "Pris ÷ förväntad framtida vinst. Om lägre än trailing P/E förväntas vinsttillväxt."),
                ("P/B", _safe_val(row.get("price_to_book"), "dec2"),
                 "Pris ÷ bokfört värde per aktie. Under 1.0 = handlas under substansvärde. Bankaktier har ofta lågt P/B."),
                ("P/S", _safe_val(row.get("price_to_sales"), "dec2"),
                 "Pris ÷ omsättning per aktie. Lägre = billigare relativt försäljning. Bra för förlustbolag utan vinst."),
                ("EV/EBITDA", _safe_val(row.get("ev_to_ebitda"), "dec1"),
                 "Företagsvärde ÷ rörelseresultat före avskrivningar. Under 10 = relativt billigt. Används för att jämföra bolag med olika skuldsättning."),
                ("EV/Revenue", _safe_val(row.get("ev_to_revenue"), "dec2"),
                 "Företagsvärde ÷ omsättning. Bra för att jämföra tillväxtbolag utan vinst. Under 2 = lågt."),
                ("PEG Ratio", _safe_val(row.get("peg_ratio"), "dec2"),
                 "P/E ÷ förväntad vinsttillväxt. Under 1.0 = aktien kan vara undervärderad relativt sin tillväxt. Populariserad av Peter Lynch."),
                ("Värderingsscore", _safe_val(row.get("score_value"), "dec0"),
                 "Systemets sammanvägda värderingspoäng 0–100 baserat på ovanstående nyckeltal. Högt = relativt billig aktie."),
            ]
            st.dataframe(
                pd.DataFrame(val_rows, columns=["Mått", "Värde", "ℹ️ Förklaring"]),
                use_container_width=True, hide_index=True,
                column_config={"ℹ️ Förklaring": st.column_config.TextColumn("ℹ️ Förklaring", width="large")},
            )

        with tab_qual:
            qual_rows = [
                ("ROE", _safe_val(row.get("roe"), "pct"),
                 "Return on Equity — avkastning på eget kapital. Visar hur effektivt bolaget tjänar pengar på ägarnas investering. 15%+ = bra, 25%+ = utmärkt."),
                ("ROA", _safe_val(row.get("roa"), "pct"),
                 "Return on Assets — avkastning på totalt kapital. 5%+ = bra. Viktigt för kapitalintensiva branscher som tillverkning."),
                ("Bruttomarginal", _safe_val(row.get("gross_margin"), "pct"),
                 "(Intäkter − kostnader för sålda varor) ÷ intäkter. Hög marginal = starkt prissättningsutrymme. Tech/pharma har ofta 60–80%."),
                ("Rörelsemarginal", _safe_val(row.get("operating_margin"), "pct"),
                 "Rörelseresultat ÷ omsättning. Visar lönsamhet efter löner och drift men före räntor och skatt. 10%+ = bra."),
                ("Nettomarginal", _safe_val(row.get("profit_margin"), "pct"),
                 "Nettovinst ÷ omsättning. Den slutliga vinsten per intäktskrona efter alla kostnader inklusive skatt och räntor."),
                ("FCF", _safe_val(row.get("free_cash_flow"), "dec0"),
                 "Fritt kassaflöde — kassa som genereras efter investeringar. Positivt = bolaget genererar pengar. Används för utdelning, återköp eller tillväxt."),
                ("Piotroski F-Score", _safe_val(row.get("piotroski_f"), "ratio"),
                 "9 binära nyckeltal för finansiell styrka: lönsamhet (4p), finansiering (3p), effektivitet (2p). 7–9 = stark. 0–2 = svag."),
                ("Kvalitetsscore", _safe_val(row.get("score_quality"), "dec0"),
                 "Systemets sammanvägda kvalitetspoäng 0–100 baserat på ovanstående. Högt = finansiellt starkt bolag."),
            ]
            st.dataframe(
                pd.DataFrame(qual_rows, columns=["Mått", "Värde", "ℹ️ Förklaring"]),
                use_container_width=True, hide_index=True,
                column_config={"ℹ️ Förklaring": st.column_config.TextColumn("ℹ️ Förklaring", width="large")},
            )

        with tab_mom:
            mom_rows = [
                ("1 månad", _safe_val(row.get("return_1m"), "pct_plus"),
                 "Kursavkastning senaste månaden. Kortsiktigt momentum — positiv = aktien rört sig uppåt nyligen."),
                ("3 månader", _safe_val(row.get("return_3m"), "pct_plus"),
                 "Kursavkastning senaste 3 månaderna. Mellanlångt momentum. Viktig faktor för teknisk analys."),
                ("6 månader", _safe_val(row.get("return_6m"), "pct_plus"),
                 "Kursavkastning senaste 6 månaderna. Stark 6m-avkastning = etablerad upptrend."),
                ("12 månader", _safe_val(row.get("return_12m"), "pct_plus"),
                 "Kursavkastning senaste 12 månaderna. Långsiktigt momentum — den starkaste prediktorn för fortsatt avkastning (momentum-faktor)."),
                ("vs MA50", _safe_val(row.get("price_vs_ma50"), "pct_plus"),
                 "Hur mycket aktiekursen ligger över/under 50-dagars glidande medelvärde. Positiv = kurs över MA50 = teknisk styrka."),
                ("vs MA200", _safe_val(row.get("price_vs_ma200"), "pct_plus"),
                 "Hur mycket kursen ligger över/under 200-dagars medelvärde. Positiv = långsiktig upptrend. Att ligga under MA200 kallas 'death cross'-zonen."),
                ("RSI (14)", _safe_val(row.get("rsi_14"), "dec0"),
                 "Relative Strength Index: 0–100. Under 30 = översåld (potentiellt köpläge). Över 70 = överköpt (potentiellt säljläge). 40–60 = neutral."),
                ("MACD ovan signal", str(row.get("macd_above_signal", "—")),
                 "Moving Average Convergence Divergence: True = momentum är uppåt (MACD-linjen är över signallinjen). False = nedåtmomentum."),
                ("Momentumscore", _safe_val(row.get("score_momentum"), "dec0"),
                 "Systemets sammanvägda momentumpoäng 0–100. Högt = aktien är i stark upptrend på kort och lång sikt."),
            ]
            st.dataframe(
                pd.DataFrame(mom_rows, columns=["Mått", "Värde", "ℹ️ Förklaring"]),
                use_container_width=True, hide_index=True,
                column_config={"ℹ️ Förklaring": st.column_config.TextColumn("ℹ️ Förklaring", width="large")},
            )

        with tab_risk:
            risk_rows = [
                ("Beta", _safe_val(row.get("beta"), "dec2"),
                 "Rörelsekänslighet vs marknaden. 1.0 = rör sig som index. 1.5 = 50% mer volatil än index. Under 0.8 = defensiv aktie."),
                ("Volatilitet", _safe_val(row.get("volatility"), "pct"),
                 "Historisk prisvariabilitet (standardavvikelse av dagliga avkastningar). Hög volatilitet = aktien svänger mycket. Riskfyllt men även möjlighet."),
                ("D/E", _safe_val(row.get("debt_to_equity"), "dec0"),
                 "Skuld ÷ eget kapital. Mäter hur skuldsatt bolaget är. Under 1.0 = låg skuldsättning. Över 2.0 = hög hävstång — känsligare vid ränteuppgång."),
                ("Current Ratio", _safe_val(row.get("current_ratio"), "dec2"),
                 "Omsättningstillgångar ÷ kortfristiga skulder. Mäter kortsiktig betalningsförmåga. Över 1.5 = bra. Under 1.0 = kan ha problem att betala räkningar."),
                ("Quick Ratio", _safe_val(row.get("quick_ratio"), "dec2"),
                 "Som Current Ratio men exkluderar lager (som kan vara svårt att sälja snabbt). Över 1.0 = god likviditet."),
                ("52v High", _safe_val(row.get("pct_from_52w_high"), "pct_plus"),
                 "Hur långt aktiekursen är från sin 52-veckorshöjning. −10% = 10% under toppnivån. Aktier nära 52v-high har ofta starkt momentum."),
                ("Riskscore", _safe_val(row.get("score_risk"), "dec0"),
                 "Systemets sammanvägda riskpoäng 0–100. Högt = låg risk (stabilt bolag med låg skuld och volatilitet). Lågt = hög risk."),
            ]
            st.dataframe(
                pd.DataFrame(risk_rows, columns=["Mått", "Värde", "ℹ️ Förklaring"]),
                use_container_width=True, hide_index=True,
                column_config={"ℹ️ Förklaring": st.column_config.TextColumn("ℹ️ Förklaring", width="large")},
            )

        with tab_div:
            _render_dividend_analysis(row)


# ══════════════════════════════════════════════════════════════════════════════
# 4. SCORE-RADARCHART
# ══════════════════════════════════════════════════════════════════════════════

def _radar_chart(row: pd.Series) -> go.Figure:
    """Skapa en radarchart över de 8 faktorerna."""
    score_fields = [
        ("score_value", "Värdering"),
        ("score_quality", "Kvalitet"),
        ("score_momentum", "Momentum"),
        ("score_growth", "Tillväxt"),
        ("score_risk", "Risk"),
        ("score_size", "Storlek"),
        ("score_dividend", "Utdelning"),
        ("score_sentiment", "Sentiment"),
    ]

    categories = [label for _, label in score_fields]
    values = []
    for field, _ in score_fields:
        v = row.get(field)
        v = float(v) if v is not None and not pd.isna(v) else 0
        values.append(v)

    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor="rgba(66, 165, 245, 0.25)",
        line=dict(color="#42a5f5", width=2),
        name="Scoreprofil",
    ))

    fig.update_layout(
        title="🕸️ 8-faktorsprofil",
        template="plotly_dark",
        paper_bgcolor="#131722",
        polar=dict(
            bgcolor="#1e2230",
            radialaxis=dict(range=[0, 100], color="#8892a4", showticklabels=True),
            angularaxis=dict(color="#8892a4"),
        ),
        height=380,
        margin=dict(t=44, b=20, l=60, r=60),
    )

    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 5. NYHETSFLÖDE
# ══════════════════════════════════════════════════════════════════════════════

def _news_feed(ticker: str, company_name: str = None):
    """Visa de senaste nyheterna för en aktie."""
    st.subheader("📰 Nyheter")

    if _fetch_news is None:
        st.info("news_fetcher-modulen är inte tillgänglig.")
        return

    try:
        news = _fetch_news(ticker, days_back=7, company_name=company_name)
    except Exception as e:
        st.info(f"Kunde inte hämta nyheter: {e}")
        news = []

    if not news:
        st.caption("Inga nyheter den senaste veckan.")
        return

    for item in news[:10]:
        title = item.get("headline") or item.get("title") or "—"
        source = item.get("source", "?")
        date_raw = item.get("datetime") or item.get("publishedAt") or ""
        date_str = ""
        if date_raw:
            try:
                dt = datetime.fromisoformat(str(date_raw).replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                date_str = str(date_raw)[:10]

        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{title}**")
            with c2:
                if source and source.lower() not in ("", "?"):
                    st.caption(f"📡 {source}")
                if date_str:
                    st.caption(f"🕐 {date_str}")

            # Kort sammanfattning om tillgänglig
            summary = item.get("summary") or item.get("description") or ""
            if summary:
                st.caption(summary[:200])


# ══════════════════════════════════════════════════════════════════════════════
# 6. AI-ANALYS-PANEL
# ══════════════════════════════════════════════════════════════════════════════

AI_PRESET_PROMPTS = {
    "📈 Fullständig analys": "full",
    "🎯 Sammanfattning (kort)": "brief",
    "💰 Värderingsfokus": "value",
    "📊 Tekniskt fokus": "technical",
    "⚠️ Riskfokus": "risk",
    "🔮 Framtidsutsikter": "outlook",
    "✏️ Egen fråga": "custom",
}

AI_PROMPTS_MAP = {
    "full": ("Fullständig analys", ""),
    "brief": (
        "Kort sammanfattning",
        "Ge en kort sammanfattning av aktien. Max 100 ord. Fokusera på "
        "det viktigaste: är detta ett köp eller inte just nu?"
    ),
    "value": (
        "Värderingsfokus",
        "Analysera endast värderingen. Kommentera P/E, P/B, EV/EBITDA "
        "i relation till sektorn. Är aktien billig eller dyr?"
    ),
    "technical": (
        "Tekniskt fokus",
        "Analysera endast teknisk data: RSI, MACD, MA50/MA200, trender, "
        "volym. Bullish eller bearish setup?"
    ),
    "risk": (
        "Riskfokus",
        "Fokusera på risker: skuldsättning, volatilitet, beta, short-interest, "
        "sektorkoncentration. Vilka är de största riskerna?"
    ),
    "outlook": (
        "Framtidsutsikter",
        "Baserat på tillgänglig data, vad är dina framtidsutsikter för "
        "denna aktie de kommande 3-6 månaderna?"
    ),
}


def _ai_analysis_panel(ticker: str, row: pd.Series, df: pd.DataFrame, company_name: str = ""):
    """AI-analyspanel med preset prompts och provider-väljare."""
    st.subheader("🤖 AI-analys")

    # Provider-väljare
    provider = _provider_selector(f"detail_{ticker}")

    # Förifyllda frågor
    preset_options = list(AI_PRESET_PROMPTS.keys())
    selected_preset = st.selectbox("Välj analys-typ", preset_options, key=f"ai_preset_{ticker}")

    custom_question = ""
    if selected_preset == "✏️ Egen fråga":
        custom_question = st.text_area(
            "Din fråga om aktien:",
            placeholder="Ställ en egen fråga om aktien...",
            key=f"ai_custom_q_{ticker}",
            height=80,
        )

    force_refresh = st.checkbox("Hoppa över cache", key=f"ai_refresh_{ticker}")

    # Analysera-knapp
    analyze_col1, analyze_col2 = st.columns([3, 1])
    with analyze_col1:
        clicked = st.button(
            "🤖 Analysera",
            key=f"btn_ai_detail_{ticker}",
            type="primary",
            use_container_width=True,
        )
    with analyze_col2:
        # Nyhetsanalys-knapp
        news_clicked = st.button(
            "📰 Analysera nyheter",
            key=f"btn_news_detail_{ticker}",
            use_container_width=True,
        )

    if clicked:
        # Bestäm vilken prompt som ska användas
        preset_key = AI_PRESET_PROMPTS[selected_preset]
        if preset_key == "custom":
            if not custom_question.strip():
                st.warning("Skriv en fråga först.")
                return
            # Använd chat-funktionen för egen fråga
            with st.spinner(f"🤖 Hämtar nyheter och analyserar {ticker}..."):
                try:
                    # Bygg stockdata-kontext
                    context_fields = {}
                    for field in ["score_total", "sector", "current_price", "name",
                                  "pe_trailing", "roe", "rsi_14", "trend_signal",
                                  "entry_signal", "piotroski_f", "return_1m",
                                  "return_3m", "return_12m", "price_vs_ma200"]:
                        v = row.get(field)
                        if v is not None and not pd.isna(v):
                            context_fields[field] = float(v) if isinstance(v, (int, float)) else v

                    stock_json = ai_analysis._safe_json(context_fields, ensure_ascii=False)

                    # Hämta live-nyheter
                    news_lines = []
                    if _fetch_news is not None:
                        try:
                            raw = _fetch_news(ticker, days_back=7, company_name=company_name) or []
                            for n in raw[:8]:
                                title = n.get("headline", n.get("title", "")).strip()
                                src   = n.get("source", "")
                                age   = n.get("age_hours")
                                age_s = f" ({age:.0f}h sedan)" if age is not None else ""
                                if title:
                                    news_lines.append(f"- {title} [{src}]{age_s}")
                        except Exception:
                            pass

                    # Slå ihop: stock-JSON + nyheter med separator som ai_chat förstår
                    full_context = stock_json
                    if news_lines:
                        full_context += "\n\nFärska nyheter:\n" + "\n".join(news_lines)

                    depth = _get_depth()
                    result = ai_analysis.ai_chat(
                        f"Aktie: {ticker}\n\n{custom_question}",
                        context=full_context,
                        force_refresh=force_refresh,
                        provider=provider,
                        depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                    if news_lines:
                        with st.expander(f"📋 {len(news_lines)} nyheter hämtades", expanded=False):
                            for line in news_lines:
                                st.markdown(line)
                except Exception as e:
                    st.error(f"❌ {e}")
        else:
            with st.spinner(f"🤖 AI (via {provider}) analyserar..."):
                try:
                    depth = _get_depth()
                    result = ai_analysis.analyze_stock(
                        ticker, df=df, force_refresh=force_refresh, provider=provider,
                        depth=depth,
                    )
                    with st.container(border=True):
                        st.markdown(result)
                except Exception as e:
                    st.error(f"❌ {e}")

    if news_clicked:
        # Hämta och analysera nyheter
        with st.spinner("Hämtar och analyserar nyheter..."):
            try:
                news_items = None
                if _fetch_news is not None:
                    try:
                        raw_news = _fetch_news(ticker, days_back=7, company_name=company_name)
                        if raw_news:
                            news_items = [
                                {
                                    "title": n.get("headline", n.get("title", "")),
                                    "summary": n.get("summary", n.get("description", "")),
                                    "source": n.get("source", "?"),
                                    "date": n.get("datetime", n.get("publishedAt", "")),
                                }
                                for n in raw_news[:10]
                            ]
                    except Exception:
                        pass

                depth = _get_depth()
                result = ai_analysis.analyze_news(
                    ticker, news_items=news_items,
                    force_refresh=force_refresh, provider=provider,
                    depth=depth,
                )
                with st.container(border=True):
                    st.markdown(result)
            except Exception as e:
                st.error(f"❌ {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDKOMPONENT – render_stock_detail
# ══════════════════════════════════════════════════════════════════════════════

def render_stock_detail(
    ticker: str,
    row: pd.Series = None,
    df: pd.DataFrame = None,
    show_ai: bool = True,
    show_news: bool = True,
    show_chart: bool = True,
    show_detail_data: bool = True,
):
    """
    Rendera hela Stock Detail Panel för en ticker.

    Args:
        ticker: Ticker-symbol (t.ex. "AAPL")
        row: Rad från scored_universe DataFrame med aktuell data
        df: Hela scored_universe DataFrame (för AI-kontext)
        show_ai: Visa AI-analyspanel
        show_news: Visa nyhetsflöde
        show_chart: Visa prisgraf
        show_detail_data: Visa detaljerad data
    """
    company_name = ""
    industry_str = ""
    if row is not None and not row.empty:
        company_name = str(row.get("name", "")).strip()
        industry_str = str(row.get("industry", "")).strip()

    display_title = f"`{ticker}`" + (f" — {company_name}" if company_name else "")
    st.markdown(f"## 📈 {display_title}")
    if industry_str and industry_str not in ("—", "nan", "None", ""):
        st.caption(f"🏭 {industry_str}")
    st.markdown("---")

    # ── Sektion 1: Snabbdata-kort ──────────────────────────────────────────
    if row is not None and not row.empty:
        _quick_data_cards(row)

    # ── Sektion 2: Prisgraf + Radar ────────────────────────────────────────
    if show_chart:
        period = st.selectbox(
            "Välj tidsperiod",
            list(PERIOD_OPTIONS.keys()),
            format_func=lambda k: PERIOD_OPTIONS[k],
            index=3,  # Default: 1y
            key=f"period_{ticker}",
        )

        chart = _price_chart(ticker, period=period)
        if chart is not None:
            st.plotly_chart(chart, use_container_width=True)
        else:
            st.info("Prisdata saknas för denna aktie.")

        # Radar-chart bredvid prisgraf?
        if row is not None and not row.empty:
            c1, c2 = st.columns([3, 2])
            with c1:
                pass  # Utrymme för framtida användning
            with c2:
                st.plotly_chart(_radar_chart(row), use_container_width=True)

    st.markdown("---")

    # ── Sektion 3: Detaljerad data ─────────────────────────────────────────
    if show_detail_data and row is not None and not row.empty:
        _detail_table(row)

    # ── Sektion 4: Nyhetsflöde + AI sida vid sida ─────────────────────────
    col_news, col_ai = st.columns([1, 1])

    with col_news:
        if show_news:
            _news_feed(ticker, company_name=company_name)

    with col_ai:
        if show_ai and row is not None and not row.empty:
            _ai_analysis_panel(ticker, row, df, company_name=company_name)

    # ── Botten: API-status ─────────────────────────────────────────────────
    st.markdown("---")
    with st.container():
        st.caption(
            f"💰 Data från yfinance | "
            f"🤖 AI: {config.AI_PROVIDER} (DeepSeek) / Gemini | "
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
