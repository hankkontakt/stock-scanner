# 📊 Stock Scanner

En kvantitativ aktiescanner som rangordnar 100-1000 aktier baserat på akademiskt validerade faktorer (value, quality, momentum, growth, risk, size, dividend) och jämför dina innehav mot toppen.

**Designad för att fungera med Claude Pro – ingen API-kostnad krävs.**

## Vad systemet gör

1. **Hämtar data** för alla aktier i ditt universum (yfinance, gratis)
2. **Beräknar 7 faktorscores** (0-100 skala, percentil-baserad)
3. **Genererar topp 50-rekommendation** baserat på composite score
4. **Analyserar din portfölj** och ger köp/behåll/sälj-rekommendationer
5. **Skapar markdown-rapport** som du klistrar in i Claude Pro för djupanalys

## Installation

### 1. Installera Python (om du inte redan har det)

- **Mac:** `brew install python` eller ladda ner från [python.org](https://python.org)
- **Windows:** Ladda ner från [python.org](https://python.org) (välj "Add to PATH" vid installation)
- **Linux:** `sudo apt install python3 python3-pip`

Verifiera: `python --version` (ska visa 3.9 eller högre)

### 2. Installera beroenden

```bash
cd stock-scanner
pip install -r requirements.txt
```

### 3. (Valfritt) Lägg till dina innehav

Editera `holdings.csv`:

```csv
ticker,shares,cost_basis
AAPL,10,150.00
VOLV-B.ST,100,210.50
```

Lämna filen tom om du bara vill se topp 50 utan portföljanalys.

## Användning

```bash
# Komplett scan (rekommenderas söndag kväll, tar 5-10 min första gången)
python scan.py

# Snabb scan (kör bara på specifika tickers)
python scan.py --tickers AAPL,MSFT,GOOGL

# Tyst läge (mindre output)
python scan.py --quiet
```

## Workflow varje söndag (10 min)

1. Kör `python scan.py`
2. Öppna senaste rapporten i `reports/weekly_report_YYYY-MM-DD.md`
3. Kopiera hela innehållet
4. Klistra in i en ny Claude Pro-chatt
5. Claude söker nyheter, filtrerar bort röda flaggor och ger dig kvalitativ analys

## Anpassning

All konfiguration finns i `config.py`:

- **`UNIVERSE`** – Lista över aktier att scanna (lägg till/ta bort själv)
- **`FACTOR_WEIGHTS`** – Hur mycket varje faktor väger (måste summera till 1.0)
- **`CACHE_HOURS`** – Hur länge data cachas (default: 24h)
- **`BUY_MORE_PERCENTILE`** – Tröskeln för "KÖP MER" rekommendation (default: top 20%)

### Exempel: Mer fokus på value-investing

```python
FACTOR_WEIGHTS = {
    "value":     0.40,  # Mer vikt på lågt värderade
    "quality":   0.25,
    "momentum":  0.10,  # Mindre momentum
    "growth":    0.10,
    "risk":      0.10,
    "size":      0.03,
    "dividend":  0.02,
}
```

### Exempel: Lägg till svenska småbolag

I `config.py`, lägg till i `OMX_LARGE_CAP`:
```python
"VITROLIFE.ST", "BHG.ST", "AAK.ST", "BEIJ-B.ST", "ELUX-B.ST"
```

## Filstruktur

```
stock-scanner/
├── README.md           # Den här filen
├── requirements.txt    # Python-beroenden
├── config.py           # Inställningar och universum
├── data_fetcher.py     # Datahämtning + caching
├── scoring.py          # Faktorberäkningar
├── portfolio.py        # Portföljanalys
├── scan.py             # Huvudscript
├── holdings.csv        # Dina aktieinnehav (du editerar denna)
├── data/cache/         # Cachad data (skapas automatiskt)
└── reports/            # Genererade rapporter (skapas automatiskt)
```

## Faktorerna förklarade

| Faktor | Vad det mäter | Datapunkter |
|---|---|---|
| **Value** | Lågt värderad relativt fundamenta | P/E, P/B, P/S, EV/EBITDA |
| **Quality** | Lönsamhet och effektivitet | ROE, ROA, marginaler |
| **Momentum** | Senaste prisutveckling | 3m/6m/12m return, % från 52v-high |
| **Growth** | Tillväxt i intäkter och vinst | Revenue growth, earnings growth |
| **Risk** | Finansiell stabilitet (inverterad – lägre risk = högre score) | Skuld/eget kapital, volatilitet, beta |
| **Size** | Småbolagsfaktor (mild positiv) | Market cap (log) |
| **Dividend** | Utdelningskvalitet | Direktavkastning, payout ratio |

## Datakällor

- **Primär:** Yahoo Finance via `yfinance` (gratis, ingen nyckel behövs)
- **Cache:** Lokal pickle-fil (24h livslängd)
- **Backup (valfritt):** Financial Modeling Prep – sätt `FMP_API_KEY` i config.py

## Kända begränsningar

- ⚠ **yfinance kan ha datakvalitetsproblem för europeiska aktier** – verifiera viktiga datapunkter manuellt
- ⚠ **Rate limiting:** Hög volym kan ge `429 Too Many Requests` – lös genom att öka `REQUEST_DELAY_SEC`
- ⚠ **Historisk data ≠ framtida resultat** – inget kvantitativt system slår marknaden konsekvent
- ⚠ **Faktorerna roterar:** Value har underpresterat 2007-2020. Justera vikter över tid

## Felsökning

**`429 Too Many Requests` error:**
- Öka `REQUEST_DELAY_SEC` i config.py till 1.0 eller högre
- Vänta 30 minuter och försök igen
- Aktivera FMP_API_KEY som backup

**Många "FAILED" tickers:**
- Kontrollera att tickers är korrekta (svenska aktier behöver `.ST`-suffix)
- Vissa aktier kan ha avnoterats
- Kontrollera internetanslutning

**Tomma scores för alla aktier:**
- Du behöver minst 5 aktier med data per faktor – utöka universumet
- Vissa europeiska aktier har glesa fundamentaldata i yfinance

## Nästa steg

När basen fungerar kan du utveckla systemet:

1. **Lägga till nyhetsentiment** – integrera Finnhub API (gratis 60 anrop/min)
2. **Backtest** – testa hur dina faktorvikter presterat historiskt
3. **Sektor-justering** – ranka inom sektor istället för globalt
4. **Risk-hantering** – sätt automatiska stop-loss nivåer baserat på volatilitet

---

*Detta är ett research-verktyg, inte finansiell rådgivning. Investeringar innebär risk för förlust.*
