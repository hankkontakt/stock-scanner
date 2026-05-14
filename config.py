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
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "V", "MA",
    "BRK-B", "SCHW", "PYPL", "COIN", "BX", "KKR", "ICE", "CME", "SPGI", "MCO",
    "PGR", "TRV", "AIG", "MET", "PRU", "ALL", "AFL", "HIG", "RNR", "EG",
    "CBOE", "NDAQ", "IVZ", "BEN", "TROW", "STT", "NTRS", "FDS", "MKTX",
    "SQ", "AFRM", "SOFI", "HOOD", "UPST", "NU", "ALLY", "SYF", "DFS", "COF", 
    "CACC", "OMF", "NAVI", "SLM", "PRAA", "ENVA",
    
    # Krypto / High Beta (Ny)
    "MSTR", "MARA", "RIOT", "CLEU", "HUT", "HIVE", "BITF", "IREN", "CORZ", "MIGI", 
    "WULF", "SDIG", "BTBT", "ARBK",

    # Healthcare / Biotech
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "CVS", "ELV", "CI", "ISRG", "VRTX", "REGN", "BIIB", "MRNA",
    "DXCM", "BSX", "MDT", "SYK", "EW", "ZBH", "IDXX", "IQV", "HCA", "MOH",
    "CNC", "DGX", "LH", "HOLX", "EXAS", "VEEV", "RMD", "BAX", "BDX", "WAT",
    "MTD", "TECH", "PODD", "ACAD", "BEAM", "CRSP", "EDIT", "NTLA", "RXRX", "NUVL",
    "VKTX", "ALNY", "EXEL", "SRPT", "IOVA", "ROIV", "CPRX", "NBIX", "INCY", "UTHR", 
    "UTMD", "MDGL", "BMRN", "BNTX", "PRGO", "CTLT", "CRL", "ICON", "ALGN", "MASI", 
    "PEN", "GMED", "LMAT", "HALO", "GH", "NTRA", "TMDX",

    # Consumer Staples
    "WMT", "PG", "KO", "PEP", "COST", "MDLZ", "PM", "MO", "CL", "KMB",
    "GIS", "K", "SYY", "MNST", "STZ", "EL", "CHD", "CLX", "HRL", "MKC",
    "SJM", "CAG", "CPB", "HSY", "INGR", "LANC", "BRBR", "SMPL", "TR", "SFM", 
    "KR", "ACI", "WBA", "RAD", "DG", "DLTR", "OLLI", "FIVE", "BJ", "BMBL", "GRND",

    # Consumer Discretionary
    "MCD", "NKE", "SBUX", "TGT", "HD", "LOW", "DIS", "NFLX", "BKNG", "MAR",
    "HLT", "CMG", "ORLY", "AZO", "ROST", "TJX", "LULU", "YUM", "DRI", "QSR",
    "EAT", "TXRH", "WING", "FWRG", "ETSY", "CHWY", "W", "RH", "WSM",
    "F", "GM", "APTV", "LEA", "BWA", "MGA",

    # Industri / Försvar
    "CAT", "BA", "GE", "HON", "UPS", "FDX", "LMT", "RTX", "DE", "MMM",
    "EMR", "ETN", "ITW", "PH", "ROK", "GD", "NOC", "TDG", "WM", "CSX",
    "UNP", "NSC", "LUV", "DAL", "UAL", "AAL", "PCAR", "CMI", "AGCO", "TEX",
    "HII", "KTOS", "BWXT", "TXT", "DRS", "MRCY", "HEI", "TDY", "WWD", "SPR", 
    "MANT", "CACI", "LDOS", "SAIC", "BAH", "LHX", "HWM", "WNC", "GBX", "ALG", 
    "GGG", "NDSN", "DOV", "AME", "ROIC", "FIX", "EME", "PWR", "MYRG", "TTC", "MIDD",

    # Energi / Förnybart / Utilities / Kärnkraft
    "XOM", "CVX", "COP", "EOG", "SLB", "FANG", "MPC", "PSX", "VLO", "OXY",
    "APA", "DVN", "WMB", "KMI", "ENB", "NEE", "FSLR", "ENPH", "SEDG", "RUN",
    "PLUG", "FLNC", "BE", "ARRY", "DUK", "SO", "AEP", "EXC", "XEL", "SRE", "ED", 
    "ETR", "WEC", "EIX", "ES", "PPL", "FE", "NI", "AES", "D", "CEG", "VST", "CCJ", 
    "NRG", "TLN", "LEU", "SMR", "OKLO", "FLR", "CW", "BPC", "TRN", "AR", "RRC", 
    "CHK", "SWN", "EQT", "CNX", "MUR", "MRO", "PR", "MTDR", "PEG", "AEE", 
    "AWK", "PNW", "OGE",

    # Material / Guld
    "LIN", "SHW", "FCX", "NEM", "NUE", "VMC", "MLM", "DOW", "DD", "ECL",
    "APD", "EMN", "STLD", "X", "AA", "ALB", "MP", "ALTM",
    "AEM", "GOLD", "KGC", "WPM", "FNV", "RGLD", "SAND", "AG", "PAAS",

    # Kommunikation / Media / Gaming
    "T", "VZ", "TMUS", "CMCSA", "CHTR", "WBD", "RBLX", "EA", "TTWO", "ROKU",
    "SNAP", "PINS", "MTCH", "ZG", "LYV", "MSGS",

    # REITs
    "PLD", "AMT", "EQIX", "PSA", "O", "SPG", "WELL", "CCI", "DLR", "VICI",
    "VTR", "EXR", "AVB", "EQR", "MAA", "UDR", "NNN", "ADC", "STAG", "COLD",
]

