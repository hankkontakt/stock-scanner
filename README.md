# MarketScan — Quantitative Stock Scanner

En kvantitativ aktiescanner som rangordnar 800+ aktier baserat på akademiskt validerade faktorer och ger rekommendationer för portföljen.

**Designad för att fungera helt gratis** — yfinance + GitHub Actions + Streamlit Cloud + Gemini.

## Arkitektur

```
core/daily_pipeline.py        ← Central orchestrator (5 modes: morning/evening/weekly/smallcap/targeted)
core/scoring.py               ← 8-factor scoring engine (Value, Quality, Momentum, Growth, Risk, Size, Dividend, Sentiment)
core/data_fetcher.py          ← yfinance data fetching with caching/retry/timeout
core/macro_regime.py          ← Market regime detection (bull/bear/uncertain)
core/ai_analysis.py           ← AI analysis (DeepSeek + Gemini)
web/streamlit_app.py          ← Streamlit dashboard (20 pages)
```

## 8 faktorer

| Faktor | Vikt | Vad den mäter |
|---|---|---|
| **Value** | 22% | FCF Yield (primär), EV/EBITDA, fallback P/E/PB |
| **Quality** | 18% | ROE, marginaler, D/E |
| **Momentum** | 18% | 1/3/6/12m return, RSI, MA50/MA200 |
| **Growth** | 13% | Revenue/earnings growth |
| **Risk** | 9% | Beta, volatilitet, drawdown |
| **Sentiment** | 10% | Finnhub news sentiment, insider signals |
| **Size** | 5% | Small-cap premium |
| **Dividend** | 5% | Yield + payout ratio |

## Komma igång

```
pip install -r requirements.txt
cp .env.example .env    # Fyll i API-nycklar
streamlit run streamlit_app.py
```

Se `docs/KOMMANDON.md` för alla kommandon.
Se `docs/SYSTEM_AI.md` för full systemdokumentation.

## Datakällor

yfinance (gratis), Finnhub (60/min gratis), Finansinspektionen (gratis), FMP (250/dag gratis), DeepSeek/Gemini (<$5/mån)
