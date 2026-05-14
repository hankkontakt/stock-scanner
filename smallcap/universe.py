"""
universe.py – Svenska småbolagsuniversum (~400 bolag).

Marknader:
  FIRST_NORTH – Nasdaq First North Growth Market
  SMALL_CAP   – Nasdaq Stockholm Small Cap
  SPOTLIGHT   – Spotlight Stock Market + NGM (mikrokap, hög risk)

Ticker-format: Yahoo Finance .ST-suffix.
  B-aktie: TICKER-B.ST (bindestreck)   A-aktie: TICKER-A.ST

Verifiera: python -m smallcap.validate_universe
"""

# ── NASDAQ FIRST NORTH GROWTH MARKET ─────────────────────────────────────────
# Tillväxtbolag, ofta grundarledd med högt ägarengagemang.

FIRST_NORTH = [

    # ── Mjukvara & SaaS ──────────────────────────────────────────────────────
    "LIME.ST",      # Lime Technologies – CRM för SME, extremt lönsam nisch
    "FNOX.ST",      # Fortnox – molnredovisning, dominerar SME-marknaden
    "VIT-B.ST",     # Vitec Software B – vertikala marknadssystem (VMS)
    "ANOD-B.ST",    # AddNode Group B – design/construction-mjukvara
    "ENEA.ST",      # Enea – nätverksmjukvara för telecom
    "IAR-B.ST",     # IAR Systems B – embedded development tools
    "RAY-B.ST",     # RaySearch Laboratories B – strålbehandlingssoftware
    "SECT-B.ST",    # Sectra B – medicinsk bilddiagnostik & cybersäkerhet
    "CINT.ST",      # Cint Group – digital insiktsplattform (surveys)
    "KNOW.ST",      # Knowit – IT-konsult
    "PRIC-B.ST",    # Pricer B – elektroniska hylletiketter
    "TOBII.ST",     # Tobii – eye tracking-teknik
    "NETI-B.ST",    # Net Insight B – mediakommunikationsnätverk
    "CTEK.ST",      # CTEK – batterihantering och laddning
    "ALCA.ST",      # Alcadon Group – nätverksinfrastruktur
    "SPEQTA.ST",    # Speqta – prestationsmarknadsföring
    "CTM.ST",       # Catena Media – online gaming affiliates
    "ACAST.ST",     # Acast – global podcastplattform
    "BUSER.ST",     # Bambuser – live video commerce
    "EGTX.ST",      # Enad Global 7 – spelstudio
    "EMPIR-B.ST",   # Empir Group B – IT-tjänster & mjukvaruutveckling
    "PROACT.ST",    # ProAct IT Group – lagring & molnlösningar
    "BAHNHOF.ST",   # Bahnhof – oberoende internetleverantör

    # ── MedTech & Life Science ───────────────────────────────────────────────
    "XVIVO.ST",     # XVIVO Perfusion – organpreservering, global nischledare
    "ELOS-B.ST",    # Elos Medtech B – kontraktstillverkning medicinsk utrustning
    "BOMILL.ST",    # Bomill – spannmålssorteringsteknik
    "BIOG-B.ST",    # BioGaia B – probiotika med stark IP-position
    "CEVI.ST",      # CellaVision – automatisk bloddifferentiering
    "MNTC.ST",      # Mentice – kirurgisk simulering
    "ALIG.ST",      # Alligator Bioscience – immuno-onkologiplattform
    "IRRAS.ST",     # IRRAS – neurointensivvård
    "QLINEA.ST",    # Q-linea – snabbdiagnos antibiotikaresistens
    "ONCO.ST",      # Oncopeptides – blodcancer (myelom)
    "XSPRAY.ST",    # XSpray Pharma – nanopartikelformulering
    "HNSA.ST",      # Hansa Biopharma – enzymterapi mot antikroppar
    "CALTX.ST",     # Calliditas Therapeutics – IgA-nefropati
    "DMYD-B.ST",    # Diamyd Medical – autoimmun diabetes
    "ORX.ST",       # Orexo – beroendemedicin (suboxone-konkurrent)
    "ACTI.ST",      # Active Biotech – immunologisk forskning
    "IMMU.ST",      # Immunicum – cancerimmunologi
    "LINC.ST",      # LINC – life science-investmentbolag
    "CAMX.ST",      # CancerQ/CancerXomics – diagnostik
    "MCOV-B.ST",    # Medicover B – hälsovård & diagnostik Östeuropa
    "VIMIAN.ST",    # Vimian Group – veterinär MedTech
    "BOUL.ST",      # Boule Diagnostics – blodanalysinstrument
    "MOBERG.ST",    # Moberg Pharma – OTC dermatologi
    "PEPTONIC.ST",  # Peptonic Medical – medicinteknisk enhet
    "CERENO.ST",    # Cereno Scientific – trombosbehandling
    "XBRANE.ST",    # Xbrane Biopharma – biosimilarer
    "SEDANA.ST",    # Sedana Medical – inhalationssedation
    "SENZIME.ST",   # Senzime – intraoperativ neuroövervakning
    "GLYCOREX.ST",  # Glycorex Transplantation – blodgruppsbehandling
    "CANTARGIA.ST", # Cantargia – IL1RAP-cancerbehandling
    "POWERCELL.ST", # PowerCell Sweden – vätgasbränsleceller
    "MINESTO.ST",   # Minesto – tidvattenskraft
    "RECI-B.ST",    # Recipharm B – kontraktstillverkning läkemedel
    "MAHA-A.ST",    # Maha Energy A – oljeproduktion (Kanada/Brasilien)
    "OBDU.ST",      # Obducat – nanoimprintingteknologi
    "ANOTO.ST",     # Anoto Group – digital skriv- och ritteknologi
    "BRIGHTER.ST",  # Brighter – digital diabeteshantering
    "INTEG-B.ST",   # Integrum B – bioniska proteser med direktnervkoppling

    # ── Industri & Clean Tech ────────────────────────────────────────────────
    "MIPS.ST",      # MIPS – patenterad hjälmteknik, royaltymodell
    "GARO.ST",      # GARO – el-installationer och EV-laddning
    "OEM-B.ST",     # OEM International B – teknisk distributör
    "SDIP-B.ST",    # Sdiptech B – infrastrukturprodukter, seriell förvärvare
    "XANO-B.ST",    # XANO Industri B – industritillverkning & automation
    "REJL-B.ST",    # Rejlers B – teknikkonsult (energi & infra)
    "HEXA-B.ST",    # Hexatronic Group B – fibernätsinfrastruktur
    "MILDEF.ST",    # Mildef Group – militär elektronikutrustning
    "INSTAL.ST",    # Instalco – tekniska installationstjänster
    "IVSO.ST",      # Invisio – hörsel/kommunikationssystem för militär
    "BERG-B.ST",    # Bergman & Beving B – tekniska produkter & lösningar
    "COIC.ST",      # Coieo – industriell distribution
    "EOLU-B.ST",    # Eolus Vind B – vindkraftsutveckling
    "BRAV.ST",      # Bravida – teknisk installation & service
    "SENSYS.ST",    # Sensys Gatso – trafiksäkerhetslösningar (kameror)
    "HANZA.ST",     # Hanza – elektroniktillverkning (contract manufacturing)
    "TAGM.ST",      # TagMaster – RFID för transport & logistik
    "NILAR.ST",     # Nilar International – nickelmetallhydridbatterier

    # ── Fintech & Finans ─────────────────────────────────────────────────────
    "QLIRO.ST",     # Qliro – BNPL & betalningslösningar för e-handel
    "NOWO.ST",      # Nowo – digital bank för privatkunder
    "RESURS.ST",    # Resurs Bank – konsumentlån & retailkortkort
    "HOFI.ST",      # Hoist Finance – kreditfordringsinköp

    # ── Konsument & Livsstil ─────────────────────────────────────────────────
    "RVRC.ST",      # RVRC Holding – outdoor/workwear DTC-varumärke
    "SKIS-B.ST",    # Skistar B – skidorter (Sälen, Åre, Trysil)
    "CARY.ST",      # Cary Group – skadeverkstäder (vindrutor & kaross)
    "BHG.ST",       # BHG Group – onlinehandel hem & trädgård
    "BJBO.ST",      # Björn Borg – sportmode och underkläder
    "FING-B.ST",    # Fingerprint Cards B – fingeravtrycksbiometri

    # ── Gaming & Underhållning ───────────────────────────────────────────────
    "G5EN.ST",      # G5 Entertainment – mobilspel (casual)
    "BETS-B.ST",    # Betsson B – online gaming & betting
    "EMBRAC-B.ST",  # Embracer Group B – global spelkoncern
    "PDX.ST",       # Paradox Interactive – strategi-PC-spel

    # ── Investmentbolag ──────────────────────────────────────────────────────
    "BURE.ST",      # Bure Equity – tillväxtbolagsinvesteringar
    "CRED-A.ST",    # Creades A – investmentbolag (Avanza spin-off)
    "NAXS.ST",      # NAXS – PE-fokuserat investmentbolag
    "TRAC-B.ST",    # Traction B – aktivt ägarbolag
    "SVOL-B.ST",    # Svolder B – small/micro cap-fokus
    "VNV.ST",       # VNV Global – tech & marketplace
    "EAST.ST",      # East Capital Explorer – tillväxtmarknader

    # ── Fastighet ────────────────────────────────────────────────────────────
    "KFAST-B.ST",   # K-Fast Holding B – hyresbostäder
    "SSM.ST",       # SSM Holding – studentbostäder
    "NIV.ST",       # Nivika Fastigheter
    "NP3.ST",       # NP3 Fastigheter – norrländska kommersiella fastigheter
    "SLP-B.ST",     # SLP B – industri- och logistikfastigheter
    "CIBUS.ST",     # Cibus Nordic Real Estate – dagligvaruankrade fastigheter
    "PION-B.ST",    # Pioneer Property Group B

    # ── Energi & Miljö ───────────────────────────────────────────────────────
    "ARISE.ST",     # Arise – vindkraftsutveckling Sverige
    "GRNG.ST",      # Greening – förnybar energi
    "EPRO-B.ST",    # Epro B – energibolag
]


