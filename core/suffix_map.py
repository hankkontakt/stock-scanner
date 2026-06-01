"""
suffix_map.py — Centraliserad karta over ticker-suffix och landskategorier.

Single Source of Truth for alla suffix-mappningar i projektet.
Alla moduler som behover suffix-till-land eller suffix-till-kategori
skall importera harifran. Fem oberoende kopior har tidigare funnits
utspridda och har redan bortjat divergera.

Anvandning:
    from core.suffix_map import SUFFIX_COUNTRY, SUFFIX_CATEGORY, COUNTRY_SUFFIXES
    suffix_to_category(".ST")  -> "OMX_SE"
    suffix_to_region(".L")     -> "UK"
"""

# suffix -> (landflagga, landsnamn)
SUFFIX_COUNTRY: dict[str, tuple[str, str]] = {
    ".ST":  ("\U0001f1f8\U0001f1ea", "Sverige"),
    ".CO":  ("\U0001f1e9\U0001f1f0", "Danmark"),
    ".OL":  ("\U0001f1f3\U0001f1f4", "Norge"),
    ".HE":  ("\U0001f1eb\U0001f1ee", "Finland"),
    ".L":   ("\U0001f1ec\U0001f1e7", "Storbritannien"),
    ".DE":  ("\U0001f1e9\U0001f1ea", "Tyskland"),
    ".PA":  ("\U0001f1eb\U0001f1f7", "Frankrike"),
    ".AS":  ("\U0001f1f3\U0001f1f1", "Nederlanderna"),
    ".MI":  ("\U0001f1ee\U0001f1f9", "Italien"),
    ".MC":  ("\U0001f1ea\U0001f1f8", "Spanien"),
    ".SW":  ("\U0001f1e8\U0001f1ed", "Schweiz"),
    ".VI":  ("\U0001f1e6\U0001f1f9", "Osterrike"),
    ".WA":  ("\U0001f1f5\U0001f1f1", "Polen"),
    ".LS":  ("\U0001f1f1\U0001f1fb", "Luxemburg"),
    ".BR":  ("\U0001f1e7\U0001f1ea", "Belgien"),
    ".TO":  ("\U0001f1e8\U0001f1e6", "Kanada"),
    ".AX":  ("\U0001f1e6\U0001f1fa", "Australien"),
    ".NZ":  ("\U0001f1f3\U0001f1ff", "Nya Zeeland"),
    ".T":   ("\U0001f1ef\U0001f1f5", "Japan"),
    ".TW":  ("\U0001f1f9\U0001f1fc", "Taiwan"),
    ".KS":  ("\U0001f1f0\U0001f1f7", "Sydkorea"),
    ".HK":  ("\U0001f1ed\U0001f1f0", "Hongkong"),
    ".NS":  ("\U0001f1ee\U0001f1f3", "Indien"),
    ".BO":  ("\U0001f1ee\U0001f1f3", "Indien"),
    ".SI":  ("\U0001f1f8\U0001f1ec", "Singapore"),
    ".KL":  ("\U0001f1f2\U0001f1fe", "Malaysia"),
    ".BK":  ("\U0001f1f9\U0001f1ed", "Thailand"),
    ".SS":  ("\U0001f1e8\U0001f1f3", "Kina (Shanghai)"),
    ".SZ":  ("\U0001f1e8\U0001f1f3", "Kina (Shenzhen)"),
    ".SA":  ("\U0001f1e7\U0001f1f7", "Brasilien"),
    ".MX":  ("\U0001f1f2\U0001f1fd", "Mexiko"),
}

# suffix -> kategori i universe.json
SUFFIX_CATEGORY: dict[str, str] = {
    ".ST":  "OMX_SE",
    ".CO":  "NORDIC",
    ".OL":  "NORDIC",
    ".HE":  "NORDIC",
    ".L":   "UK",
    ".DE":  "GERMANY",
    ".PA":  "EUROPE",
    ".AS":  "EUROPE",
    ".MI":  "EUROPE",
    ".MC":  "EUROPE",
    ".VI":  "EUROPE",
    ".WA":  "EUROPE",
    ".LS":  "EUROPE",
    ".SW":  "EUROPE",
    ".TO":  "CANADA",
    ".AX":  "ASIA_PACIFIC",
    ".T":   "ASIA_PACIFIC",
    ".HK":  "ASIA_PACIFIC",
    ".TW":  "ASIA_PACIFIC",
    ".KS":  "ASIA_PACIFIC",
    ".NS":  "ASIA_PACIFIC",
    ".BO":  "ASIA_PACIFIC",
    ".SI":  "ASIA_PACIFIC",
    ".SA":  "BRAZIL",
    ".MX":  "BRAZIL",
}

# Land -> suffix for UI-filter (anvands i weekly_scan, smallcap, technical)
# Nycklar maste matcha streamlit-filter-exakt (med emoji-prefix)
COUNTRY_SUFFIXES: dict[str, str] = {
    "\U0001f1fa\U0001f1f8 USA": ".US",
    "\U0001f1f8\U0001f1ea Sverige":  ".ST",
    "\U0001f1ec\U0001f1e7 UK":       ".L",
    "\U0001f1e9\U0001f1ea Tyskland": ".DE",
    "\U0001f1eb\U0001f1ee Finland":  ".HE",
    "\U0001f1e9\U0001f1f0 Danmark":  ".CO",
    "\U0001f1f3\U0001f1f4 Norge":    ".OL",
    "\U0001f1e8\U0001f1f3 Kina":     ".SS",
    "\U0001f1ef\U0001f1f5 Japan":    ".T",
}


def suffix_to_category(ticker: str) -> str:
    """Gissa universe.json-kategori baserat pa tickers borst-suffix."""
    t = ticker.upper().strip()
    for suffix, cat in SUFFIX_CATEGORY.items():
        if t.endswith(suffix):
            return cat
    return "US_LARGE_CAP"


def suffix_to_region(ticker: str) -> str:
    """Gissa region baserat pa borst-suffix (for universe_discovery)."""
    t = ticker.upper().strip()
    if any(t.endswith(s) for s in (".ST", ".CO", ".OL", ".HE")):
        return "NORDIC"
    if t.endswith(".L"):
        return "UK"
    if any(t.endswith(s) for s in (".DE", ".PA", ".AS", ".MI", ".MC", ".VI", ".WA", ".LS", ".SW")):
        return "EUROPE"
    if t.endswith(".TO"):
        return "CANADA"
    if any(t.endswith(s) for s in (".AX", ".T", ".HK", ".TW", ".KS", ".NS", ".BO", ".SI")):
        return "ASIA"
    if any(t.endswith(s) for s in (".SA", ".MX")):
        return "LATAM"
    return "US"
