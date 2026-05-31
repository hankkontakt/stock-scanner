 # =====================================================================
# MarketScan - Config.py
# =====================================================================
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ════════════════ TICKER-UNIVERSUM (läses från data/universe.json) ════════════
_CONFIG_DIR = Path(__file__).resolve().parent.parent
_UNIVERSE_FILE = _CONFIG_DIR / "data" / "universe.json"

def _load_universe():
    """Läs tickerlistor från data/universe.json. Fallback till tomma listor.

    Fångar ALLA fel (inte bara FileNotFoundError): en trasig/halvskriven
    universe.json (merge-konflikt, avbruten commit) kastar annars
    JSONDecodeError vid import av config.py → hela appen OCH alla pipelines
    kraschar. Graciös fallback till {} → tom UNIVERSE → pipeline laddar
    senaste cache istället för att braka.
    """
    try:
        with open(_UNIVERSE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, ValueError, OSError) as e:
        import sys
        print(f"⚠ KRITISKT: data/universe.json kunde inte läsas ({e}). "
              f"Använder tom universe – kontrollera filen!", file=sys.stderr)
        return {}

_UNIVERSE_DATA = _load_universe()

# Exportera varje kategori som en separat variabel för bakåtkompatibilitet
US_LARGE_CAP = _UNIVERSE_DATA.get("US_LARGE_CAP", {}).get("tickers", [])
UK          = _UNIVERSE_DATA.get("UK", {}).get("tickers", [])
GERMANY     = _UNIVERSE_DATA.get("GERMANY", {}).get("tickers", [])
NORDIC      = _UNIVERSE_DATA.get("NORDIC", {}).get("tickers", [])
OMX_SE      = _UNIVERSE_DATA.get("OMX_SE", {}).get("tickers", [])
EUROPE      = _UNIVERSE_DATA.get("EUROPE", {}).get("tickers", [])
ASIA_PACIFIC = _UNIVERSE_DATA.get("ASIA_PACIFIC", {}).get("tickers", [])
CANADA      = _UNIVERSE_DATA.get("CANADA", {}).get("tickers", [])
BRAZIL      = _UNIVERSE_DATA.get("BRAZIL", {}).get("tickers", [])
EMERGING    = BRAZIL  # Behåller EMERGING alias för bakåtkompabilitet

UNIVERSE = list(dict.fromkeys(
    US_LARGE_CAP + UK + GERMANY + NORDIC + OMX_SE + EUROPE +
    ASIA_PACIFIC + CANADA + EMERGING
))

# Smallcap tickers (separat kategori i JSON med market-struktur)
_SMALLCAP_DATA = _UNIVERSE_DATA.get("SMALLCAP", {})
SMALLCAP_MARKETS = _SMALLCAP_DATA.get("markets", {})
SMALLCAP_TICKERS = (
    SMALLCAP_MARKETS.get("FIRST_NORTH", []) +
    SMALLCAP_MARKETS.get("SMALL_CAP", []) +
    SMALLCAP_MARKETS.get("SPOTLIGHT", [])
)



# ════════════════ NYA FAKTORER – viktaberedskap ════════════════
# Dessa vikter läggs till om short_interest/seasonality/options_flow integreras
EXTRA_FACTOR_WEIGHTS = {
    "short_interest": 0.03,  # Blankningsgrad – låg blankning = positivt
    "seasonality":    0.03,  # Säsongsmönster – stark månad = positivt
    "options_flow":   0.02,  # Optionsflöde – puts/calls ratio
}

# ════════════════ FAKTORVIKTER ════════════════
FACTOR_WEIGHTS = {
    "value":          0.2134,  # 0.22 × 0.97
    "quality":        0.1746,  # 0.18 × 0.97
    "momentum":       0.1746,  # 0.18 × 0.97
    "growth":         0.1261,  # 0.13 × 0.97
    "risk":           0.0873,  # 0.09 × 0.97
    "size":           0.0485,  # 0.05 × 0.97
    "dividend":       0.0485,  # 0.05 × 0.97
    "sentiment":      0.0970,  # 0.10 × 0.97
    "short_interest": 0.0300,  # Ny faktor: låg blankning = positivt signal
}
# Vikterna skalas så att sum = 1.0. short_interest lades till 2026-06-01.
# Källdata: short_pct_float / short_ratio från yfinance (hämtas sedan länge men var oanvänd).

assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 0.001

# ════════════════ STREAMLIT SECRETS (fallback om .env inte finns) ════════════
# Streamlit Cloud injicerar secrets som miljövariabler, men vi läser även
# direkt från st.secrets för säkerhets skull.
def _get_secret(key: str, default: str = "") -> str:
    """Läs från miljövariabel. Fallback till st.secrets om tillgängligt."""
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return default

