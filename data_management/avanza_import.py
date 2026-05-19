"""
avanza_import.py
================
Importerar dina innehav direkt från Avanza-exportfilen.

Hur du exporterar från Avanza:
  1. Logga in på Avanza
  2. Gå till: Konto → Depå/ISK → fliken "Innehav"
  3. Klicka "Exportera" (längst ner till höger)
  4. Spara CSV-filen
  5. Kör: python avanza_import.py avanza_export.csv

Vad scriptet gör:
  - Läser Avanzas CSV (hanterar semikolon-separering och svenska siffror)
  - Mappar svenska namn → Yahoo Finance-tickers automatiskt
  - Okända bolag visas för manuell mappning och sparas till ticker_map.json
  - Uppdaterar holdings.csv direkt

Avanza CSV-format (typiskt):
  Värdepapper;Antal;Kurs;Aktuellt värde;Köpkurs;Resultat;Resultat (%)
  Ericsson B;200;78,50;15 700,00;75,30;640,00;4,3
"""

import json
import sys
import re
import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKER_MAP_FILE = Path("data/ticker_map.json")
HOLDINGS_FILE   = Path("holdings.csv")

# ── Inbyggd mappning (de vanligaste svenska + nordiska aktierna) ──────────────
BUILTIN_MAP = {
    # Stockholmsbörsen (vanligaste namnen som Avanza visar)
    "ericsson b":           "ERIC-B.ST",
    "ericsson a":           "ERIC-A.ST",
    "volvo b":              "VOLV-B.ST",
    "volvo a":              "VOLV-A.ST",
    "h&m b":                "HM-B.ST",
    "hennes & mauritz b":   "HM-B.ST",
    "investor b":           "INVE-B.ST",
    "investor a":           "INVE-A.ST",
    "industrivärden c":     "INDU-C.ST",
    "industrivärden a":     "INDU-A.ST",
    "atlas copco a":        "ATCO-A.ST",
    "atlas copco b":        "ATCO-B.ST",
    "assa abloy b":         "ASSA-B.ST",
    "seb a":                "SEB-A.ST",
    "handelsbanken a":      "SHB-A.ST",
    "swedbank a":           "SWED-A.ST",
    "nordea bank":          "NDA-SE.ST",
    "telia":                "TELIA.ST",
    "telia company":        "TELIA.ST",
    "abb":                  "ABB.ST",
    "sandvik":              "SAND.ST",
    "skf b":                "SKF-B.ST",
    "alfa laval":           "ALFA.ST",
    "boliden":              "BOL.ST",
    "ssab b":               "SSAB-B.ST",
    "ssab a":               "SSAB-A.ST",
    "sca b":                "SCA-B.ST",
    "nibe industrier b":    "NIBE-B.ST",
    "essity b":             "ESSITY-B.ST",
    "getinge b":            "GETI-B.ST",
    "astrazeneca":          "AZN.ST",
    "evolution":            "EVO.ST",
    "embracer group b":     "EMBRAC-B.ST",
    "eqt":                  "EQT.ST",
    "latour b":             "LATO-B.ST",
    "lifco b":              "LIFCO-B.ST",
    "castellum":            "CAST.ST",
    "wihlborgs":            "WIHL.ST",
    "fabege":               "FABG.ST",
    "sagax b":              "SAGA-B.ST",
    "balder b":             "BALD-B.ST",
    "lundin energy":        "LUNE.ST",
    "mips":                 "MIPS.ST",
    "invisio":              "INVISIO.ST",
    "ncab group":           "NCAB.ST",
    "vitrolife":            "VITROLIFE.ST",
    "sinch":                "SINCH.ST",
    "tele2 b":              "TEL2-B.ST",
    "kinnevik b":           "KINV-B.ST",
    "trelleborg b":         "TRELLEBORG-B.ST",
    "hexagon b":            "HEXA-B.ST",
    "peab b":               "PEAB-B.ST",
    "ncc b":                "NCC-B.ST",
    "jm":                   "JM.ST",
    "bure equity":          "BURE.ST",
    "indutrade":            "INDT.ST",
    "bufab":                "BUFAB.ST",
    "troax":                "TROAX.ST",

    # ── ETF:er och indexfonder (handlas på börs, har Yahoo Finance-ticker) ──────
    # Svenska ETF:er (Nasdaq Stockholm)
    "xact omxsb":           "XACTO.ST",
    "xact omxs30":          "XACTS.ST",
    "xact bull":            "XACTBULL.ST",
    "xact bear":            "XACTBEAR.ST",
    "xact norden":          "XACTN.ST",
    "xact högutdelande":    "XACTHDIV.ST",
    "xact usa":             "XACTUSA.ST",
    "xact obligationer":    "XACTOBLIG.ST",
    # Europeiska ETF:er (handlas på Nasdaq Stockholm som EUR-noterade)
    "xtrackers msci world":         "XDWD.DE",
    "ishares core msci world":      "IWDA.AS",
    "ishares msci world":           "URTH",
    "vanguard ftse all-world":      "VWRL.AS",
    "vanguard s&p 500":             "VUSD.AS",
    "ishares core s&p 500":         "CSPX.AS",
    "lyxor msci world":             "LCWL.PA",
    "spdr s&p 500":                 "SPY",
    "invesco qqq":                  "QQQ",
    "ishares nasdaq 100":           "CNDX.AS",
    # Råvaru-ETP:er
    "xetra-gold":                   "4GLD.DE",
    "wisdomtree physical gold":     "PHGP.AS",
    "ishares physical gold":        "IGLN.AS",
    # Nordiska utdelningsfokuerade ETF:er
    "carnegie corporate bond":      "0P00017NJI.F",   # eventuellt ej på YF
    "skagen global":                None,              # aktivt förvaltad, ej på YF
    "länsförsäkringar global":       None,              # aktivt förvaltad, ej på YF
    "länsförsäkringar global index": None,             # aktivt förvaltad, ej på YF
    "länsförsäkringar sverige index": None,
    "länsförsäkringar tillväxtmarknad index": None,
    "swedbank robur access global": None,              # aktivt förvaltad, ej på YF
    "avanza global":                None,              # aktivt förvaltad, ej på YF
    "avanza zero":                  None,              # indexfond, ej på YF
    "spiltan aktiefond investmentbolag": None,         # aktivt förvaltad, ej på YF
    "handelsbanken global index":   None,              # indexfond, ej på YF

    # USA (Avanza visar ofta bara företagsnamn utan ticker)
    "apple":                "AAPL",
    "microsoft":            "MSFT",
    "alphabet a":           "GOOGL",
    "alphabet c":           "GOOG",
    "amazon":               "AMZN",
    "meta platforms":       "META",
    "meta":                 "META",
    "nvidia":               "NVDA",
    "tesla":                "TSLA",
    "broadcom":             "AVGO",
    "oracle":               "ORCL",
    "salesforce":           "CRM",
    "adobe":                "ADBE",
    "amd":                  "AMD",
    "advanced micro devices":"AMD",
    "intel":                "INTC",
    "cisco":                "CSCO",
    "qualcomm":             "QCOM",
    "texas instruments":    "TXN",
    "palantir":             "PLTR",
    "snowflake":            "SNOW",
    "jp morgan":            "JPM",
    "jpmorgan":             "JPM",
    "bank of america":      "BAC",
    "goldman sachs":        "GS",
    "morgan stanley":       "MS",
    "blackrock":            "BLK",
    "visa":                 "V",
    "mastercard":           "MA",
    "berkshire hathaway b": "BRK-B",
    "paypal":               "PYPL",
    "johnson & johnson":    "JNJ",
    "unitedhealth":         "UNH",
    "eli lilly":            "LLY",
    "pfizer":               "PFE",
    "abbvie":               "ABBV",
    "merck":                "MRK",
    "abbvie":               "ABBV",
    "bristol-myers squibb": "BMY",
    "gilead":               "GILD",
    "walmart":              "WMT",
    "costco":               "COST",
    "coca-cola":            "KO",
    "pepsico":              "PEP",
    "mcdonald's":           "MCD",
    "nike":                 "NKE",
    "starbucks":            "SBUX",
    "home depot":           "HD",
    "netflix":              "NFLX",
    "disney":               "DIS",
    "exxon mobil":          "XOM",
    "chevron":              "CVX",

    # Europa
    "asml":                 "ASML.AS",
    "asml holding":         "ASML.AS",
    "sap":                  "SAP.DE",
    "siemens":              "SIE.DE",
    "allianz":              "ALV.DE",
    "basf":                 "BAS.DE",
    "bayer":                "BAYN.DE",
    "volkswagen":           "VOW3.DE",
    "bmw":                  "BMW.DE",
    "mercedes-benz":        "MBG.DE",
    "lvmh":                 "MC.PA",
    "totalenergies":        "TTE.PA",
    "sanofi":               "SAN.PA",
    "bnp paribas":          "BNP.PA",
    "shell":                "SHEL.L",
    "astrazeneca":          "AZN.L",
    "hsbc":                 "HSBA.L",
    "unilever":             "ULVR.L",
    "bp":                   "BP.L",
    "rio tinto":            "RIO.L",
    "nestle":               "NESN.SW",
    "novartis":             "NOVN.SW",
    "roche":                "ROG.SW",
    "novo nordisk b":       "NOVO-B.CO",
    "novo nordisk":         "NOVO-B.CO",
    "equinor":              "EQNR.OL",
    "nokia":                "NOKIA.HE",
}


