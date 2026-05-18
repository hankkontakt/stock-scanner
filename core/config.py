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
    "ABNB", "DASH", "SPOT", "ADSK", "CDNS", "SNPS", "VRSN", "CTSH", "GLW",
    "HPQ", "HPE", "DELL", "WDC", "STX", "PSTG", "NTAP", "AKAM", "CDW", "ZBRA",
    "ARM", "SMCI", "ACN", "EPAM", "GLOB", "APP", "FLUT", "ANET", "VRT", "NTNX", 
    "CHKP", "CYBR", "TOST", "FOUR", "ASAN", "ESTC", "DOCS", "LAW", "AMPL", 
    "COUR", "UDEMY", "ZM", "DBX", "BOX", "FSLY", "WOLF", "ON", "COHR", "AEHR", 
    "RMBS", "AMKR", "ALGM", "SWKS", "QRVO", "FFIV", "IONQ", "RGTI", "QBTS", 
    "ARQQ", "RKLB", "ASTS", "JOBY", "ACHR", "AI", "PATH", "SOUN", "BBAI", "OPEN",
    
    # Finans
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "V", "MA",
    "BRK-B", "SCHW", "PYPL", "COIN", "BX", "KKR", "ICE", "CME", "SPGI", "MCO",
    "PGR", "TRV", "AIG", "MET", "PRU", "ALL", "AFL", "HIG", "RNR", "EG",
    "CBOE", "NDAQ", "IVZ", "BEN", "TROW", "STT", "NTRS", "FDS", "MKTX",
    "SQ", "AFRM", "SOFI", "HOOD", "UPST", "NU", "ALLY", "SYF", "COF", 
    "CACC", "OMF", "NAVI", "SLM", "PRAA", "ENVA",
    
    # Krypto / High Beta (Ny)
    "MSTR", "MARA", "RIOT", "HUT", "HIVE", "BITF", "IREN", "CORZ", "MIGI", 
    "WULF", "BTBT", "ARBK",

    # Healthcare / Biotech
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "CVS", "ELV", "CI", "ISRG", "VRTX", "REGN", "BIIB", "MRNA",
    "DXCM", "BSX", "MDT", "SYK", "EW", "ZBH", "IDXX", "IQV", "HCA", "MOH",
    "CNC", "DGX", "LH", "HOLX", "EXAS", "VEEV", "RMD", "BAX", "BDX", "WAT",
    "MTD", "TECH", "PODD", "ACAD", "BEAM", "CRSP", "EDIT", "NTLA", "RXRX", "NUVL",
    "VKTX", "ALNY", "EXEL", "SRPT", "IOVA", "ROIV", "CPRX", "NBIX", "INCY", "UTHR", 
    "UTMD", "MDGL", "BMRN", "BNTX", "PRGO", "CRL", "ICON", "ALGN", "MASI", 
    "PEN", "GMED", "LMAT", "HALO", "GH", "NTRA", "TMDX",

    # Consumer Staples
    "WMT", "PG", "KO", "PEP", "COST", "MDLZ", "PM", "MO", "CL", "KMB",
    "GIS", "SYY", "MNST", "STZ", "EL", "CHD", "CLX", "HRL", "MKC",
    "SJM", "CAG", "CPB", "HSY", "INGR", "LANC", "BRBR", "SMPL", "TR", "SFM", 
    "KR", "ACI", "RAD", "DG", "DLTR", "OLLI", "FIVE", "BJ", "BMBL", "GRND",

    # Consumer Discretionary
    "MCD", "NKE", "SBUX", "TGT", "HD", "LOW", "DIS", "NFLX", "BKNG", "MAR",
    "HLT", "CMG", "ORLY", "AZO", "ROST", "TJX", "LULU", "YUM", "DRI", "QSR",
    "EAT", "TXRH", "WING", "FWRG", "ETSY", "CHWY", "W", "RH", "WSM",
    "F", "GM", "APTV", "LEA", "BWA", "MGA",

    # Industri / Försvar
    "CAT", "BA", "GE", "HON", "UPS", "FDX", "LMT", "RTX", "DE", "MMM",
    "EMR", "ETN", "ITW", "PH", "ROK", "GD", "NOC", "TDG", "WM", "CSX",
    "UNP", "NSC", "LUV", "DAL", "UAL", "AAL", "PCAR", "CMI", "AGCO", "TEX",
    "HII", "KTOS", "BWXT", "TXT", "DRS", "MRCY", "HEI", "TDY", "WWD",
    "CACI", "LDOS", "SAIC", "BAH", "LHX", "HWM", "WNC", "GBX", "ALG", 
    "GGG", "NDSN", "DOV", "AME", "FIX", "EME", "PWR", "MYRG", "TTC", "MIDD",

    # Energi / Förnybart / Utilities / Kärnkraft
    "XOM", "CVX", "COP", "EOG", "SLB", "FANG", "MPC", "PSX", "VLO", "OXY",
    "APA", "DVN", "WMB", "KMI", "ENB", "NEE", "FSLR", "ENPH", "SEDG", "RUN",
    "PLUG", "FLNC", "BE", "ARRY", "DUK", "SO", "AEP", "EXC", "XEL", "SRE", "ED", 
    "ETR", "WEC", "EIX", "ES", "PPL", "FE", "NI", "AES", "D", "CEG", "VST", "CCJ", 
    "NRG", "TLN", "LEU", "SMR", "OKLO", "FLR", "CW", "TRN", "AR", "RRC", 
    "CHK", "EQT", "CNX", "MUR", "PR", "MTDR", "PEG", "AEE", 
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

