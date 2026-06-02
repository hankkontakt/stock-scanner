"""
country_flags.py - Landflaggor för ticker-symboler.

Använder ticker-suffix för att avgöra land.
US-aktier har inget suffix -> 🇺🇸 som default.
Endast kända ADR-tickers (suffix-lösa som inte är US) behöver undantag.

Användning:
    from core.country_flags import flag_for_ticker, name_for_ticker
    flag_for_ticker("VOLV-B.ST")   -> "🇸🇪"
    flag_for_ticker("AAPL")        -> "🇺🇸"
    flag_for_ticker("NVO")         -> "🇩🇰"  (Novo Nordisk ADR)
"""

from core.suffix_map import SUFFIX_COUNTRY as _SUFFIX_MAP

# Kända ADR-tickers (US-noterade men utländska bolag) som saknar suffix
_ADR_EXCEPTIONS: dict[str, tuple[str, str]] = {
    # Norden
    "NVO":  ("🇩🇰", "Danmark"),   # Novo Nordisk
    "SPOT": ("🇸🇪", "Sverige"),   # Spotify

    # Europa
    "AZN":  ("🇬🇧", "Storbritannien"), # AstraZeneca
    "BP":   ("🇬🇧", "Storbritannien"), # BP
    "UL":   ("🇬🇧", "Storbritannien"), # Unilever
    "BCS":  ("🇬🇧", "Storbritannien"), # Barclays
    "HSBC": ("🇬🇧", "Storbritannien"), # HSBC
    "DEO":  ("🇬🇧", "Storbritannien"), # Diageo
    "ARM":  ("🇬🇧", "Storbritannien"), # ARM Holdings
    "NVS":  ("🇨🇭", "Schweiz"),   # Novartis
    "RHHBY":("🇨🇭", "Schweiz"),   # Roche
    "NSRGY":("🇨🇭", "Schweiz"),   # Nestlé
    "ABB":  ("🇨🇭", "Schweiz"),   # ABB
    "ADYEN":("🇳🇱", "Nederländerna"), # Adyen
    "FLUT": ("🇮🇪", "Irland"),    # Flutter Entertainment

    # Asien
    "TM":   ("🇯🇵", "Japan"),     # Toyota
    "HMC":  ("🇯🇵", "Japan"),     # Honda
    "SONY": ("🇯🇵", "Japan"),     # Sony
    "MUFG": ("🇯🇵", "Japan"),     # Mitsubishi UFJ
    "SMFG": ("🇯🇵", "Japan"),     # Sumitomo Mitsui
    "BABA": ("🇨🇳", "Kina"),      # Alibaba
    "JD":   ("🇨🇳", "Kina"),      # JD.com
    "BIDU": ("🇨🇳", "Kina"),      # Baidu
    "NIO":  ("🇨🇳", "Kina"),      # NIO
    "LI":   ("🇨🇳", "Kina"),      # Li Auto
    "XPEV": ("🇨🇳", "Kina"),      # XPeng
    "TCEHY":("🇨🇳", "Kina"),      # Tencent
    "PDD":  ("🇨🇳", "Kina"),      # PDD Holdings
    "INFY": ("🇮🇳", "Indien"),    # Infosys
    "HDB":  ("🇮🇳", "Indien"),    # HDFC Bank
    "CPNG": ("🇰🇷", "Sydkorea"),  # Coupang

    # Americas
    "SHOP": ("🇨🇦", "Kanada"),    # Shopify
    "RY":   ("🇨🇦", "Kanada"),    # Royal Bank of Canada
    "TD":   ("🇨🇦", "Kanada"),    # TD Bank
    "BNS":  ("🇨🇦", "Kanada"),    # Bank of Nova Scotia
    "BMO":  ("🇨🇦", "Kanada"),    # Bank of Montreal
    "NU":   ("🇧🇷", "Brasilien"), # Nu Holdings
    "MELI": ("🇦🇷", "Argentina"), # MercadoLibre

    # Övriga
    "SE":   ("🇸🇬", "Singapore"), # Sea Limited
    "GRAB": ("🇸🇬", "Singapore"), # Grab
}


def _normalize_ticker(ticker: str) -> str:
    """Rensa ticker: ta bort mellanslag, versaler."""
    return str(ticker).upper().strip()