# ── Ladda/spara anpassad mappning ──────────────────────────────────────────────

def load_custom_map() -> dict:
    """Läser sparade manuella mappningar från data/ticker_map.json."""
    if not TICKER_MAP_FILE.exists():
        return {}
    try:
        return json.loads(TICKER_MAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_custom_map(mapping: dict):
    """Sparar manuella mappningar till data/ticker_map.json."""
    TICKER_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    TICKER_MAP_FILE.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Namnmatchning ──────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normaliserar bolagsnamn för matchning."""
    return (
        name.lower()
        .strip()
        .replace(",", "")
        .replace(".", "")
        .replace("  ", " ")
    )


def find_ticker(name: str, custom_map: dict, isin: str | None = None) -> str | None:
    """
    Försöker hitta Yahoo Finance-ticker för ett Avanza-bolagsnamn eller ISIN.
    Söker i: 1) custom_map, 2) BUILTIN_MAP, 3) ISIN-sökning via yfinance,
             4) Namnbaserad sökning via yfinance

    Returnerar None om det är en känd aktivt förvaltad fond utan börshandel.
    """
    norm = normalize_name(name)

    # 1. Kolla anpassad mappning
    if norm in custom_map:
        return custom_map[norm]

    # 2. Kolla inbyggd mappning (None = känd fond utan YF-ticker)
    if norm in BUILTIN_MAP:
        return BUILTIN_MAP[norm]  # kan vara None för aktivt förvaltade fonder

    # 3. ISIN-baserad sökning (hittar ofta ETF:er och utländska fonder)
    if isin and len(isin) == 12:
        try:
            results = yf.Search(isin, max_results=3).quotes
            for r in results:
                if r.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND"):
                    ticker = r.get("symbol", "")
                    if ticker:
                        return ticker
        except Exception:
            pass

    # 4. Namnbaserad sökning
    try:
        results = yf.Search(name, max_results=5).quotes
        for r in results:
            if r.get("quoteType") in ("EQUITY", "ETF"):
                ticker = r.get("symbol", "")
                if ticker:
                    return ticker
    except Exception:
        pass

    return None


def classify_security(name: str, ticker: str | None) -> str:
    """
    Klassificerar ett värdepapper baserat på namn och ticker.
    Returnerar: 'stock', 'etf', 'fund', 'certificate', 'unknown'
    """
    n = name.lower()
    # Kända fond-nyckelord (aktivt förvaltade, ej börshandlade)
    fund_keywords = ("fond", "fund", "robur", "länsförsäkringar",
                     "avanza global", "avanza zero", "spiltan", "handelsbanken global",
                     "carnegie", "lannebo", "öhman", "coeli", "didner",
                     "global index", "sverige index", "world index")
    # Klassificera som fond baserat på namn OAVSETT om en ticker hittades
    if any(kw in n for kw in fund_keywords):
        return "fund"
    # Morningstar-fondkoder (0P-prefix) som yfinance returnerar för aktivt förvaltade fonder
    if ticker and str(ticker).upper().startswith("0P"):
        return "fund"
    # ETF-nyckelord
    etf_keywords = ("etf", "xact", "xtrackers", "ishares", "vanguard", "lyxor",
                    "spdr", "invesco qqq", "wisdomtree", "amundi")
    if any(kw in n for kw in etf_keywords):
        return "etf"
    # Certifikat
    if any(kw in n for kw in ("bull", "bear", "certifikat", "turbo", "mini future",
                               "warrant", "teckningsoption")):
        return "certificate"
    if ticker:
        return "stock"
    return "unknown"


# ── Avanza CSV-parser ──────────────────────────────────────────────────────────

def parse_avanza_csv(filepath: str) -> pd.DataFrame:
    """
    Läser och tolkar en Avanza-exportfil.

    Avanza varianter:
    - Semikolon-separerad
    - Svenska decimaler (komma) och tusentalsavgränsare (mellanslag)
    - Kolumnnamn kan variera något mellan kontotyper (ISK, Depå, KF)
    - Kan ha metadata-rader i toppen (depånamn, datum) som hoppas över
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Filen hittades inte: {filepath}")

    # Läs råfilen för att detektera format
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw[:3] == b"\xef\xbb\xbf" else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    lines = text.splitlines()

    # ── Detektera separator från första icke-tomma raden ──────────────────────
    first_nonempty = next((l for l in lines if l.strip()), lines[0] if lines else "")
    sep = ";" if ";" in first_nonempty else ","

    # ── Hitta rubrikraden (hoppa över eventuella metadata-rader i toppen) ─────
    # Avanza kan exportera med metadata i toppen, t.ex.:
    #   "ISK: MinDepå"
    #   "Datum: 2026-05-19"
    #   (tom rad)
    #   Värdepapper;Antal;Kurs;...
    _HEADER_KEYWORDS = {"värdepapper", "antal", "security", "quantity", "name", "isin",
                        "kontonummer", "volym", "kortnamn"}
    skip_rows = 0
    for i, line in enumerate(lines):
        cols_in_line = {c.strip().lower().strip('"') for c in line.split(sep)}
        if cols_in_line & _HEADER_KEYWORDS:
            skip_rows = i
            break

    # Läs CSV med rätt startrad
    import io
    df = pd.read_csv(
        io.StringIO(text),
        sep=sep,
        skiprows=skip_rows,
        encoding=None,
        on_bad_lines="skip",  # hoppa över korrupta rader
    )

    # ── Normalisera kolumnnamn (unik mappning – en output per input) ──────────
    # Bugfix: om två kolumner mappas till samma namn (t.ex. "Kurs" och
    # "Förändring kurs" → båda "current_price") returnerar df["current_price"]
    # en DataFrame istället för en Series, vilket orsakar "has no attribute 'str'".
    # Lösning: spåra vilka output-namn som redan är använda och skippa dubletter.
    col_map: dict[str, str] = {}
    used_targets: set[str] = set()

    for col in df.columns:
        c = col.lower().strip().strip('"')
        target = None

        # Värdepappersnamn
        if any(kw in c for kw in ("värdepapper", "security")) or c in ("namn", "name"):
            target = "name"
        # ISIN
        elif c == "isin" or c.startswith("isin"):
            target = "isin"
        # Antal / Volym (positioner-format)
        elif any(kw in c for kw in ("antal", "quantity", "shares", "volym")):
            target = "shares"
        # Köpkurs / GAV / anskaffningskurs (cost basis per share)
        elif any(kw in c for kw in ("köpkurs", "genomsnittlig", "purchase", "anskaffningskurs")) \
                or c == "gav" or c.startswith("gav "):
            target = "cost_basis"
        # Aktuell kurs — matchar "kurs" men INTE köp/anskaff-varianter
        elif ("kurs" in c
              and "köp" not in c
              and "anskaff" not in c
              and "förändring" not in c
              and "resultat" not in c):
            target = "current_price"

        # Registrera mappningen bara om output-namnet inte redan är använt
        if target and target not in used_targets:
            col_map[col] = target
            used_targets.add(target)

    df = df.rename(columns=col_map)

    # ── Kontrollera obligatoriska kolumner ────────────────────────────────────
    if "name" not in df.columns:
        # Sista utväg: om ingen kolumn matchar, ta den första kolumnen som "name"
        first_col = df.columns[0] if not df.columns.empty else None
        if first_col:
            df = df.rename(columns={first_col: "name"})
        else:
            raise ValueError(
                "Kunde inte hitta kolumn för värdepappersnamn. "
                "Förväntade: 'Värdepapper', 'Namn', 'Security' eller liknande."
            )

    # ── Se till att "name" är en Series, inte en DataFrame ───────────────────
    # (extra skydd ifall ovanstående mappning ändå skapar dubbletter)
    if isinstance(df["name"], pd.DataFrame):
        df = df.copy()
        # Behåll bara den första av de duplicerade kolumnerna
        df = df.loc[:, ~df.columns.duplicated()]

    # ── Konvertera siffror (svenska format: "1 234,56" → 1234.56) ────────────
    def parse_swedish_number(s) -> float | None:
        if pd.isna(s):
            return None
        s = str(s).strip().replace("\xa0", "").replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    for col in ["shares", "cost_basis", "current_price"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_swedish_number)

    # ── Rensa tomma rader ─────────────────────────────────────────────────────
    df = df.dropna(subset=["name"])
    # Säkerställ att "name"-kolumnen är en Series innan .str används
    name_col = df["name"]
    if isinstance(name_col, pd.DataFrame):
        name_col = name_col.iloc[:, 0]
        df = df.drop(columns="name")
        df.insert(0, "name", name_col)
    df = df[df["name"].astype(str).str.strip() != ""]

    return df


