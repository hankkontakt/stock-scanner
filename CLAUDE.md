# MarketScan

> ⚠️ **LÄS FÖRST:** `docs/SYSTEM_AI.md` — komplett systemdokumentation med varenda fil, funktion och dataflöde.
> All kodlogik, arkitektur, konfiguration och förbättringsidéer finns där.

## Snabbreferens

| Vad | Var |
|---|---|
| Huvudingång (pipeline) | `core/daily_pipeline.py:run_pipeline(mode)` |
| Scoring-motor | `core/scoring.py` |
| Datahämtning | `core/data_fetcher.py` |
| AI-analys | `core/ai_analysis.py` |
| Streamlit-app | `web/streamlit_app.py` |
| Admin + debug | `web/pages/admin_page.py` |
| Manuella kommandon | `docs/KOMMANDON.md` |
| Tester | `tests/` (92 tests) |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env    # Fyll i API-nycklar
streamlit run streamlit_app.py
```

## Vanliga buggsymptom

| Symptom | Lösning |
|---|---|
| `ModuleNotFoundError: No module named 'core'` | CI workflow saknar `PYTHONPATH: .` |
| `ValueError: If using all scalar values` | `pd.concat(list, axis=1)` istället för `pd.DataFrame(dict)` |
| `IndexError` på `.iloc[-1]` | yfinance returnerade tom DataFrame |
