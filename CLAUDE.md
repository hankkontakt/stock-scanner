# MarketScan — utvecklarguide för AI-assistenter

Den här filen är till för AI-assistenter (Claude Code etc) som behöver navigera repot snabbt. Det är inte ett user-manual.

## Arkitektur

```
            ┌──────────────────┐
            │  GitHub Actions  │  cron-schemalägger körningar
            └────────┬─────────┘
                     │
                     ▼
       core/daily_pipeline.run_pipeline(mode)
                     │
        ┌────────────┼────────────────────┐
        ▼            ▼                    ▼
   data_fetcher   scoring         email_template
   (yfinance,     (faktor-vikter, (HTML-rapport
   fmp, finnhub)  regime, ranking) + SMTP)
        │            │                    │
        ▼            ▼                    ▼
   data/cache    reports/        EMAIL_TO inkorgar
   (parquet)     scored_*.csv
                 *.md
                     │
                     ▼
            web/streamlit_app.py
            (läser reports/, visar
            i Streamlit Cloud)
```

## Entry points

| Trigger | Fil | Vad den gör |
|---|---|---|
| Streamlit Cloud | `streamlit_app.py` (root-shim) | Importerar `web/streamlit_app.py` med rätt `__file__`-kontext |
| Streamlit lokal | `streamlit run streamlit_app.py` | Samma som ovan |
| CI morning/evening | `.github/workflows/daily_scan.yml` | `python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')"` |
| CI smallcap | `.github/workflows/smallcap_scan.yml` | `python -m smallcap.scanner --market all` |
| CI news_alerts | `.github/workflows/news_alerts.yml` | `python -c "from core.news_alerts import check_alerts; check_alerts()"` |

## Setup lokalt

```bash
# Klona och installera editable så imports fungerar utan PYTHONPATH-hacks
pip install -e .
pip install -r requirements.txt

# Skapa .env med API-nycklar (kopiera från .env.example)
cp .env.example .env
# → fyll i FMP_API_KEY, FINNHUB_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY,
#   EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_TO

# Kör en scan manuellt
python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')"

# Starta Streamlit-appen
streamlit run streamlit_app.py
```

## Vilka API-nycklar krävs?

| Nyckel | Obligatorisk? | Används för |
|---|---|---|
| `FMP_API_KEY` | Valfri | Earnings-kalender, financial data |
| `FINNHUB_API_KEY` | Valfri | News sentiment |
| `DEEPSEEK_API_KEY` | Krävs för AI-analys | Default-provider för AI |
| `GEMINI_API_KEY` | Valfri | Fallback om DeepSeek failar |
| `EMAIL_SENDER` + `EMAIL_PASSWORD` | Krävs för rapport-mail | Gmail App Password (16 tecken, ej kontolösen) |
| `EMAIL_TO` | Krävs för rapport-mail | Komma-separerad lista |
| `SITE_PASSWORD` | Valfri | Skydda Streamlit-sidan |
| `ADMIN_PASSWORD` | Valfri | Skydda Admin-fliken |

**Riktiga nycklar i prod lagras i GitHub Secrets (för workflows) och Streamlit Cloud Secrets (för web).** `.env` används bara lokalt och är gitignored.

## Vanliga buggsymptom & var man tittar

| Symptom | Sannolik fil | Anteckning |
|---|---|---|
| `ModuleNotFoundError: No module named 'core'` i CI | workflow saknar `PYTHONPATH: .` | finns nu på job-nivå i alla workflows |
| `ValueError: If using all scalar values...` | dict→DataFrame med skalär-värden | `pd.concat(list, axis=1)` istället, se [web/streamlit_app.py:1817](web/streamlit_app.py:1817) |
| `IndexError` på `.iloc[-1]` | yfinance returnerade tom DataFrame | guard med `if not df.empty and len(df) >= 2:` |
| FX-priser 100x för stora | `ffill().bfill()` propagerade gamla kurser | nu begränsat till 5 dagar + sanity check |
| `DSML tool_calls` läcker i Cline-DeepSeek-flöde | inte ett repo-problem, Cline-bugg | se C:\Users\hthur\.claude\projects\.../memory/ |

## Test- och lint-kommandon

```bash
# Köra tester
pytest tests/ -v

# Med coverage
pytest tests/ --cov=core --cov-report=term

# Linta
ruff check .

# Typkolla
mypy core/
```

## Deploy

Streamlit Cloud auto-deployer från `main`. Det innebär att varje push till main går live efter ~30s rebuild. Om en push bryter prod:

```bash
git revert <sha>
git push origin main
```

Streamlit Cloud reagerar på reverten automatiskt.

## Datafiler

- `reports/scored_universe_YYYY-MM-DD.csv` — daglig scan-output (commitas av CI)
- `reports/smallcap_scored_YYYY-MM-DD.csv` — veckans smallcap-scan
- `reports/*.md` — markdown-rapporter (commitas av CI)
- `data/cache/*.parquet` — yfinance-cache (gitignored)
- `data/holdings.csv` — portfölj (inte gitignored, men user-specifik)
- `data/strikes.json` — fetch-fel-räknare per ticker
- `data/blacklist.json` — permanenta blacklist (3+ strikes)

Gamla rapporter rensas automatiskt efter 60 dagar via `_cleanup_old_reports()` i pipeline.

## Hur jag debuggar en misslyckad scan

1. **Kolla GitHub Actions-loggen** — vid failure skickas ett mail via `send_failure_alert()`.
2. **Reproducera lokalt:** `python -c "from core.daily_pipeline import run_pipeline; run_pipeline('morning')"` med samma `.env`.
3. **Kolla `data/scan_log.json`** för senaste run-metadata (commitad av CI).
4. **Streamlit-appen kraschad?** Streamlit Cloud → Manage app → Logs.