# ── Avanza "positioner"-format (Min ekonomi → Analys → Exportera data) ─────────

# Marknad-suffix: Avanzas marknadsnamn → Yahoo Finance-suffix
_MARKET_SUFFIX: dict[str, str | None] = {
    "XSTO": ".ST",   # Nasdaq Stockholm
    "FNSE": ".ST",   # First North Sweden
    "NGMX": ".ST",   # Nordic Growth Market
    "XHEL": ".HE",   # Helsinki
    "XCSE": ".CO",   # Copenhagen
    "XOSL": ".OL",   # Oslo
    "XLON": ".L",    # London
    "XETR": ".DE",   # Frankfurt
    "XPAR": ".PA",   # Paris
    "XAMS": ".AS",   # Amsterdam
    "XMIL": ".MI",   # Milano
    "XNYS": "",      # NYSE (ingen suffix i Yahoo)
    "XNAS": "",      # Nasdaq (ingen suffix)
    "FUND": None,    # Aktivt förvaltad fond
}


def kortnamn_to_ticker(kortnamn: str, marknad: str) -> str | None:
    """
    Konverterar Avanzas kortnamn + marknad till Yahoo Finance-ticker.
    Exempel: "INVE B" + "XSTO" → "INVE-B.ST"
             "NCAB"  + "XSTO" → "NCAB.ST"
             "AAPL"  + "XNAS" → "AAPL"
    Returnerar None för fonder (FUND) eller okänd marknad.
    """
    suffix = _MARKET_SUFFIX.get((marknad or "").upper().strip())
    if suffix is None and (marknad or "").upper() not in _MARKET_SUFFIX:
        # Okänd marknad – försök utan suffix
        suffix = ""
    if suffix is None:
        return None  # fond
    base = kortnamn.strip().replace(" ", "-")
    return f"{base}{suffix}" if base else None


