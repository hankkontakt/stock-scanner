# Manuella kommandon – Stock Scanner

Alla Python-kommandon för att köra systemet manuellt.
Kör från projektets rotmapp: `D:\Trader\stock-scanner\`

---

## Dagliga skanningar

### Morgonkoll (dagsbrev)
```bash
# Standard – skickar alltid e-post
python scans/morning_scan.py

# Utan e-post (bara utskrift i terminalen)
python scans/morning_scan.py --no-email

# Tyst (minimalt output)
python scans/morning_scan.py --quiet
```

### Kvällsrapport (portföljstatus + hold/sälj)
```bash
# Standard
python scans/evening_scan.py

# Utan e-post
python scans/evening_scan.py --no-email

# Tyst
python scans/evening_scan.py --quiet
```

---

## Veckoskanning (söndagsrapport)

```bash
# Full scan – hela universumet
python scans/scan.py

# Bara specifika tickers
python scans/scan.py --tickers "AAPL,MSFT,NVDA"

# Snabb körning (hoppar över extra data)
python scans/scan.py --quick

# Tyst
python scans/scan.py --quiet
```

---

## Möjlighetsscan

```bash
python scans/opportunity_scan.py
```

---

## Småbolagsskanner (svenska small caps)

```bash
# Hela universumet (First North + Small Cap + Spotlight)
python -m smallcap.scanner

# Bara First North
python -m smallcap.scanner --market first_north

# Bara Nasdaq Stockholm Small Cap
python -m smallcap.scanner --market small_cap

# Bara Spotlight Stock Market
python -m smallcap.scanner --market spotlight

# Anpassa antal bolag i listan
python -m smallcap.scanner --top 10
python -m smallcap.scanner --top 30

# Fler djupdyksprofiler (standard: 5)
python -m smallcap.scanner --profiles 10

# Snabb körning utan insiderhämtning
python -m smallcap.scanner --no-insider

# Spara rapport i specifik mapp
python -m smallcap.scanner --output reports/

# Skicka rapport via e-post
python -m smallcap.scanner --email

# Kombinerat exempel – First North, top 15, spara + skicka
python -m smallcap.scanner --market first_north --top 15 --output reports/ --email
```

---

## Webbgränssnitt (portföljhantering)

```bash
# Starta webbservern (öppnar på http://localhost:5001)
python web/app.py
```

Funktioner: innehav, bevakningslista, Avanza CSV-import, GitHub-synk.

---

## Streamlit Dashboard

```bash
# Starta Streamlit-dashboarden
streamlit run web/streamlit_app.py
```

---

## Importera från Avanza

```bash
# Importera från Avanza CSV-export
python data_management/avanza_import.py import avanza_export.csv

# Förhandsgranska utan att spara
python data_management/avanza_import.py import avanza_export.csv --dry-run

# Importera utan interaktiva frågor
python data_management/avanza_import.py import avanza_export.csv --no-interactive

# Lägg till en manuell ticker-mappning (bolagsnamn → ticker)
python data_management/avanza_import.py map "Kinnevik B" KINV-B.ST
python data_management/avanza_import.py map "Evolution" EVO.ST

# Visa alla sparade mappningar
python data_management/avanza_import.py list
```

---

## Transaktioner & P&L

```bash
# Registrera ett köp
python portfolio/positions.py add-buy AAPL 10 185.50
python portfolio/positions.py add-buy AAPL 10 185.50 --fee 39 --date 2024-01-15

# Registrera en försäljning
python portfolio/positions.py add-sell AAPL 5 210.00
python portfolio/positions.py add-sell AAPL 5 210.00 --fee 39 --date 2024-06-01

# Visa performance-rapport
python portfolio/positions.py report

# Synka holdings.csv från transaktionsloggen
python portfolio/positions.py sync
```

---

## Paper Trading (simulera systemet)

```bash
# Visa aktuell status och track record
python portfolio/paper_trading.py status

# Uppdatera priser för öppna positioner
python portfolio/paper_trading.py update

# Stäng positioner äldre än 6 veckor
python portfolio/paper_trading.py update --close-after 6

# Generera detaljerad rapport
python portfolio/paper_trading.py report
```

---

## Backtest & Optimering

### Enkel backtest
```bash
# Standard (3 år, top-20, jämfört mot SPY)
python backtesting/backtest.py

# Anpassa
python backtesting/backtest.py --years 5
python backtesting/backtest.py --years 5 --top 15 --bench QQQ
```

### Walk-forward backtest (mer tillförlitlig)
```bash
# Standard (4 år totalt, 2 träning + 1 test)
python backtesting/walk_forward.py

# Anpassa
python backtesting/walk_forward.py --years 5 --train 2 --test 6
python backtesting/walk_forward.py --years 6 --top 15 --bench ^OMX
```

### Faktoroptimering (hitta bästa vikter)
```bash
# Kör optimering – visa resultat utan att ändra
python backtesting/factor_optimizer.py
python backtesting/factor_optimizer.py --trials 500 --tickers 80

# Applicera bästa vikter till config.py
python backtesting/factor_optimizer.py --apply

# Förhandsgranska ändringar
python backtesting/factor_optimizer.py --apply --dry-run
```

---

## Verktyg

```bash
# Ticker-hälsokontroll
python -m tools.ticker_health
python -m tools.ticker_health --check AAPL MSFT INVALID.ST
python -m tools.ticker_health --universe all --workers 4
python -m tools.ticker_health --blacklist
```

---

## Snabbguide – vanligaste användningen

| Vad | Kommando |
|---|---|
| Morgonkoll | `python scans/morning_scan.py` |
| Kvällsrapport | `python scans/evening_scan.py` |
| Söndagsskanning | `python scans/scan.py` |
| Möjlighetsscan | `python scans/opportunity_scan.py` |
| Småbolag (snabb) | `python -m smallcap.scanner --no-insider` |
| Småbolag (full) | `python -m smallcap.scanner --email` |
| Portföljwebb | `python web/app.py` |
| Streamlit | `streamlit run web/streamlit_app.py` |
| Avanza-import | `python data_management/avanza_import.py import fil.csv` |
| Ticker-hälsa | `python -m tools.ticker_health` |
| Backtest | `python backtesting/backtest.py --years 3` |