# ── NASDAQ STOCKHOLM SMALL CAP ────────────────────────────────────────────────
# Mer etablerade bolag. Ofta starkare kassaflöde och utdelning.

SMALL_CAP = [

    # ── Industri & Verkstad ───────────────────────────────────────────────────
    "BUFAB.ST",     # Bufab – global distributör av fästelement
    "LIAB.ST",      # Lindab International – ventilationssystem
    "ITAB.ST",      # ITAB Shop Concept – butiksinredning
    "THULE.ST",     # Thule Group – outdoor & transportprodukter
    "NCAB.ST",      # NCAB Group – PCB-distribution, asset-light
    "TROAX.ST",     # Troax Group – maskinsäkerhetsskydd
    "SYSR.ST",      # Systemair – industriventilation
    "MYCR.ST",      # Mycronic – SMT-maskiner & lasersystem
    "NOTE.ST",      # NOTE – elektroniktillverkning (EMS)
    "AQ.ST",        # AQ Group – elektroniktillverkning
    "BEIJ-B.ST",    # Beijer Electronics B – industriautomation & HMI
    "HMSN.ST",      # HMS Networks B – industriell datakommunikation
    "NOLA-B.ST",    # Nolato B – polymertillverkning (medtech, packaging)
    "HPOL-B.ST",    # Hexpol B – gummiblandningar
    "BMAX.ST",      # Byggmax – lågprisbyggvaruhandel
    "VBG-B.ST",     # VBG Group B – dragkopplingssystem & trucksystem
    "ADDT-B.ST",    # Addtech B – teknisk distribution (annan än AddNode!)
    "BETE.ST",      # BE Group – stålhandel
    "LOOMIS.ST",    # Loomis – värdetransporter & kontanthantering
    "DOM.ST",       # Dometic Group – mobillivsprodukter (RV, marin, last)
    "AAK.ST",       # AAK – specialfetter & vegetabiliska oljor
    "AXFO.ST",      # Axfood – dagligvaruhandel (Willys, Hemköp)
    "INWI.ST",      # Inwido – fönster och dörrar (Norden & Europa)
    "NIBE-B.ST",    # NIBE Industrier B – värmepumpar & energilösningar

    # ── Konsument & Handel ────────────────────────────────────────────────────
    "MEKO.ST",      # Mekonomen – bildelehandel & verkstäder
    "BILI-A.ST",    # Bilia A – bilhandel
    "CLAS-B.ST",    # Clas Ohlson B – verktyg & fritidsprodukter
    "DUNI.ST",      # Duni – bordsdukning & förpackningar
    "MSON-B.ST",    # Midsona B – hälsokostprodukter (Kung Markatta, Urtekram)
    "DORO.ST",      # Doro – seniortelefoner & trygghetslarm

    # ── Tjänster & Konsult ────────────────────────────────────────────────────
    "BTS-B.ST",     # BTS Group B – affärssimuleringar & lärande
    "COOR.ST",      # Coor Service Management – FM-tjänster
    "HUMANA.ST",    # Humana – omsorgstjänster (LSS, äldreomsorg)

    # ── MedTech & Pharma ──────────────────────────────────────────────────────
    "EKTA-B.ST",    # Elekta B – strålbehandlingssystem
    "GETI-B.ST",    # Getinge B – medicinsk teknologi (intensivvård, infra)
    "ESSITY-B.ST",  # Essity B – hygien & hälsovårdsprodukter
    "ARJO-B.ST",    # Arjo B – patientlyft & mobilitetslösningar
    "VITR.ST",      # Vitrolife – IVF-medier & utrustning
    "BICO.ST",      # BICO Group – bioprinting & life science tools

    # ── Tech & Mjukvara ───────────────────────────────────────────────────────
    "SINCH.ST",     # Sinch – kommunikationsplattform (CPaaS)
    "MYFC.ST",      # myFC Holding – bränsleceller (mikrokraft)

    # ── Fastighet ─────────────────────────────────────────────────────────────
    "BALD-B.ST",    # Balder B – bostäder & kommersiella fastigheter
    "CAST.ST",      # Castellum – kontors- & handsfastigheter
    "FABG.ST",      # Fabege – kontorsfastigheter Stockholm CBD
    "SAGA-B.ST",    # Sagax B – industri- & lagerfastigheter
    "WIHL.ST",      # Wihlborgs Fastigheter – Malmö/Öresund
    "DIOS.ST",      # Diös Fastigheter – norrländska fastigheter
    "JM.ST",        # JM – bostadsutveckling
    "PEAB-B.ST",    # Peab B – bygg & anläggning
    "NCC-B.ST",     # NCC B – bygg & anläggning
    "HUFV-A.ST",    # Hufvudstaden A – premium kontors-/butiksfastigheter
    "CORE-B.ST",    # Corem Property Group B – logistik & industri
    "FPAR-A.ST",    # Fastpartner A
    "HEBA-B.ST",    # Heba Fastighets B – hyresbostäder
    "BONAV-B.ST",   # Bonavista B
    "PLAZ-B.ST",    # Platzer Fastigheter B – kommersiella fastigheter Göteborg
    "NYF.ST",       # Nyfosa – kommersiella fastigheter
    "SBB-B.ST",     # Samhällsbyggnadsbolaget B – samhällsfastigheter

    # ── Finans & Kapitalförvaltning ───────────────────────────────────────────
    "INTRUM.ST",    # Intrum – inkasso & kredithantering
    "KINV-B.ST",    # Kinnevik B – investmentbolag (Zalando m.fl.)
    "LIFCO-B.ST",   # Lifco B – förvärvsmaskin (dental, bygg, miljö)
    "INDT.ST",      # Indutrade – industriell distribution, seriell förvärvare
    "RATO-B.ST",    # Ratos B – PE-investmentbolag
    "NOBI.ST",      # Nobina – kollektivtrafikoperatör (buss)
    "LATO-B.ST",    # Latour B – investmentbolag (Swegon, Tomra m.fl.)
    "BINV.ST",      # Byggmästare Anders J Ahlström Invest B
    "KFAB.ST",      # Kungsleden B (numera sammanslagen)

    # ── Material & Skog ───────────────────────────────────────────────────────
    "SSAB-A.ST",    # SSAB A – höghållfast specialstål
    "SSAB-B.ST",    # SSAB B
    "SCA-B.ST",     # SCA B – skog, papper & förpackningar
    "HOLM-B.ST",    # Holmen B – skog, papper & energi
    "HPOL-B.ST",    # Hexpol B – gummiblandningar (dup)

    # ── Telecom ───────────────────────────────────────────────────────────────
    "NENT-B.ST",    # Nordic Entertainment Group B – streaming & sport
    "MTG-B.ST",     # Modern Times Group B – gaming & media
]


