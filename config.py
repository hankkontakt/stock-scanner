# =====================================================================
# MarketScan - Config.py
# Uppdaterad med nya aktier och sektorsindelning för Europa och Sverige
# =====================================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ════════════════ USA LARGE/MID/SMALL CAP ════════════════
US_LARGE_CAP = [
    # Tech / Halvledare / AI Infrastruktur
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL",
    "CRM", "ADBE", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU",
    "PANW", "PLTR", "SNOW", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "FTNT",
    "DDOG", "CRWD", "WDAY", "TEAM", "MDB", "NET", "ZS", "OKTA", "SHOP", "UBER",
    "ABNB", "DASH", "SPOT", "ADSK", "ANSS", "CDNS", "SNPS", "VRSN", "CTSH", "GLW",
    "HPQ", "HPE", "DELL", "WDC", "STX", "PSTG", "NTAP", "AKAM", "CDW", "ZBRA",
    "ARM", "SMCI", "ACN", "EPAM", "GLOB", "APP", "FLUT", "ANET", "VRT", "NTNX", 
    "CHKP", "CYBR", "TOST", "FOUR", "ASAN", "ESTC", "SMTS", "DOCS", "LAW", "AMPL", 
    "COUR", "UDEMY", "ZM", "DBX", "BOX", "FSLY", "WOLF", "ON", "COHR", "AEHR", 
    "RMBS", "AMKR", "ALGM", "SWKS", "QRVO", "JNPR", "FFIV", "IONQ", "RGTI", "QBTS", 
    "ARQQ", "RKLB", "ASTS", "JOBY", "ACHR", "AI", "PATH", "SOUN", "BBAI", "OPEN",
    
    # Finans
  
]

# ════════════════ SVERIGE ════════════════
OMX_SE = [
    # Industri & Verkstad
    
]

# ════════════════ EUROPA (Uppdelad i Sektorer) ════════════════
EUROPE = [
    # Industri & Verkstad
   
]

# ════════════════ ASIEN / STILLA HAVET ════════════════
ASIA_PACIFIC = [
   
]

# ════════════════ KANADA (Med Rätta .TO Suffix) ════════════════
CANADA = [
    "ENB.TO", "TD.TO", "BNS.TO", "RY.TO", "CP.TO", "CNR.TO", "BCE.TO", "TRP.TO", "SU.TO", "CVE.TO",
    "IMO.TO", "PPL.TO", "WFG.TO", "CCO.TO", "FM.TO", "ABX.TO", "G.TO", "WPM.TO", "FNV.TO",
    "SHOP.TO", "BAM.TO", "BN.TO", "MFC.TO", "SLF.TO", "POW.TO", "FFH.TO", "DOL.TO", "ATD.TO", "L.TO",
    "WN.TO", "EMP-A.TO", "MRU.TO", "SAP.TO", "GIB-A.TO", "CSU.TO", "KXS.TO", "DSG.TO", 
    "TIH.TO", "TFII.TO", "WSP.TO", "STN.TO", "NTR.TO", "AGI.TO", "OSK.TO", "IMG.TO", "YRI.TO", 
    "LSPD.TO", "NVEI.TO", "REAL.TO", "DND.TO", "CIGI.TO", "FSV.TO", "ERF.TO", "MEG.TO", "BTE.TO", 
    "NXE.TO", "LUN.TO"
]

# ════════════════ EMERGING / LATINAMERIKA ════════════════
EMERGING = [
    "VALE", "ITUB", "BBD", "MELI", "NU", "GLOB", "ARCO", "SE", "GRAB",
    "AMX", "FMX",
]

# ════════════════ KOMBINERA ════════════════
UNIVERSE = list(dict.fromkeys(
    US_LARGE_CAP + OMX_SE + EUROPE + ASIA_PACIFIC + CANADA + EMERGING
))

# ════════════════ FAKTORVIKTER ════════════════
FACTOR_WEIGHTS = {
    "value":     0.22,
    "quality":   0.18,
    "momentum":  0.18,
    "growth":    0.13,
    "risk":      0.09,
    "size":      0.05,
    "dividend":  0.05,
    "sentiment": 0.10,
}
assert abs(sum(FACTOR_WEIGHTS.values()) - 1.0) < 0.001

# ════════════════ API-NYCKLAR ════════════════
FMP_API_KEY      = os.getenv("FMP_API_KEY", "")
FINNHUB_API_KEY  = os.getenv("FINNHUB_API_KEY", "")

# ════════════════ DATA-INSTÄLLNINGAR ════════════════
CACHE_DIR             = "data/cache"
CACHE_HOURS           = 720  # Statisk fundamental data – cachas 30 dagar (ändras bara vid kvartalsrapport)
DYNAMIC_CACHE_HOURS   = 170  # Dynamisk data – cachas 7 dagar (P/E, analytikermål, blankning, beta)
PRICE_CACHE_HOURS     = 24   # Prishistorik – alltid färsk (RSI, MACD, marknadsvärde)
REQUEST_DELAY_SEC     = 0.8  # 1000+ aktier kräver längre paus för att undvika Yahoo rate limit
MAX_RETRIES           = 2
RETRY_BACKOFF_SEC     = 3
FINNHUB_NEWS_DAYS     = 7
SENTIMENT_CACHE_HOURS = 6
FLASK_PORT            = 5000
MIN_DATA_QUALITY      = 0.8

# ════════════════ RAPPORT ════════════════
TOP_N_RECOMMENDATIONS   = 10        # Topp 10 – läsbart och fokuserat
REPORT_DIR              = "reports"
REPORT_FILENAME_PATTERN = "weekly_report_{date}.md"

# ════════════════ PORTFÖLJ ════════════════
HOLDINGS_FILE       = "holdings.csv"
BUY_MORE_PERCENTILE = 80
HOLD_PERCENTILE     = 50

# ════════════════ EMAIL ════════════════
EMAIL_SENDER   = ""
EMAIL_PASSWORD = ""
EMAIL_TO       = ""

# ════════════════ BENCHMARK ════════════════
BENCHMARK_OMXS30 = "XACTOMXS3.ST"
BENCHMARK_SPY    = "SPY"
BENCHMARK_LABEL  = "OMXS30"
