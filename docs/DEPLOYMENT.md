# MarketScan — Deployment-guide

> **Uppdaterad:** 2026-06-04 · Se `docs/SYSTEM_AI.md` för fullständig systemöversikt.

## Snabbstart (lokal)

```bash
git clone https://github.com/OWNER/marketscan.git
cd marketscan
pip install -r requirements.txt
cp .env.example .env      # Fyll i dina API-nycklar
streamlit run web/streamlit_app.py
```

## Streamlit Cloud (produktion)

### Förutsättningar
- Konto på [streamlit.io](https://streamlit.io)
- GitHub-repo med koden (kan vara privat)

### Steg

1. **Skapa app** — [share.streamlit.io](https://share.streamlit.io) → "New app"
   - Repository: ditt repo
   - Branch: `main`
   - Main file: `web/streamlit_app.py`

2. **Konfigurera Secrets** (Manage app → Secrets)

```toml
# Nödvändiga
[credentials]
# Streamlit-authenticator format
usernames.admin.email = "admin@example.com"
usernames.admin.name = "Admin"
usernames.admin.password = "$2b$12$..."  # bcrypt-hash

cookie.expiry_days = 30
cookie.key = "din-slumpmässiga-nyckel-64-tecken"
cookie.name = "marketscan_auth"

DEEPSEEK_API_KEY = "sk-..."
GEMINI_API_KEY = "AIza..."
FINNHUB_API_KEY = "..."
EMAIL_SENDER = "scanner@example.com"
EMAIL_PASSWORD = "..."
EMAIL_TO = "you@example.com"

# Valfria
APP_URL = "https://din-app.streamlit.app"
ROTATION_DRY_RUN = "true"
```

3. **Konfigurera GitHub Actions Secrets** (repo Settings → Secrets → Actions)

| Secret | Beskrivning |
|--------|-------------|
| `DEEPSEEK_API_KEY` | AI-analys |
| `GEMINI_API_KEY` | AI-analys (fallback) |
| `FINNHUB_API_KEY` | Finnhub-nyheter |
| `EMAIL_SENDER` | Scan-mailavsändare |
| `EMAIL_PASSWORD` | SMTP app-lösenord |
| `EMAIL_TO` | Mottagare |
| `WATCHLIST_JSON` | Bevakningslista (JSON-sträng) |
| `ROTATION_DRY_RUN` | `"true"` för preview, `"false"` för auto-execution |

## GitHub Actions Workflows

| Workflow | Schema | Syfte |
|----------|--------|-------|
| `daily_scan.yml` | Vardagar 09:05 + 17:30 CEST | Morgon- och kvällsscan |
| `daily_scan.yml` | Lördag 09:00 CEST | Veckoscan |
| `daily_scan.yml` | Måndag 09:15 CEST | Småbolagsscan |
| `tests.yml` | Push/PR till main | Automatiska tester + lint |
| `train_ml.yml` | Söndag 04:00 CEST | ML-modellträning |
| `keep_alive.yml` | Var 30:e min, 07-22 | Håller Streamlit-appen igång |
| `news_alerts.yml` | Vardagar 08:00 CEST | Nyhetslarm |
| `universe_update.yml` | Manuell | Uppdatera ticker-univers |

### Kör pipeline manuellt

GitHub → Actions → "MarketScan Pipeline" → "Run workflow"

```
Körläge: morning | evening | weekly | smallcap | targeted | refresh_missing | retry_rate_limited
Tickers (för targeted): VOLV-B.ST,ERIC-B.ST
```

## Konfigurationshierarki

```
1. GitHub Secrets / Streamlit Secrets    ← högst prioritet
2. .env (lokal utveckling)
3. core/config.py (defaults)             ← lägst prioritet
```

## Lokal pipeline-körning

```bash
# Kör morgonscan manuellt
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')"

# Kör veckoscan
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('weekly')"

# Riktat scan
python -c "from core.daily_pipeline import run_targeted; run_targeted(['AAPL','MSFT'])"
```

## Felsökning

### Pipeline misslyckas i CI

1. Kontrollera GitHub Actions-loggen (fliken "Actions")
2. Sök efter `⚠` eller `❌` i loggarna
3. Vanliga orsaker:
   - `RATE_LIMITED` — yfinance rate-limit, vänta och kör igen
   - `ModuleNotFoundError` — beroende saknas i `requirements.txt`
   - `Permission denied` — GITHUB_TOKEN saknar `contents: write`

### Streamlit-appen startar inte

```bash
# Kontrollera att alla beroenden är installerade
pip install -r requirements.txt

# Kontrollera secrets
python -c "import streamlit as st; print(st.secrets)"

# Kör med debug-logging
PYTHONPATH=. streamlit run web/streamlit_app.py --logger.level=debug
```

### ML-modeller laddas inte

```bash
# Kontrollera SHA-256 checksumfiler
ls models/*.sha256

# Regenerera checksumfiler
python -c "
from core.ml_predictor import load_model, save_model
# Träna modeller på nytt via GitHub Actions: Actions → Train ML
"
```

## Monitorering

- **Pipeline-status**: GitHub Actions → fliken "Actions"
- **Fel-mail**: `send_failure_alert()` skickar automatiskt mail om ett workflow misslyckas
- **Admin-sida**: `/admin` → "Felsökning" för systemstatus och loggar
- **AI-logg**: Admin → "AI-logg" för AI-anropshistorik

## Databaser och filer

Systemet använder platta filer (CSV, JSON, Parquet) committade till GitHub-repot:

| Fil | Innehåll | Uppdateras av |
|-----|----------|---------------|
| `data/universe.json` | Ticker-universum | Manuellt / universe_update workflow |
| `data/holdings.csv` | Portföljinnehav | Streamlit-appen / pipeline |
| `data/watchlist.json` | Bevakningslista | Streamlit-appen |
| `data/blacklist.json` | Delistade tickers | Pipeline (auto) |
| `reports/*.parquet` | Scanresultat | Pipeline |
| `models/*.pkl` | ML-modeller | train_ml workflow |

---

## Fallback & Disaster Recovery (E6)

### Om GitHub Actions är nere

Pipeline kan köras manuellt lokalt med:
```bash
# Morgonscan
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')"

# Kvällscan
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('evening')"

# Veckoscanning (lördag)
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('weekly')"

# Småbolagsscan
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('smallcap')"

# Specifika tickers
TARGET_TICKERS="VOLV-B.ST,ERIC-B.ST" python -c "from core.daily_pipeline import run_pipeline; run_pipeline('targeted')"
```

Kräver: `.env`-filen med API-nycklar + Python-dependencies installerade.

### Om Streamlit Cloud är nere

Starta appen lokalt:
```bash
streamlit run streamlit_app.py
```

### Återställ data från backup

1. GitHub är master-backup: `git pull origin main`
2. Om `reports/` är tomma: kör `morning`-pipeline manuellt
3. Om `models/*.pkl` är borta: kör `train_ml` workflow manuellt via Actions

### Alternativ schemaläggning (utan GitHub Actions)

Sätt upp cron-jobb lokalt (Linux/Mac):
```bash
# Öppna crontab
crontab -e

# Morgonscan mån-fre 09:05
5 7 * * 1-5 cd /path/to/marketscan && python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')" >> /tmp/ms_morning.log 2>&1

# Kvällscan mån-fre 17:30
30 15 * * 1-5 cd /path/to/marketscan && python -c "from core.daily_pipeline import run_pipeline; run_pipeline('evening')" >> /tmp/ms_evening.log 2>&1
```

Alternativt: Azure Functions, Railway, Render, eller Fly.io som sekundär deployment.

### Viktiga felsökningskommandon

```bash
# Kontrollera senaste pipeline-körning
cat data/scan_log.json | python -m json.tool | tail -40

# Lista alla rapportfiler
ls -la reports/scored_universe_*.parquet | tail -10

# Kolla ML-modellernas ålder
ls -la models/*.pkl

# Diagnostikskript (fullständig systemkontroll)
python scripts/diagnose.py --quick

# Kör bara specifika diagnostik-sektioner
python scripts/diagnose.py --section pipeline --section ml
```
