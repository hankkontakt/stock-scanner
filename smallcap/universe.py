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
    "XMREAL.ST",    # XM Reality – fjärrstöd med AR
    "SDLAB.ST",     # Sdiptech Lab – (se SDIP-B.ST)
    "PREV-B.ST",    # Prevas B – teknikkonsult
    "NEWE-B.ST",    # New Wave Group B (alt. noteringssymbol)
    "SYNC.ST",      # Syncro Group – dealer management system
    "PROG-B.ST",    # Progrits B – affärsutveckling
    "NIL-B.ST",     # Nilörngruppen B – emballage & etikettering
    "FRON.ST",      # Frontline (Swedish entity)
    "VADS.ST",      # Vadsbo Group – elektrisk infrastruktur
    "PEN.ST",       # Penneo – e-signatur & KYC
    "ZIGN.ST",      # ZignSec – identitetsverifiering
    "CS-B.ST",      # Creades B (alt. symbol)
    "FORM.ST",      # FormPipe (alt. symbol)
    "TEX-B.ST",     # Textilia B – tvätteri & textilservice
    "ADVE.ST",      # Adverty – in-game advertising
    "CSEC.ST",      # C-SEC – cybersäkerhet
    "EXS.ST",       # Exsitec – Visma-partner
    "IMNT.ST",      # Imint Image Intelligence – videostabilisering
    "TCOK.ST",      # TC CONNECT – bredband Norden
    "ZETA.ST",      # Zeta Displays – digital skyltning
    "SMART.ST",     # SmartLighting Industries
    "HOPS.ST",      # Hoist Finance (alt. symbol)
    "INFR.ST",      # Infracom Group – kommunikationstjänster
    "IRIS.ST",      # Iris AB – mjukvara
    "SUST.ST",      # Sustainable Energy Solutions
    "MCAP.ST",      # Midroc Invest (Spotlight)
    "VICO.ST",      # Vicore Pharma – IPF-behandling
    "BONE.ST",      # Bonava (alt. symbol)
    "MEND.ST",      # Mendus – cancervaccin
    "HERIS.ST",     # Heristo (tysklistad, ev. SEK-handel)
    "RLS.ST",       # RLS Global – infektionsskydd
    "EQL.ST",       # Equalizer Group
    "MEDV.ST",      # MedVivo Group
    "SYME.ST",      # Symcel – kalorimetri
    "NANO.ST",      # Nanologica – nanomaterial
    "CHLO.ST",      # Chlora Connecting – telekommunikation
    "GENT.ST",      # Gentec – teknikkonsult
    "TIGO.ST",      # Tigerholm Innovation – brandsäkerhet
    "TETR.ST",      # Tetrapak-relaterat (kontrollera)
    "ISAB.ST",      # ISAB – kemikalieindustri
    "BRIG.ST",      # Bridgefunds – fintech
    "DIGN.ST",      # Dignita Systems – HR-mjukvara
    "OASM.ST",      # Oasmia Pharmaceutical – läkemedelsutveckling
    "SINT.ST",      # SinterCast – CGI-teknologi
    "FNM.ST",       # FNM – elsystem
    "NORDIS.ST",    # Nordisk Solar – solenergi
    "FMAT.ST",      # Fingerprint Cards alt. symbol
    "ENGCON-B.ST",  # engcon B – tiltrotatorer
    "CNC.ST",       # CNC Invest
    "VOLO.ST",      # Volo Group – friskvård
    "BEGR.ST",      # Begravningsgruppen
    "PROF-B.ST",    # Proffice B (historical / kontrollera)
    "WESC.ST",      # WeSC – streetwear
    "POLY.ST",      # Polyplank – skummad plast
    "MIDW-B.ST",    # Midway Holding B
    "INVI.ST",      # Inviqa – IT-konsult
    "ROB.ST",       # Robit – borrutrustning
    "ENQ.ST",       # Enquest (SEK-handel)
    "SVED-B.ST",    # Svedbergs B – badrumsinredning
    "FERRO.ST",     # Ferroamp Elektronik – energilagring
    "NOVTE.ST",     # Novatel Wireless (SEK-handel)
    "SBEF.ST",      # SBEF – byggentreprenad
    "INAB.ST",      # Invuo Technologies
    "RUSTA.ST",     # Rusta – lågprisvaruhus
    "SYNT.ST",      # Synthetica – läkemedelsutveckling
    "NWG-B.ST",     # New Wave Group B (se NEWE-B.ST)
    "ALLIGO-B.ST",  # Alligo B – teknisk distribution
    "KOPP-B.ST",    # Kopparbergs Bryggeri B
    "LYKO-A.ST",    # Lyko Group A – skönhet online
    "PIZZ.ST",      # Pizza Royale (Spotlight)
    "BOOZ.ST",      # Boozt – mode-e-handel
    "MELL.ST",      # Melker Schörling AB
    "HVD.ST",       # Hövding Sverige – airbag-hjälm
    "NAVA.ST",      # Navamedic – specialty pharma
    "HAYP.ST",      # Haypp Group – tobaksalternativ
    "DSNAB.ST",     # DS Smith (SEK-handel)
    "FOOT-B.ST",    # Footway Group B – skohandel
    "MNO.ST",       # Mentimeter (ej noterat?) / kontrollera
    "PEARL.ST",     # Pearl Gold Group
    "NIVI-B.ST",    # Nivika Fastigheter B
    "STEND.ST",     # Stendörren Fastigheter
    "CATE.ST",      # Catella – fastighetsrådgivning
    "BOSJO.ST",     # Bosjö Fastigheter
    "LOGI-B.ST",    # Logistea B
    "AMST.ST",      # Amste (kontrollera)
    "ALM.ST",       # ALM Equity
    "TITAN.ST",     # Titan X Group
    "KVAR.ST",      # Kvartilen (kontrollera)
    "MAGE.ST",      # Mäklarsamfundet (ej noterat?) / kontrollera
    "SBF.ST",       # SBF Bostad
    "TROS.ST",      # Troostsbeeken (kontrollera)
    "TETY.ST",      # Teralytics (kontrollera)
    "ENRO.ST",      # Enro – energirådgivning
    "CORT.ST",      # Cortendo – läkemedel
    "BENG.ST",      # BEngtssons Trävaru
    "MINA.ST",      # Mina Tjänster – digital post
    "LUMI.ST",      # Luminar Media Group
    "GIGSEK.ST",    # GigSek – IT-säkerhet
    "KAMBI.ST",     # Kambi Group – B2B sportbetting SaaS
    "STORY-B.ST",   # Story of AMS B
    "AGIG.ST",      # Academy of Gigolos (kontrollera)
    "ZORD.ST",      # Zordix – spelutveckling
    "THQ.ST",       # THQ Nordic (se EMBRAC-B.ST för moderbolag)
    "FRBL.ST",      # Frisq Holding
    "MAGI.ST",      # Maginatics (kontrollera)
    "NITA.ST",      # Nita Group
    "RVR.ST",       # Rover Group
    "SF.ST",        # SF Studios (kontrollera)
    "SDOL.ST",      # Skanska Dolderaa (kontrollera)
    "SVEA.ST",      # Sveaskog (statligt, ej börsen?) / kontrollera
    "TFH.ST",       # TF Holding
    "PENN.ST",      # Penna – digitala pennor
    "NOVA.ST",      # Novatek International (kontrollera)
    "FSK.ST",       # Fastighetskreditering (kontrollera)
    "AGR.ST",       # Agra – lantbruk
    # ── Nya bolag: kvantitativ analys maj 2026 ───────────────────────────────
    "NYAB.ST",      # NYAB AB – infrastruktur & anläggning, stark insideraktivitet
    "SECARE.ST",    # Swedencare – husdjurshälsa, 57,9% bruttomarginal
    "DVYSR.ST",     # Devyser Diagnostics – genetisk diagnostik, FCF-positiv
    "ZZ-B.ST",      # Zinzino B – kosttillskott direktförsäljning
    "TCC.ST",       # TCECUR Sweden – säkerhetsteknik (f.d. TCECUR.ST)
    "QBNK.ST",      # QBNK Holding – DAM SaaS, 70%+ bruttomarginal
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
    "COIC.ST",      # Coieo – industriell distribution
    "EOLU-B.ST",    # Eolus Vind B – vindkraftsutveckling
    "BRAV.ST",      # Bravida – teknisk installation
    "SENS.ST",      # Sensys Gatso – trafiksäkerhetslösningar
    "HANZA.ST",     # Hanza – elektroniktillverkning
    "TAGM-B.ST",    # TagMaster B – RFID transport & logistik
    # ── Fintech & Finans ─────────────────────────────────────────────────────
    "QLIRO.ST",     # Qliro – BNPL & betalningslösningar
    "NOWO.ST",      # Nowo – digital bank
    "RESURS.ST",    # Resurs Bank – konsumentlån
    "HOFI.ST",      # Hoist Finance – kreditfordringsinköp
    # ── Konsument & Livsstil ─────────────────────────────────────────────────
    "RVRC.ST",      # RVRC Holding – outdoor/workwear DTC
    "SKIS-B.ST",    # Skistar B – skidorter
    "CARY.ST",      # Cary Group – skadeverkstäder
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
    "SSM.ST",       # SSM Holding – studentbostäder
    "NP3.ST",       # NP3 Fastigheter – norrländska fastigheter
    "SLP-B.ST",     # SLP B – industri- och logistikfastigheter
    "CIBUS.ST",     # Cibus Nordic Real Estate
    "PION-B.ST",    # Pioneer Property Group B
    # ── Energi & Miljö ───────────────────────────────────────────────────────
    "ARISE.ST",     # Arise – vindkraftsutveckling
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
    "IRRAS.ST",     # IRRAS – neurointensivvård
    "QLINEA.ST",    # Q-linea – antibiotikaresistens
    "ONCO.ST",      # Oncopeptides – blodcancer
    "XSPRAY.ST",    # XSpray Pharma – nanopartikelformulering
    "HNSA.ST",      # Hansa Biopharma – enzymterapi
    "CALTX.ST",     # Calliditas Therapeutics – IgA-nefropati
    "DMYD-B.ST",    # Diamyd Medical – autoimmun diabetes
    "ORX.ST",       # Orexo – beroendemedicin
    "ACTI.ST",      # Active Biotech – immunologi
    "IMMU.ST",      # Immunicum – cancerimmunologi
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
    "RECI-B.ST",    # Recipharm B – kontraktstillverkning läkemedel
    "MAHA-A.ST",    # Maha Energy A – oljeproduktion
    "ANOT.ST",      # Anoto Group – digital skrivteknik
    "INTEG-B.ST",   # Integrum B – bioniska proteser
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
    "ENGCON-B.ST",  # engcon B – tiltrotatorer för grävmaskiner
    "VOLV-B.ST",    # Volvo B – lastbilar & anläggningsmaskiner
    "SAND.ST",      # Sandvik – verktyg & gruvteknik
    "ALFA.ST",      # Alfa Laval – värmeöverföring & separation
    "ASSA-B.ST",    # ASSA ABLOY B – säkerhetslösningar
    "SKF-B.ST",     # SKF B – kullager
    "TREL-B.ST",    # Trelleborg B – polymerlösningar
    "HUSQ-B.ST",    # Husqvarna B – robotgräsklippare & motorsågar
    "INDUC-C.ST",   # Industrivärden C – investmentbolag
    "LUG.ST",       # Lugnet (kontrollera)
    "SWEC-B.ST",    # Sweco B – arkitektur & ingenjörstjänster
    "AFRY.ST",      # AFRY AB – teknikkonsult
    "ALEM.ST",      # Aleris Group – privat sjukvård
    "ATT.ST",       # Attendo – omsorgsföretag
    "AMBEA.ST",     # Ambea – LSS & äldreomsorg
    "RROS.ST",      # RörTjänst (kontrollera)
    "DUST.ST",      # Dustin Group – IT-produkter B2B
    "BYGG.ST",      # Bygghemma Group
    "WISE.ST",      # Wise Group – HR-konsult
    "ACAD.ST",      # Academic Work – bemanningsföretag
    "INT.ST",       # Intoi – IT-distribution
    "SJR-B.ST",     # SJR in Scandinavia B – rekrytering
    "POOL-B.ST",    # PoolStar B (kontrollera)
    "BONG.ST",      # Bong AB – kuvert & förpackningar
    "NVP.ST",       # Nordic Waterproofing – tätskikt
    "TRUE-B.ST",    # True Heading B
    "EVO.ST",       # Evolution AB – live casino
    "NOD.ST",       # Nordic Optical Disk (kontrollera)
    "PROE.ST",      # ProEngineering (kontrollera)
    "SFTY.ST",      # Schoeller Allibert (kontrollera)
    "CTH.ST",       # Corem T H (kontrollera)
    "DATA.ST",      # DataLink (kontrollera)
    "ADDL-B.ST",    # Addlife B – medicinteknisk distribution
    "SOBI.ST",      # Sobi – Swedish Orphan Biovitrum
    "CALL.ST",      # Callaway Golf (SEK-handel)
    "KAR.ST",       # Kar Group (kontrollera)
    "BIOA-B.ST",    # BioArctic B – Alzheimer-behandling
    "HUFV-C.ST",    # Hufvudstaden C – premium fastigheter
    "BRIN-B.ST",    # Brinova Fastigheter B
    "ATRLJ-B.ST",   # Atrium Ljungberg B – fastigheter
    # ── Konsument & Handel ────────────────────────────────────────────────────
    "MEKO.ST",      # Mekonomen – bildelehandel
    "BILI-A.ST",    # Bilia A – bilhandel
    "CLAS-B.ST",    # Clas Ohlson B – verktyg & fritidsprodukter
    "DUNI.ST",      # Duni – bordsdukning & förpackningar
    "MSON-B.ST",    # Midsona B – hälsokostprodukter
    # ── Tjänster & Konsult ────────────────────────────────────────────────────
    "BTS-B.ST",     # BTS Group B – affärssimuleringar
    "COOR.ST",      # Coor Service Management
    "HUM.ST",       # Humana – omsorgstjänster LSS/äldreomsorg
    "EWORK.ST",     # Ework Group – konsultförmedling
    # ── MedTech & Pharma ──────────────────────────────────────────────────────
    "EKTA-B.ST",    # Elekta B – strålbehandlingssystem
    "GETI-B.ST",    # Getinge B – medicinsk teknologi
    "ESSITY-B.ST",  # Essity B – hygien & hälsovård
    "ARJO-B.ST",    # Arjo B – patientlyft & mobilitet
    "VITR.ST",      # Vitrolife – IVF-medier & utrustning
    "BICO.ST",      # BICO Group – bioprinting
    # ── Tech & Mjukvara ───────────────────────────────────────────────────────
    "SINCH.ST",     # Sinch – kommunikationsplattform CPaaS
    "MYFC.ST",      # myFC Holding – bränsleceller
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
    # ── Finans & Kapitalförvaltning ───────────────────────────────────────────
    "INTRUM.ST",    # Intrum – inkasso & kredithantering
    "KINV-B.ST",    # Kinnevik B – investmentbolag
    "LIFCO-B.ST",   # Lifco B – förvärvsmaskin
    "INDT.ST",      # Indutrade – industriell distribution
    "RATO-B.ST",    # Ratos B – PE-investmentbolag
    "NOBI.ST",      # Nobina – kollektivtrafikoperatör
    "LATO-B.ST",    # Latour B – investmentbolag
    "BINV.ST",      # Byggmästare Anders J Ahlström Invest B
    "AZA.ST",       # Avanza Bank – nätmäklare (f.d. AVANZ.ST)
    "EQT.ST",       # EQT AB – private equity
    "INVE-B.ST",    # Investor B – investmentbolag (Wallenberg)
    "SEB-A.ST",     # SEB A – storbank
    "SHB-A.ST",     # Handelsbanken A – storbank
    "SWED-A.ST",    # Swedbank A – storbank
    "NDA-SE.ST",    # Nordea SE – storbank
    "ICA.ST",       # ICA Gruppen – dagligvaruhandel
    "NORD.ST",      # Nordnet Bank – nätmäklare
    "SDOL.ST",      # Sdiptech (alt. symbol, se SDIP-B.ST)
    "SVEA.ST",      # Sveaskog (kontrollera – statligt)
    "TFH.ST",       # TF Holding
    "PENN.ST",      # Penna Industries (kontrollera)
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
    "MILL.ST",      # Millicom (SEK-handel, kontrollera)
    "TELE.ST",      # Tele2 (alt. symbol, kontrollera)
    # ── Nya bolag: kvantitativ analys maj 2026 ───────────────────────────────
    "MMGR-B.ST",    # Momentum Group B – industridistribution, ROE 22,9%
    "GREEN.ST",     # Green Landscaping Group – utemiljö, stark FCF
    "NELLY.ST",     # Nelly Group – e-handel mode, turnaround
    "SILEX.ST",     # Silex Microsystems – MEMS foundry, IPO maj 2026
    "CLA-B.ST",     # Cloetta B – konfektyr, stark prisningsmakt
    "MORROW.ST",    # Morrow Bank – nischbank, konsumentlån
    "ORRON.ST",     # Orrön Energy – förnybar energi, stark FCF Yield
    "OVZON.ST",     # Ovzon – SatCom-as-a-Service
    "NEOBO.ST",     # Neobo Fastigheter – bostäder, aktieåterköp
    "VICO.ST",      # Vicore Pharma – IPF-pipeline (f.d. VICOR.ST)
    "SFRG.ST",      # Stillfront Group – spelutveckling, FCF-expansion
]