# ════════════════ STORBRITANNIEN / UK MID-LARGE CAP ════════════════
UK = [
    # Banks & Financial Services
    "HSBA.L", "BARC.L", "LLOY.L", "NWG.L", "STAN.L", "PRU.L", "LSEG.L", "HICL.L",
    "III.L", "MNG.L", "PHNX.L", "AV.L", "LGEN.L",
    # Mining & Materials
    "RIO.L", "GLEN.L", "AAL.L", "ANTO.L", "FRES.L", "JMAT.L", "CRH.L", "BLND.L",
    # Consumer & Retail
    "DGE.L", "ULVR.L", "BATS.L", "IMB.L", "TSCO.L", "SBRY.L", "NXT.L",
    "JD.L", "MKS.L", "CCH.L", "ABF.L", "SPD.L",
    # Industrials & Engineering
    "RR.L", "BA.L", "IMI.L", "WEIR.L", "SMIN.L", "SPX.L", "RTO.L", "MGGT.L",
    "COB.L", "GAW.L", "GKN.L", "MRO.L",
    # Tech & Software
    "SMT.L", "REL.L", "EXPN.L", "AUTO.L", "SGE.L", "DARK.L", "BME.L",
    "MONY.L", "RWI.L", "MSY.L",
    # Healthcare
    "AZN.L", "GSK.L", "SHG.L", "SN.L",
    # Energy
    "SHEL.L", "BP.L", "TLW.L", "HBR.L", "EME.L",
    # Utilities
    "SSE.L", "NG.L", "UU.L", "SV.L", "CNA.L",
    # REITs & Property
    "LAND.L", "PSN.L", "BDEV.L",
]

# ════════════════ TYSKLAND (utökad) ════════════════
GERMANY = [
    # Industri & Engineering
    "SIE.DE", "RHM.DE", "MTX.DE", "HEI.DE", "SHL.DE", "G1A.DE", "DUE.DE",
    "MAN.DE", "SKB.DE", "KCO.DE", "STM.DE", "TKA.DE", "LEO.DE",
    # Finance
    "ALV.DE", "MUV2.DE", "DBK.DE", "DB1.DE", "CBK.DE", "HNR1.DE", "WKN.DE",
    # Tech & Software
    "SAP.DE", "IFX.DE", "AIXA.DE", "GFT.DE", "WAF.DE", "SMHN.DE", "NEM.DE",
    "QBY.DE", "UTDI.DE", "PNE.DE", "BC8.DE",
    # Healthcare
    "BAYN.DE", "FRE.DE", "EVT.DE", "SRT.DE", "MOR.DE",
    # Consumer
    "BMW.DE", "MBG.DE", "VOW3.DE", "ADS.DE", "PUM.DE", "ZAL.DE", "P911.DE",
    "BOSS.DE", "HEN3.DE", "BEI.DE", "DIC.DE", "TTE.DE",
    # Utilities & Energy
    "RWE.DE", "EOAN.DE", "ENR.DE", "UN01.DE", "S92.DE",
    # Materials
    "BAS.DE", "1COV.DE", "SY1.DE", "WCH.DE", "LXS.DE",
    # Logistics & Transport
    "DHL.DE", "MRN.DE", "FMG.DE", "HHFA.DE",
    # Media & Telecom
    "DTE.DE", "FNTN.DE",
]