def is_positioner_format(raw_bytes_or_text) -> bool:
    """Detekterar om filen är i det nya 'positioner'-formatet (har Kontonummer-kolumn)."""
    try:
        if isinstance(raw_bytes_or_text, bytes):
            text = raw_bytes_or_text[:500].decode("utf-8-sig", errors="replace")
        else:
            text = str(raw_bytes_or_text)[:500]
        first_line = text.splitlines()[0].lower() if text.splitlines() else ""
        return "kontonummer" in first_line
    except Exception:
        return False


def parse_avanza_positioner_csv(raw_bytes_or_path) -> dict[str, pd.DataFrame]:
    """
    Parsar det nya Avanza 'positioner'-formatet.

    Källa: Min ekonomi → Analys → Exportera data →
           "Mitt innehav fördelat per konto – Ladda ner innehav per konto som .csv"

    CSV-kolumner:
        Kontonummer;Namn;Kortnamn;Volym;Marknadsvärde;GAV (SEK);GAV;Valuta;Land;ISIN;Marknad;Typ

    Returnerar:
        {kontonummer_str: DataFrame} med kolumnerna:
            name, kortnamn, shares, cost_basis, isin, marknad, av_typ
    """
    import io as _io

    if isinstance(raw_bytes_or_path, (bytes, bytearray)):
        raw = bytes(raw_bytes_or_path)
        enc = "utf-8-sig" if raw[:3] == b"\xef\xbb\xbf" else "utf-8"
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        p = Path(raw_bytes_or_path)
        raw = p.read_bytes()
        enc = "utf-8-sig" if raw[:3] == b"\xef\xbb\xbf" else "utf-8"
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

    df = pd.read_csv(_io.StringIO(text), sep=";", on_bad_lines="skip")
    df.columns = [c.strip() for c in df.columns]

    def _num(s):
        if pd.isna(s):
            return None
        s = str(s).strip().replace("\xa0", "").replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    for col in ["Volym", "GAV (SEK)", "GAV", "Marknadsvärde"]:
        if col in df.columns:
            df[col] = df[col].apply(_num)

    df = df.dropna(subset=["Namn"])
    df = df[df["Namn"].astype(str).str.strip() != ""]

    result: dict[str, pd.DataFrame] = {}
    for konto_nr, group in df.groupby("Kontonummer"):
        rows = []
        for _, r in group.iterrows():
            cost = r.get("GAV (SEK)") if pd.notna(r.get("GAV (SEK)")) else r.get("GAV")
            rows.append({
                "name":      str(r.get("Namn", "")).strip(),
                "kortnamn":  str(r.get("Kortnamn", "")).strip(),
                "shares":    r.get("Volym"),
                "cost_basis": cost,
                "isin":      str(r.get("ISIN", "")).strip(),
                "marknad":   str(r.get("Marknad", "")).strip(),
                "av_typ":    str(r.get("Typ", "")).strip().upper(),  # STOCK / FUND
            })
        result[str(konto_nr)] = pd.DataFrame(rows)

    return result