# ── SPOTLIGHT STOCK MARKET & NGM (urval) ─────────────────────────────────────
# Mikrokap. Hög risk. Filtret tar bort illikvida bolag.
SPOTLIGHT = [
    # ── Biotech & MedTech ────────────────────────────────────────────────────
    "BIOT.ST",      # Biotage – analytiska instrument
    "ELIC.ST",      # Elicera Therapeutics – CAR-T
    "KDEV.ST",      # Karolinska Development – life science investmentbolag
    "ENZY.ST",      # Enzymatica – enzymbaserade läkemedel
    "IMPC.ST",      # Impact Coatings – PVD-beläggning
    "PHARM.ST",     # PharmNovo – läkemedelsutveckling (kontrollera)
    "DICOT.ST",     # Dicot Pharma – erektil dysfunktion
    "AURA.ST",      # Aura Energy – uranutvinning (kontrollera)
    "NEXA.ST",      # Nexa Resources (kontrollera)
    "SYN.ST",       # Synthetica (alt. symbol)
    "NEOS.ST",      # Neonode – touchsensorteknik
    "PROL.ST",      # Prollenium (kontrollera)
    "CANT.ST",      # Cantargia (alt. symbol, se CANTA.ST)
    "RDI.ST",       # Radiopharm Theranostics (kontrollera)
    "PEPT.ST",      # PeptiCo (kontrollera)
    "TINY.ST",      # Tiny Minds (kontrollera)
    "CANA.ST",      # Cannabist / Canarc (kontrollera)
    "SPAGO.ST",     # Spago Nanomedical – radiosensibilisering
    "CLIN.ST",      # ClinSol (kontrollera)
    "AQLX.ST",      # Aquilos (kontrollera)
    "RHO.ST",       # RhoVac – prostatacancer
    "VIGX.ST",      # VigilBio (kontrollera)
    "LUMITO.ST",    # Lumito – upconverting nanoparticles
    "NEURA.ST",     # Neuravive (kontrollera)
    "CYNT.ST",      # Cyntho Pharma (kontrollera)
    "PROX.ST",      # Promore Pharma
    "RED.ST",       # Redwood Pharma
    # ── Cleantech & Energi ────────────────────────────────────────────────────
    "PCELL.ST",     # PowerCell Sweden
    "MINEST.ST",    # Minesto – tidvattenskraft
    "CLEAN.ST",     # Clean Bite (kontrollera)
    "ECO.ST",       # Eco Wave Power – vågenergi
    "WIND.ST",      # WindSim (kontrollera)
    "SOL.ST",       # Soltech Energy – solenergi
    "WAVE.ST",      # Wavefront Technology (kontrollera)
    "BESQAB.ST",    # Besqab AB – bostadsutveckling (f.d. AROS.ST)
    "ROST.ST",      # RostaFin (kontrollera)
    "MECK.ST",      # Mekonomen (alt. symbol, se MEKO.ST) / kontrollera
    "FLOW.ST",      # FlowIT – verksamhetsutveckling
    "OPTI.ST",      # Opti AB – avloppsoptimering
    "MVA.ST",       # Movestic Livförsäkring (kontrollera)
    "FREE.ST",      # Free2move Lease (kontrollera)
    "NBZ.ST",       # Northbaze Group – headphones (f.d. JAYS.ST)
    "EVM.ST",       # Evolution Mining (kontrollera)
    "ZAP.ST",       # Zapway (kontrollera)
    "SUN.ST",       # Sunstone Capital (kontrollera)
    "POW.ST",       # Power Cell (alt. symbol, se PCELL.ST)
    "WAT.ST",       # Watercircles (kontrollera)
    "AMMA.ST",      # Ammega Group (kontrollera)
    "LIDD.ST",      # Lidds AB – prostatacancer
    "AYI.ST",       # Ayima Group – digital marknadsföring
    "CLAV.ST",      # Clavister Holding – cybersäkerhet
    "MOBI.ST",      # MobiMass (kontrollera)
    "DIVI.ST",      # DividendMax (kontrollera)
    "SPEC.ST",      # Speakerset (kontrollera)
    "TRENT.ST",     # Trentino (kontrollera)
    "VERI.ST",      # Verisec – digital identitet
    "XIN.ST",       # Xintela – ledbroskterapier
    "APP.ST",       # AppSpotr – applikationsplattform
    "WRE.ST",       # WR Empain (kontrollera)
    "AWA.ST",       # AWA – IP-juridik & rådgivning
    "BRI.ST",       # BrightBid (f.d. Speqta, se not)
    "GOM.ST",       # GoMore – bildelning (kontrollera)
    "AWAR.ST",      # Awardit – lojalitetsprogram
    "PANT.ST",      # Pantamera Recycling (kontrollera)
    "SAFE.ST",      # Safeture – resandesäkerhet
    "IDEN.ST",      # Idenix (kontrollera)
    "VISI.ST",      # Visicom (kontrollera)
    "EASY.ST",      # EasyFill – fyllnadsautomation för butiker
    "INIX.ST",      # Inission (alt. symbol, se NOTE.ST area) / kontrollera
    "VOX.ST",       # Voxbone (kontrollera)
    "REAL.ST",      # Real Heart – konstgjort hjärta
    "BUILD.ST",     # BuildData Group
    "LAND.ST",      # Landmark Infrastructure (kontrollera)
    "ESTA.ST",      # Estea – fastigheter (kontrollera)
    "PROP.ST",      # Property 365 (kontrollera)
    "CASA.ST",      # Casa Sales (kontrollera)
    "HEM.ST",       # Hemnet (alt. symbol, se HIOF.ST area) / kontrollera
    # ── Fastighet (Spotlight) ────────────────────────────────────────────────
    "MTRS.ST",      # Mälarstaden – fastighetsbolag
    "HTRO.ST",      # Heatron – fastighetsutveckling
    "NIVI-B.ST",    # Nivika Fastigheter B
    "STEND.ST",     # Stendörren Fastigheter
    "CATE.ST",      # Catella – fastighetsrådgivning
    "BOSJO.ST",     # Bosjö Fastigheter
    "LOGI-B.ST",    # Logistea B
    "AMST.ST",      # Amste
    "ALM.ST",       # ALM Equity
    "TITAN.ST",     # Titan X Group
    "KVAR.ST",      # Kvartilen
    "MAGE.ST",      # Mäklarsamfundet-relaterat (kontrollera)
    "SBF.ST",       # SBF Bostad
    "TROS.ST",      # Trostsbeeken
    "ENRO.ST",      # Enro
    "CORT.ST",      # Cortendo
    # ── Gaming (Spotlight) ───────────────────────────────────────────────────
    "GIGSEK.ST",    # GigSek
    "STORY-B.ST",   # Story of AMS B
    "AGIG.ST",      # Academy of Gigolos (kontrollera)
    "ZORD.ST",      # Zordix – spelutveckling
    "THQ.ST",       # THQ Nordic
    "FRBL.ST",      # Frisq Holding
    "MAGI.ST",      # Maginatics
    "NITA.ST",      # Nita Group
    "RVR.ST",       # Rover Group
    # ── Nya bolag: kvantitativ analys maj 2026 ───────────────────────────────
    "PLEJD.ST",     # Plejd – smart belysning, 1 Mdr+ omsättning, stark FCF
    "FREETR.ST",    # Freetrailer – delningsekonomi, asset-light
    "SUSG.ST",      # Sustainion Group – hållbarhetsteknik
    "ANGL.ST",      # Angler Gaming – iGaming, 40%+ bruttomarginal
    "BPCINS.ST",    # BPC Instruments – biogas analytik
    "GJAB.ST",      # Gullberg & Jansson – klimatprodukter
    "SOLIDX.ST",    # SolidX – IT-konsult, snabbväxande
    "BEYOND.ST",    # Beyond Frames Entertainment – VR-spel
    "REDS.ST",      # Redsense Medical – dialysövervakning
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


# ── Bransch-kategorier ────────────────────────────────────────────────────────
SECTOR_GROUPS = {
    "Mjukvara & SaaS": [
        "LIME.ST", "FNOX.ST", "VIT-B.ST", "ANOD-B.ST", "ENEA.ST", "IAR-B.ST",
        "RAY-B.ST", "SECT-B.ST", "CINT.ST", "KNOW.ST", "PRIC-B.ST", "TOBII.ST",
        "NETI-B.ST", "CTEK.ST", "ALCA.ST", "CTM.ST", "ACAST.ST", "BUSER.ST",
        "SAFETY-B.ST", "PACT.ST", "BAHN-B.ST", "FPIP.ST", "MSAB-B.ST", "SOF-B.ST",
        "PRFO.ST", "BIM.ST", "UPSALE.ST", "SYNC.ST", "PROG-B.ST", "ZIGN.ST",
        "CSEC.ST", "EXS.ST", "IMNT.ST", "TCOK.ST", "ZETA.ST", "INFR.ST",
        "SINCH.ST", "NOD.ST", "PROE.ST", "AYI.ST", "CLAV.ST", "VERI.ST",
        "APP.ST", "AWA.ST", "AWAR.ST", "SAFE.ST", "EASY.ST", "VOX.ST",
        "QBNK.ST", "TCC.ST",
    ],
    "MedTech & Life Science": [
        "XVIVO.ST", "ELOS-B.ST", "BOMILL.ST", "BIOG-B.ST", "CEVI.ST", "MNTC.ST",
        "ALIG.ST", "IRRAS.ST", "QLINEA.ST", "ONCO.ST", "XSPRAY.ST", "HNSA.ST",
        "CALTX.ST", "DMYD-B.ST", "ORX.ST", "ACTI.ST", "IMMU.ST", "MCOV-B.ST",
        "VIMIAN.ST", "BOUL.ST", "MOB.ST", "PMED.ST", "CRNO-B.ST", "XBRANE.ST",
        "SEDANA.ST", "SEZI.ST", "CANTA.ST", "RECI-B.ST", "INTEG-B.ST", "EGTX.ST",
        "BIOT.ST", "ELIC.ST", "KDEV.ST", "ENZY.ST", "GETI-B.ST", "EKTA-B.ST",
        "ARJO-B.ST", "VITR.ST", "BICO.ST", "LINC.ST", "CAMX.ST", "ADDL-B.ST",
        "SOBI.ST", "BIOA-B.ST", "PHARM.ST", "DICOT.ST", "SPAGO.ST", "LUMITO.ST",
        "PROX.ST", "RED.ST", "LIDD.ST", "REAL.ST", "RHO.ST", "SECARE.ST",
        "DVYSR.ST", "VICO.ST", "REDS.ST",
    ],
    "Industri & Verkstad": [
        "MIPS.ST", "GARO.ST", "OEM-B.ST", "SDIP-B.ST", "XANO-B.ST", "REJL-B.ST",
        "HEXA-B.ST", "MILDEF.ST", "INSTAL.ST", "IVSO.ST", "BERG-B.ST", "EOLU-B.ST",
        "BRAV.ST", "SENS.ST", "HANZA.ST", "TAGM-B.ST", "BUFAB.ST", "LIAB.ST",
        "ITAB.ST", "NCAB.ST", "TROAX.ST", "SYSR.ST", "MYCR.ST", "NOTE.ST",
        "AQ.ST", "BEIJ-B.ST", "HMS.ST", "NOLA-B.ST", "HPOL-B.ST", "VBG-B.ST",
        "ADDT-B.ST", "DOM.ST", "INWI.ST", "LOOMIS.ST", "ANOT.ST", "ENGCON-B.ST",
        "VOLV-B.ST", "SAND.ST", "ALFA.ST", "ASSA-B.ST", "SKF-B.ST", "TREL-B.ST",
        "HUSQ-B.ST", "SWEC-B.ST", "AFRY.ST", "MMGR-B.ST", "GREEN.ST", "SILEX.ST",
    ],
    "Konsument & Livsstil": [
        "THULE.ST", "RVRC.ST", "SKIS-B.ST", "CARY.ST", "BHG.ST", "BORG.ST",
        "FING-B.ST", "MEKO.ST", "BILI-A.ST", "CLAS-B.ST", "DUNI.ST", "MSON-B.ST",
        "AAK.ST", "AXFO.ST", "BMAX.ST", "RUSTA.ST", "ALLIGO-B.ST", "LYKO-A.ST",
        "KABE-B.ST", "FAG.ST", "ICA.ST", "NELLY.ST", "CLA-B.ST", "PLEJD.ST",
        "HAYP.ST", "KOPP-B.ST",
    ],
    "Fintech & Finans": [
        "QLIRO.ST", "NOWO.ST", "RESURS.ST", "HOFI.ST", "INTRUM.ST",
        "AZA.ST", "NORD.ST", "SEB-A.ST", "SHB-A.ST", "SWED-A.ST", "NDA-SE.ST",
        "MORROW.ST",
    ],
    "Gaming & Underhållning": [
        "G5EN.ST", "BETS-B.ST", "EMBRAC-B.ST", "PDX.ST", "VPLAY-B.ST", "MTG-B.ST",
        "EVO.ST", "ZORD.ST", "THQ.ST", "ANGL.ST", "BEYOND.ST", "SFRG.ST",
        "KAMBI.ST",
    ],
    "Cleantech & Energi": [
        "ARISE.ST", "EOLU-B.ST", "GRNG.ST", "PCELL.ST", "MINEST.ST", "MYFC.ST",
        "MAHA-A.ST", "EPRO-B.ST", "ORRON.ST", "SUSG.ST", "ECO.ST", "SOL.ST",
    ],
    "Investmentbolag": [
        "BURE.ST", "CRED-A.ST", "NAXS.ST", "TRAC-B.ST", "SVOL-B.ST", "VNV.ST",
        "EAST.ST", "KINV-B.ST", "LIFCO-B.ST", "INDT.ST", "RATO-B.ST", "LATO-B.ST",
        "BINV.ST", "EQT.ST", "INVE-B.ST", "INDUC-C.ST",
    ],
    "Fastighet": [
        "KFAST-B.ST", "SSM.ST", "NP3.ST", "SLP-B.ST", "CIBUS.ST", "PION-B.ST",
        "BALD-B.ST", "CAST.ST", "FABG.ST", "SAGA-B.ST", "WIHL.ST", "DIOS.ST",
        "JM.ST", "PEAB-B.ST", "NCC-B.ST", "HUFV-A.ST", "CORE-B.ST", "FPAR-A.ST",
        "HEBA-B.ST", "BONAV-B.ST", "PLAZ-B.ST", "NYF.ST", "SBB-B.ST",
        "MTRS.ST", "HTRO.ST", "NIVI-B.ST", "STEND.ST", "CATE.ST", "BOSJO.ST",
        "LOGI-B.ST", "AMST.ST", "ALM.ST", "BRIN-B.ST", "ATRLJ-B.ST",
        "NEOBO.ST", "BESQAB.ST", "OVZON.ST",
    ],
    "Tjänster & Konsult": [
        "BTS-B.ST", "COOR.ST", "HUM.ST", "NOBI.ST", "ESSITY-B.ST", "EWORK.ST",
        "DUST.ST", "WISE.ST", "ACAD.ST", "SJR-B.ST", "ATT.ST", "AMBEA.ST",
        "SWEC-B.ST", "AFRY.ST", "SOLIDX.ST", "GJAB.ST", "FREETR.ST", "BPCINS.ST",
    ],
    "Material & Skog": [
        "SSAB-A.ST", "SSAB-B.ST", "SCA-B.ST", "HOLM-B.ST", "SCST.ST", "NEXAM.ST",
        "BERNER-B.ST",
    ],
    "Telecom & Media": [
        "VPLAY-B.ST", "MTG-B.ST", "TEL2-B.ST", "TELIA.ST", "SINCH.ST",
    ],
}
