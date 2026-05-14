"""
universe.py – Svenska småbolagsuniversum.

Täcker tre marknader:
  FIRST_NORTH  – Nasdaq First North Growth Market (tillväxtbolag, 50M–3B SEK)
  SMALL_CAP    – Nasdaq Stockholm Small Cap (etablerade, 150M–2B SEK)
  SPOTLIGHT    – Spotlight Stock Market (mikrokap, lägre likviditet)

Logiken: körs med get_universe() som standard. Använd market="first_north"
för att bara köra First North etc.

Ticker-format: Yahoo Finance .ST suffix (t.ex. LIME.ST, FNOX.ST).
"""

# ── NASDAQ FIRST NORTH GROWTH MARKET ──────────────────────────────────────────
# Bolag med starkare tillväxtprofil. Ofta grundar-ledd, högt ägarengagemang.

FIRST_NORTH = [
    # ── Mjukvara / SaaS ──────────────────────────────────────────
    "LIME.ST",       # Lime Technologies – CRM för SME, extremt lönsam nisch
    "FNOX.ST",       # Fortnox – molnbaserat redovisningssystem, 40%+ tillväxt
    "VITEC-B.ST",    # Vitec Software – VMS (vertikala marknadssystem), seriell förvärvare
    "ADDNODE-B.ST",  # Addnode Group – design/construction-mjukvara
    "ENEA.ST",       # Enea – nätverksmjukvara för telecom
    "IAR-B.ST",      # IAR Systems – embedded development tools (C/C++ för MCU)
    "RAYSR.ST",      # RaySearch Laboratories – strålbehandlingssoftware
    "SECTRA-B.ST",   # Sectra – medicinsk bilddiagnostik och cybersäkerhet
    "CINT.ST",       # Cint Group – digital insiktsplattform (survey/market research)
    "BRAV.ST",       # Bravida? Nej – kontrollera
    "PDLA.ST",       # PolarX? – kontrollera

    # ── Fintech / Betalningar ─────────────────────────────────────
    "QLIRO.ST",      # Qliro – BNPL/betalningslösningar för e-handel
    "NOWO.ST",       # Nowo – digital bank för unga

    # ── MedTech / HealthTech ──────────────────────────────────────
    "XVIVO.ST",      # XVIVO Perfusion – organpreservering (hjärta/lunga), global nisch
    "ELOS-B.ST",     # Elos Medtech – kontraktstillverkning medicinteknik
    "BOMILL.ST",     # Bomill – spannmålssorterings­teknik
    "BIOG-B.ST",     # BioGaia – probiotika, stark varumärkesposition
    "MEDI.ST",       # Medicover – hälsovård Östeuropa

    # ── Industri / Clean Tech ─────────────────────────────────────
    "MIPS.ST",       # MIPS – patenterad helmetteknik, royaltymodell
    "GARO.ST",       # GARO – el-installationer och EV-laddning
    "OEM-B.ST",      # OEM International – teknisk distributör
    "SDIP-B.ST",     # Sdiptech – infrastrukturprodukter, seriell förvärvare
    "XANO-B.ST",     # XANO Industri – industri­tillverkning och automation
    "REJLERS-B.ST",  # Rejlers – teknikkonsult

    # ── Konsument ─────────────────────────────────────────────────
    "RVRC.ST",       # RVRC Holding – outdoor/workwear DTC-brand
    "BURE.ST",       # Bure Equity – investmentbolag med fokus på tillväxtbolag
    "CREADES-A.ST",  # Creades – investmentbolag (Avanza-spin-off, VC-fokus)
    "NAXS.ST",       # NAXS – PE-focused investment company

    # ── Fastighet / Samhälle ─────────────────────────────────────
    "KFAST-D.ST",    # K-Fast Holding – studentbostäder
    "SSM.ST",        # SSM Holding – studentbostäder Stockholm/Göteborg

    # ── Övrigt tillväxt ───────────────────────────────────────────
    "BETCO.ST",      # Betsson? – gaming, kontrollera suffix
    "SINCH.ST",      # Sinch – kommunikationsplattform (CPaaS), vuxit till mid cap
    "LATO-B.ST",     # Latour – investmentbolag (delvis small cap-exponering)
]

# ── NASDAQ STOCKHOLM SMALL CAP ────────────────────────────────────────────────
# Mer etablerade bolag. Lägre tillväxt men ofta starkare kassaflöde och utdelning.