# ── Huvud-importfunktion ────────────────────────────────────────────────────────

def import_from_avanza(
    filepath:     str,
    interactive:  bool = True,
    update_holdings: bool = True,
) -> pd.DataFrame:
    """
    Importerar innehav från Avanza-exportfil.

    interactive: Fråga användaren om okända bolag (True = interaktivt läge)
    update_holdings: Skriv till holdings.csv när klar

    Returnerar DataFrame med matchade innehav.
    """
    print(f"\n📂 Läser Avanza-export: {filepath}")

    # Läs CSV
    df = parse_avanza_csv(filepath)
    print(f"   Hittade {len(df)} rader")

    # Ladda anpassade mappningar
    custom_map = load_custom_map()

    # Mappa namn → tickers
    results   = []
    unknown   = []

    for _, row in df.iterrows():
        name    = str(row["name"]).strip()
        shares  = row.get("shares")
        cost    = row.get("cost_basis")

        if not shares or shares <= 0:
            continue

        ticker = find_ticker(name, custom_map)

        if ticker:
            results.append({
                "ticker":     ticker,
                "name":       name,
                "shares":     round(float(shares), 4),
                "cost_basis": round(float(cost), 2) if cost else None,
                "mapped":     True,
            })
            print(f"   ✓ {name:<35} → {ticker}")
        else:
            unknown.append({
                "name":       name,
                "shares":     shares,
                "cost_basis": cost,
            })
            print(f"   ? {name:<35} → EJ HITTAD")

    # Hantera okända bolag
    if unknown:
        print(f"\n⚠  {len(unknown)} bolag kunde inte matchas automatiskt:")

        if interactive:
            for item in unknown:
                print(f"\n   Bolag: {item['name']}")
                print(f"   Antal: {item['shares']}")
                ticker = input("   Ange ticker (t.ex. ERIC-B.ST), eller Enter för att hoppa över: ").strip().upper()

                if ticker:
                    # Validera tickern
                    try:
                        info = yf.Ticker(ticker).fast_info
                        if info.last_price:
                            print(f"   ✓ {ticker} verifierad (pris: {info.last_price:.2f})")
                        else:
                            print(f"   ⚠ Kunde inte verifiera {ticker} – läggs till ändå")
                    except Exception:
                        pass

                    # Spara mappningen
                    norm = normalize_name(item["name"])
                    custom_map[norm] = ticker
                    save_custom_map(custom_map)
                    print(f"   💾 Mappning sparad: '{item['name']}' → {ticker}")

                    results.append({
                        "ticker":     ticker,
                        "name":       item["name"],
                        "shares":     item["shares"],
                        "cost_basis": item["cost_basis"],
                        "mapped":     True,
                    })
        else:
            print("   Kör med --interactive för att mappa dem manuellt")
            print("   Eller lägg till i data/ticker_map.json manuellt:")
            for item in unknown:
                print(f'     "{normalize_name(item["name"])}": "TICKER"')

    # Bygg resultat-DataFrame
    result_df = pd.DataFrame(results)

    if result_df.empty:
        print("\n❌ Inga innehav importerades")
        return pd.DataFrame()

    print(f"\n✓ {len(result_df)} av {len(df)} innehav mappade")

    # Uppdatera holdings.csv
    if update_holdings and not result_df.empty:
        holdings_df = result_df[["ticker", "shares", "cost_basis"]].copy()
        holdings_df.to_csv(HOLDINGS_FILE, index=False)
        print(f"✅ holdings.csv uppdaterad med {len(holdings_df)} positioner")

        # Om positions.py används – visa info
        print(f"\n💡 Tips: Registrera dina ursprungliga köp i transaktionsloggen för full P&L:")
        print(f"   python positions.py add-buy TICKER ANTAL KÖPKURS")

    return result_df


