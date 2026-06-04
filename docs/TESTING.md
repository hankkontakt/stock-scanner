# MarketScan — Testdokumentation

> **Uppdaterad:** 2026-06-04 · Se `docs/SYSTEM_AI.md` för fullständig systemöversikt.

## Snabbstart

```bash
# Kör alla snabba tester
pytest tests/ -m "not slow" -v

# Kör med täckningsrapport
pytest tests/ --cov=core --cov-report=term-missing -m "not slow"

# Kör specifik testfil
pytest tests/test_scoring.py -v

# Kör parallellt (kräver pytest-xdist)
pytest tests/ -n auto -m "not slow"
```

## Teststruktur

```
tests/
├── conftest.py                    — Delade fixtures (sample_scored_df etc.)
├── test_ai_analysis.py            — AI-analys, token-sanitering, fallback
├── test_config.py                 — Konfigurationsvalidering
├── test_daily_pipeline.py         — Pipeline-logik, score-deltas, atomic writes
├── test_data_fetcher.py           — yfinance-hämtning, rate-limiting, backoff
├── test_filters.py                — Entry-signals, RSI, filterlogik
├── test_ml_predictor.py           — ML-prediktering, feature engineering
├── test_news_fetcher.py           — Nyhetshämtning, Finnhub-backoff
├── test_performance.py            — Prestandatester (markerade @pytest.mark.slow)
├── test_property_based.py         — Invariant-tester + Hypothesis property tests
├── test_scoring.py                — Scoring-engine, faktorvikter, neutralisering
└── test_security.py               — Säkerhetstester (T3): auth, injection, tokens
```

## Testmarkeringar

| Mark | Syfte | Körs i CI |
|------|-------|-----------|
| *(ingen)* | Snabba unit-tests | ✅ alltid |
| `@pytest.mark.slow` | Prestandatester (>5s) | Separat CI-steg |

```python
# Hoppa över slow-tester:
pytest tests/ -m "not slow"

# Kör bara slow-tester:
pytest tests/test_performance.py -m slow
```

## Täckningskrav

| Modul | Aktuell | Mål |
|-------|---------|-----|
| `core/` (totalt) | ~30% | 40% (nästa sprint) |
| `core/scoring.py` | ~65% | 70% |
| `core/daily_pipeline.py` | ~15% | 25% |
| `core/filters.py` | ~45% | 60% |

**CI-tröskel:** `--cov-fail-under=30` (höjs löpande i takt med nya tester)

## Mocking-strategi

### Nätverksanrop
Alla externa API-anrop mockas med `pytest-mock` eller `unittest.mock.patch`:

```python
@patch("core.data_fetcher.requests.get")
def test_finnhub_backoff(mock_get):
    mock_get.return_value.status_code = 429
    ...
```

### Filsystem
Tester som skriver filer använder `tmp_path`-fixture (pytest built-in):

```python
def test_save_scored(tmp_path):
    from core.daily_pipeline import _save_scored
    df = pd.DataFrame({"ticker": ["AAPL"], "score_total": [75.0]})
    _save_scored(df, tmp_path / "scored.parquet")
    assert (tmp_path / "scored.csv").exists()
```

### Modul-konstanter
Monkeypatch används för att byta ut sökvägar i moduler:

```python
def test_load_portfolio(tmp_path, monkeypatch):
    from core import daily_pipeline
    monkeypatch.setattr(daily_pipeline, "DATA_DIR", tmp_path)
    ...
```

## Property-based Tests (Hypothesis)

Kräver `pip install hypothesis`. Verifierar invarianta egenskaper:

```bash
# Kör property-based tests
pytest tests/test_property_based.py -v

# Med fler exempel (standard är 100)
pytest tests/test_property_based.py --hypothesis-seed=42
```

Invarianter som testas:
- `percentile_rank()` returnerar ALLTID [0, 100]
- `score_total` är ALLTID [0, 100]
- Alla faktorvikter summerar ALLTID till 1.0
- `_get_score_deltas()` kraschar aldrig oavsett input

## CI/CD

Tester körs automatiskt vid:
- Push till `main`-branchen (om `core/`, `tests/`, `web/` ändrats)
- Pull requests mot `main`

**CI-pipeline:**
1. `lint` — ruff check på core/, tests/, portfolio/, web/, smallcap/, scripts/
2. `type-check` — mypy core/ (continue-on-error)
3. `test` (python 3.11 + 3.12) — pytest med täckning
4. `security` — pip-audit för CVE-skanning

## Lägga till nya tester

### Principer
1. En testfil per modul (`test_<module>.py`)
2. Klasser grupperar relaterade tester (`class TestScoreDelta`)
3. Testnamnet beskriver *vad* och *förväntat utfall*
4. Inga nätverksanrop utan mock
5. Inga filsystemsskrivningar utan `tmp_path`

### Mall

```python
"""tests/test_<module>.py — Tester för <module>."""
import sys
from pathlib import Path
import pytest
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestMyFunction:
    """Testar <function> edge cases."""

    def test_happy_path(self):
        """Normalt flöde returnerar korrekt resultat."""
        from core.my_module import my_function
        result = my_function("input")
        assert result == "expected"

    def test_empty_input(self):
        """Tom input returnerar tom output utan krasch."""
        from core.my_module import my_function
        result = my_function("")
        assert result == ""
```

## Kör tester lokalt (komplett)

```bash
# Installation
pip install -r requirements.txt
pip install pytest pytest-cov pytest-xdist pytest-mock hypothesis

# Alla tester
pytest tests/ -v --tb=short -n auto --cov=core --cov-report=term-missing -m "not slow"

# Med HTML-rapport
pytest tests/ --cov=core --cov-report=html -m "not slow"
open htmlcov/index.html
```
