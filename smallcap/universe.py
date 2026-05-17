"""
universe.py – Svenska småbolagsuniversum (~280 bolag).

Marknader:
  FIRST_NORTH – Nasdaq First North Growth Market
  SMALL_CAP   – Nasdaq Stockholm Small Cap & Mid/Large Cap (urval)
  SPOTLIGHT   – Spotlight Stock Market + NGM (mikrokap, hög risk)

Ticker-format: Yahoo Finance .ST-suffix.
  B-aktie: TICKER-B.ST (bindestreck)   A-aktie: TICKER-A.ST

Verifiera: python -m smallcap.validate_universe
"""

from pathlib import Path

# ── NASDAQ FIRST NORTH GROWTH MARKET ─────────────────────────────────────────
FIRST_NORTH = [
    # ── Mjukvara & SaaS ──────────────────────────────────────────────────────
    "LIME.ST",      # Lime Technologies – CRM för SME
    "FNOX.ST",      # Fortnox – molnredovisning
    "VIT-B.ST",     # Vitec Software B – vertikala marknadssystem
    "ANOD-B.ST",    # AddNode Group B – design/construction-mjukvara
    "ENEA.ST",      # Enea – nätverksmjukvara för telecom
    "IAR-B.ST",     # IAR Systems B – embedded development tools
    "RAY-B.ST",     # RaySearch Laboratories B – strålbehandlingssoftware
    "SECT-B.ST",    # Sectra B – medicinsk bilddiagnostik & cybersäkerhet
    "CINT.ST",      # Cint Group – digital insiktsplattform
    "KNOW.ST",      # Knowit – IT-konsult
    "PRIC-B.ST",    # Pricer B – elektroniska hylletiketter
    "TOBII.ST",     # Tobii – eye tracking
    "NETI-B.ST",    # Net Insight B – mediakommunikationsnätverk
    "CTEK.ST",      # CTEK – batterihantering och laddning
    "ALCA.ST",      # Alcadon Group – nätverksinfrastruktur
    "CTM.ST",       # Catena Media – online gaming affiliates
    "ACAST.ST",     # Acast – global podcastplattform
    "BUSER.ST",     # Bambuser – live video commerce
    "EGTX.ST",      # Egetis Therapeutics – särläkemedel
    "SAFETY-B.ST",  # mySafety Group B – f.d. Empir Group
    "PACT.ST",      # ProAct IT Group – lagring & molnlösningar
    "BAHN-B.ST",    # Bahnhof B – internetleverantör
    "FPIP.ST",      # Formpipe Software – offentlig sektor SaaS
    "MSAB-B.ST",    # Micro Systemation B – forensisk programvara
    "SOF-B.ST",     # Softronic B – IT-konsult
    "PRFO.ST",      # Profoto Holding – professionell fotoblixtutrustning
    "BIM.ST",       # BIMobject – BIM-innehållsplattform
    "UPSALE.ST",    # Upsales Technology – CRM/sälj-mjukvara
    "PREV-B.ST",    # Prevas B – teknikkonsult
    "NIL-B.ST",     # Nilörngruppen B – emballage & etikettering
    "EXS.ST",       # Exsitec – Visma-partner
    "ADVE.ST",      # Adverty – in-game advertising
    "IRIS.ST",      # Iris AB – mjukvara
    "SVED-B.ST",    # Svedbergs B – badrumsinredning
    "FERRO.ST",     # Ferroamp Elektronik – energilagring
    # ── Konsument & Handel ───────────────────────────────────────────────────
    "RUSTA.ST",     # Rusta – lågprisvaruhus
    "NEWA-B.ST",    # New Wave Group B – profilkläder & sport (f.d. NWG-B.ST)
    "ALLIGO-B.ST",  # Alligo B – teknisk distribution
    "LYKO-A.ST",    # Lyko Group A – skönhet online
    "BOOZT.ST",     # Boozt AB – mode-e-handel (f.d. BOOZ.ST)
    "HAYPP.ST",     # Haypp Group – tobaksalternativ (f.d. HAYP.ST)
    # ── Industri & Clean Tech ────────────────────────────────────────────────
    "MIPS.ST",      # MIPS – hjälmteknik, royaltymodell
    "GARO.ST",      # GARO – el-installationer och EV-laddning
    "OEM-B.ST",     # OEM International B – teknisk distributör
    "SDIP-B.ST",    # Sdiptech B – infrastrukturprodukter
    "XANO-B.ST",    # XANO Industri B – industritillverkning
    "REJL-B.ST",    # Rejlers B – teknikkonsult
    "HEXA-B.ST",    # Hexatronic Group B – fibernätsinfrastruktur
    "MILDEF.ST",    # Mildef Group – militär elektronik
    "INSTAL.ST",    # Instalco – tekniska installationstjänster
    "IVSO.ST",      # Invisio – hörsel/kommunikation för militär
    "BERG-B.ST",    # Bergman & Beving B
    "EOLU-B.ST",    # Eolus Vind B – vindkraftsutveckling
    "BRAV.ST",      # Bravida – teknisk installation
    "SENS.ST",      # Sensys Gatso – trafiksäkerhetslösningar
    "HANZA.ST",     # Hanza – elektroniktillverkning
    "TAGM-B.ST",    # TagMaster B – RFID transport & logistik
    "SINT.ST",      # SinterCast – CGI-teknologi
    "FNM.ST",       # FNM – elsystem
    "ENGCON-B.ST",  # engcon B – tiltrotatorer
    "VOLO.ST",      # Volo Group – friskvård
    "BEGR.ST",      # Begravningsgruppen
    # ── Fintech & Finans ─────────────────────────────────────────────────────
    "QLIRO.ST",     # Qliro – BNPL & betalningslösningar
    "NOWO.ST",      # Nowo – digital bank
    "RESURS.ST",    # Resurs Holding – konsumentlån
    "HOFI.ST",      # Hoist Finance – kreditfordringsinköp
    # ── Konsument & Livsstil ─────────────────────────────────────────────────
    "RVRC.ST",      # RVRC Holding – outdoor/workwear DTC
    "SKIS-B.ST",    # Skistar B – skidorter
    "BHG.ST",       # BHG Group – onlinehandel hem & trädgård
    "BORG.ST",      # Björn Borg – sportmode
    "FING-B.ST",    # Fingerprint Cards B – fingeravtrycksbiometri
    # ── Gaming & Underhållning ───────────────────────────────────────────────
    "G5EN.ST",      # G5 Entertainment – mobilspel
    "BETS-B.ST",    # Betsson B – online gaming
    "EMBRAC-B.ST",  # Embracer Group B – spelkoncern
    "PDX.ST",       # Paradox Interactive – strategi-PC-spel
    # ── Investmentbolag ──────────────────────────────────────────────────────
    "BURE.ST",      # Bure Equity – tillväxtbolagsinvesteringar
    "CRED-A.ST",    # Creades A – investmentbolag
    "NAXS.ST",      # NAXS – PE-fokuserat investmentbolag
    "TRAC-B.ST",    # Traction B – aktivt ägarbolag
    "SVOL-B.ST",    # Svolder B – small/micro cap-fokus
    "VNV.ST",       # VNV Global – tech & marketplace
    "EAST.ST",      # East Capital Explorer – tillväxtmarknader
    # ── Fastighet ────────────────────────────────────────────────────────────
    "KFAST-B.ST",   # K-Fast Holding B – hyresbostäder
    "NP3.ST",       # NP3 Fastigheter – norrländska fastigheter
    "SLP-B.ST",     # SLP B – industri- och logistikfastigheter
    "CIBUS.ST",     # Cibus Nordic Real Estate
    "PION-B.ST",    # Pioneer Property Group B
    "NIVI-B.ST",    # Nivika Fastigheter B
    "CATE.ST",      # Catella – fastighetsrådgivning
    "LOGI-B.ST",    # Logistea B
    "ALM.ST",       # ALM Equity
    "ENRO.ST",      # Enro – energirådgivning
    "LUMI.ST",      # Luminar Media Group
    # ── Energi & Miljö ───────────────────────────────────────────────────────
    "GRNG.ST",      # Greening – förnybar energi
    "EPRO-B.ST",    # Epro B – energibolag
    # ── MedTech & Life Science ───────────────────────────────────────────────
    "XVIVO.ST",     # XVIVO Perfusion – organpreservering
    "ELOS-B.ST",    # Elos Medtech B
    "BOMILL.ST",    # Bomill – spannmålssorteringsteknik
    "BIOG-B.ST",    # BioGaia B – probiotika
    "CEVI.ST",      # CellaVision – bloddifferentiering
    "MNTC.ST",      # Mentice – kirurgisk simulering
    "ALIG.ST",      # Alligator Bioscience – immuno-onkologi
    "QLINEA.ST",    # Q-linea – antibiotikaresistens
    "ONCO.ST",      # Oncopeptides – blodcancer
    "XSPRAY.ST",    # XSpray Pharma – nanopartikelformulering
    "HNSA.ST",      # Hansa Biopharma – enzymterapi
    "DMYD-B.ST",    # Diamyd Medical – autoimmun diabetes
    "ORX.ST",       # Orexo – beroendemedicin
    "ACTI.ST",      # Active Biotech – immunologi
    "IMMU.ST",      # Mendus AB – cancervaccin (f.d. Immunicum)
    "LINC.ST",      # LINC – life science-investmentbolag
    "CAMX.ST",      # CancerQ/CancerXomics – diagnostik
    "MCOV-B.ST",    # Medicover B – hälsovård Östeuropa
    "VIMIAN.ST",    # Vimian Group – veterinär MedTech
    "BOUL.ST",      # Boule Diagnostics – blodanalysinstrument
    "MOB.ST",       # Moberg Pharma – OTC dermatologi
    "PMED.ST",      # Peptonic Medical – medicinteknisk enhet
    "CRNO-B.ST",    # Cereno Scientific B – trombosbehandling
    "XBRANE.ST",    # Xbrane Biopharma – biosimilarer
    "SEDANA.ST",    # Sedana Medical – inhalationssedation
    "SEZI.ST",      # Senzime – intraoperativ neuroövervakning
    "CANTA.ST",     # Cantargia – IL1RAP-cancerbehandling
    "PCELL.ST",     # PowerCell Sweden – vätgasbränsleceller
    "MINEST.ST",    # Minesto – tidvattenskraft
    "MAHA-A.ST",    # Maha Energy A – oljeproduktion
    "ANOT.ST",      # Anoto Group – digital skrivteknik
    "INTEG-B.ST",   # Integrum B – bioniska proteser
    # ── Nya bolag: kvantitativ analys maj 2026 (v2) ─────────────────────────
    "NYAB.ST",      # NYAB AB – infrastruktur & anläggning
    "SECARE.ST",    # Swedencare – husdjurshälsa, 57,9% bruttomarginal
    "DVYSR.ST",     # Devyser Diagnostics – genetisk diagnostik
    "ZZ-B.ST",      # Zinzino B – kosttillskott direktförsäljning
    "QBNK.ST",      # QBNK Holding – DAM SaaS, 70%+ bruttomarginal
    "KAMBI.ST",     # Kambi Group – B2B sportbetting SaaS
    "STORY-B.ST",   # Story of AMS B
    "MAGI.ST",      # Maginatics (kontrollera)
    "SF.ST",        # Stillfront Group – spelutveckling
    # ── Kvantitativ allokeringsstudie maj 2026: 30 högpotentiella småbolag ──
    "W5.ST",        # W5 Solutions – försvarsindustri, orderbok 828 MSEK
    "GOMX.ST",      # GomSpace – nanosatelliter
    "AAC.ST",       # AAC Clyde Space – rymdsystem
    "VER.ST",       # Verve Group – AI-driven ad-tech-plattform
    "VERT-B.ST",    # Vertiseit – Digital In-store SaaS, ARR 341 MSEK
    "CX.ST",        # CombinedX – digitalisering & IT-konsult
    "IDUN-B.ST",    # Idun Industrier – förvärvsbyggare, 59% bruttomarginal
    "HUMBLE.ST",    # Humble Group – FMCG-hälsa, kassaflöde 515 MSEK
]


