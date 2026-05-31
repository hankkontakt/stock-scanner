# MarketScan — utvecklarguide för AI-assistenter

Det här är en kort navigeringsguide. För komplett systemdokumentation se `docs/SYSTEM_AI.md`.

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

## Manuella kommandon

Se `docs/KOMMANDON.md`.

## Vanliga buggsymptom & var man tittar

| Symptom | Sannolik fil | Anteckning |
|---|---|---|
| `ModuleNotFoundError: No module named 'core'` i CI | workflow saknar `PYTHONPATH: .` | finns nu på job-nivå i alla workflows |
| `ValueError: If using all scalar values...` | dict→DataFrame med skalär-värden | `pd.concat(list, axis=1)` istället, se `web/streamlit_app.py:1817` |
| `IndexError` på `.iloc[-1]` | yfinance returnerade tom DataFrame | guard med `if not df.empty and len(df) >= 2:` |
| FX-priser 100x för stora | `ffill().bfill()` propagerade gamla kurser | nu begränsat till 5 dagar + sanity check |

## Test

```bash
pytest tests/ -v
pytest tests/ --cov=core --cov-report=term
ruff check .
```

## Deploy

Streamlit Cloud auto-deployer från `main`. Varje push till main går live efter ~30s rebuild.

```bash
git revert <sha>
git push origin main
```

## Datafiler

- `reports/scored_universe_YYYY-MM-DD.csv` — daglig scan-output
- `reports/smallcap_scored_YYYY-MM-DD.csv` — veckans smallcap-scan
- `reports/*.md` — markdown-rapporter (gitignored)
- `data/cache/*.parquet` — yfinance-cache (gitignored)
- `data/holdings.csv` — portfölj (commitas av CI)
- `data/blacklist.json` — permanenta blacklist (3+ strikes)

Gamla rapporter rensas automatiskt efter 60 dagar via `_cleanup_old_reports()` i pipeline.