# ════════════════ NORDEN (exkl. Sverige) ════════════════
NORDIC = [
    # Danmark
    "NOVO-B.CO", "MAERSK-A.CO", "MAERSK-B.CO", "DSV.CO", "CARL-B.CO", "CARL-A.CO",
    "GMAB.CO", "DEMANT.CO", "ZEAL.CO", "PANDORA.CO", "ORSTED.CO", "ALK-B.CO",
    "AMBU-B.CO", "ROCK-A.CO", "FLS.CO", "GN.CO", "NZYM-B.CO", "HHS.CO",
    "TOP.CO", "ISS.CO", "JYSK.CO", "SYDB.CO", "DANSKE.CO", "COLO-B.CO",
    # Norge
    "EQNR.OL", "DNB.OL", "TOM.OL", "AKSO.OL", "MOWI.OL", "ORK.OL",
    "SALM.OL", "YAR.OL", "KOG.OL", "NHY.OL", "TEL.OL", "BOUV.OL",
    "FLNG.OL", "FRO.OL", "BWLPG.OL", "GJF.OL", "GOGL.OL",
    "SUBC.OL", "AUSS.OL", "SCATC.OL", "NOD.OL", "BWO.OL",
    # Finland
    "NOKIA.HE", "SAMPO.HE", "UPM.HE", "NESTE.HE", "FORTUM.HE",
    "KEMIRA.HE", "METSB.HE", "VALMT.HE", "METSO.HE", "TOKMAN.HE",
    "KAMUX.HE", "ELISA.HE", "STORA.HE", "ORION-B.HE", "QTCOM.HE",
    "RELAIS.HE", "PUUILO.HE", "HARVIA.HE", "MARIMEKKO.HE",
]

# ════════════════ SVERIGE – OMX Stockholm Large/Mid Cap ════════════════
OMX_SE = [
    # Industri & Verkstad
    "VOLV-B.ST", "VOLV-A.ST", "SAND.ST", "SKF-B.ST", "ALFA.ST",
    "ATCO-A.ST", "ATCO-B.ST", "HEXA-B.ST", "EPIR-B.ST", "SWEC-B.ST",
    "NCC-B.ST", "SSAB-A.ST", "SSAB-B.ST", "BOLM.ST", "THULE.ST",
    "HUSQ-B.ST", "TROAX.ST", "DIOS.ST", "AFRY.ST", "MSAB-B.ST",

    # Finans & Bank
    "SEB-A.ST", "SHB-A.ST", "SWED-A.ST", "NDA-SE.ST", "INVE-A.ST",
    "INVE-B.ST", "LATO-A.ST", "LATO-B.ST", "LUND-B.ST",
    "BURE.ST", "SVNK-A.ST", "KINV-B.ST", "CBRE.ST",

    # Tech & Mjukvara
    "ERIC-B.ST", "ERIC-A.ST", "EVO.ST", "CINT.ST", "BOKU.ST",
    "NOLA-B.ST", "INDT.ST", "HMS.ST", "DIAM-B.ST", "ADDV-B.ST",
    "SINCH.ST", "NETG-B.ST", "CMORE.ST",

    # Healthcare & Life Science
    "SOBI.ST", "ONCO.ST", "BIOG-B.ST", "ALZ.ST", "HMED.ST",
    "BIOTAGE.ST", "XVIVO.ST", "NANOFORM.ST",

    # Konsument & Handel
    "HM-B.ST", "HM-A.ST", "AXFO.ST", "CLAS-B.ST", "BOOZT.ST",
    "BILIA-A.ST", "OEM-B.ST", "KNOW-IT.ST", "MATAS.ST",

    # Fastighet
    "CAST.ST", "SBB-B.ST", "CALD.ST", "FABG.ST", "WIHL.ST",
    "CAPP.ST", "KLOVERN-B.ST", "NYFOSA.ST", "NIBE-B.ST",

    # Energi & Utilities
    "VATTENFALL.ST", "TELIA.ST", "SSCP.ST",

    # Material & Skog
    "SCA-B.ST", "HOLM-B.ST", "ESSITY-B.ST", "BETZ.ST",
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
    "TEP.PA", "ASML.AS", "PRX.AS", "BESI.AS", "BOUV.OL", "OPRA", 
    "NOKIA.HE", "ADYEN.AS", "NEM.DE",

    # Healthcare / Läkemedel
    "BAYN.DE", "FRE.DE", "SAN.PA", "AZN.L", "GSK.L", "NOVN.SW", "ROG.SW", "LONN.SW", 
    "ALC.SW", "PHIA.AS", "NOVO-B.CO", "GMAB.CO", "DEMANT.CO", "ZEAL.CO", "ALK-B.CO", 
    "AMBU-B.CO", "FRES.L", "EVT.DE", "DIM.PA",

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
    "ELISA.HE", "UMG.AS", "KPN.AS", "VIV.PA",
]