# ════════════════ SVERIGE ════════════════
OMX_SE = [
    # Industri & Verkstad
    "VOLV-B.ST", "ATCO-A.ST", "ATCO-B.ST", "SAND.ST", "SKF-B.ST", "ABB.ST",
    "ALFA.ST", "EPI-A.ST", "EPI-B.ST", "INDU-C.ST", "INDU-A.ST",
    "TREL-B.ST", "HEXA-B.ST", "AXFO.ST", "NIBE-B.ST", "ASSA-B.ST", 
    "HMSN.ST", "SYSR.ST", "MYCR.ST", "GARO.ST", "AFCO-B.ST", "FAG.ST", 
    "NOTE.ST", "AQ.ST", "BUFAB.ST", "MIPS.ST", "NCAB.ST", "OEM-B.ST", "IVSO.ST",
    "MILDEF.ST", "INSTAL.ST", "BEIJ-B.ST", "TROAX.ST", "BERG-B.ST", "COIC.ST",

    # Finans & Investmentbolag
    "SEB-A.ST", "SHB-A.ST", "SWED-A.ST", "NDA-SE.ST", "INVE-A.ST", "INVE-B.ST",
    "LATO-B.ST", "KINV-B.ST", "LIFCO-B.ST", "EQT.ST", "BURE.ST", "INDT.ST",
    "SVOL-B.ST", "CRED-A.ST", "CATE.ST", "VNV.ST", "NOBI.ST", "RATO-B.ST", 
    "INTRUM.ST", "RESURS.ST", "HOFI.ST", "KFAB.ST",

    # Tech / IT / Mjukvara
    "ERIC-B.ST", "SINCH.ST", "ENEA.ST", "CINT.ST", "IAR-B.ST", "KNOW.ST",
    "BTS-B.ST", "VNE-SDB.ST", "ALIV-SDB.ST", "PRIC-B.ST", "ADDT-B.ST", "VIT-B.ST",
    "FNOX.ST", "PNDX-B.ST", "TRUE-B.ST",

    # Telecom & Media
    "TELIA.ST", "TEL2-B.ST", "NENT-B.ST", "MTG-B.ST",

    # Healthcare / Medtech / Biotech
    "AZN.ST", "GETI-B.ST", "ESSITY-B.ST", "ARJO-B.ST", "XVIVO.ST",
    "VITR.ST", "BICO.ST", "BIOT.ST", "RAY-B.ST", "CTM.ST", "EKTA-B.ST",
    "CAMX.ST", "VIMIAN.ST", "LINC.ST", "SECT-B.ST", "MCAP.ST", "MNTC.ST", "ALIG.ST",

    # Consumer / Gaming / Handel
    "HM-B.ST", "EVO.ST", "EMBRAC-B.ST", "BETS-B.ST", "G5EN.ST", "PDX.ST",
    "CLAS-B.ST", "MEKO.ST", "BILI-A.ST", "BHG.ST", "SKIS-B.ST", "DUNI.ST", 
    "RVRC.ST", "CARY.ST", "KDEV.ST", "BINV.ST", "VOLCAR-B.ST", "AAK.ST", "THULE.ST", 
    "LOOMIS.ST", "DOM.ST",

    # Material & Skog
    "BOL.ST", "SSAB-A.ST", "SSAB-B.ST", "SCA-B.ST", "HOLM-B.ST", "BMAX.ST", "HPOL-B.ST",

    # Fastighet & Bygg
    "BALD-B.ST", "CAST.ST", "FABG.ST", "SAGA-B.ST", "WIHL.ST", "DIOS.ST",
    "JM.ST", "PEAB-B.ST", "NCC-B.ST", "SKA-B.ST", "CIBUS.ST", "KFAST-B.ST",
    "NP3.ST", "SBB-B.ST", "CORE-B.ST", "NYF.ST", "FPAR-A.ST", "SLP-B.ST", "PLAT.ST",
    "HEBA-B.ST", "NIV.ST", "HTRO.ST", "MTRS.ST", "BONAV-B.ST", "SDIP-B.ST",

    # Energi
    "ARISE.ST", "GRNG.ST", "EPRO-B.ST", "ELCG.ST"
]