# ── NASDAQ STOCKHOLM SMALL CAP & MID CAP ─────────────────────────────────────
SMALL_CAP = [
    # ── Industri & Verkstad ───────────────────────────────────────────────────
    "BUFAB.ST",     # Bufab – global distributör av fästelement
    "LIAB.ST",      # Lindab International – ventilationssystem
    "ITAB.ST",      # ITAB Shop Concept – butiksinredning
    "THULE.ST",     # Thule Group – outdoor & transportprodukter
    "NCAB.ST",      # NCAB Group – PCB-distribution
    "TROAX.ST",     # Troax Group – maskinsäkerhetsskydd
    "SYSR.ST",      # Systemair – industriventilation
    "MYCR.ST",      # Mycronic – SMT-maskiner & lasersystem
    "NOTE.ST",      # NOTE – elektroniktillverkning
    "AQ.ST",        # AQ Group – elektroniktillverkning
    "BEIJ-B.ST",    # Beijer Electronics B – industriautomation
    "HMS.ST",       # HMS Networks – industriell datakommunikation
    "NOLA-B.ST",    # Nolato B – polymertillverkning
    "HPOL-B.ST",    # Hexpol B – gummiblandningar
    "BMAX.ST",      # Byggmax – lågprisbyggvaruhandel
    "VBG-B.ST",     # VBG Group B – dragkopplingssystem
    "ADDT-B.ST",    # Addtech B – teknisk distribution
    "LOOMIS.ST",    # Loomis – värdetransporter
    "DOM.ST",       # Dometic Group – mobillivsprodukter
    "AAK.ST",       # AAK – specialfetter & vegetabiliska oljor
    "AXFO.ST",      # Axfood – dagligvaruhandel
    "INWI.ST",      # Inwido – fönster och dörrar
    "NIBE-B.ST",    # NIBE Industrier B – värmepumpar
    "KABE-B.ST",    # KABE Group B – husvagnar
    "FAG.ST",       # Fagerhult Group – belysningslösningar
    "VOLV-B.ST",    # Volvo B – lastbilar & anläggningsmaskiner
    "SAND.ST",      # Sandvik – verktyg & gruvteknik
    "ALFA.ST",      # Alfa Laval – värmeöverföring & separation
    "ASSA-B.ST",    # ASSA ABLOY B – säkerhetslösningar
    "SKF-B.ST",     # SKF B – kullager
    "TREL-B.ST",    # Trelleborg B – polymerlösningar
    "HUSQ-B.ST",    # Husqvarna B – robotgräsklippare & motorsågar
    "INDU-C.ST",    # Industrivärden C – investmentbolag (f.d. INDUC-C.ST)
    "SWEC-B.ST",    # Sweco B – arkitektur & ingenjörstjänster
    "AFRY.ST",      # AFRY AB – teknikkonsult
    "ATT.ST",       # Attendo – omsorgsföretag
    "AMBEA.ST",     # Ambea – LSS & äldreomsorg
    "DUST.ST",      # Dustin Group – IT-produkter B2B
    "WISE.ST",      # Wise Group – HR-konsult
    "BONG.ST",      # Bong AB – kuvert & förpackningar
    "EVO.ST",       # Evolution AB – live casino
    "TRUE-B.ST",    # True Heading B
    # ── Konsument & Handel ────────────────────────────────────────────────────
    "MEKO.ST",      # Mekonomen – bildelehandel
    "BILI-A.ST",    # Bilia A – bilhandel
    "CLAS-B.ST",    # Clas Ohlson B – verktyg & fritidsprodukter
    "DUNI.ST",      # Duni – bordsdukning & förpackningar
    "MSON-B.ST",    # Midsona B – hälsokostprodukter
    "ICA.ST",       # ICA Gruppen – dagligvaruhandel
    # ── Tjänster & Konsult ────────────────────────────────────────────────────
    "BTS-B.ST",     # BTS Group B – affärssimuleringar
    "COOR.ST",      # Coor Service Management
    "HUM.ST",       # Humana – omsorgstjänster LSS/äldreomsorg
    "EWRK.ST",      # Ework Group – konsultförmedling
    "OGUN-B.ST",    # Ogunsen B – rekrytering (f.d. SJR in Scandinavia)
    "NOBI.ST",      # Nobina – kollektivtrafikoperatör
    # ── MedTech & Pharma ──────────────────────────────────────────────────────
    "EKTA-B.ST",    # Elekta B – strålbehandlingssystem
    "GETI-B.ST",    # Getinge B – medicinsk teknologi
    "ESSITY-B.ST",  # Essity B – hygien & hälsovård
    "ARJO-B.ST",    # Arjo B – patientlyft & mobilitet
    "VITR.ST",      # Vitrolife – IVF-medier & utrustning
    "BICO.ST",      # BICO Group – bioprinting
    "SOBI.ST",      # Sobi – Swedish Orphan Biovitrum
    "ALIF-B.ST",    # AddLife B – medicinteknisk distribution (f.d. ADDL-B.ST)
    "BIOA-B.ST",    # BioArctic B – Alzheimer-behandling
    "ARISE.ST",     # Arise – vindkraftsutveckling
    "BIOT.ST",      # Biotage – analytiska instrument
    # ── Tech & Mjukvara ───────────────────────────────────────────────────────
    "SINCH.ST",     # Sinch – kommunikationsplattform CPaaS
    # ── Fastighet ─────────────────────────────────────────────────────────────
    "BALD-B.ST",    # Balder B – bostäder & kommersiella fastigheter
    "CAST.ST",      # Castellum – kontors- & handelsfastigheter
    "FABG.ST",      # Fabege – kontorsfastigheter Stockholm CBD
    "SAGA-B.ST",    # Sagax B – industri- & lagerfastigheter
    "WIHL.ST",      # Wihlborgs Fastigheter – Malmö/Öresund
    "DIOS.ST",      # Diös Fastigheter – norrland
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
    "SBB-B.ST",     # Samhällsbyggnadsbolaget B
    "BRIN-B.ST",    # Brinova Fastigheter B
    "ATRLJ-B.ST",   # Atrium Ljungberg B – fastigheter
    # ── Finans & Kapitalförvaltning ───────────────────────────────────────────
    "INTRUM.ST",    # Intrum – inkasso & kredithantering
    "KINV-B.ST",    # Kinnevik B – investmentbolag
    "LIFCO-B.ST",   # Lifco B – förvärvsmaskin
    "INDT.ST",      # Indutrade – industriell distribution
    "RATO-B.ST",    # Ratos B – PE-investmentbolag
    "LATO-B.ST",    # Latour B – investmentbolag
    "BINV.ST",      # Byggmästare Anders J Ahlström Invest B
    "AZA.ST",       # Avanza Bank – nätmäklare (f.d. AVANZ.ST)
    "EQT.ST",       # EQT AB – private equity
    "INVE-B.ST",    # Investor B – investmentbolag (Wallenberg)
    "SEB-A.ST",     # SEB A – storbank
    "SHB-A.ST",     # Handelsbanken A – storbank
    "SWED-A.ST",    # Swedbank A – storbank
    "NDA-SE.ST",    # Nordea SE – storbank
    # ── Material & Skog ───────────────────────────────────────────────────────
    "SSAB-A.ST",    # SSAB A – höghållfast specialstål
    "SSAB-B.ST",    # SSAB B
    "SCA-B.ST",     # SCA B – skog, papper & förpackningar
    "HOLM-B.ST",    # Holmen B – skog, papper & energi
    "SCST.ST",      # Scandi Standard – kyckling
    "NEXAM.ST",     # Nexam Chemical – polymerteknik
    "BERNER-B.ST",  # Berner Industrier B (f.d. BERN.ST)
    # ── Telecom & Media ───────────────────────────────────────────────────────
    "VPLAY-B.ST",   # Viaplay Group B – streaming (f.d. NENT-B.ST)
    "MTG-B.ST",     # Modern Times Group B – gaming & media
    "TEL2-B.ST",    # Tele2 B – telekommunikation
    "TELIA.ST",     # Telia – telekommunikation
    # ── Nya bolag: kvantitativ analys maj 2026 (v2) ─────────────────────────
    "MMGR-B.ST",    # Momentum Group B – industridistribution, ROE 22,9%
    "GREEN.ST",     # Green Landscaping Group – utemiljö, stark FCF
    "NELLY.ST",     # Nelly Group – e-handel mode, turnaround
    "SILEX.ST",     # Silex Microsystems – MEMS foundry
    "CLA-B.ST",     # Cloetta B – konfektyr, stark prisningsmakt
    "MORROW.ST",    # Morrow Bank – nischbank, konsumentlån
    "ORRON.ST",     # Orrön Energy – förnybar energi, stark FCF Yield
    "OVZON.ST",     # Ovzon – SatCom-as-a-Service
    "NEOBO.ST",     # Neobo Fastigheter – bostäder, aktieåterköp
    "VICO.ST",      # Vicore Pharma – IPF-pipeline (f.d. VICOR.ST)
    "KDEV.ST",      # Karolinska Development – life science investmentbolag
    # ── Kvantitativ allokeringsstudie maj 2026: 30 högpotentiella småbolag ──
    "BONEX.ST",     # Bonesupport – ortobiologi, 95,3% bruttomarginal
    "ADDV-B.ST",    # ADDvise Group – life science förvärvsbyggare
    "SUS.ST",       # Surgical Science – VR-kirurgisimulatorer
    "NTEK-B.ST",    # Novotek – industriell IT & automation
    "B3.ST",        # B3 Consulting Group – IT-konsult
    "KARNEL-B.ST",  # Karnell Group – industriell förvärvsbyggare
    "LAGR-B.ST",    # Lagercrantz Group – förvärvsbyggare, ROE 27,9%
    "BULTEN.ST",    # Bulten – fästelement, expanderande marginaler
    "INISS-B.ST",   # Inission – kontraktstillverkning EMS, 37% tillväxt
    "CBTT-B.ST",    # Christian Berner Tech Trade – teknisk B2B-handel
    "DUROC-B.ST",   # Duroc – industrigrupp, robust kassaflöde
    "HAKI-B.ST",    # HAKI Safety – säkra arbetsplatser, oelastisk efterfrågan
    "ELON.ST",      # Elon Group – vitvaror & hemelektronik
]