# ════════════════ ASIEN / STILLA HAVET (utökad) ════════════════
ASIA_PACIFIC = [
    # Japan - Large Cap
    "TM", "SONY", "HMC", "NTDOY", "MUFG", "SMFG",
    "7203.T", "6758.T", "9984.T", "6501.T", "6902.T",
    "6954.T", "7751.T", "8306.T", "8316.T", "9433.T", "9432.T",
    "8031.T", "8053.T", "8058.T", "8002.T", "7974.T", "6861.T", "6594.T", "6098.T", 
    "4661.T", "4502.T", "4519.T", "4568.T", "4063.T", "3382.T", "2914.T",
    # Japan - Mid Cap (utökad)
    "4507.T", "4523.T", "4578.T", "4631.T", "4901.T", "4911.T", "4922.T",
    "5108.T", "5201.T", "5301.T", "5332.T", "5333.T", "5401.T", "5411.T",
    "5713.T", "5714.T", "5801.T", "5802.T", "5901.T", "6103.T", "6113.T",
    "6135.T", "6141.T", "6201.T", "6301.T", "6367.T", "6383.T", "6395.T",
    "6406.T", "6457.T", "6471.T", "6479.T", "6506.T", "6586.T", "6592.T",
    "6645.T", "6674.T", "6701.T", "6714.T", "6723.T", "6728.T", "6770.T",
    "6841.T", "6857.T", "6871.T", "6952.T", "6963.T", "6971.T", "6976.T",
    "7004.T", "7011.T", "7012.T", "7013.T", "7014.T", "7022.T", "7105.T",
    "7148.T", "7167.T", "7186.T", "7564.T", "8001.T", "8015.T", "8028.T",
    # Taiwan
    "2330.TW", "2317.TW", "2412.TW", "3008.TW", "2454.TW", "2308.TW", "2881.TW",
    "2379.TW", "2303.TW", "2409.TW", "2395.TW", "2347.TW", "2382.TW",
    # Sydkorea
    "005930.KS", "000660.KS", "035420.KS", "005380.KS", "051910.KS",
    "035720.KS", "207940.KS", "068270.KS", "028260.KS", "086790.KS",
    "105560.KS", "012330.KS", "006400.KS", "011070.KS", "000270.KS",
    # Kina / Hong Kong
    "9988.HK", "9618.HK", "0700.HK", "1810.HK", "3690.HK", "9999.HK",
    "0941.HK", "2318.HK", "1398.HK", "3968.HK", "1299.HK", "0001.HK", "0002.HK", 
    "0003.HK", "0016.HK", "0066.HK", "0386.HK", "0883.HK",
    "0939.HK", "2388.HK", "0011.HK", "0005.HK", "0012.HK", "0027.HK",
    "0083.HK", "0101.HK", "0268.HK", "0708.HK", "0762.HK", "0836.HK",
    "0968.HK", "1024.HK", "1211.HK", "1818.HK", "1833.HK", "1928.HK",
    "2269.HK", "2333.HK", "2382.HK", "2628.HK", "2800.HK",
    # Indien (utökad)
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "SBIN.NS", "ADANIENT.NS", "BHARTIARTL.NS", "KOTAKBANK.NS", "WIPRO.NS",
    "LTIM.NS", "HCLTECH.NS", "MARUTI.NS", "TATAMOTORS.NS", "TITAN.NS",
    "AXISBANK.NS", "BAJFINANCE.NS", "HINDUNILVR.NS", "SUNPHARMA.NS", "ITC.NS",
    "ULTRACEMCO.NS", "NTPC.NS", "POWERGRID.NS", "M&M.NS", "ASIANPAINT.NS",
    "TATASTEEL.NS", "JSWSTEEL.NS", "TRENT.NS", "BAJAJFINSV.NS", "ADANIPORTS.NS",
    "CIPLA.NS", "DIVISLAB.NS", "DRREDDY.NS", "EICHERMOT.NS", "GRASIM.NS",
    "HEROMOTOCO.NS", "HINDALCO.NS", "SBILIFE.NS", "TATACONSUM.NS", "TECHM.NS",
    # Australien
    "BHP", "RIO", "CSL", "MQG.AX", "ANZ.AX", "CBA.AX", "WBC.AX", "NAB.AX",
    "FMG.AX", "ALL.AX", "REA.AX", "WES.AX", "GMG.AX", "WOW.AX", "COL.AX",
    "TLS.AX", "RMD.AX", "XRO.AX", "SHL.AX", "COH.AX",
    # Singapore
    "D05.SI", "O39.SI", "U11.SI", "C6L.SI", "Z74.SI", "S58.SI",
]

