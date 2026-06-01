"""web/pages/guide.py - Sida 8: Guide & Hjälp"""

import streamlit as st


def page_guide():
    """Introduktionssida som förklarar systemet för nya användare."""

    st.title("📚 Guide & Hjälp")
    st.markdown(
        "Välkommen till **MarketScan** -- ett automatiserat system som scannar "
        "hundratals aktier varje dag, betygsätter dem på 8 faktorer och lyfter fram "
        "de som har bäst förutsättningar att prestera. Den här sidan förklarar hur "
        "allt hänger ihop."
    )

    # ── Kom igång snabbt ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🚀 Kom igång på 3 steg")
    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("""
**1️⃣ Titta på Översikt**

Gå till **📊 Översikt** för att se vilka aktier som har starka köpsignaler just nu och hur marknadsläget ser ut generellt.
        """)
    with s2:
        st.markdown("""
**2️⃣ Utforska Veckoscanner**

**🔍 Veckoscanner** visar alla scorade aktier rankade. Filtrera på sektor, signal eller score. Klicka på en aktie för full analys.
        """)
    with s3:
        st.markdown("""
**3️⃣ Följ en aktie**

Lägg till intressanta aktier på ⭐ **Bevakningslistan** eller **💼 Portföljen** för att hålla koll löpande.
        """)

    # ── Systemet bakom kulisserna ───────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚙️ Hur systemet fungerar")

    st.markdown("""
MarketScan kör en **automatisk pipeline** varje dag via GitHub Actions (gratis molntjänst).
Processen ser ut såhär:
    """)

    p1, p2, p3, p4, p5 = st.columns(5)
    _pipe_style = "border:1px solid #334155; border-radius:8px; padding:12px; text-align:center; height:130px;"
    p1.markdown(f'<div style="{_pipe_style}">🌐<br><b>Hämta data</b><br><small>yfinance, Finnhub, RSS</small></div>', unsafe_allow_html=True)
    p2.markdown(f'<div style="{_pipe_style}">🧮<br><b>Beräkna score</b><br><small>8 faktorer x vikter</small></div>', unsafe_allow_html=True)
    p3.markdown(f'<div style="{_pipe_style}">🤖<br><b>AI-analys</b><br><small>ML + GPT-liknande modell</small></div>', unsafe_allow_html=True)
    p4.markdown(f'<div style="{_pipe_style}">💾<br><b>Spara rapport</b><br><small>CSV committas till GitHub</small></div>', unsafe_allow_html=True)
    p5.markdown(f'<div style="{_pipe_style}">📊<br><b>Visa i appen</b><br><small>Streamlit Cloud läser CSV</small></div>', unsafe_allow_html=True)

    with st.expander("🔍 Mer om datakällorna", expanded=False):
        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown("""
**Vad hämtas?**
- **Priser & historik** -- Yahoo Finance (yfinance). Justerat för utdelningar och splits.
- **Fundamentala nyckeltal** -- P/E, P/B, ROE, skulder m.m. via yfinance/Finnhub.
- **Nyheter** -- Finnhub (engelska) + Placera/DI/Google News (svenska).
- **Insideraffärer** -- rapporterade köp/sälj från bolagets ledning.
- **Analyst targets** -- genomsnittlig riktkurs från analytiker.
            """)
        with c_b:
            st.markdown("""
**Hur ofta uppdateras det?**
- Universumscanning: **dagligen** (måndag-fredag, morgon & kväll)
- Småbolag (svenska): **dagligen**
- Nyheter: **var 6:e timme**
- Utdelningskalender: **dagligen**
- Pris i realtid: **15 min fördröjning** via gratis-tier yfinance

Data lagras som CSV-filer i GitHub-repot och läses av Streamlit.
            """)

    # ── Poängsystemet ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🎯 Poängsystemet -- 8 faktorer")

    st.markdown(
        "Varje aktie får ett **totalpoäng 0-100** baserat på åtta faktorer. "
        "Varje faktor mäter en dimension av aktiens kvalitet. "
        "Vikterna justeras automatiskt beroende på **marknadsregim** (bull/bear/neutral)."
    )

    fac_cols = st.columns(4)
    _factors = [
        ("💰", "Värdering",  "0-100", "Är aktien billig eller dyr? Baseras på P/E, P/B, EV/EBITDA m.m. Högt = relativt billig."),
        ("🏆", "Kvalitet",   "0-100", "Är bolaget finansiellt starkt? ROE, marginaler, Piotroski F-Score. Högt = stabilt bolag."),
        ("📈", "Momentum",   "0-100", "Rör sig aktien uppåt? 1m/3m/6m/12m avkastning + RSI + MACD. Högt = stark upptrend."),
        ("🌱", "Tillväxt",   "0-100", "Växer bolaget? Vinst- och omsättningstillväxt historiskt. Högt = växande bolag."),
        ("🛡️", "Risk",       "0-100", "Hur stabil är aktien? Beta, volatilitet, skuldsättning. Högt = låg risk."),
        ("🔬", "Storlek",    "0-100", "Bolagets marknadsvärde. Justerar för att jämföra store vs små bolag rättvist."),
        ("💎", "Utdelning",  "0-100", "Utdelningskvalitet. Direktavkastning, payout ratio, FCF-täckning. Högt = stabil utdelning."),
        ("📰", "Sentiment",  "0-100", "Nyhetsflöde + analytikerkonsensus + insideraffärer. Högt = positiv extern syn."),
    ]
    for i, (icon, name, scale, desc) in enumerate(_factors):
        with fac_cols[i % 4]:
            st.markdown(f"**{icon} {name}** `{scale}`")
            st.caption(desc)
            if i % 4 == 3 and i < 7:
                st.markdown("")

    with st.expander("📐 Hur räknas totalpoänget ut?", expanded=False):
        st.markdown("""
Varje faktor percentilrankas mot alla bolag i universumet -- ett bolag i topp 10% för en faktor
får 90+ poäng på den faktorn. Sedan viktas faktorerna ihop:

| Marknadsregim | Momentum | Kvalitet | Värdering | Tillväxt | Risk | Sentiment |
|---|---|---|---|---|---|---|
| **Bullish** | 30% | 20% | 15% | 15% | 10% | 10% |
| **Neutral** | 20% | 25% | 20% | 15% | 10% | 10% |
| **Bearish** | 15% | 30% | 25% | 10% | 15% | 5% |

I en bull-marknad väger momentum tyngst -- vinnare fortsätter att vinna.
I en bear-marknad skiftar systemet mot kvalitet och värdering för att skydda kapitalet.
        """)

    # ── Signaler ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚡ Köpsignaler -- Entry, Konfidens, Trend")

    g1, g2, g3 = st.columns(3)
    with g1:
        st.markdown("#### ⚡ Entry-signal")
        st.markdown("""
Baseras på tekniska indikatorer:

🟢 **STARK** -- Tydlig uppåtrörelse med stöd av ökad volym. Prioriterat köpläge.

🔵 **OK** -- Viss positiv rörelse men inte lika tydlig signal.

⚪ **VÄNTA** -- Neutral eller avvaktande läge. Inte rätt timing.

🔴 **EJ AKTUELL** -- Teknisk svaghet. Undvika för tillfället.
        """)
    with g2:
        st.markdown("#### 🎯 Konfidensnivå")
        st.markdown("""
Hur starka är de underliggande indikatorerna?

🔥 **HÖG** -- Flera indikatorer pekar åt samma håll. Hög tillförlitlighet.

📊 **MEDEL** -- Blandat signalmönster. OK men lägre säkerhet.

💧 **LÅG** -- Motstridiga signaler. Var försiktig.

Kombinera alltid entry med konfidens: **STARK + HÖG** = starkast möjliga signal.
        """)
    with g3:
        st.markdown("#### 📈 Teknisk trend")
        st.markdown("""
Baseras på 50- och 200-dagars glidande medelvärden:

🟢 **UPPTREND** -- Kursen är *över* MA50 och MA200. Stark bullish position.

⚪ **SIDLED** -- Kursen befinner sig mellan MA50 och MA200. Ingen tydlig riktning.

🔴 **NEDTREND** -- Kursen är *under* MA200. Långsiktig björnmarknad för aktien.

Köp helst i upptrend -- "the trend is your friend".
        """)

    # ── Inloggning & konton ───────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔑 Inloggning & konton")

    with st.expander("Hur loggar jag in?", expanded=False):
        st.markdown("""
Appen kräver ett personligt konto med användarnamn och lösenord.

1. Öppna appen i webbläsaren
2. Fyll i ditt **användarnamn** och **lösenord** på inloggningssidan
3. Klicka **Logga in**

En inloggningscookie sparas i 90 dagar -- du behöver inte logga in igen på samma enhet.
        """)

    with st.expander("Varje användare har egna data", expanded=False):
        st.markdown("""
Varje inloggad användare har sin **egna** portfölj, bevakningslista och paper trading-historik.
Inga data delas mellan användare.

- Scandata (scores, signaler, historik) är delad -- samma för alla
- Portfölj, bevakning och paper trading är personligt per inloggning
        """)

    with st.expander("Glömt lösenord / ny användare", expanded=False):
        st.markdown("""
Kontakta administratören för att:
- Återställa ditt lösenord
- Skapa ett nytt konto

Admin-sidan nås bara av admin-kontot (du ser ingen admin-knapp annars).
        """)

    # ── Portföljhantering ─────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("💼 Portföljhantering")

    with st.expander("Importera från Avanza (rekommenderat)", expanded=False):
        st.markdown("""
Det enklaste sättet att lägga in dina aktier är att importera direkt från Avanza:

1. Logga in på **avanza.se**
2. Gå till **Konto -> din depå/ISK**
3. Klicka på fliken **Innehav**
4. Scrolla längst ner -> klicka **Exportera**
5. Spara filen (.csv) på din dator
6. Gå till **💼 Portfölj -> Importera från Avanza** i MarketScan
7. Ladda upp filen -- verifiera och bekräfta varje rad

Filen läses lokalt i din webbläsare och skickas inte vidare.
        """)

    with st.expander("Lägg till via sök", expanded=False):
        st.markdown("""
I **💼 Portfölj -> Sök & lägg till** kan du söka på bolagsnamn (t.ex. "Volvo", "Apple") eller ticker
(t.ex. VOLV-B.ST, AAPL). Välj aktie från listan, fyll i **antal** och **genomsnittligt inköpspris**
och klicka Lägg till.
        """)

    with st.expander("Lägg till manuellt (med ticker)", expanded=False):
        st.markdown("""
Vet du exakt vilket Yahoo Finance-ticker aktien har? Använd **✏️ Lägg till manuellt**:

- Svenska aktier slutar på `.ST` -- t.ex. `VOLV-B.ST`, `ERIC-B.ST`, `SEB-A.ST`
- Amerikanska: `AAPL`, `MSFT`, `NVDA`
- Övriga: sök på finance.yahoo.com för korrekt ticker

Fyll i ticker, antal aktier och genomsnittligt inköpspris per aktie.
        """)

    with st.expander("Redigera eller ta bort en aktie", expanded=False):
        st.markdown("""
Gå till **💼 Portfölj -> Ta bort aktie**, välj aktien i listan och klicka antingen:

- **✏️ Ändra antal / pris** -- uppdatera om du köpt fler eller snittar ner
- **🗑️ Ta bort** -- ta bort aktien helt ur portföljen
        """)

    # ── E-postnotiser ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📧 E-postnotiser")

    with st.expander("Vilka rapporter skickas?", expanded=False):
        st.markdown("""
| Rapport | Frekvens | Innehåll |
|---|---|---|
| 🌅 Morgonbrief | Varje vardag ~7:00 | STARK-signaler, portföljstatus, marknad |
| 🌆 Kvällsuppdatering | Varje vardag ~18:00 | Daglig sammanfattning, movers |
| 📊 Veckosammanfattning | Fredag | AI-veckoanalys, topplistor, portfölj |
| 🏦 Småbolagsrapport | Måndag | Senaste småbolagsscan |
| ⚡ STARK-signaler | Vid signal | Omedelbart när en stark köpsignal dyker upp |
| 💼 Portföljlarm | Vid händelse | Stop-loss eller take-profit nått |
| 🚨 Tekniska fel | Vid fel | Pipeline-problem |
        """)

    with st.expander("Hur aktiverar jag/inaktiverar notiser?", expanded=False):
        st.markdown("""
Gå till **⚙️ Inställningar** i sidofältet under PORTFÖLJ:

1. Fyll i din e-postadress
2. Bocka i de rapporter du vill ha
3. Klicka **Spara inställningar**

Dina inställningar sparas omedelbart och tas i bruk vid nästa utskick.
        """)

    with st.expander("Personliga portföljdata i e-posten", expanded=False):
        st.markdown("""
I morgonbriefet och veckorapporten inkluderas automatiskt **dina egna innehav och bevakningar**:

- Aktuell P&L per aktie
- Senaste score och entrysignal
- Din bevakningslista med signaler

Ingen annan användare ser din portföljdata -- rapporterna är personaliserade per konto.
        """)

    # ── Scan-fördröjning ──────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⏳ Ny aktie i universumet -- scan-fördröjning")

    with st.expander("Varför ser jag inte data direkt för en nylagd aktie?", expanded=False):
        st.markdown("""
När du lägger till en aktie i din portfölj eller bevakningslista som **inte tidigare funnits i
systemets universum**, läggs den automatiskt till i nästa schemalagda scan.

**Tidplan:**
- **Storbolag** (index-aktier): scan körs **lördag** ~06:00
- **Småbolag** (First North/Spotlight): scan körs **måndag** ~06:00

Tills dess är **live-prisinformation** (från yfinance) tillgänglig direkt -- men fullständiga
score, signaler och nyckeltal saknas.

Du ser ett blått infofält (**⏳**) bredvid aktien tills nästa scan är klar.
        """)

    # ── Sidorna ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🗺️ Sidornas funktioner")

    tab_m, tab_p, tab_a, tab_x = st.tabs(["📈 Marknad", "💼 Portfölj & Trading", "🤖 AI & Analys", "🔬 Avancerat"])

    with tab_m:
        pages_m = [
            ("📊 Översikt", "Startskärmen. Visar aktuella STARK-signaler (köpkandidater), marknadens snittpoäng och vilka av dina innehav som kan vara dags att se över. Bra för daglig koll."),
            ("🔍 Veckoscanner", "Hela universumet av ~800 aktier rankat och filtrerbart. Välj sektor, signal, score-intervall. Klicka på en rad för full detaljanalys med priskurva, hexdiagram, nyckeltal och AI-kommentar."),
            ("🏦 Småbolag", "Samma som Veckoscanner men fokus på svenska småbolag med extra nyckeltal som insideraffärer, FCF och stjärnbetyg. Småbolag har ofta högre risk men mer potential."),
            ("🔍 Aktie-sök", "Sök vilken aktie som helst direkt -- inte bara de i universumet. Ange en ticker (t.ex. AAPL, VOLV-B.ST) och se pris, P/E, sektor och priskurva."),
            ("⭐ Bevakningar", "Din personliga bevakningslista. Lägg till aktier du är intresserad av. Systemet visar deras senaste poäng och signaler."),
            ("🌍 Globala marknader", "Realtidsöversikt av globala index (S&P500, OMXS30, Nikkei m.fl.), valutakurser (USD/SEK, EUR/USD), räntor och marknadsnyheter."),
            ("🏭 Sektorrotation", "Visar vilka branscher som är starka eller svaga just nu. Köp aktier i starka sektorer -- sektorrotation är ett av de kraftfullaste mönstren i finans."),
        ]
        for name, desc in pages_m:
            with st.expander(name, expanded=False):
                st.markdown(desc)

    with tab_p:
        pages_p = [
            ("💼 Portfölj", "Hantera dina riktiga innehav. Importera från Avanza, sök & lägg till, eller ange manuellt. Se orealiserad vinst/förlust och portföljanalys. Data är personlig per inloggning."),
            ("📄 Paper Trading", "Simulera handel utan riktiga pengar. Systemet öppnar och stänger positioner automatiskt baserat på klassisk score-strategi. Starta 100 000 kr och se hur strategin presterar."),
            ("🤖 AI Paper Trading", "Samma som Paper Trading men driven av ML-modellen (XGBoost). Kör parallellt med klassisk paper trading för att se om maskininlärning tillför värde. Positioner stängs efter 30 dagar."),
            ("🚨 Larm & Notiser", "Visa aktier i din portfölj som är nära stop-loss eller take-profit. Se också senaste nyheterna för dina innehav och bevakade aktier."),
            ("⚙️ Inställningar", "Konfigurera din e-postadress och välj vilka rapporter du vill ta emot: morgonbrief, veckosammanfattning, STARK-signaler, portföljlarm m.m. Rapporterna inkluderar din personliga portfölj."),
        ]
        for name, desc in pages_p:
            with st.expander(name, expanded=False):
                st.markdown(desc)

    with tab_a:
        pages_a = [
            ("🤖 AI-analys (i detaljvyn)", "Varje aktie har en AI-knapp som genererar en full analys på svenska: värdering, risker, möjligheter och konkreta rekommendationer. Välj djup: Snabb (30s) -> Extra djup (2-3 min)."),
            ("🤖 AI (sidan)", "Veckobrev och marknadssammanfattningar genererade av AI. Täcker hela universumet, sektorrotation och makroläge."),
            ("📈 Teknisk analys", "Filtrera och jämför aktier på tekniska faktorer: RSI, MA50/MA200, MACD, volatilitet. Bra för att hitta tekniska inträden och exits."),
            ("📈 Backtesting", "Simulera hur momentum-strategin hade fungerat historiskt. Kör 1-10 år bakåt och se Sharpe ratio, drawdown och jämförelse mot SPY/OMX. OBS: Survivorship bias gör siffrorna för optimistiska."),
        ]
        for name, desc in pages_a:
            with st.expander(name, expanded=False):
                st.markdown(desc)

    with tab_x:
        st.markdown("""
#### 🤖 ML-modellen (XGBoost)

Systemet tränar en maskininlärningsmodell (XGBoost) på historisk prisdata för att förutsäga
30-dagars avkastning. Modellen lär sig vilka kombinationer av faktorer som historiskt lett till
bra avkastning -- inte ett deterministiskt mönster utan statistiska samband.

**Ingår i:** Veckoscanner (kolumn "AI 30d-ret"), AI Paper Trading, Universe Health-fliken.

---

#### 📊 Universum

Systemet scannar ~800 aktier uppdelade i:
- **USA large-cap** -- S&P500 och Nasdaq 100
- **Nordiska aktier** -- OMXS30, norska, danska och finska blue chips
- **Svenska småbolag** -- First North och Spotlight
- **Europa** -- DAX, CAC40, FTSE100 m.fl.
- **Asien/Pacific** -- Nikkei, Hang Seng, ASX
- **Kanada + LatAm** -- TSX och Bovespa

---

#### 🏗️ Infrastruktur (gratis)

| Komponent | Tjänst | Kostnad |
|---|---|---|
| Pipeline (daglig scan) | GitHub Actions | Gratis |
| Webbapp | Streamlit Cloud | Gratis |
| Prisdata | yfinance (Yahoo Finance) | Gratis |
| Nyheter | Finnhub free tier + Google News | Gratis |
| AI-analys | DeepSeek / Google Gemini | ~<$5/mån |
| Lagring | GitHub-repot (CSV-filer) | Gratis |

Hela systemet kan köras utan en enda betalningslösning om du byter till Gemini-only.
        """)

    # ── Tips ────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("💡 Tips för nybörjare")

    t1, t2 = st.columns(2)
    with t1:
        st.success("""
**✅ Gör detta:**
- Titta alltid på **Entry + Konfidens + Trend** tillsammans
- Jämför aktien mot **sektorsnittet** -- en bra aktie i en dålig sektor ger ofta svagare avkastning
- Använd **Piotroski F-Score >6** som ett extra filter för fundamentalt starka bolag
- Läs **AI-analysen** för en nyanserad bild -- den lyfter både möjligheter och risker
- Kolla **utdelningshistoriken** för defensiva innehav -- konsistent tillväxt >5 år är ett bra tecken
        """)
    with t2:
        st.warning("""
**⚠️ Undvik detta:**
- Köp inte bara för att score är högt -- kolla alltid nyheter och fundamenta
- Lita inte blint på AI-analysen -- den kan ha föråldrade data eller missa sektorspecifika faktorer
- Backtesting-siffror är **alltid för optimistiska** pga survivorship bias (+10-15%/år)
- Högt P/E (~50+) är okej för tillväxtbolag men riskabelt för stabila bolag
- Direktavkastning >7% kan vara en **fälla** -- kolla payout ratio och FCF-täckning
        """)

    st.info("""
**ℹ️ Kom ihåg:** MarketScan är ett **beslutsunderlag**, inte en handelsbot.
Systemet hjälper dig att hitta kandidater och förstå dem -- men det slutliga beslutet är alltid ditt.
Alla investeringar innebär risk och historisk prestanda garanterar inte framtida avkastning.
    """)

    st.markdown("---")
    st.caption("MarketScan * Byggd med Python, Streamlit, yfinance, XGBoost och DeepSeek/Gemini * Data uppdateras dagligen via GitHub Actions")