# ════════════════ EUROPA (Uppdelad i Sektorer) ════════════════
EUROPE = [
    # Industri & Verkstad
    "SIE.DE", "AIR.PA", "SAF.PA", "BA.L", "RR.L", "ABBN.SW", "DSV.CO", "MAERSK-B.CO", 
    "DHL.DE", "MTX.DE", "RHM.DE", "HO.PA", "DSY.PA", "CPG.L", "SMT.L", "SGSN.SW",
    "KNIN.SW", "FER.MC", "PRY.MI", "LDO.MI", "TOM.OL", "AKSO.OL", "METSO.HE", "VALMT.HE",
    "FLS.CO", "ROCK-A.CO", "KOG.OL", "NDX1.DE",

    # Finans & Försäkring
    "ALV.DE", "MUV2.DE", "DBK.DE", "DB1.DE", "BNP.PA", "GLE.PA", "ACA.PA", "HSBA.L", 
    "BARC.L", "LSEG.L", "PRU.L", "LLOY.L", "NWG.L", "STAN.L", "UBSG.SW", "ZURN.SW", 
    "SLHN.SW", "INGA.AS", "ASRNL.AS", "SAN.MC", "BBVA.MC", "ISP.MI", "UCG.MI", "DNB.OL",
    "SAMPO.HE", "PKO.WA", "PZU.WA", "VIG.VI", "EXOR.AS", "CABK.MC", "BKT.MC", "NEXI.MI",

    # Tech & Mjukvara
    "SAP.DE", "IFX.DE", "AIXA.DE", "GFT.DE", "WAF.DE", "SMHN.DE", "STMPA.PA", "CAP.PA", 
    "TEP.PA", "ASML.AS", "PRX.AS", "BESI.AS", "STM.MI", "BOUV.OL", "OPRA", 
    "NOKIA.HE", "ADYEN.AS", "NEM.DE",

    # Healthcare / Läkemedel
    "BAYN.DE", "FRE.DE", "SAN.PA", "AZN.L", "GSK.L", "NOVN.SW", "ROG.SW", "LONN.SW", 
    "ALC.SW", "PHIA.AS", "NOVO-B.CO", "GMAB.CO", "DEMANT.CO", "ZEAL.CO", "ALK-B.CO", 
    "AMBU-B.CO", "FRES.DE", "EVT.DE", "DIM.PA",

    # Consumer Discretionary / Lyx / Fordon
    "BMW.DE", "MBG.DE", "VOW3.DE", "ADS.DE", "PUM.DE", "ZAL.DE", "P911.DE", "MC.PA", 
    "RMS.PA", "KER.PA", "RNO.PA", "STLAP.PA", "JD.L", "NXT.L", "CFR.SW", 
    "RACE.MI", "MONC.MI", "PANDORA.CO", "TOKMAN.HE", "KAMUX.HE", "BOSS.DE",

    # Consumer Staples / Dagligvaror
    "HEN3.DE", "BEI.DE", "OR.PA", "ULVR.L", "DGE.L", "BATS.L", "TSCO.L", "IMB.L", 
    "NESN.SW", "GIVN.SW", "AD.AS", "HEIA.AS", "CARL-B.CO", "MOWI.OL", "ORK.OL", "SALM.OL",

    # Energi & Utilities
    "RWE.DE", "EOAN.DE", "ENR.DE", "TTE.PA", "ENGI.PA", "VIE.PA", "SHEL.L", "BP.L", 
    "IBE.MC", "REP.MC", "ENI.MI", "ENEL.MI", "ORSTED.CO", "EQNR.OL", "FORTUM.HE", 
    "NESTE.HE", "PKN.WA", "OMV.VI", "GALP.LS", "EDP.LS", "FLNG.OL", "FRO.OL", "BWLPG.OL",

    # Material & Kemi
    "BAS.DE", "1COV.DE", "SY1.DE", "AI.PA", "RIO.L", "GLEN.L", "AAL.L", "ANTO.L", 
    "HOLN.SW", "AKZA.AS", "IMCD.AS", "NSIS-B.CO", "UPM.HE", "KEMIRA.HE", 
    "METSB.HE", "MT.AS",

    # Telekom & Media
    "DTE.DE", "PUB.PA", "VOD.L", "REL.L", "EXPN.L", "WKL.AS", "TEF.MC", "TEL.OL", 
    "ELISA.HE", "UMG.AS", "KPN.AS", "VIV.PA"
]

