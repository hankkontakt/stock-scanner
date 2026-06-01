"""
glossary.py — Central ordlista för alla nyckeltal + info-bubblor.

ENDA källan för "vad är detta och vad är ett bra värde"-texter. Används av alla
st.metric(help=...), data_table-kolumner och sektionsrubriker så att användaren
kan hovra på vad som helst och förstå det.

Mönster för varje post: vad det är · vad som är bra/dåligt · ev. sektorvarning.
"""

# key → {"label": kort namn, "help": fullständig förklaring inkl. bra värde}
METRICS: dict[str, dict] = {
    # ── Composite & signaler ────────────────────────────────────────────────
    "score_total": {"label": "Score", "help":
        "Totalpoäng 0–100 från 10 viktade faktorer. 70+ = stark, 50–69 = neutral, "
        "<50 = svag. Relativ ranking inom universet, inte ett absolut betyg."},
    "entry_signal": {"label": "Entry-signal", "help":
        "Tajmingsignal: STARK = alla faktorer pekar upp, OK = bra läge, "
        "VÄNTA = avvakta, EJ AKTUELL = svag. Säger NÄR, inte OM, du bör köpa."},
    "trend_signal": {"label": "Trend", "help":
        "Teknisk trend mot glidande medel: UPP = över MA50 & MA200 (styrka), "
        "NED = under MA200 (svaghet)."},
    "predicted_return": {"label": "ML-prognos", "help":
        "ML-modellens prediktion av relativ 30-dagars avkastning. Används för "
        "rangordning (ml_rank), inte som exakt avkastningsgaranti."},
    "ml_rank": {"label": "ML-rank", "help":
        "Percentil 0–100 av ML-prognosen. 100 = modellens starkaste köpkandidat."},

    # ── Värdering ─────────────────────────────────────────────────────────────
    "pe_trailing": {"label": "P/E (TTM)", "help":
        "Pris ÷ vinst senaste 12 mån. Lägre = billigare. <15 ofta attraktivt, "
        ">30 dyrt — men starkt sektorberoende (tech har högre, banker lägre)."},
    "pe_forward": {"label": "P/E (framåt)", "help":
        "Pris ÷ förväntad vinst nästa år. Lägre än trailing P/E = vinsttillväxt väntas."},
    "price_to_book": {"label": "P/B", "help":
        "Pris ÷ eget kapital per aktie. <1 = handlas under bokfört värde. "
        "Viktigast för banker/fastighet; mindre relevant för tech."},
    "ev_to_ebitda": {"label": "EV/EBITDA", "help":
        "Bolagsvärde ÷ rörelseresultat. <8 ofta billigt, >15 dyrt. Bra för att "
        "jämföra bolag med olika skuldsättning."},
    "price_to_sales": {"label": "P/S", "help":
        "Pris ÷ omsättning. Används för bolag utan vinst. <1 lågt, >5 högt."},
    "fcf_yield": {"label": "FCF-yield", "help":
        "Fritt kassaflöde ÷ bolagsvärde. Högre = mer kassagenerering per krona. "
        ">5% starkt. Den mest robusta värderingssignalen över tid."},

    # ── Kvalitet / lönsamhet ─────────────────────────────────────────────────
    "roe": {"label": "ROE", "help":
        "Avkastning på eget kapital. Hur effektivt ägarnas pengar används. "
        ">15% bra, >20% utmärkt. Mycket hög ROE kan dock bero på hög skuld."},
    "roa": {"label": "ROA", "help":
        "Avkastning på totala tillgångar. >5% bra. Mindre känslig för skuld än ROE."},
    "profit_margin": {"label": "Vinstmarginal", "help":
        "Nettovinst ÷ omsättning. Högre = mer lönsamt. >10% bra, varierar per bransch."},
    "operating_margin": {"label": "Rörelsemarginal", "help":
        "Rörelseresultat ÷ omsättning. Mäter kärnverksamhetens lönsamhet."},
    "gross_margin": {"label": "Bruttomarginal", "help":
        "Bruttoresultat ÷ omsättning. Hög = prissättningskraft. >40% ofta starkt."},

    # ── Tillväxt ─────────────────────────────────────────────────────────────
    "revenue_growth": {"label": "Omsättningstillväxt", "help":
        "Tillväxt i omsättning år över år. >10% bra, >20% stark tillväxt."},
    "earnings_growth": {"label": "Vinsttillväxt", "help":
        "Tillväxt i vinst år över år. Helst i nivå med eller över omsättningstillväxten."},
    "earnings_surprise": {"label": "Vinst-överraskning", "help":
        "Hur mycket bolaget slår analytikernas vinstestimat. Positivt = momentum (PEAD)."},

    # ── Finansiell hälsa / risk ──────────────────────────────────────────────
    "debt_to_equity": {"label": "Skuldsättning (D/E)", "help":
        "Skulder ÷ eget kapital. Lägre = stabilare. <1 konservativt, >2 högt — "
        "men banker/fastighet har strukturellt hög D/E (normalt för dem)."},
    "current_ratio": {"label": "Kassalikviditet", "help":
        "Omsättningstillgångar ÷ kortfristiga skulder. >1,5 = god betalningsförmåga, "
        "<1 = ansträngd likviditet."},
    "beta": {"label": "Beta", "help":
        "Hur mycket aktien svänger mot marknaden. 1 = som index, >1,3 = volatil, "
        "<0,8 = defensiv."},
    "volatility": {"label": "Volatilitet", "help":
        "Årlig standardavvikelse i avkastning. Lägre = lugnare kurs. "
        "<20% lågt, >40% högt."},

    # ── Teknisk ──────────────────────────────────────────────────────────────
    "rsi_14": {"label": "RSI (14)", "help":
        "Momentum 0–100. >70 = överköpt (kan vända ned), <30 = översålt (kan studsa), "
        "40–60 = neutralt."},
    "macd_hist": {"label": "MACD-histogram", "help":
        "Skillnad mellan MACD och signallinje. Positivt & stigande = tilltagande "
        "uppåtmomentum."},
    "bb_position": {"label": "Bollinger-position", "help":
        "Var priset ligger i Bollinger-bandet. 0 = vid nedre bandet (billigt/översålt), "
        "1 = övre bandet (dyrt/överköpt), 0,5 = mitten."},
    "pct_from_52w_high": {"label": "Från 52v-högsta", "help":
        "Avstånd till 52-veckors högsta. Nära 0 = stark trend; mycket negativt = "
        "nedtryckt (kan vara köpläge eller fallande kniv)."},
    "return_12m": {"label": "Avkastning 12m", "help":
        "Kursavkastning senaste 12 mån. Långsiktigt momentum — stark prediktor för "
        "fortsatt utveckling (momentum-faktorn)."},
    "return_6m": {"label": "Avkastning 6m", "help": "Kursavkastning senaste 6 mån (mellanmomentum)."},
    "return_3m": {"label": "Avkastning 3m", "help": "Kursavkastning senaste 3 mån (kortmomentum)."},

    # ── Utdelning ────────────────────────────────────────────────────────────
    "dividend_yield": {"label": "Direktavkastning", "help":
        "Årlig utdelning ÷ kurs. 2–4% = normalt. >6–7% kan vara varningssignal "
        "(nedtryckt kurs eller hotad utdelning)."},
    "payout_ratio": {"label": "Utdelningsandel", "help":
        "Andel av vinsten som delas ut. <60% hållbart, >100% = delar ut mer än man "
        "tjänar (ohållbart)."},

    # ── Sentiment / flöden ───────────────────────────────────────────────────
    "sentiment_raw": {"label": "Sentiment", "help":
        "Nyhetssentiment −1 till +1. Positivt = övervägande positiva nyheter."},
    "short_pct_float": {"label": "Blankat %", "help":
        "Andel av aktierna som är blankade. Lågt = få skeptiker (positivt). "
        ">20% = mycket blankat (risk, men möjlig short squeeze)."},
    "short_ratio": {"label": "Dagar att täcka", "help":
        "Antal handelsdagar för att täcka alla blankningar. Högre = mer blankningstryck."},
    "piotroski_f": {"label": "Piotroski F-Score", "help":
        "Nio nyckeltal för lönsamhet, skuld och effektivitet. 7–9 = stark balansräkning, "
        "0–3 = svag."},

    # ── Portfölj / backtest ──────────────────────────────────────────────────
    "sharpe": {"label": "Sharpe-kvot", "help":
        "Avkastning per risk-enhet. >1 bra, >2 utmärkt. <0 = sämre än riskfritt."},
    "max_drawdown": {"label": "Max drawdown", "help":
        "Största fall från topp till botten. Närmare 0 = mildare. Mått på nedsiderisk."},
    "correlation": {"label": "Korrelation", "help":
        "Hur lika två aktier rör sig (−1 till +1). >0,8 = rör sig nästan likadant "
        "(låg diversifiering)."},
    "current_price": {"label": "Kurs", "help": "Senaste handelskurs (yfinance, ~15 min fördröjning)."},
    "market_cap": {"label": "Börsvärde", "help":
        "Totalt marknadsvärde. Stora bolag = stabilare, små = högre tillväxt/risk."},
    "data_quality": {"label": "Datakvalitet", "help":
        "Andel nyckeltal som finns för aktien. Lågt värde → osäkrare score."},
}


def help_for(key: str) -> str | None:
    """Returnerar hjälptext för ett nyckeltal, eller None om okänt."""
    entry = METRICS.get(key)
    return entry["help"] if entry else None


def label_for(key: str, default: str | None = None) -> str:
    """Returnerar kort etikett för ett nyckeltal."""
    entry = METRICS.get(key)
    return entry["label"] if entry else (default if default is not None else key)