# ── SPOTLIGHT STOCK MARKET & NGM (urval) ─────────────────────────────────────
# Mikrokap. Hög risk, lägre likviditet och ofta begränsad Yahoo-data.
# Filtret tar bort de illikvida – resten kan ge asymmetrisk uppsida.

SPOTLIGHT = [
    # ── Biotech & MedTech ────────────────────────────────────────────────────
    "BIOT.ST",      # Biotech IgG – antikroppsproduktion
    "ELCG.ST",      # Elicera Therapeutics – CAR-T-cellterapi
    "KDEV.ST",      # Kancera – kinasbaserad cancerforskning
    "ENZY.ST",      # Enzymatica – enzymbaserade läkemedel
    "IMPC.ST",      # Impact Coatings – PVD-beläggningssystem
    "GLYCOREX.ST",  # Glycorex Transplantation (dup, dedup)
    "WNTRESEARCH.ST", # Wnt Research – kancerstammceller
    "BRIGHTER.ST",  # Brighter (dup, dedup)

    # ── Cleantech & Energi ────────────────────────────────────────────────────
    "MYFC.ST",      # myFC Holding – bränsleceller (dup)
    "POWERCELL.ST", # PowerCell Sweden (dup)
    "MINESTO.ST",   # Minesto (dup)

    # ── Industri / Nisch ─────────────────────────────────────────────────────
    "OBDU.ST",      # Obducat – nanoimprinting (dup)
    "TAGM.ST",      # TagMaster (dup)
    "ANOTO.ST",     # Anoto Group (dup)
    "SENSYS.ST",    # Sensys Gatso (dup)

    # ── Fastighet ────────────────────────────────────────────────────────────
    "MTRS.ST",      # Mälarstaden – fastighetsbolag
    "HTRO.ST",      # Heatron – fastighetsutveckling
]