# ════════════════ ASIEN / STILLA HAVET ════════════════
ASIA_PACIFIC = [
    # Japan
    "TM", "SONY", "HMC", "NTDOY", "MUFG", "SMFG",
    "7203.T", "6758.T", "9984.T", "6501.T", "6902.T",
    "6954.T", "7751.T", "8306.T", "8316.T", "9433.T", "9432.T",
    "8031.T", "8053.T", "8058.T", "8002.T", "7974.T", "6861.T", "6594.T", "6098.T", 
    "4661.T", "4502.T", "4519.T", "4568.T", "4063.T", "3382.T", "2914.T",
    # Taiwan
    "2330.TW", "2317.TW", "2412.TW", "3008.TW", "2454.TW", "2308.TW", "2881.TW",
    # Sydkorea
    "005930.KS", "000660.KS", "035420.KS", "005380.KS", "051910.KS",
    "035720.KS", "207940.KS",
    # Kina / Hong Kong
    "9988.HK", "9618.HK", "0700.HK", "1810.HK", "3690.HK", "9999.HK",
    "0941.HK", "2318.HK", "1398.HK", "3968.HK", "1299.HK", "0001.HK", "0002.HK", 
    "0003.HK", "0016.HK", "0066.HK", "0386.HK", "0883.HK",
    # Indien
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "SBIN.NS", "ADANIENT.NS", "BHARTIARTL.NS", 
    "LTIM.NS", "HCLTECH.NS", "MARUTI.NS",
    # Australien
    "BHP", "RIO", "CSL", "MQG.AX", "ANZ.AX", "CBA.AX", "WBC.AX", "NAB.AX",
    "FMG.AX", "ALL.AX", "REA.AX", "WES.AX",
    # Singapore
    "D05.SI", "O39.SI", "U11.SI", "C6L.SI",
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
    "VALE", "ITUB", "BBD", "MELI", "ARCO", "SE", "GRAB",
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
MIN_DATA_QUALITY      = 0.5  # 0.5 = accepterar 4/8 fält (investmentbolag, råvarubolag etc.)

# ════════════════ RAPPORT ════════════════
TOP_N_RECOMMENDATIONS   = 10        # Topp 10 – läsbart och fokuserat
REPORT_DIR              = "reports"
REPORT_FILENAME_PATTERN = "weekly_report_{date}.md"

# ════════════════ PORTFÖLJ ════════════════
HOLDINGS_FILE       = "holdings.csv"
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