def flag_for_ticker(ticker: str) -> str:
    """Returnera landsflagga-emoji för en ticker.

    Prioritering:
      1. Suffix-matchning (.ST, .L, .DE, etc.)
      2. ADR-exception för kända utländska bolag noterade i USA
      3. Default: 🇺🇸 (US-aktier utan suffix)

    Exempel:
      >>> flag_for_ticker("VOLV-B.ST")  -> "🇸🇪"
      >>> flag_for_ticker("AAPL")       -> "🇺🇸"
      >>> flag_for_ticker("NVO")        -> "🇩🇰"
      >>> flag_for_ticker("NOVO-B.CO")  -> "🇩🇰"
    """
    t = _normalize_ticker(ticker)

    # 1. Suffix-matchning
    for suffix, (flag, _) in _SUFFIX_MAP.items():
        if t.endswith(suffix):
            return flag

    # 2. Känd ADR-exception
    if t in _ADR_EXCEPTIONS:
        return _ADR_EXCEPTIONS[t][0]

    # 3. Default: USA
    return "🇺🇸"


def name_for_ticker(ticker: str) -> str:
    """Returnera landsnamn för en ticker."""
    t = _normalize_ticker(ticker)

    for suffix, (_, name) in _SUFFIX_MAP.items():
        if t.endswith(suffix):
            return name

    if t in _ADR_EXCEPTIONS:
        return _ADR_EXCEPTIONS[t][1]

    return "USA"


# suffix → ISO 2-bokstavs landskod (för tabell-display utan emoji)
_SUFFIX_ISO: dict[str, str] = {
    ".ST": "SE", ".CO": "DK", ".OL": "NO", ".HE": "FI",
    ".L":  "GB", ".DE": "DE", ".PA": "FR", ".AS": "NL",
    ".MI": "IT", ".MC": "ES", ".SW": "CH", ".VI": "AT",
    ".WA": "PL", ".LS": "LU", ".BR": "BE", ".TO": "CA",
    ".AX": "AU", ".NZ": "NZ", ".T":  "JP", ".TW": "TW",
    ".KS": "KR", ".HK": "HK", ".NS": "IN", ".BO": "IN",
    ".SI": "SG", ".KL": "MY", ".BK": "TH",
    ".SS": "CN", ".SZ": "CN", ".SA": "BR", ".MX": "MX",
}

# ADR → ISO
_ADR_ISO: dict[str, str] = {
    "NVO": "DK", "SPOT": "SE",
    "AZN": "GB", "BP": "GB", "UL": "GB", "BCS": "GB", "HSBC": "GB", "DEO": "GB", "ARM": "GB",
    "NVS": "CH", "RHHBY": "CH", "NSRGY": "CH", "ABB": "CH",
    "ADYEN": "NL", "FLUT": "IE",
    "TM": "JP", "HMC": "JP", "SONY": "JP", "MUFG": "JP", "SMFG": "JP",
    "BABA": "CN", "JD": "CN", "BIDU": "CN", "NIO": "CN", "LI": "CN", "XPEV": "CN",
    "TCEHY": "CN", "PDD": "CN",
    "INFY": "IN", "HDB": "IN",
    "CPNG": "KR",
    "SHOP": "CA", "RY": "CA", "TD": "CA", "BNS": "CA", "BMO": "CA",
    "NU": "BR", "MELI": "AR",
    "SE": "SG", "GRAB": "SG",
}


def country_code_for_ticker(ticker: str) -> str:
    """Returnera ISO-2 landskod för en ticker (t.ex. 'SE', 'US', 'DE').

    Används för ren text-display i tabeller där flag-emojis inte renderas.
    """
    t = _normalize_ticker(ticker)
    for suffix, iso in _SUFFIX_ISO.items():
        if t.endswith(suffix):
            return iso
    if t in _ADR_ISO:
        return _ADR_ISO[t]
    return "US"


def ticker_display(ticker: str) -> str:
    """Formaterar ticker för tabell-display: 'SE · VOLV-B.ST', 'US · NVDA'.

    Undviker flag-emojis (renderas som text 'us'/'se' i ag-Grid).
    Används istf. f'{flag_for_ticker(t)} {t}' i DataFrames.
    """
    code = country_code_for_ticker(ticker)
    return f"{code} · {ticker}"