# ── SPOTLIGHT STOCK MARKET & NGM (urval) ─────────────────────────────────────
# Mikrokap. Hög risk. Filtret tar bort illikvida bolag.
SPOTLIGHT = [
    # ── Biotech & MedTech ────────────────────────────────────────────────────
    "BIOT.ST",      # Biotage – analytiska instrument (alt. notering)
    "ELIC.ST",      # Elicera Therapeutics – CAR-T
    "ENZY.ST",      # Enzymatica – enzymbaserade läkemedel
    "IMPC.ST",      # Impact Coatings – PVD-beläggning
    "DICOT.ST",     # Dicot Pharma – erektil dysfunktion
    "SPAGO.ST",     # Spago Nanomedical – radiosensibilisering
    "XINT.ST",      # Xintela – ledbroskterapier
    "REAL.ST",      # Real Heart – konstgjort hjärta
    # ── Cleantech & Energi ────────────────────────────────────────────────────
    "SOLT.ST",      # Soltech Energy – solenergi (f.d. SOL.ST)
    "BESQAB.ST",    # Besqab AB – bostadsutveckling (f.d. AROS.ST)
    "OPTI.ST",      # Opti AB – avloppsoptimering
    # ── IT & Digitalt ────────────────────────────────────────────────────────
    "CLAV.ST",      # Clavister Holding – cybersäkerhet
    "VERI.ST",      # Verisec – digital identitet
    "AYIMA-B.ST",   # Ayima Group B – digital marknadsföring
    "BRIGHT.ST",    # BrightBid – AI-baserad annonsering
    "AWRD.ST",      # Awardit – lojalitetsprogram
    "EASY-B.ST",    # EasyFill B – fyllnadsautomation för butiker
    "NBZ.ST",       # Northbaze Group – headphones (f.d. JAYS.ST)
    "SAFE.ST",      # Safeture – resandesäkerhet
    "SPEC.ST",      # Speakerset
    "MCAP.ST",      # Midroc Invest
    # ── Fastighet (Spotlight) ────────────────────────────────────────────────
    "MTRS.ST",      # Mälarstaden – fastighetsbolag
    "HTRO.ST",      # Heatron – fastighetsutveckling
    # ── Nya bolag: kvantitativ analys maj 2026 (v2) ─────────────────────────
    "PLEJD.ST",     # Plejd – smart belysning, 1 Mdr+ omsättning, stark FCF
    "FREETR.ST",     # Freetrailer – delningsekonomi, asset-light
    "SUSG.ST",      # Sustainion Group – hållbarhetsteknik
    "ANGL.ST",      # Angler Gaming – iGaming, 40%+ bruttomarginal
    "BPCINS.ST",    # BPC Instruments – biogas analytik
    "GJAB.ST",      # Gullberg & Jansson – klimatprodukter
    "SOLIDX.ST",    # SolidX – IT-konsult, snabbväxande
    "BEYOND.ST",    # Beyond Frames Entertainment – VR-spel
    "REDS.ST",      # Redsense Medical – dialysövervakning
    # ── Kvantitativ allokeringsstudie maj 2026: 30 högpotentiella småbolag ──
    "ASTOR.ST",     # Scandinavian Astor Group – försvar & cybersäkerhet
]


