# MarketScan — Faktorjustering och Backtesting

> **Uppdaterad:** 2026-06-04 · Se `docs/SYSTEM_AI.md` för fullständig systemöversikt.

## Scoring-arkitektur

MarketScan rankar aktier på **8 faktorgrupper** + 3 tilläggsmoduler:

| Faktor | Källa | Komponent i koden |
|--------|-------|-------------------|
| **Value** | PE, PB, FCF-yield | `score_value`, `score_fcf_yield` |
| **Quality** | ROE, ROA, vinstmarginal | `score_quality` |
| **Momentum** | 1m/3m/6m/12m avkastning | `score_momentum` |
| **Growth** | Omsättningstillväxt, vinst | `score_growth` |
| **Risk** | Volatilitet, D/E | `score_risk` |
| **Size** | Market cap (small-cap boost) | `score_size` |
| **Dividend** | Utdelning + payout ratio | `score_dividend` |
| **Sentiment** | Insider-köp, short interest | `score_sentiment`, `score_short_interest` |
| **Options flow** | Put/call-ratio signal | `score_options_flow` |

## Faktorvikter

Grundvikterna definieras i `core/config.py`:

```python
FACTOR_WEIGHTS = {
    "value":       0.20,
    "quality":     0.15,
    "momentum":    0.20,
    "growth":      0.15,
    "risk":        0.10,
    "size":        0.05,
    "dividend":    0.05,
    "sentiment":   0.10,
}
```

**Regel:** Vikterna summerar alltid till 1.0. Testas automatiskt i `test_property_based.py`.

### Dynamisk viktjustering (regimfilter)

`scoring.py:get_dynamic_weights()` justerar vikter baserat på marknadsklimat:

| Regim | Logik | Effekt |
|-------|-------|--------|
| `TJUR` | VIX < 20, positiv trend | +momentum, +growth |
| `BJÖRN` | VIX > 30, negativ trend | +quality, +dividend |
| `OSÄKER` | Däremellan | Basvikter |

### Sektorjusteringar

`scoring.py:get_sector_weights()` justerar per sektor:

- **Financials**: +quality, -momentum (banker värderas annorlunda)
- **Energy**: +momentum, +sentiment (cyklisk)
- **Technology**: +growth, +momentum
- **Consumer Staples**: +dividend, +quality

## Justera faktorvikter

### Metod 1: Direkt i config.py

```python
# core/config.py
FACTOR_WEIGHTS = {
    "value":       0.25,   # Höjt från 0.20
    "quality":     0.20,   # Höjt från 0.15
    "momentum":    0.15,   # Sänkt från 0.20
    ...
}
```

⚠️ **Kräver**: Vikterna summerar till 1.0. Verifiera med:

```bash
python -c "from core.config import FACTOR_WEIGHTS; print(sum(FACTOR_WEIGHTS.values()))"
```

### Metod 2: Via Admin-UI

Admin → Konfiguration → Faktorvikter (om konfigurerat).

### Metod 3: scoring_config.json (dynamiskt)

`data/scoring_config.json` kan överskriva config.py-värdena utan kod-deploy:

```json
{
  "factor_weights": {
    "value": 0.25,
    "momentum": 0.15
  },
  "regime_thresholds": {
    "vix_bull": 20,
    "vix_bear": 30
  }
}
```

## Backtesting-metodologi

### Hur backtesting fungerar

`web/pages/backtesting_page.py` simulerar en momentum-strategi:

1. Ladda historiska scored_universe-filer
2. Välj top-N aktier varje vecka
3. Simulera köp/sälj baserat på signaler
4. Jämför avkastning mot OMXS30/S&P500

### Survivorship bias-varning

**Backtesting-resultaten lider av survivorship bias** — historiska scanfiler innehåller bara aktier som fortfarande handlas. Avlistade/konkursade bolag saknas, vilket överskattar strategins prestanda.

### Köra backtesting

```bash
# Via Streamlit-appen
# Navigera till "Backtesting" → välj period och parametrar

# Programmatiskt
python -c "
from web.pages.backtesting_page import run_backtest
results = run_backtest(start_date='2024-01-01', top_n=20)
print(results)
"
```

## Entry-signaler

`core/filters.py:get_entry_signal()` returnerar en av:

| Signal | Villkor |
|--------|---------|
| `STARK` | RSI 35-68 + under MA200 + score ≥ 70 |
| `OK` | RSI 35-68 + score ≥ 55 |
| `VÄNTA` | RSI saknas (ny notering) ELLER utanför 35-68 |
| `EJ AKTUELL` | Score < 40 |

**Regel:** Om RSI är `None` → returnera alltid `VÄNTA` (aldrig `STARK` utan teknisk bekräftelse).

## Sensitivitetsanalys

Testa hur känslig scoring är för faktorvikt-förändringar:

```python
from core.scoring import score_universe
from core import config
import pandas as pd

# Ladda testdata
df = pd.read_parquet("reports/scored_universe_2026-06-01.parquet")

# Baseline
baseline = score_universe(df)

# Sensitivity: öka momentum-vikt med 10%
config.FACTOR_WEIGHTS["momentum"] += 0.10
config.FACTOR_WEIGHTS["value"] -= 0.10

modified = score_universe(df)

# Jämför rankordning
rank_change = baseline["ticker"].reset_index(drop=True).compare(
    modified.sort_values("score_total", ascending=False)["ticker"].reset_index(drop=True)
)
print(f"Rank-förändringar: {len(rank_change)} aktier")
```

## ML-faktor (ml_rank)

`core/ml_predictor.py` tränar en XGBoost-ensemble som förutsäger 4-veckors avkastning.

**Features:** RSI, momentum, fundamental-ratios, volym, sector-dummies

**Träningsstrategi:** 80/20 tidsserie-split (äldsta 80% = träning, senaste 20% = validering)

**Träning:** Kör manuellt eller via GitHub Actions → "Train ML Models"

```bash
# Lokal träning
python -m scripts.train_ml --universe universe --sectors

# Eller via workflow
# GitHub → Actions → "Train ML Models" → "Run workflow"
```

**Varning:** ML-modellen är tränad på historisk data och kan inte förutsäga framtida avkastning. Använd som ett *kompletterande* filter, inte som enda beslutsunderlag.
