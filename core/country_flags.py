"""
country_flags.py – Landflaggor för ticker-symboler.

Använder ticker-suffix för att avgöra land.
US-aktier har inget suffix → 🇺🇸 som default.
Endast kända ADR-tickers (suffix-lösa som inte är US) behöver undantag.

Användning:
    from core.country_flags import flag_for_ticker, name_for_ticker
    flag_for_ticker("VOLV-B.ST")   → "🇸🇪"
    flag_for_ticker("AAPL")        → "🇺🇸"
    flag_for_ticker("NVO")         → "🇩🇰"  (Novo Nordisk ADR)
"""

_SUFFIX_MAP: dict[str, tuple[str, str]] = {
    ".ST":  ("🇸🇪", "Sverige"),
    ".CO":  ("🇩🇰", "Danmark"),
    ".OL":  ("🇳🇴", "Norge"),
    ".HE":  ("🇫🇮", "Finland"),
    ".L":   ("🇬🇧", "Storbritannien"),
    ".DE":  ("🇩🇪", "Tyskland"),
    ".PA":  ("🇫🇷", "Frankrike"),
    ".AS":  ("🇳🇱", "Nederländerna"),
    ".T":   ("🇯🇵", "Japan"),
    ".TW":  ("🇹🇼", "Taiwan"),
    ".KS":  ("🇰🇷", "Sydkorea"),
    ".HK":  ("🇭🇰", "Hongkong"),
    ".NS":  ("🇮🇳", "Indien"),
    ".TO":  ("🇨🇦", "Kanada"),
    ".SA":  ("🇧🇷", "Brasilien"),
    ".MI":  ("🇮🇹", "Italien"),
    ".MC":  ("🇪🇸", "Spanien"),
    ".SW":  ("🇨🇭", "Schweiz"),
    ".VI":  ("🇦🇹", "Österrike"),
    ".BR":  ("🇧🇪", "Belgien"),
    ".AX":  ("🇦🇺", "Australien"),
    ".NZ":  ("🇳🇿", "Nya Zeeland"),
    ".SI":  ("🇸🇬", "Singapore"),
    ".KL":  ("🇲🇾", "Malaysia"),
    ".BK":  ("🇹🇭", "Thailand"),
    ".SS":  ("🇨🇳", "Kina (Shanghai)"),
    ".SZ":  ("🇨🇳", "Kina (Shenzhen)"),
}

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
      >>> flag_for_ticker("VOLV-B.ST")  → "🇸🇪"
      >>> flag_for_ticker("AAPL")       → "🇺🇸"
      >>> flag_for_ticker("NVO")        → "🇩🇰"
      >>> flag_for_ticker("NOVO-B.CO")  → "🇩🇰"
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


def flag_and_name(ticker: str) -> str:
    """Returnera flagga + landsnamn, t.ex. '🇸🇪 Sverige'."""
    return f"{flag_for_ticker(ticker)} {name_for_ticker(ticker)}"