# ── Visa mappningstatus ────────────────────────────────────────────────────────

def show_mapping_status():
    """Visar alla sparade anpassade mappningar."""
    custom = load_custom_map()
    if not custom:
        print("Inga anpassade mappningar sparade ännu.")
        return

    print(f"\n📋 Sparade mappningar ({len(custom)} st):")
    for name, ticker in sorted(custom.items()):
        print(f"   '{name}' → {ticker}")


def add_manual_mapping(avanza_name: str, ticker: str):
    """Lägger till en mappning manuellt."""
    custom = load_custom_map()
    norm   = normalize_name(avanza_name)
    custom[norm] = ticker.upper()
    save_custom_map(custom)
    print(f"✓ Mappning tillagd: '{avanza_name}' → {ticker.upper()}")


# ── MAIN ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importera innehav från Avanza CSV-export")
    sub = parser.add_subparsers(dest="cmd")

    # import
    p_import = sub.add_parser("import", help="Importera från Avanza-fil")
    p_import.add_argument("file", help="Sökväg till CSV-filen från Avanza")
    p_import.add_argument("--no-interactive", action="store_true",
                          help="Fråga inte om okända bolag")
    p_import.add_argument("--dry-run", action="store_true",
                          help="Visa vad som skulle importeras utan att spara")

    # map
    p_map = sub.add_parser("map", help="Lägg till en manuell mappning")
    p_map.add_argument("name",   help="Bolagsnamn som det visas i Avanza (inom citattecken)")
    p_map.add_argument("ticker", help="Yahoo Finance-ticker (t.ex. ERIC-B.ST)")

    # list
    sub.add_parser("list", help="Visa alla sparade mappningar")

    args = parser.parse_args()

    if args.cmd == "import":
        import_from_avanza(
            args.file,
            interactive  = not args.no_interactive,
            update_holdings = not args.dry_run,
        )

    elif args.cmd == "map":
        add_manual_mapping(args.name, args.ticker)

    elif args.cmd == "list":
        show_mapping_status()

    else:
        parser.print_help()
        print("\nExempel:")
        print("  python avanza_import.py import ~/Downloads/avanza_export.csv")
        print("  python avanza_import.py map 'Kinnevik B' KINV-B.ST")
        print("  python avanza_import.py list")