# ── KOMBINERAT UNIVERSUM ──────────────────────────────────────────────────────

_ALL = FIRST_NORTH + SMALL_CAP + SPOTLIGHT

# Deduplicera (behåll första förekomsten)
SMALLCAP_UNIVERSE = list(dict.fromkeys(t.upper() for t in _ALL))

# Sökväg till användarens egna tickers
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


# ── Bransch-kategorier (uppdaterad med 30 nya bolag maj 2026) ─────────────────
SECTOR_GROUPS = {
    "Försvar & Rymd": [
        "MILDEF.ST", "IVSO.ST", "W5.ST", "ASTOR.ST", "OVZON.ST",
        "GOMX.ST", "AAC.ST", "CLAV.ST",
    ],
    "Mjukvara & SaaS": [
        "LIME.ST", "FNOX.ST", "VIT-B.ST", "ANOD-B.ST", "ENEA.ST", "IAR-B.ST",
        "RAY-B.ST", "SECT-B.ST", "CINT.ST", "KNOW.ST", "PRIC-B.ST", "TOBII.ST",
        "NETI-B.ST", "CTEK.ST", "ALCA.ST", "CTM.ST", "ACAST.ST", "BUSER.ST",
        "SAFETY-B.ST", "PACT.ST", "BAHN-B.ST", "FPIP.ST", "MSAB-B.ST", "SOF-B.ST",
        "PRFO.ST", "BIM.ST", "UPSALE.ST", "PREV-B.ST", "NIL-B.ST", "EXS.ST",
        "ADVE.ST", "SINCH.ST", "VERI.ST", "AWRD.ST",
        "SAFE.ST", "EASY-B.ST", "QBNK.ST", "EWRK.ST", "BRIGHT.ST", "AYIMA-B.ST",
        "KAMBI.ST", "NBZ.ST", "VER.ST", "VERT-B.ST", "CX.ST",
    ],
    "MedTech & Life Science": [
        "XVIVO.ST", "ELOS-B.ST", "BOMILL.ST", "BIOG-B.ST", "CEVI.ST", "MNTC.ST",
        "ALIG.ST", "QLINEA.ST", "ONCO.ST", "XSPRAY.ST", "HNSA.ST",
        "DMYD-B.ST", "ORX.ST", "ACTI.ST", "IMMU.ST", "MCOV-B.ST",
        "VIMIAN.ST", "BOUL.ST", "MOB.ST", "PMED.ST", "CRNO-B.ST", "XBRANE.ST",
        "SEDANA.ST", "SEZI.ST", "CANTA.ST", "INTEG-B.ST", "EGTX.ST",
        "BIOT.ST", "ELIC.ST", "KDEV.ST", "ENZY.ST", "GETI-B.ST", "EKTA-B.ST",
        "ARJO-B.ST", "VITR.ST", "BICO.ST", "LINC.ST", "CAMX.ST", "ALIF-B.ST",
        "SOBI.ST", "BIOA-B.ST", "DICOT.ST", "SPAGO.ST",
        "REAL.ST", "SECARE.ST",
        "DVYSR.ST", "VICO.ST", "REDS.ST", "XINT.ST", "IMPC.ST",
        "BONEX.ST", "ADDV-B.ST", "SUS.ST",
    ],
    "Industri & Verkstad": [
        "MIPS.ST", "GARO.ST", "OEM-B.ST", "SDIP-B.ST", "XANO-B.ST", "REJL-B.ST",
        "HEXA-B.ST", "INSTAL.ST", "BERG-B.ST", "EOLU-B.ST",
        "BRAV.ST", "SENS.ST", "HANZA.ST", "TAGM-B.ST", "BUFAB.ST", "LIAB.ST",
        "ITAB.ST", "NCAB.ST", "TROAX.ST", "SYSR.ST", "MYCR.ST", "NOTE.ST",
        "AQ.ST", "BEIJ-B.ST", "HMS.ST", "NOLA-B.ST", "HPOL-B.ST", "VBG-B.ST",
        "ADDT-B.ST", "DOM.ST", "INWI.ST", "LOOMIS.ST", "ANOT.ST", "ENGCON-B.ST",
        "VOLV-B.ST", "SAND.ST", "ALFA.ST", "ASSA-B.ST", "SKF-B.ST", "TREL-B.ST",
        "HUSQ-B.ST", "SWEC-B.ST", "AFRY.ST", "MMGR-B.ST", "GREEN.ST", "SILEX.ST",
        "SINT.ST", "FNM.ST", "NTEK-B.ST", "INISS-B.ST", "CBTT-B.ST",
        "DUROC-B.ST", "HAKI-B.ST", "BULTEN.ST",
    ],
    "Konsument & Livsstil": [
        "THULE.ST", "RVRC.ST", "SKIS-B.ST", "BHG.ST", "BORG.ST",
        "FING-B.ST", "MEKO.ST", "BILI-A.ST", "CLAS-B.ST", "DUNI.ST", "MSON-B.ST",
        "AAK.ST", "AXFO.ST", "BMAX.ST", "RUSTA.ST", "NEWA-B.ST", "ALLIGO-B.ST", "LYKO-A.ST",
        "KABE-B.ST", "FAG.ST", "ICA.ST", "NELLY.ST", "CLA-B.ST", "PLEJD.ST",
        "HAYPP.ST", "BOOZT.ST", "HUMBLE.ST", "ELON.ST",
    ],
    "Fintech & Finans": [
        "QLIRO.ST", "NOWO.ST", "RESURS.ST", "HOFI.ST", "INTRUM.ST",
        "AZA.ST", "SEB-A.ST", "SHB-A.ST", "SWED-A.ST", "NDA-SE.ST",
        "MORROW.ST", "KAMBI.ST",
    ],
    "Gaming & Underhållning": [
        "G5EN.ST", "BETS-B.ST", "EMBRAC-B.ST", "PDX.ST", "VPLAY-B.ST", "MTG-B.ST",
        "EVO.ST", "ANGL.ST", "BEYOND.ST", "SF.ST",
    ],
    "Cleantech & Energi": [
        "EOLU-B.ST", "GRNG.ST", "PCELL.ST", "MINEST.ST",
        "MAHA-A.ST", "EPRO-B.ST", "ORRON.ST", "SUSG.ST", "SOLT.ST",
        "ARISE.ST", "OPTI.ST",
    ],
    "Investmentbolag & Förvärvsbyggare": [
        "BURE.ST", "CRED-A.ST", "NAXS.ST", "TRAC-B.ST", "SVOL-B.ST", "VNV.ST",
        "EAST.ST", "KINV-B.ST", "LIFCO-B.ST", "INDT.ST", "RATO-B.ST", "LATO-B.ST",
        "BINV.ST", "EQT.ST", "INVE-B.ST", "INDU-C.ST", "KDEV.ST",
        "KARNEL-B.ST", "LAGR-B.ST", "IDUN-B.ST",
    ],
    "Fastighet": [
        "KFAST-B.ST", "NP3.ST", "SLP-B.ST", "CIBUS.ST", "PION-B.ST",
        "BALD-B.ST", "CAST.ST", "FABG.ST", "SAGA-B.ST", "WIHL.ST", "DIOS.ST",
        "JM.ST", "PEAB-B.ST", "NCC-B.ST", "HUFV-A.ST", "CORE-B.ST", "FPAR-A.ST",
        "HEBA-B.ST", "BONAV-B.ST", "PLAZ-B.ST", "NYF.ST", "SBB-B.ST",
        "MTRS.ST", "HTRO.ST", "NIVI-B.ST", "CATE.ST", "LOGI-B.ST",
        "ALM.ST", "BRIN-B.ST", "ATRLJ-B.ST", "NEOBO.ST", "BESQAB.ST",
    ],
    "Tjänster & Konsult": [
        "BTS-B.ST", "COOR.ST", "HUM.ST", "NOBI.ST", "ESSITY-B.ST", "EWRK.ST",
        "DUST.ST", "WISE.ST", "OGUN-B.ST", "ATT.ST", "AMBEA.ST",
        "SWEC-B.ST", "AFRY.ST", "SOLIDX.ST", "GJAB.ST", "FREETR.ST", "BPCINS.ST",
        "VOLO.ST", "BEGR.ST", "B3.ST",
    ],
    "Material & Skog": [
        "SSAB-A.ST", "SSAB-B.ST", "SCA-B.ST", "HOLM-B.ST", "SCST.ST", "NEXAM.ST",
        "BERNER-B.ST",
    ],
    "Telecom & Media": [
        "VPLAY-B.ST", "MTG-B.ST", "TEL2-B.ST", "TELIA.ST", "SINCH.ST",
        "CTM.ST", "ACAST.ST",
    ],
}