# ════════════════ KANADA (Med Rätt .TO Suffix) ════════════════
CANADA = [
    "ENB.TO", "TD.TO", "BNS.TO", "RY.TO", "CP.TO", "CNR.TO", "BCE.TO", "TRP.TO", "SU.TO", "CVE.TO",
    "IMO.TO", "PPL.TO", "WFG.TO", "CCO.TO", "FM.TO", "ABX.TO", "G.TO", "WPM.TO", "FNV.TO",
    "SHOP.TO", "BAM.TO", "BN.TO", "MFC.TO", "SLF.TO", "POW.TO", "FFH.TO", "DOL.TO", "ATD.TO", "L.TO",
    "WN.TO", "EMP-A.TO", "MRU.TO", "SAP.TO", "GIB-A.TO", "CSU.TO", "KXS.TO", "DSG.TO", 
    "TIH.TO", "TFII.TO", "WSP.TO", "STN.TO", "NTR.TO", "AGI.TO", "OSK.TO", "IMG.TO", 
    "LSPD.TO", "REAL.TO", "DND.TO", "CIGI.TO", "FSV.TO", "MEG.TO", "BTE.TO", 
    "NXE.TO", "LUN.TO",
]

# ════════════════ BRASILIEN / LATINAMERIKA (utökad) ════════════════
BRAZIL = [
    "VALE", "ITUB", "BBD", "MELI", "ARCO", "SE", "GRAB",
    "AMX", "FMX", "ABEV", "B3SA3.SA", "PETR4.SA", "BBAS3.SA", "ITSA4.SA",
    "WEGE3.SA", "LREN3.SA", "RENT3.SA", "SUZB3.SA", "CSNA3.SA",
    "JBSS3.SA", "BRFS3.SA", "GGBR4.SA", "CMIG4.SA", "EGIE3.SA",
    "EQTL3.SA", "EMBR3.SA", "AZUL4.SA", "BOOM", "MGLU3.SA",
    "UGPA3.SA", "RADL3.SA", "HAPV3.SA", "FLRY3.SA", "TOTS3.SA",
    # Mexico & Other LATAM
    "WALMEX.MX", "CEMEX.MX", "FEMSA.MX", "GFNORTEO.MX", "TLEVISACPO.MX",
    "AC.MX", "LABB.MX", "KIMBERA.MX",
]

EMERGING = BRAZIL  # Behåller EMERGING alias för bakåtkompabilitet

# ════════════════ KOMBINERA ════════════════
UNIVERSE = list(dict.fromkeys(
    US_LARGE_CAP + UK + GERMANY + NORDIC + OMX_SE + EUROPE +
    ASIA_PACIFIC + CANADA + EMERGING
))


# ════════════════ NYA FAKTORER – viktaberedskap ════════════════
# Dessa vikter läggs till om short_interest/seasonality/options_flow integreras
EXTRA_FACTOR_WEIGHTS = {
    "short_interest": 0.03,  # Blankningsgrad – låg blankning = positivt
    "seasonality":    0.03,  # Säsongsmönster – stark månad = positivt
    "options_flow":   0.02,  # Optionsflöde – puts/calls ratio
}

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
# Om EXTRA_FACTOR_WEIGHTS läggs till, justeras FACTOR_WEIGHTS proportionellt
# Detta görs i scoring.py med en helper-funktion

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
    "min_daily_turnover_sek":  500_000,         # Daglig omsättning ≥ 500k SEK
    "min_market_cap_sek":      30_000_000,      # Börsvärde ≥ 30 MSEK
    "max_market_cap_sek":      10_000_000_000,  # Börsvärde ≤ 10 GSEK (annars mid/large cap)
    "max_debt_to_equity":      300,             # D/E > 300 % = skuldfälla
    "min_current_ratio":       0.5,             # CR < 0.5 = akut likviditetskris
    "min_cash_runway_months":  12,              # Kassan måste räcka ≥ 12 månader
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