SMALL_CAP = [
    # ── Industri / Verkstad ───────────────────────────────────────
    "BUFAB.ST",      # Bufab – global distributör av fästelement, god lönsamhet
    "LINDAB.ST",     # Lindab International – ventilationssystem, stabil cash flow
    "INWIDO.ST",     # Inwido – fönster och dörrar (Norden + Europa)
    "ITAB.ST",       # ITAB Shop Concept – butiksinredning
    "GARO.ST",       # GARO (även Small Cap) – EV-laddning och el-installationer
    "AGES-B.ST",     # Ages Industri? – kontrollera
    "TRAD.ST",       # TradeDoubler? – kontrollera
    "BTS-B.ST",      # BTS Group – affärssimuleringar och utbildning

    # ── Konsument / Livsstil ──────────────────────────────────────
    "THULE.ST",      # Thule Group – outdoor- och transportprodukter, starkt brand
    "DUNI.ST",       # Duni – bordsdukning/förpackningar för foodservice
    "MIDSONA-B.ST",  # Midsona – hälsokostprodukter (Kung Markatta, Urtekram)
    "DORO.ST",       # Doro – mobiltelefoner och trygghetslarm för äldre

    # ── Tjänster / Konsult ────────────────────────────────────────
    "COOR.ST",       # Coor Service Management – FM-tjänster
    "BETEK.ST",      # BE Group? – stålhandel
    "NIBE-B.ST",     # NIBE Industrier – värmepumpar (vuxit till large cap)

    # ── MedTech / Pharma ──────────────────────────────────────────
    "HANSA.ST",      # Hansa Biopharma – enzymterapi mot antikroppar
    "CALTX.ST",      # Calliditas Therapeutics – nefrologiläkemedel

    # ── Fastighet ─────────────────────────────────────────────────
    "HUFVUD-A.ST",   # Hufvudstaden – premium kontors- och butiksfastigheter
    "BHG.ST",        # BHG Group – onlinehandel hem & trädgård

    # ── Tech / Halvledare ─────────────────────────────────────────
    "NETI-B.ST",     # Net Insight – mediakommunikation
    "MYFC.ST",       # myFC Holding – bränsleceller (spec-stage)
    "QUANT.ST",      # Quant Industrial – underhållstjänster

    # ── Finans / Kapitalförvaltning ────────────────────────────────
    "SVOLD-B.ST",    # Svolder – investmentbolag small/micro cap
    "TRACTION-B.ST", # Traction – aktivt investmentbolag
]

# ── SPOTLIGHT STOCK MARKET (urval) ────────────────────────────────────────────
# Mikrokap. Högre risk, lägre likviditet. Bara de mest lovande inkluderade.
# Kräver manuell likviditetskontroll (filtret tar bort de illikvida).

SPOTLIGHT = [
    "XSPRAY.ST",     # XSpray Pharma – nanopartikel-läkemedelsteknologi
    "CFISH.ST",      # Catfish? – kontrollera
    "BIOT.ST",       # Biotech IgG – antikroppsproduktion
    "ELCG.ST",       # Elicera Therapeutics – CAR-T-cellterapi
    "KDEV.ST",       # Kancera – cancer-immunologi
    "NIV.ST",        # Nivika Fastigheter – fastighetsutveckling
    "ARISE.ST",      # Arise – vindkraftutvecklare
    "PLAT.ST",       # Platzer Fastigheter – kommersiella fastigheter Göteborg
]

# ── KOMBINERAT UNIVERSUM ───────────────────────────────────────────────────────

_ALL = FIRST_NORTH + SMALL_CAP + SPOTLIGHT

# Deduplicera och normalisera
SMALLCAP_UNIVERSE = list(dict.fromkeys(t.upper() for t in _ALL))


def get_universe(market: str = "all") -> list:
    """
    Returnerar ticker-lista baserat på marknad.

    market: "all" | "first_north" | "small_cap" | "spotlight"
    """
    mapping = {
        "all":          SMALLCAP_UNIVERSE,
        "first_north":  [t.upper() for t in FIRST_NORTH],
        "small_cap":    [t.upper() for t in SMALL_CAP],
        "spotlight":    [t.upper() for t in SPOTLIGHT],
    }
    return list(dict.fromkeys(mapping.get(market, SMALLCAP_UNIVERSE)))


# Bransch-kategorier för rapporten
SECTOR_GROUPS = {
    "Mjukvara & SaaS":      ["LIME.ST", "FNOX.ST", "VITEC-B.ST", "ADDNODE-B.ST",
                              "ENEA.ST", "IAR-B.ST", "RAYSR.ST", "SECTRA-B.ST", "CINT.ST"],
    "MedTech & Pharma":     ["XVIVO.ST", "ELOS-B.ST", "BIOG-B.ST", "HANSA.ST",
                              "CALTX.ST", "XSPRAY.ST", "BIOT.ST", "ELCG.ST", "KDEV.ST"],
    "Industri & Clean Tech":["MIPS.ST", "GARO.ST", "OEM-B.ST", "SDIP-B.ST",
                              "XANO-B.ST", "BUFAB.ST", "LINDAB.ST", "INWIDO.ST",
                              "ITAB.ST", "ARISE.ST"],
    "Konsument & Livsstil": ["THULE.ST", "DUNI.ST", "MIDSONA-B.ST", "DORO.ST",
                              "RVRC.ST"],
    "Tjänster & Konsult":   ["REJLERS-B.ST", "COOR.ST", "BTS-B.ST"],
    "Fastighet":            ["KFAST-D.ST", "SSM.ST", "HUFVUD-A.ST", "PLAT.ST",
                              "NIV.ST"],
    "Investmentbolag":      ["BURE.ST", "CREADES-A.ST", "NAXS.ST", "SVOLD-B.ST",
                              "TRACTION-B.ST", "LATO-B.ST"],
}
