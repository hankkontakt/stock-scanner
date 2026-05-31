# MarketScan

> ⚠️ **LÄS FÖRST:** `docs/SYSTEM_AI.md` — komplett systemdokumentation med varenda fil, funktion och dataflöde.
> All kodlogik, arkitektur, konfiguration och förbättringsidéer finns där.
>
> 🔴 **OBLIGATORISKT FÖR ALLA AI-MODELLER:** Du MÅSTE hålla `docs/SYSTEM_AI.md` uppdaterad.
> Varje gång du ändrar kod, hittar en bugg, eller upptäcker en förbättringsmöjlighet —
> **även om det inte hör ihop med uppgiften du arbetar med just nu** — ska du lägga in det
> i `docs/SYSTEM_AI.md` (se avsnittet "0. Underhållsprotokoll" överst i den filen).
> Detta gäller löpande under hela arbetet, inte bara i slutet.

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