# ════════════════ API-NYCKLAR ════════════════
FMP_API_KEY      = _get_secret("FMP_API_KEY", "")
FINNHUB_API_KEY  = _get_secret("FINNHUB_API_KEY", "")

# ════════════════ AI / MULTI-PROVIDER ════════════════
AI_PROVIDER       = _get_secret("AI_PROVIDER", "deepseek")  # "deepseek" (betal, stabil) eller "gemini" (gratis, rate-limited 15/min)
AI_DEEP_PROVIDER  = _get_secret("AI_DEEP_PROVIDER", "deepseek")  # Används för djupa analyser (weekly, deep stock analysis)
AI_TASK_MODE      = _get_secret("AI_TASK_MODE", "hybrid")  # "hybrid": light->gemini, heavy->deepseek; "gemini": alltid gemini; "deepseek": alltid deepseek
DEEPSEEK_API_KEY  = _get_secret("DEEPSEEK_API_KEY", "")
AI_MODEL          = "deepseek-chat"          # deepseek-chat eller deepseek-reasoner
GEMINI_API_KEY    = _get_secret("GEMINI_API_KEY", "")
GEMINI_MODEL      = "gemini-2.5-flash"       # nyaste gratis-modellen (1.5-flash deprecerades okt 2024). Fallback-kedja i ai_analysis.py
AI_MAX_TOKENS     = 4096                     # Max tokens per svar
AI_TEMPERATURE    = 0.3                      # Låg temperatur = mer deterministiska svar

# ════════════════ PARALLELLA INSTÄLLNINGAR ════════════════
# Yahoo Finance: informell gräns ~5-10 req/sek per IP. 8 workers hamrar för hårt
# och triggar 429-klumpar. 4 workers + 0.5s delay = ~8 req/sek totalt, vilket
# Yahoo i praktiken accepterar utan rate-limit.
PARALLEL_WORKERS          = 4   # Antal parallella trådar för yfinance-datahämtning
PARALLEL_TICKER_TIMEOUT   = 30  # Max sekunder per ticker (ersätter SIGALRM)
REQUEST_DELAY_SEC         = 0.5 # Fördröjning per anrop i trådpoolen (total delay = delay * workers)
MAX_RETRIES               = 2
RETRY_BACKOFF_SEC         = 3

# Finnhub (gratis: 60 anrop/min)
FINNHUB_PARALLEL_WORKERS  = 3   # Antal parallella Finnhub-anrop
FINNHUB_CALLS_PER_MINUTE  = 50  # Lämna headroom på 60/min-gränsen

FINNHUB_NEWS_DAYS         = 7
SENTIMENT_CACHE_HOURS     = 6
FLASK_PORT                = 5000
MIN_DATA_QUALITY          = 0.5  # 0.5 = accepterar 4/8 fält (investmentbolag, råvarubolag etc.)

# ════════════════ DATA-INSTÄLLNINGAR ════════════════
CACHE_DIR             = "data/cache"
CACHE_HOURS           = 720  # Statisk fundamental data - cachas 30 dagar (ändras bara vid kvartalsrapport)
DYNAMIC_CACHE_HOURS   = 48   # Dynamisk data - cachas 2 dagar (P/E, analytikermål, blankning, beta)
PRICE_CACHE_HOURS     = 24   # Prishistorik - alltid färsk (RSI, MACD, marknadsvärde)
MIN_DATA_QUALITY      = 0.5  # 0.5 = accepterar 4/8 fält (investmentbolag, råvarubolag etc.)


# ════════════════ RAPPORT ════════════════
TOP_N_RECOMMENDATIONS   = 10        # Topp 10 - läsbart och fokuserat
REPORT_DIR              = "reports"
REPORT_FILENAME_PATTERN = "weekly_report_{date}.md"

# ════════════════ PORTFÖLJ ════════════════
HOLDINGS_FILE       = "data/holdings.csv"
WATCHLIST_FILE      = "data/watchlist.json"
BUY_MORE_PERCENTILE = 80
HOLD_PERCENTILE     = 50