# ── KOMBINERAT UNIVERSUM ──────────────────────────────────────────────────────

_ALL = FIRST_NORTH + SMALL_CAP + SPOTLIGHT

# Deduplicera (behåll första förekomsten, ordning spelar ingen roll)
SMALLCAP_UNIVERSE = list(dict.fromkeys(t.upper() for t in _ALL))

# Sökväg till användarens egna tickers (skapas automatiskt vid första tillägget)
_CUSTOM_FILE = Path(__file__).parent.parent / "data" / "smallcap_custom.json"


# ── Anpassat universum (via app.py) ───────────────────────────────────────────

def load_custom() -> list:
    """Returnerar användartillagda tickers från data/smallcap_custom.json."""
    try:
        if _CUSTOM_FILE.exists():
            import json
            return json.loads(_CUSTOM_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_custom(items: list):
    import json
    _CUSTOM_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CUSTOM_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_custom(ticker: str, name: str = "", segment: str = "first_north") -> bool:
    """Lägger till en ticker i custom-listan. Returnerar True om ny."""
    from datetime import date
    ticker = ticker.strip().upper()
    custom = load_custom()
    if any(c["ticker"] == ticker for c in custom):
        return False
    custom.append({
        "ticker":  ticker,
        "name":    name.strip(),
        "segment": segment,
        "added":   str(date.today()),
    })
    _save_custom(custom)
    return True


def remove_custom(ticker: str) -> bool:
    """Tar bort en ticker ur custom-listan. Returnerar True om borttagen."""
    ticker = ticker.strip().upper()
    custom = load_custom()
    new = [c for c in custom if c["ticker"] != ticker]
    if len(new) == len(custom):
        return False
    _save_custom(new)
    return True


def is_builtin(ticker: str) -> bool:
    """Returnerar True om tickern redan finns i basuniversumet."""
    return ticker.strip().upper() in SMALLCAP_UNIVERSE


def get_universe(market: str = "all") -> list:
    """
    Returnerar ticker-lista baserat på marknad (inkl. custom-tickers).
    market: "all" | "first_north" | "small_cap" | "spotlight"
    """
    mapping = {
        "all":         SMALLCAP_UNIVERSE,
        "first_north": list(dict.fromkeys(t.upper() for t in FIRST_NORTH)),
        "small_cap":   list(dict.fromkeys(t.upper() for t in SMALL_CAP)),
        "spotlight":   list(dict.fromkeys(t.upper() for t in SPOTLIGHT)),
    }
    base = mapping.get(market, SMALLCAP_UNIVERSE)

    custom = load_custom()
    if market == "all":
        extra = [c["ticker"] for c in custom]
    else:
        extra = [c["ticker"] for c in custom if c.get("segment") == market]

    return list(dict.fromkeys(base + extra))


# ── Bransch-kategorier ────────────────────────────────────────────────────────
SECTOR_GROUPS = {
    "Mjukvara & SaaS": [
        "LIME.ST", "FNOX.ST", "VIT-B.ST", "ANOD-B.ST", "ENEA.ST", "IAR-B.ST",
        "RAY-B.ST", "SECT-B.ST", "CINT.ST", "KNOW.ST", "PRIC-B.ST", "TOBII.ST",
        "NETI-B.ST", "CTEK.ST", "ALCA.ST", "SPEQTA.ST", "CTM.ST", "ACAST.ST",
        "BUSER.ST", "EGTX.ST", "EMPIR-B.ST", "PROACT.ST", "BAHNHOF.ST",
    ],
    "MedTech & Life Science": [
        "XVIVO.ST", "ELOS-B.ST", "BOMILL.ST", "BIOG-B.ST", "CEVI.ST", "MNTC.ST",
        "ALIG.ST", "IRRAS.ST", "QLINEA.ST", "ONCO.ST", "XSPRAY.ST", "HNSA.ST",
        "CALTX.ST", "DMYD-B.ST", "ORX.ST", "ACTI.ST", "IMMU.ST", "MCOV-B.ST",
        "VIMIAN.ST", "BOUL.ST", "MOBERG.ST", "PEPTONIC.ST", "CERENO.ST",
        "XBRANE.ST", "SEDANA.ST", "SENZIME.ST", "GLYCOREX.ST", "CANTARGIA.ST",
        "RECI-B.ST", "INTEG-B.ST", "BIOT.ST", "ELCG.ST", "KDEV.ST", "ENZY.ST",
        "GETI-B.ST", "EKTA-B.ST", "ARJO-B.ST", "VITR.ST", "BICO.ST",
    ],
    "Industri & Verkstad": [
        "MIPS.ST", "GARO.ST", "OEM-B.ST", "SDIP-B.ST", "XANO-B.ST",
        "REJL-B.ST", "HEXA-B.ST", "MILDEF.ST", "INSTAL.ST", "IVSO.ST",
        "BERG-B.ST", "EOLU-B.ST", "BRAV.ST", "SENSYS.ST", "HANZA.ST",
        "TAGM.ST", "BUFAB.ST", "LIAB.ST", "ITAB.ST", "NCAB.ST", "TROAX.ST",
        "SYSR.ST", "MYCR.ST", "NOTE.ST", "AQ.ST", "BEIJ-B.ST", "HMSN.ST",
        "NOLA-B.ST", "HPOL-B.ST", "VBG-B.ST", "ADDT-B.ST", "BETE.ST",
        "DOM.ST", "INWI.ST", "LOOMIS.ST", "OBDU.ST", "IMPC.ST",
    ],
    "Konsument & Livsstil": [
        "THULE.ST", "RVRC.ST", "SKIS-B.ST", "CARY.ST", "BHG.ST", "BJBO.ST",
        "FING-B.ST", "MEKO.ST", "BILI-A.ST", "CLAS-B.ST", "DUNI.ST",
        "MSON-B.ST", "DORO.ST", "AAK.ST", "AXFO.ST", "BMAX.ST",
    ],
    "Fintech & Finans": [
        "QLIRO.ST", "NOWO.ST", "RESURS.ST", "HOFI.ST", "INTRUM.ST",
    ],
    "Gaming & Underhållning": [
        "G5EN.ST", "BETS-B.ST", "EMBRAC-B.ST", "PDX.ST", "NENT-B.ST", "MTG-B.ST",
    ],
    "Cleantech & Energi": [
        "ARISE.ST", "EOLU-B.ST", "GRNG.ST", "POWERCELL.ST", "MINESTO.ST",
        "MYFC.ST", "MAHA-A.ST",
    ],
    "Investmentbolag": [
        "BURE.ST", "CRED-A.ST", "NAXS.ST", "TRAC-B.ST", "SVOL-B.ST",
        "VNV.ST", "EAST.ST", "KINV-B.ST", "LIFCO-B.ST", "INDT.ST",
        "RATO-B.ST", "LATO-B.ST",
    ],
    "Fastighet": [
        "KFAST-B.ST", "SSM.ST", "NIV.ST", "NP3.ST", "SLP-B.ST", "CIBUS.ST",
        "PION-B.ST", "BALD-B.ST", "CAST.ST", "FABG.ST", "SAGA-B.ST",
        "WIHL.ST", "DIOS.ST", "JM.ST", "PEAB-B.ST", "NCC-B.ST", "HUFV-A.ST",
        "CORE-B.ST", "FPAR-A.ST", "HEBA-B.ST", "BONAV-B.ST", "PLAZ-B.ST",
        "NYF.ST", "SBB-B.ST", "MTRS.ST", "HTRO.ST",
    ],
    "Tjänster & Konsult": [
        "BTS-B.ST", "COOR.ST", "HUMANA.ST", "NOBI.ST", "ESSITY-B.ST",
    ],
    "Material & Skog": [
        "SSAB-A.ST", "SSAB-B.ST", "SCA-B.ST", "HOLM-B.ST",
    ],
}
