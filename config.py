"""
config.py  –  MarketScan inställningar
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ════════════════ USA LARGE/MID/SMALL CAP ════════════════
US_LARGE_CAP = [
    # Tech / Halvledare
    "AAPL","MSFT","GOOGL","GOOG","AMZN","META","NVDA","TSLA","AVGO","ORCL",
    "CRM","ADBE","AMD","INTC","CSCO","QCOM","TXN","IBM","NOW","INTU",
    "PANW","PLTR","SNOW","MU","AMAT","LRCX","KLAC","ADI","MRVL","FTNT",
    "DDOG","CRWD","WDAY","TEAM","MDB","NET","ZS","OKTA","SHOP","UBER",
    "ABNB","DASH","SPOT","ADSK","ANSS","CDNS","SNPS","VRSN","CTSH","GLW",
    "HPQ","HPE","DELL","WDC","STX","PSTG","NTAP","AKAM","CDW","ZBRA",
    "ARM","SMCI","ACN","EPAM","GLOB","APP","FLUT",
    # Finans
    "JPM","BAC","WFC","GS","MS","C","BLK","AXP","V","MA",
    "BRK-B","SCHW","PYPL","COIN","BX","KKR","ICE","CME","SPGI","MCO",
    "PGR","TRV","AIG","MET","PRU","ALL","AFL","HIG","RNR","RE",
    "CBOE","NDAQ","IVZ","BEN","TROW","STT","NTRS","FDS","MKTX",
    "SQ","AFRM","SOFI","HOOD","UPST","NU",
    # Healthcare
    "JNJ","UNH","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","BMY",
    "AMGN","GILD","CVS","ELV","CI","ISRG","VRTX","REGN","BIIB","MRNA",
    "DXCM","BSX","MDT","SYK","EW","ZBH","IDXX","IQV","HCA","MOH",
    "CNC","DGX","LH","HOLX","EXAS","VEEV","RMD","BAX","BDX","WAT",
    "MTD","TECH","PODD","ACAD","BEAM","CRSP","EDIT","NTLA","RXRX","NUVL",
    # Consumer Staples
    "WMT","PG","KO","PEP","COST","MDLZ","PM","MO","CL","KMB",
    "GIS","K","SYY","MNST","STZ","EL","CHD","CLX","HRL","MKC",
    "SJM","CAG","CPB","HSY","INGR","LANC",
    # Consumer Discretionary
    "MCD","NKE","SBUX","TGT","HD","LOW","DIS","NFLX","BKNG","MAR",
    "HLT","CMG","ORLY","AZO","ROST","TJX","LULU","YUM","DRI","QSR",
    "EAT","TXRH","WING","FWRG","ETSY","CHWY","W","RH","WSM",
    "F","GM","APTV","LEA","BWA","MGA",
    # Industri / Försvar
    "CAT","BA","GE","HON","UPS","FDX","LMT","RTX","DE","MMM",
    "EMR","ETN","ITW","PH","ROK","GD","NOC","TDG","WM","CSX",
    "UNP","NSC","LUV","DAL","UAL","AAL","PCAR","CMI","AGCO","TEX",
    "HII","KTOS","BWXT","TXT","DRS","MRCY",
    # Energi / Förnybart
    "XOM","CVX","COP","EOG","SLB","PXD","MPC","PSX","VLO","OXY",
    "HES","DVN","WMB","KMI","ENB","NEE","FSLR","ENPH","SEDG","RUN",
    "PLUG","FLNC","BE","ARRY",
    # Material / Guld
    "LIN","SHW","FCX","NEM","NUE","VMC","MLM","DOW","DD","ECL",
    "APD","EMN","STLD","X","AA","ALB","MP","LTHM",
    "AEM","GOLD","KGC","WPM","FNV","RGLD","SAND","AG","PAAS",
    # Kommunikation / Media / Gaming
    "T","VZ","TMUS","CMCSA","CHTR","WBD","RBLX","EA","TTWO","ROKU",
    "SNAP","PINS","MTCH","ZG","LYV","MSGS",
    # REITs
    "PLD","AMT","EQIX","PSA","O","SPG","WELL","CCI","DLR","VICI",
    "VTR","EXR","AVB","EQR","MAA","UDR","NNN","ADC","STAG","COLD",
    # Utilities
    "DUK","SO","AEP","EXC","XEL","SRE","ED","ETR","WEC","EIX",
    "ES","PPL","FE","NI","AES","D",
    # S&P 400 MidCap
    "MANH","FICO","POOL","DECK","WSO","CABO","CASY","ELF","WING","CIVI",
    "LNTH","TMHC","NEU","SLGN","IRDM","MTZ","KBH","PHM","TOL","NVR",
    "HALO","ACLS","FORM","DOCN","GTLB","CFLT","MNDY","BILL","PRCT",
    "CELH","USPH","IPAR","MGNI","TTD","PUBM","DV","IAS",
    "RBC","EXPO","MEDP","HIMS","RDDT","DUOL","APP","CAVA","BROS",
    "MODG","SMAR","PCVX","TGTX","PRAX","KYMR","FOLD",
    # Quantum / Space / AI
    "IONQ","RGTI","QBTS","ARQQ","RKLB","ASTS","JOBY","ACHR",
    "AI","PATH","SOUN","BBAI","OPEN",
]

# ════════════════ SVERIGE ════════════════
OMX_SE = [
    # Industri
    "VOLV-B.ST","ATCO-A.ST","ATCO-B.ST","SAND.ST","SKF-B.ST","ABB.ST",
    "ALFA.ST","EPI-A.ST","EPI-B.ST","INDU-C.ST","INDU-A.ST",
    "TRELLEBORG-B.ST","HEXA-B.ST","AXFO.ST","NIBE-B.ST","ASSA-B.ST",
    # Finans
    "SEB-A.ST","SHB-A.ST","SWED-A.ST","NDA-SE.ST","INVE-A.ST","INVE-B.ST",
    "LATO-B.ST","KINV-B.ST","LIFCO-B.ST","EQT.ST","BURE.ST","INDT.ST",
    "SVOL-B.ST","CREADES.ST","CATO-B.ST",
    # Tech
    "ERIC-B.ST","SINCH.ST","ENEA.ST","CINT.ST","IAR-B.ST","KNOW-IT.ST",
    # Telecom
    "TELIA.ST","TEL2-B.ST",
    # Healthcare
    "AZN.ST","GETI-B.ST","ESSITY-B.ST","ARJO-B.ST","XVIVO.ST",
    "VITROLIFE.ST","BICO.ST","BIOT.ST","RAY-B.ST","CTM.ST","ELEK-B.ST",
    # Consumer / Gaming
    "HM-B.ST","EVO.ST","EMBRAC-B.ST","BETS-B.ST","G5EN.ST","PARADOX.ST",
    "CLAS-B.ST","MEKO.ST","BILI-A.ST","BHG.ST","SKIS-B.ST",
    # Material
    "BOL.ST","SSAB-A.ST","SSAB-B.ST","SCA-B.ST","LUNE.ST","TROAX.ST",
    # Fastighet
    "BALD-B.ST","CAST.ST","FABG.ST","SAGA-B.ST","WIHL.ST","DIOS.ST",
    "JM.ST","PEAB-B.ST","NCC-B.ST","SKA-B.ST","CIBUS.ST","K-FAST-B.ST",
    # Energi
    "ARISE.ST","GRNG.ST","OX2.ST",
    # Mid/Small
    "NCAB.ST","MIPS.ST","BUFAB.ST","AQ.ST","BEIJ-B.ST","OEM-B.ST",
    "INVISIO.ST","HEXP-B.ST","DOM.ST","INSTAL.ST","MILDEF.ST","SDIP-B.ST",
    "FNOX.ST","VITEC.ST","PNDX-B.ST","INTRUM.ST","RESURS.ST","MEDCAP.ST",
    "CONCEN.ST","BERG-B.ST","MENTICE.ST","ALIG.ST","ADDV-B.ST",
]

# ════════════════ EUROPA ════════════════
EUROPE = [
    # Tyskland
    "SAP.DE","SIE.DE","DTE.DE","ALV.DE","BAS.DE","BAYN.DE","BMW.DE",
    "MBG.DE","VOW3.DE","ADS.DE","MUV2.DE","DBK.DE","DPW.DE","DB1.DE",
    "IFX.DE","RWE.DE","EOAN.DE","FRE.DE","MTX.DE","HEN3.DE","BEI.DE",
    "PUM.DE","ZAL.DE","AIR.DE","P911.DE","RHM.DE","1COV.DE","SHL.DE",
    "AIXA.DE","GFT.DE","SY1.DE","WAF.DE","SMHN.DE","KGX.DE","ENR.DE",
    # Frankrike
    "MC.PA","OR.PA","AIR.PA","TTE.PA","SAN.PA","BNP.PA","RMS.PA","KER.PA",
    "EL.PA","SU.PA","CS.PA","DG.PA","VIE.PA","AI.PA","ML.PA","ENGI.PA",
    "GLE.PA","ACA.PA","STM.PA","CAP.PA","TEP.PA","SAF.PA","PUB.PA",
    "LR.PA","VK.PA","HO.PA","DSY.PA","RCO.PA",
    # UK
    "SHEL.L","AZN.L","HSBA.L","ULVR.L","BP.L","RIO.L","GSK.L","BARC.L",
    "LSEG.L","DGE.L","REL.L","PRU.L","VOD.L","BATS.L","LLOY.L","NWG.L",
    "TSCO.L","BT-A.L","EXPN.L","STAN.L","IMB.L","GLEN.L","AAL.L","ANTO.L",
    "RR.L","BA.L","IAG.L","EZJ.L","CPG.L","JD.L","NXT.L","SMT.L",
    # Schweiz
    "NESN.SW","NOVN.SW","ROG.SW","ABBN.SW","UBSG.SW","ZURN.SW","RICN.SW",
    "GIVN.SW","CFR.SW","LONN.SW","ALC.SW","HOLN.SW","PGHN.SW","TEMN.SW",
    "SGSN.SW","SLHN.SW","KNIN.SW",
    # Nederländerna
    "ASML.AS","PRX.AS","AD.AS","INGA.AS","ASRNL.AS","PHIA.AS","AKZA.AS",
    "HEIA.AS","WKL.AS","REN.AS","BESI.AS","IMCD.AS","RAND.AS",
    # Spanien / Italien
    "ITX.MC","IBE.MC","SAN.MC","BBVA.MC","TEF.MC","REP.MC",
    "ENI.MI","ENEL.MI","ISP.MI","UCG.MI","G.MI","RACE.MI","STM.MI","LDO.MI",
    # Norden
    "NOVO-B.CO","MAERSK-B.CO","DSV.CO","CARL-B.CO","GN.CO","ORSTED.CO",
    "GMAB.CO","NZYM-B.CO","COLO-B.CO","PNDORA.CO","DEMANT.CO","CHR.CO",
    "EQNR.OL","DNB.OL","TEL.OL","MOWI.OL","AKER.OL","ORK.OL","TOM.OL",
    "AKSO.OL","BOUVET.OL","OPERA.OL","RECSI.OL",
    "NOKIA.HE","SAMPO.HE","FORTUM.HE","NESTE.HE","KNEBV.HE","UPM.HE",
    "STO1V.HE","ELISA.HE","TIE1V.HE","METSA-B.HE",
    # Östeuropa / Österrike
    "CD.PL","PKN.PL","PKO.PL","PZU.PL","OMV.VI","AIAG.VI","VIG.VI",
]

# ════════════════ ASIEN / STILLA HAVET ════════════════
ASIA_PACIFIC = [
    # Japan
    "TM","SONY","HMC","NTDOY","MUFG","SMFG",
    "7203.T","6758.T","9984.T","6501.T","6902.T",
    "6954.T","7751.T","8306.T","8316.T","9433.T","9432.T",
    # Taiwan
    "TSM","UMC","2330.TW","2317.TW","2412.TW","3008.TW",
    # Sydkorea
    "005930.KS","000660.KS","035420.KS","005380.KS","051910.KS",
    "035720.KS","207940.KS",
    # Kina / Hong Kong
    "BABA","JD","PDD","BIDU","NIO","LI","XPEV","TCEHY","BYDDY",
    "9988.HK","9618.HK","0700.HK","1810.HK","3690.HK","9999.HK",
    "0941.HK","2318.HK","1398.HK","3968.HK",
    # Indien
    "INFY","WIT","HDB","RELIANCE.NS","TCS.NS","HDFCBANK.NS","SBIN.NS",
    # Australien
    "BHP","RIO","CSL","MQG.AX","ANZ.AX","CBA.AX","WBC.AX","NAB.AX",
    "FMG.AX","ALL.AX","REA.AX","WES.AX",
    # Singapore
    "D05.SI","O39.SI","U11.SI","C6L.SI",
]

# ════════════════ KANADA ════════════════
CANADA = [
    "ENB","TD","BNS","RY","CP","CNR","BCE","TRP","SU","CVE",
    "IMO","PPL","WFG","CCO","FM","ABX","G","WPM","FNV",
    "SHOP","BAM","BN","MFC","SLF","POW","FFH","DOL","ATD","L",
]

# ════════════════ EMERGING / LATINAMERIKA ════════════════
EMERGING = [
    "VALE","ITUB","BBD","MELI","NU","GLOB","ARCO","SE","GRAB",
    "AMXL.MX","FEMSA","PETR4.SA","ABEV3.SA","BBAS3.SA",
]

# ════════════════ KOMBINERA ════════════════
EXTRA = [
    # US Growth / Quality mid cap
    "KNSL","ATKR","CSWI","RLI","SIGI","ERIE","AIZ","MCY","ACGL","RYAN",
    "WTW","AON","MMC","CBSH","UBSI","BOKF","SNV","FULT","IBOC","HTLF",
    # US Tech mid
    "HUBS","BRZE","FROG","ALTR","JAMF","TASK","ZI","PCOR","CWAN",
    "QLYS","TENB","PING","SAIL","VERA","SMAR","AXSM","PTCT","ITCI","ARGX",
    "KRYS","NTRA","TMDX","ACVA","CELH",
    # US Consumer / Retail
    "BOOT","CROX","SKX","DECK","HIBB","GIII","EVRI","PLAY","BOWL","LESL",
    # US Industrial small
    "IESC","CECO","ODFL","SAIA","XPO","TFII","ARCB","AEIS","KLIC","ONTO",
    "MKSI","ESAB","ASTE","STRL","ROAD","PRIM","HUBG","ECHO",
    # US Energy
    "CHRD","SM","ESTE","FLNG","GLNG","EVGO","CHPT","BLNK","STEM",
    # Fler europa
    "BOSS.DE","AIXA.DE","SDAX.DE","NOS.LS","EDP.LS","GALP.LS",
    "TITAN.AT","OPAP.AT","AMBU-B.CO","FLS.CO","SIM.CO","ROCK-A.CO",
    "RBREW.CO","NETCO.CO",
    # Fler nordiska
    "KAHOT.OL","ATEA.OL","KONGSBERG.OL","NEL.OL","SCATC.OL","AKRBP.OL",
    "SALM.OL","PROTCT.OL","HAVI.OL",
    "OPTER.ST","HOLM-B.ST","LUMI.ST",
    "PUUILO.HE","REMEDY.HE","NETUM.HE",
    # Fler Asien
    "9888.HK","2015.HK","9961.HK","1024.HK","1211.HK","4151.T","8035.T",
    "9735.T","6367.T","7267.T","8001.T",
    "ADANIENT.NS","BHARTIARTL.NS","LTIM.NS","HCLTECH.NS","MARUTI.NS",
    # Kanada extra
    "NTR","AGI","OSK","IMG","YRI","OTEX","LSPD","NVEI","REAL","DND",
    "CIGI","FSV","ERF","MEG","BTE","NXE","LUN","FM","CS","WRK",
    # Brasilien / LatAm extra
    "BRFS","NTCO","LREN3.SA","WEGE3.SA","RENT3.SA","RADL3.SA",
]

UNIVERSE = list(dict.fromkeys(
    US_LARGE_CAP + OMX_SE + EUROPE + ASIA_PACIFIC + CANADA + EMERGING + EXTRA
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
CACHE_HOURS           = 24
PRICE_CACHE_HOURS     = 24
REQUEST_DELAY_SEC     = 0.4
MAX_RETRIES           = 3
RETRY_BACKOFF_SEC     = 5
FINNHUB_NEWS_DAYS     = 7
SENTIMENT_CACHE_HOURS = 6
FLASK_PORT            = 5000
MIN_DATA_QUALITY      = 0.5

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