# ════════════════ EMAIL ════════════════
# Lägg till i GitHub Actions Secrets: EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_TO
EMAIL_SENDER   = os.getenv("EMAIL_SENDER",   "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO       = os.getenv("EMAIL_TO",       "")

# ════════════════ BENCHMARK ════════════════
BENCHMARK_OMXS30 = "XACTOMXS3.ST"
BENCHMARK_SPY    = "SPY"
BENCHMARK_LABEL  = "OMXS30"

# ════════════════ SMÅBOLAGSSKANNER ════════════════
# Inställningar för python -m smallcap.scanner
# Alla filter-trösklar och scoringvikter samlade här.
SMALLCAP_CONFIG = {

    # ── Hårda filter (bolag som inte uppfyller dessa stryks innan scoring) ───
    "min_daily_turnover_sek":  150_000,         # Daglig omsättning ≥ 150k SEK (sänkt från 500k för bredare täckning)
    "min_market_cap_sek":      20_000_000,      # Börsvärde ≥ 20 MSEK (sänkt från 30 MSEK)
    "max_market_cap_sek":      10_000_000_000,  # Börsvärde ≤ 10 GSEK (annars mid/large cap)
    "max_debt_to_equity":      300,             # D/E > 300 % = skuldfälla
    "min_current_ratio":       0.5,             # CR < 0.5 = akut likviditetskris
    "min_cash_runway_months":  6,               # Kassan måste räcka ≥ 6 månader (sänkt från 12; många saknar kassadata)
    "max_piotroski_skip":      2,               # F-Score ≤ 2 = eliminera helt
    "max_dilution_pct":        0.20,            # Aktieantal +20 % på 1 år = röd flagga

    # ── Scoringvikter (8 faktorer, summerar till 1.0) ─────────────────────────
    # Baserad på design-dokumentet: fokus på insider + FCF + Piotroski.
    "scoring_weights": {
        "insider":    0.18,  # Insynsägande & -handel (skin in the game)
        "fcf_yield":  0.16,  # Fritt kassaflöde / börsvärde
        "piotroski":  0.15,  # Piotroski F-Score (redovisningskvalitet 0-9)
        "growth":     0.13,  # Omsättningstillväxt YoY
        "balance":    0.12,  # Balansräkning (D/E + current ratio)
        "value":      0.12,  # Värdering (EV/EBITDA eller P/B)
        "momentum":   0.09,  # Relativ styrka 6-12 månader
        "liquidity":  0.05,  # Daglig handelsvolym (exit-möjlighet)
    },

    # ── Rapport & utmatning ───────────────────────────────────────────────────
    "top_n":                     20,        # Antal bolag i rankinglistan
    "profiles_n":                5,         # Antal djupdyks-profiler
    "output_dir":                "reports", # Mapp för rapportfil

    # ── E-post ────────────────────────────────────────────────────────────────
    "email_subject_template": "📊 Småbolagsrapport {date} | Topp: {top1} | {stars}",
}
assert abs(sum(SMALLCAP_CONFIG["scoring_weights"].values()) - 1.0) < 0.001, \
    "SMALLCAP_CONFIG scoring_weights summerar inte till 1.0"


# ── Custom-tickers för UNIVERSE (läggs till via webbgränssnittet) ──
from pathlib import Path
_CUSTOM_UNIVERSE_FILE = Path(__file__).parent.parent / "data" / "custom_universe.json"

def load_custom_universe() -> list:
    """Returnerar användartillagda tickers för universumscannern."""
    try:
        if _CUSTOM_UNIVERSE_FILE.exists():
            import json
            return json.loads(_CUSTOM_UNIVERSE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_custom_universe(items: list):
    import json
    _CUSTOM_UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CUSTOM_UNIVERSE_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )

def add_custom_to_universe(ticker: str, name: str = "") -> bool:
    """Lägger till en ticker i universumscannerns custom-lista. Returnerar True om ny."""
    from datetime import date
    ticker = ticker.strip().upper()
    custom = load_custom_universe()
    if any(c["ticker"] == ticker for c in custom):
        return False
    custom.append({
        "ticker": ticker,
        "name": name.strip(),
        "added": str(date.today()),
    })
    _save_custom_universe(custom)
    return True

def remove_custom_from_universe(ticker: str) -> bool:
    """Tar bort en ticker ur universumscannerns custom-lista."""
    ticker = ticker.strip().upper()
    custom = load_custom_universe()
    new = [c for c in custom if c["ticker"] != ticker]
    if len(new) == len(custom):
        return False
    _save_custom_universe(new)
    return True

# Slå ihop UNIVERSE med custom-tickers
try:
    _custom_tickers = [c["ticker"] for c in load_custom_universe()]
    if _custom_tickers:
        # Behåll UNIVERSE som en tuple (original), skapa en combined-lista vid runtime
        pass
except Exception:
    pass

# ── Scoring-config override (sätts via admin-UI, sparas i data/scoring_config.json) ──
import json as _json
_SCORING_CONFIG_FILE = Path(__file__).parent.parent / "data" / "scoring_config.json"
try:
    _override = _json.loads(_SCORING_CONFIG_FILE.read_text(encoding="utf-8")) if _SCORING_CONFIG_FILE.exists() else {}
    if "factor_weights" in _override:
        FACTOR_WEIGHTS.update(_override["factor_weights"])
    if "smallcap_config" in _override:
        for _k, _v in _override["smallcap_config"].items():
            if _k in SMALLCAP_CONFIG:
                SMALLCAP_CONFIG[_k] = _v
except Exception:
    pass
