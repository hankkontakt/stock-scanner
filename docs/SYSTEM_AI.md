# MarketScan — Full System Architecture Reference for AI Agents

---

## 0. Underhållsprotokoll (LÄS FÖRST — gäller alla AI-modeller)

> 🔴 **DETTA DOKUMENT ÄR LEVANDE. DU MÅSTE HÅLLA DET UPPDATERAT.**

Om du är en AI-modell (Claude, Gemini, GPT, etc.) som läser, felsöker eller utvecklar
detta projekt gäller följande **obligatoriska regler**:

1. **Uppdatera detta dokument löpande** — inte bara i slutet av en uppgift. Så fort du:
   - ändrar kod (ny funktion, ändrad logik, ny fil, borttagen fil),
   - hittar en bugg (även en du inte hinner/ska fixa nu),
   - upptäcker en förbättringsmöjlighet, eller
   - ser något som *borde* ändras/läggas till
   → **skriv in det här direkt.**

2. **Även orelaterade fynd ska med.** Om du felsöker X och råkar se ett problem i Y —
   logga det i §16 (Known Weaknesses) eller §17 (Improvement Ideas) ändå. Tappa aldrig en
   observation bara för att den ligger utanför din nuvarande uppgift.

3. **Var ska det skrivas?**
   | Vad du upptäckte | Skriv i |
   |---|---|
   | Genomförd ändring (kod/arkitektur) | Relevant avsnitt (§3–§13) + en rad i §18 Ändringslogg |
   | Bugg eller risk (oavsett om den är fixad) | §16 Known Weaknesses & Technical Debt |
   | Idé/förbättring som inte är gjord | §17 Improvement Ideas |
   | Möjlig bugg du är osäker på | §16 med taggen `[MISSTÄNKT]` |

4. **Format på loggrader:** datum (YYYY-MM-DD) + kort beskrivning + fil(er). Håll det kort
   och konkret så nästa AI snabbt förstår.

5. **Om du fixar något som står i §16/§17** — markera det `DONE ✅` istället för att radera,
   så historiken bevaras.

6. **Commit-disciplin:** dokumentuppdateringen ska ingå i samma commit som kodändringen
   (eller en direkt uppföljande commit), aldrig glömmas bort.

> Syftet: vem som helst — människa eller AI — ska kunna öppna detta dokument och se hela
> systemets nuläge, kända problem och idéer, utan att läsa all kod eller all git-historik.

---

## Purpose

This document is a **complete technical reference** for AI coding assistants (Claude Code, Gemini, etc.) that need to understand, debug, and extend this project. It supersedes `SYSTEM_AI.md` (old structure reference) and `CLAUDE.md` (developer guide).

Every module, file, function, and data flow is documented so an AI can:
- Find the right file for any task in seconds
- Understand architecture decisions and trade-offs
- Debug failures by following the data flow
- Identify improvement opportunities

---

## 1. Project Overview

A fully automated **multi-factor quantitative stock scanner** covering ~1,000+ global tickers with a Swedish/nordic focus. Runs entirely on free/gratis data sources + GitHub Actions CI + Streamlit Cloud web UI.

**Stack:** Python 3.11+, yfinance, pandas, numpy, XGBoost, Streamlit, Flask, GitHub Actions, DeepSeek/Gemini AI

**Two repo copies exist on disk:**
- `stock-scanner-main/` — older version, less developed
- `stock-scanner-fix/` — **active version**, this document covers this one

### 1.1 Key design decisions

| Decision | Why | Where |
|---|---|---|
| File-based storage (JSON/CSV/Parquet) | Git-committed snapshots = full version history; Streamlit reads reports/ dir directly — no DB needed; CI commits automatically | All `data/` and `reports/` files |
| Percentile ranking within universe | Scores are relative (0-100), not absolute — a "top 20%" stock gets ~80 regardless of absolute P/E | `core/scoring.py` |
| Region-neutralized fundamentals | Nordic P/E 15 not ranked against Nasdaq tech P/E 35 | `core/scoring.py:_region_neutralize_fundamentals()` |
| yfinance primary data source | Free, covers global exchanges, but no SLA | `core/data_fetcher.py` |
| Multi-provider AI (DeepSeek + Gemini) | DeepSeek = daily driver, Gemini = free fallback | `core/ai_analysis.py` |
| Dual-format output (Parquet + CSV) | Parquet = fast reads (Streamlit), CSV = git-diffable | `core/daily_pipeline.py:_save_scored()` |
| Atomic writes | `.tmp.parquet` → `.rename()` prevents corruption | `core/daily_pipeline.py:88-109` |
| 3-layer timeout system | socket(7s) → requests patch(3/5s) → thread watchdog(12s) | `core/data_fetcher.py:44-107` |

---

## 2. Directory Structure

```
stock-scanner/
├── .github/workflows/          # CI/CD automation (7 workflows)
│   ├── daily_scan.yml          # Morning/evening/weekly/smallcap + refresh_missing
│   ├── smallcap_scan.yml       # Dedicated smallcap scan
│   ├── news_alerts.yml         # Every 30min Mon-Fri
│   ├── train_ml.yml            # ML model training
│   ├── tests.yml               # pytest on push
│   └── keep_alive.yml          # Streamlit Cloud keep-alive
├── core/                       # Central engine (27 files, ~500KB)
│   ├── config.py               # ALL thresholds, ticker universes, factor weights
│   ├── daily_pipeline.py       # Central orchestrator (HUVUDFIL — 81KB)
│   ├── scoring.py              # Factor scoring engine (30KB)
│   ├── data_fetcher.py         # yfinance data fetching + caching + timeout (45KB)
│   ├── data_fetcher_batch.py   # Batch-oriented data fetching (24KB)
│   ├── filters.py              # Entry/exit signals, strike system (23KB)
│   ├── macro_regime.py         # Market regime detection (11KB)
│   ├── ai_analysis.py          # AI engine — DeepSeek + Gemini (70KB)
│   ├── ai_prompts.py           # Prompt templates (5KB)
│   ├── news_fetcher.py         # Multi-source news aggregation (46KB)
│   ├── news_alerts.py          # AI-driven news alerts (15KB)
│   ├── email_template.py       # Shared email engine — mistune HTML (29KB)
│   ├── logger.py               # Structured JSON scan logging (9KB)
│   ├── pipeline_report.py      # Markdown report builder (7KB)
│   ├── pipeline_alerts.py      # STARK signal alert system (5KB)
│   ├── piotroski.py            # Piotroski F-Score (15KB)
│   ├── sector_momentum.py      # Sector ETF momentum (20KB)
│   ├── sectors.py              # Sector classification/ranking (4KB)
│   ├── sentiment.py            # Finnhub sentiment (17KB)
│   ├── relative_strength.py    # Relative strength calc (5KB)
│   ├── global_markets.py       # 17 global indices (9KB)
│   ├── country_flags.py        # Ticker-to-flag mapping (5KB)
│   ├── currency.py             # FX conversion (3KB)
│   ├── extra_data.py           # Finnhub extra data (24KB)
│   ├── fx_impact.py            # FX impact analysis (7KB)
│   ├── interest_rate.py        # Yield curve tracking (10KB)
│   ├── universe_health.py      # AI-driven universe maintenance (8KB)
│   ├── earnings_calendar.py    # Earnings tracking (6KB)
│   ├── dividend_calendar.py    # Dividend tracking (4KB)
│   ├── ml_predictor.py         # XGBoost model (30KB)
│   ├── ml_paper_trading.py     # ML paper trading (8KB)
│   ├── test_pipeline.py        # Quick integration test (4KB)
│   └── __init__.py             # Re-exports all modules
├── portfolio/                  # Portfolio management (6 files, ~100KB)
│   ├── paper_trading.py        # Paper trading simulation v2 (37KB)
│   ├── black_litterman.py      # Black-Litterman optimization (16KB)
│   ├── portfolio.py            # Holdings analysis (16KB)
│   ├── portfolio_analysis.py   # Correlation, concentration (16KB)
│   ├── positions.py            # Transaction logging (18KB)
│   └── watchlist.py            # Watchlist management (2KB)
├── web/                        # Web interfaces (~20 files, ~600KB)
│   ├── streamlit_app.py        # Main Streamlit dashboard (51KB)
│   ├── stock_detail.py         # Per-stock deep dive (47KB)
│   ├── utils.py                # Shared web helpers (34KB)
│   ├── app.py                  # Flask web server (22KB)
│   ├── templates/index.html    # Flask template (55KB)
│   └── pages/                  # 20 modular Streamlit pages
│       ├── overview.py         # Main overview page (23KB)
│       ├── weekly_scan.py      # Weekly scan results (27KB)
│       ├── smallcap.py         # Smallcap view (13KB)
│       ├── portfolio.py        # Portfolio management (92KB)
│       ├── technical.py        # Technical analysis (22KB)
│       ├── ai_page.py          # AI analysis page (48KB)
│       ├── ai_journal.py       # AI journal (8KB)
│       ├── admin.py            # Admin data services (79KB)
│       ├── admin_page.py       # Admin UI rendering (80KB)
│       ├── settings_page.py    # User settings (7KB)
│       ├── guide.py            # User guide (22KB)
│       ├── alerts.py           # Alerts & notices (42KB)
│       ├── backtesting_page.py # Backtesting UI (17KB)
│       ├── sector_rotation.py  # Sector rotation UI (14KB)
│       ├── global_markets.py   # Global markets view (8KB)
│       ├── paper_trading_page.py # Paper trading UI (22KB)
│       ├── ml_paper_trading.py # ML paper trading UI (6KB)
│       ├── stock_search.py     # Stock search view (18KB)
│       ├── watchlist_detail.py # Watchlist detail (8KB)
│       └── opportunities.py    # Opportunities view (9KB)
├── smallcap/                   # Swedish small-cap subsystem
│   ├── scanner.py              # Main entry point (19KB)
│   ├── universe.py             # ~280 Swedish small-cap tickers (37KB)
│   ├── scoring.py              # Smallcap-specific scoring (15KB)
│   ├── filters.py              # Smallcap hard filters (12KB)
│   ├── report.py               # Smallcap report builder (26KB)
│   ├── insider.py              # Swedish insider data (12KB)
│   └── history.py              # Score history tracking (2KB)
├── backtesting/                # Backtesting & optimization
│   ├── backtest.py             # Historical backtest engine (28KB)
│   ├── walk_forward.py         # Walk-forward validation (12KB)
│   └── factor_optimizer.py     # Bayesian factor weight opt (18KB)
├── data_management/            # Data import & tracking
│   ├── avanza_import.py        # Avanza CSV import (34KB)
│   └── delta_tracker.py        # Score change tracking (11KB)
├── scripts/                    # Utility scripts
│   ├── build_ml_dataset.py     # ML feature engineering (6KB)
│   ├── train_ml.py             # ML training (2KB)
│   ├── replace_stock_search.py # Ticker search (12KB)
│   └── write_readme.py         # Auto-generate README (1KB)
├── tools/                      # Independent tools
│   └── ticker_health.py        # Ticker validation (10KB)
├── reporting/                  # Report generation
│   └── report_builder.py       # Markdown helper (14KB)
├── tests/                      # Test suite
│   ├── test_scoring.py         # 56 scoring tests (NEW)
│   ├── test_config.py          # Config integrity tests
│   ├── test_data_fetcher.py    # RSI calculation tests
│   ├── test_filters.py         # Strike system tests
│   ├── test_logger.py          # Logger tests
│   ├── test_ml_paper_trading.py # ML paper trading tests
│   ├── test_ml_predictor.py    # ML predictor tests
│   └── conftest.py             # PYTHONPATH fixture
├── data/                       # Runtime data (git-committed)
│   ├── blacklist.json          # Permanently removed tickers
│   ├── strike_list.json        # Tickers on warning
│   ├── scan_log.json           # Pipeline execution log
│   ├── custom_universe.json    # User-added tickers
│   ├── email_subscribers.json  # Email subscriber list
│   ├── paper_trades.json       # Paper trading positions
│   ├── paper_portfolio.json    # Paper trading P&L
│   ├── portfolio_performance.json # Portfolio perf history
│   ├── ml_paper_universe.json  # ML paper trades (universe)
│   ├── ml_paper_smallcap.json  # ML paper trades (smallcap)
│   ├── holdings.csv            # User portfolio holdings
│   ├── ticker_map.json         # Avanza→Yahoo ticker mapping
│   ├── users_config.json       # Multi-user config
│   ├── ai_cache/               # AI analysis cache
│   └── piotroski_snapshots/    # Historical F-Score data
├── reports/                    # Generated scan reports
│   ├── scored_universe_*.parquet/.csv  # Daily/weekly scans
│   ├── smallcap_scored_*.parquet/.csv  # Smallcap scans
│   └── *.md                    # Markdown reports
├── models/                     # Trained ML models
│   ├── ml_universe.pkl         # XGBoost model (universe)
│   ├── ml_smallcap.pkl         # XGBoost model (smallcap)
│   ├── ml_universe_metrics.json  # Model metrics
│   └── ml_smallcap_metrics.json
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Project config + ruff/mypy/pytest
├── CLAUDE.md                   # AI developer guide (short)
├── SYSTEM_AI.md                # THIS FILE — architecture reference
├── KOMMANDON.md                # User command reference
└── README.md                   # User-facing readme
```

---

## 3. Scoring Engine — Detailed Reference

### 3.1 The 8 Factors

| # | Factor | Weight | Key Inputs | Function | Lower Is Better? |
|---|---|---|---|---|---|
| 1 | **Value** | 22% | FCF Yield (70%), EV/EBITDA (30%), fallback P/E→P/B→P/S | `calc_value_score()` | Yes (P/E/PB) |
| 2 | **Quality** | 18% | ROE, ROA, profit margin, operating margin, gross margin | `calc_quality_score()` | No |
| 3 | **Momentum** | 18% | return_12m, return_6m, return_3m, pct_from_52w_high | `calc_momentum_score()` | No |
| 4 | **Growth** | 13% | revenue_growth, earnings_growth, earnings_quarterly_growth | `calc_growth_score()` | No |
| 5 | **Risk** | 9% | D/E (inverted), current_ratio, volatility (inv), beta (inv) | `calc_risk_score()` | Yes (volatility) |
| 6 | **Size** | 5% | market_cap (log, inverted) | `calc_size_score()` | Yes (smaller=better) |
| 7 | **Dividend** | 5% | dividend_yield (capped 15%), payout_ratio penalty | `calc_dividend_score()` | No |
| 8 | **Sentiment** | 10% | sentiment_raw, insider_executive_buy (+20), insider_cluster (+30) | `calc_sentiment_score()` | No |

### 3.2 Scoring pipeline

```
score_universe(df, regime)        # Main entry point — core/scoring.py:709
  │
  ├─ _region_neutralize_fundamentals(df)   # Subtrahera regionmedian
  │                                         # P/E, ROE, margins adjusted per region
  │                                         # Momentum INTENTIONALLY global
  │
  ├─ calc_value_score(df)          → score_value      0-100
  ├─ calc_quality_score(df)        → score_quality    0-100
  ├─ calc_momentum_score(df)       → score_momentum   0-100
  ├─ calc_growth_score(df)         → score_growth     0-100
  ├─ calc_risk_score(df)           → score_risk       0-100
  ├─ calc_size_score(df)           → score_size       0-100
  ├─ calc_dividend_score(df)       → score_dividend   0-100
  └─ calc_sentiment_score(df)      → score_sentiment  0-100 (incl insider boost)
  │
  ├─ get_dynamic_weights(regime, FACTOR_WEIGHTS)
  ├─ Weighted average → score_total
  ├─ Holding discount (×0.85) / Commodity discount (×0.90)
  ├─ rank column (1=best)
  ├─ data_quality column (% filled)
  └─ low_liquidity flag (daily turnover < $50k)
```

### 3.3 Region grouping

Exchange suffixes determine region:
- `.ST` → Nordic, `.CO` → Nordic, `.OL` → Nordic, `.HE` → Nordic
- `.L` → UK
- `.DE`, `.PA`, `.AS`, `.MI`, `.MC`, `.VI`, `.WA`, `.LS`, `.SW` → Europe
- `.TO` → Canada
- `.AX` → Australia
- `.T` → Japan
- `.HK`, `.TW`, `.KS` → Asia
- `.NS`, `.BO` → India
- `.SA`, `.MX` → LatAm
- `.SI` → Singapore
- No suffix → US

### 3.4 Key constants

| Constant | Value | Location |
|---|---|---|
| `MIN_VALID_OBSERVATIONS` | 5 | `core/scoring.py:32` |
| `NEUTRAL_SCORE` | 50.0 | `core/scoring.py:33` |
| `MAX_DIVIDEND_YIELD` | 0.15 (15%) | `core/scoring.py:34` |
| `UNSUSTAINABLE_PAYOUT` | 1.0 | `core/scoring.py:35` |
| `HOLDING_DISCOUNT` | 0.85 | `core/scoring.py:36` |
| `COMMODITY_DISCOUNT` | 0.90 | `core/scoring.py:37` |
| `MIN_DAILY_TURNOVER_USD` | 50,000 | `core/scoring.py:44` |

### 3.5 Dynamic weights (regime-based)

| Regime | Momentum | Growth | Risk | Quality | Value |
|---|---|---|---|---|---|
| TJUR | +5% | +5% | -5% | — | -5% |
| BJÖRN | -20% | -15% | +10% | +15% | +10% |
| OSÄKER | — | — | — | — | — |

---

## 4. Data Pipeline — Entry Points

### 4.1 Pipeline modes (`core/daily_pipeline.py:run_pipeline()`)

```
run_pipeline(mode)         # 790 lines, the heart of the system
  │
  ├─ mode="morning"        # Daily 07:35 UTC — global markets, portfolio, top picks
  ├─ mode="evening"        # Daily 15:30 UTC — day's P&L, opportunities
  ├─ mode="weekly"         # Saturday 09:00 UTC — full universe re-fetch + rescore
  ├─ mode="smallcap"       # Monday 08:15 UTC — smallcap specific
  ├─ mode="targeted"       # Refresh specific tickers (used for missing data)
  └─ mode="refresh_missing" # Find+refresh tickers with missing data
```

### 4.2 Pipeline flow (all modes)

```
1. Fetch global indices → core/global_markets.py
2. Load or fetch scored universe:
   morning/evening: load latest cached → re-fetch prices (up to 100 tickers)
   weekly: full fetch_universe_data() → score_universe() → filters
   smallcap: smallcap-specific flow (separate universe/scoring)
3. Macro regime detection → core/macro_regime.py
4. Region-neutralized scoring → core/scoring.py
5. Piotroski F-Score → core/piotroski.py
6. Entry/trend/confidence signals → core/filters.py
7. ML prediction → core/ml_predictor.py (if model exists)
8. ML paper trading → core/ml_paper_trading.py
9. Classic paper trading → portfolio/paper_trading.py
10. Portfolio enrichment → _enrich_holdings()
11. Score delta tracking → _get_score_deltas()
12. Opportunity detection → _get_opportunities()
13. Report generation → core/pipeline_report.py
14. AI analysis with news context → core/ai_analysis.py
15. Save + email → _save_scored() + core/email_template.py
```

### 4.3 GitHub Actions triggers

| Workflow | Cron (UTC) | Mode | Timeout |
|---|---|---|---|
| `daily_scan.yml` | 07:00 Mon-Fri | morning | 30 min |
| `daily_scan.yml` | 15:30 Mon-Fri | evening | 30 min |
| `daily_scan.yml` | 09:00 Sat | weekly | 30 min |
| `daily_scan.yml` | 08:15 Mon | smallcap | 30 min |
| `daily_scan.yml` | 08:00,15:00 Mon-Fri | refresh_missing | 30 min |
| `news_alerts.yml` | Every 30 min Mon-Fri 08:00-21:00 | news alerts | 10 min |
| `train_ml.yml` | On demand | ML training | — |
| `keep_alive.yml` | Every 20 min | Keep Streamlit awake | — |

---

## 5. Data Fetching — Detailed Reference

### 5.1 yfinance data fetch

`core/data_fetcher.py:fetch_universe_data(tickers)` is the main function.

**Two-pass retry strategy:**
1. Pass 1: Fetch all tickers with ThreadPoolExecutor (8 workers)
2. Collect 429-rate-limited tickers
3. Pass 2: Retry with longer delays

**Caching:**
- Static fundamentals (longName, sector, ROE, etc.): 720 hours (30 days)
- Dynamic fundamentals (P/E, analysts): 48 hours
- Price history: 24 hours
- Insider signals: 24 hours
- FMP key-metrics: 720 hours

**Timeouts (3-layer):**
1. `socket.setdefaulttimeout(7)` — catches C-level socket hangs
2. `requests.Session.send` patch — forces (3, 5) second (connect, read) timeout
3. `_with_timeout(fn, 12)` — threading.Event watchdog in data_fetcher

**Strike system** (core/filters.py):
- Failed fetch → strike counted (max 1 per day)
- 3 strikes → auto-blacklisted
- NEVER_BLACKLIST list protects critical tickers (SPY, OMX, etc.)
- Blacklisted tickers are skipped in all future fetches

### 5.2 Data fields extracted

`extract_metrics()` in `core/data_fetcher.py` returns a dict with:
- **Pricing:** currentPrice, previousClose, averageVolume
- **Fundamentals:** trailingPE, forwardPE, priceToBook, enterpriseValue, debtToEquity, returnOnEquity, profitMargins, revenueGrowth, freeCashflow, etc.
- **Computed:** return_1m/3m/6m/12m, rsi_14, price_vs_ma50/ma200, volatility, macd_above_signal, bb_position, volume_ratio

### 5.3 FMP fallback

`_get_fmp_fundamentals(ticker)` — Financial Modeling Prep free tier (250 calls/day).
Fills: trailingPE, priceToBook, returnOnEquity, returnOnAssets, enterpriseValueToEbitda, revenueGrowth

### 5.4 Insider data (Finansinspektionen)

`core/fi_insider_fetcher.py:get_insider_signal_fi(ticker)`
- Scrapes `marknadssok.fi.se` (HTML search → JSON XHR fallback)
- Returns: `insider_cluster` (≥3 insiders in 30d), `insider_executive_buy` (VD/CFO köp)
- Stores historical trade patterns in cache for routine vs. opportunistic classification
- 24h cache, browser-emulation headers required (FI blocks bare requests)

---

## 6. AI Analysis — Detailed Reference

### 6.1 Providers

| Provider | Model | Cost | When used |
|---|---|---|---|
| DeepSeek | deepseek-chat | ~$3/mo | Default for all analysis |
| Gemini | gemini-2.5-flash | Free | Fallback when DeepSeek fails; light tasks if `AI_TASK_MODE=hybrid` |

### 6.2 Depth levels

| Depth | max_tokens | Data sent | Cost |
|---|---|---|---|
| Snabb | 512 | 6 key fields only (P/E, ROE, Momentum, Revenue Growth, Piotroski, Entry) | Low |
| Normal | 2048 | All standard fields | Medium |
| Djup | 4096 | All + FCF Yield, EV/EBITDA, BB, returns | Medium-high |
| Extra djup | 8192 | Everything | High |

### 6.3 AI functions

- `analyze_stock(ticker, df, depth)` — per-stock analysis
- `analyze_portfolio(holdings, scored, depth)` — portfolio analysis
- `analyze_sector(sector, df, depth)` — sector analysis
- `analyze_news(ticker, headline, context)` — news evaluation
- `compare_stocks(ticker_a, ticker_b, df)` — side-by-side comparison
- `generate_market_summary(indices)` — market narrative
- `generate_morning_brief(df, news, holdings, watchlist, ...)` — morning AI report
- `generate_weekly_ai_analysis(df, news, regime, ...)` — weekly AI report
- `generate_news_alert_analysis(ticker, headlines, portfolio)` — news alert evaluation
- `generate_vad_stack_ut_analys(df, date_str)` — daily standout analysis

### 6.4 Caching

- Content-addressed: MD5 hash of (prompt + data + depth) = cache key
- Cache lives in `data/ai_cache/` as `.md` files
- News context is injected into AI prompts via `_add_news()` helper

---

## 7. ML Model — Detailed Reference

### 7.1 Model architecture

- **Algorithm:** XGBoost regressor (fallback: sklearn HistGradientBoostingRegressor)
- **Target:** 30-calendar-day forward return
- **Features (15 technical, point-in-time safe):**
  - `ret_1m, ret_3m, ret_6m, ret_12m` — past returns
  - `rsi_14` — relative strength index
  - `macd_signal` — 12/26/9 EMA crossover (bool)
  - `vs_ma50, vs_ma200` — price vs moving averages
  - `volume_ratio` — volume vs 20-day average
  - `volatility` — annualized std dev of daily returns
  - `bb_position` — Bollinger Band position (0-1)
  - `price_vs_52w_high` — distance from 52-week high
  - `momentum_3m_rank, momentum_6m_rank` — momentum percentile ranks
  - `pct_from_52w_high` — percentage from 52w high
- **Two models:** `ml_universe.pkl` (global) + `ml_smallcap.pkl` (Swedish small-caps)
- **Training:** `train_with_cpcv()` — Combinatorial Purged Cross-Validation, 6 folds, purge=30 days, embargo=1%
- **Metrics tracked:** IC (information coefficient), hit rate, MAE
- **Fundamentals excluded:** Point-in-time reconstruction impossible without look-ahead bias

### 7.2 ML paper trading

`core/ml_paper_trading.py:record_daily_signals()`
- Records top-10 ML picks as virtual trades each day
- Tracks ATR-based stop-losses, 30-day max holding
- Separate tracking for universe vs. smallcap models
- Outputs `data/ml_paper_universe.json` and `data/ml_paper_smallcap.json`

### 7.3 Black-Litterman integration

`portfolio/black_litterman.py` — blends ML predictions with market-cap prior:
- Prior: Market-cap weighted equilibrium returns via reverse optimization
- Views: score_total → expected returns (±5% cap)
- Confidence: Historical IC from model metrics
- Covariance: Ledoit-Wolf shrinkage
- Constraints: Long-only, max 15% per position

---

## 8. Paper Trading — Detailed Reference

### 8.1 Parameters

| Parameter | Default | Description |
|---|---|---|
| STOP_LOSS_PCT | -10.0% | Sell if position drops X% |
| TAKE_PROFIT_PCT | +25.0% | Sell all at X% gain |
| PARTIAL_PROFIT_PCT | +12.0% | Sell 50% at X% gain |
| TRAILING_ACTIVATE | +8.0% | Activate trailing at X% gain |
| TRAILING_DISTANCE | 8.0% | Trail stop X% below peak |
| DCA_TRIGGER | -8.0% | Buy more if price drops X% |
| MAX_DCA_PER_TICKER | 2 | Max DCA rounds |
| CLOSE_AFTER_WEEKS | 8 | Max hold time |
| DEFAULT_CAPITAL | 100,000 SEK | Weekly allocation |

### 8.2 Output files

- `data/paper_trades.json` — all simulated positions
- `data/paper_portfolio.json` — accumulated P&L per week

### 8.3 CLI commands

```
python portfolio/paper_trading.py status     # Current portfolio + P&L
python portfolio/paper_trading.py update     # Update prices, check stops
python portfolio/paper_trading.py report     # Detailed report
python portfolio/paper_trading.py close_all  # Close all positions
```

---

## 9. Streamlit Dashboard — Page Reference

All pages are in `web/pages/` and imported by `web/streamlit_app.py`. Each page is a function `page_<name>()` that renders via `st.xxx` calls.

### 9.1 Page list

| # | Page | File | Key features |
|---|---|---|---|
| 1 | 📊 Översikt | `web/pages/overview.py` | Global indices, macro regime, portfolio snapshot, top/bottom stocks |
| 2 | 📚 Guide & Hjälp | `web/pages/guide.py` | User documentation |
| 3 | 🔍 Veckoscanner | `web/pages/weekly_scan.py` | Full universe ranking, filters, sorting |
| 4 | 🏦 Småbolag | `web/pages/smallcap.py` | Smallcap ranking with scoring breakdown |
| 5 | 🔍 Aktie-sök | Shared | Ticker search → stock_detail.py |
| 6 | ⭐ Bevakningar | `web/pages/watchlist_detail.py` | Watchlist management |
| 7 | 🌍 Globala marknader | `web/pages/global_markets.py` | 17 indices, FX, yield curves |
| 8 | 🏭 Sektorrotation | `web/pages/sector_rotation.py` | Sector heatmap + AI analysis |
| 9 | 📈 Backtesting | `web/pages/backtesting_page.py` | Backtest engine + equity curve |
| 10 | 💼 Portfölj | `web/pages/portfolio.py` | **92KB** — largest page: holdings, P&L, charts, correlation, calendar |
| 11 | 📄 Paper Trading | `web/pages/paper_trading_page.py` | Equity curve, KPIs, statistics |
| 12 | 🤖 AI Paper Trading | `web/pages/ml_paper_trading.py` | ML-specific paper trading |
| 13 | 🚨 Larm & Notiser | `web/pages/alerts.py` | Stop-loss, news alerts, AI analysis |
| 14 | ⚙️ Inställningar | `web/pages/settings_page.py` | Email subscriptions |
| 15 | 📈 Teknisk analys | `web/pages/technical.py` | Technical charting |
| 16 | 🤖 AI | `web/pages/ai_page.py` | **48KB** — AI chat, analysis |
| 17 | 📓 AI Journal | `web/pages/ai_journal.py` | AI analysis history |
| 18 | 🔧 Admin | `web/pages/admin_page.py` + `admin.py` | **159KB total** — portfolio management, universe health, user config, cache, AI log, alarms, **debug** |

### 9.2 Data loading pattern

All pages load data via `web/utils.py`:
- `load_scan_reports()` — cached 300s, returns `{date: DataFrame}` for weekly scans
- `load_smallcap_reports()` — same for smallcap
- `load_portfolio()` — reads `holdings.csv`
- `load_watchlist()` — reads `watchlist.json`

### 9.3 Stock detail page

`web/stock_detail.py:render_stock_detail(ticker, df)` provides:
- Quick data cards (7 KPIs with tooltips)
- Interactive Plotly candlestick chart (period selector, MA50/MA200)
- Radar chart of 8-factor profile
- Detail data in 5 tabs (Värdering, Kvalitet, Momentum, Tillväxt, Sentiment)
- AI analysis with depth selector + live news context
- Custom AI chat with news injection
- Multi-source news section

---

## 10. Smallcap Subsystem

### 10.1 Entry point

`smallcap/scanner.py:main()`

```
python -m smallcap.scanner --market all --top 20 --profiles 5
```

### 10.2 Universe

`smallcap/universe.py` — ~280 Swedish small/micro-cap tickers:
- First North: ~70 tickers
- Nasdaq Stockholm Small Cap: ~120 tickers
- Spotlight Stock Market: ~50 tickers
- Nordic SME (other): ~40 tickers

### 10.3 Scoring weights (different from main universe)

| Factor | Weight |
|---|---|
| Insider (ownership + transactions) | 18% |
| FCF yield | 16% |
| Piotroski F-Score | 15% |
| Revenue growth | 13% |
| Balance sheet (D/E + current_ratio) | 12% |
| Valuation (EV/EBITDA or P/B) | 12% |
| Momentum (relative strength 6-12m) | 9% |
| Liquidity (daily turnover) | 5% |

### 10.4 Hard filters (smallcap-specific)

Eliminate: cash runway < 12 months, Piotroski ≤ 2, share dilution > 20%/year, D/E > 300%, current_ratio < 0.5

### 10.5 Cash runway watch

`smallcap/cash_runway_watch.py` — identifies companies at risk of running out of cash within 12 months (cash_and_equivalents / (negative_operating_cashflow) < 12 months)

---

## 11. Email System

### 11.1 Architecture

`core/email_template.py` — mistune 3.x markdown→HTML, responsive inline CSS, plain-text fallback.

### 11.2 Email types

| Type | Subject | Frequency | Subscription key |
|---|---|---|---|
| Morning report | 🌅 MarketScan Morgonbrief | Daily | `morning_report` |
| Evening report | 🌆 MarketScan Kvällsbrev | Daily | `evening_report` |
| Weekly summary | 📊 MarketScan Veckorapport | Weekly | `weekly_summary` |
| Smallcap report | 🏦 MarketScan Småbolag | Weekly | `smallcap_report` |
| STARK alerts | ⚡ STARK-signaler | On signal | `stark_alerts` |
| Portfolio alerts | 💼 Portföljlarm | On event | `portfolio_alerts` |
| Failure alerts | 🚨 Pipeline-fel | On failure | `failure_alerts` |

### 11.3 Subscriber management

- `data/email_subscribers.json` stores per-user subscription preferences (per email type)
- Admin UI in Streamlit (`web/pages/settings_page.py`)
- GitHub-commit via Contents API for Streamlit Cloud persistence
- List-Unsubscribe header for spam compliance

### 11.4 News alerts

`core/news_alerts.py:check_alerts(debug=False)` — runs every 30 min:
- Checks portfolio + watchlist + top-10 for:
  - News via Finnhub (today's date)
  - Price moves >5% via yfinance
- AI evaluates each alert (relevance + explanation in Swedish)
- Batched email with AI analysis per event
- Keyword fallback when AI fails (vinstvarning, konkurs, fusion, FDA, etc.)

---

## 12. Configuration Reference

All in `core/config.py` (~350 lines ticker lists + ~100 lines constants):

### 12.1 Ticker universes (UNIVERSE = combined list)

| Variable | Count | Description |
|---|---|---|
| `US_LARGE_CAP` | ~400 | US NYSE/NASDAQ |
| `UK` | ~60 | London Stock Exchange |
| `GERMANY` | ~80 | Xetra/Frankfurt |
| `NORDIC` | ~60 | Denmark, Norway, Finland |
| `OMX_SE` | ~80 | Sweden OMX Stockholm |
| `EUROPE` | ~180 | Broader Europe |
| `ASIA_PACIFIC` | ~200 | Japan, Taiwan, Korea, HK, India, Australia, Singapore |
| `CANADA` | ~50 | TSX |
| `BRAZIL` | ~50 | B3 + LatAm ADRs |

### 12.2 Key config variables

| Variable | Default | Description |
|---|---|---|
| `FACTOR_WEIGHTS` | see §3.1 | 8 factor weights (sum=1.0) |
| `TOP_N_RECOMMENDATIONS` | 20 | Top-N list size |
| `PARALLEL_WORKERS` | 8 | Fetch concurrency |
| `FINNHUB_PARALLEL_WORKERS` | 3 | Finnhub concurrency |
| `FINNHUB_CALLS_PER_MINUTE` | 30 | Finnhub rate limit |
| `CACHE_HOURS` | 720 | Static fundamentals cache |
| `PRICE_CACHE_HOURS` | 24 | Price cache |
| `MIN_DATA_QUALITY` | 0.3 | Minimum data quality threshold |
| `SITE_PASSWORD` | env|secret | Streamlit access password |
| `ADMIN_PASSWORD` | env|secret | Admin page password |
| `AI_PROVIDER` | "deepseek" | Primary AI provider |
| `AI_TEMPERATURE` | 0.3 | AI temperature |

### 12.3 Smallcap config

`SMALLCAP_CONFIG` dict contains:
- `scoring_weights` — 8-factor weights (must sum to 1.0, enforced by test)
- `hard_filters` — cash_runway, piotroski, dilution, D/E, current_ratio thresholds
- `top_n` — default 20
- `min_price` — 1 SEK
- `min_market_cap` — 30 MSEK
- `min_daily_turnover` — 500,000 SEK

---

## 13. Data Files — Complete Reference

### 13.1 Git-committed (survive Streamlit restarts)

| File | Format | Content | Updated by |
|---|---|---|---|
| `reports/scored_universe_YYYY-MM-DD.parquet` | Parquet (zstd) | Full scored universe snapshot | CI pipeline commit |
| `reports/scored_universe_YYYY-MM-DD.csv` | CSV | Same as above (backup) | CI pipeline commit |
| `reports/smallcap_scored_YYYY-MM-DD.parquet` | Parquet | Smallcap scores | CI pipeline commit |
| `reports/smallcap_scored_YYYY-MM-DD.csv` | CSV | Same (backup) | CI pipeline commit |
| `reports/*.md` | Markdown | AI-generated reports | CI pipeline commit |
| `data/blacklist.json` | JSON | Permanently removed tickers | CI pipeline + manual |
| `data/strike_list.json` | JSON | Ticker strike counters | CI pipeline |
| `data/scan_log.json` | JSON | Pipeline execution log | CI pipeline |
| `data/custom_universe.json` | JSON | User-added tickers | Admin UI + CI |
| `data/email_subscribers.json` | JSON | Email subscription list | Settings UI + CI |
| `data/holdings.csv` | CSV | Portfolio holdings | Portfolio UI + CI |
| `data/users_config.json` | JSON | Multi-user passwords | Admin UI + CI |
| `data/paper_trades.json` | JSON | Paper trading positions | Pipeline + manual |
| `data/paper_portfolio.json` | JSON | Paper trading P&L | Pipeline + manual |
| `models/ml_universe.pkl` | Pickle | Trained XGBoost model | CI train workflow |
| `models/ml_smallcap.pkl` | Pickle | Trained XGBoost model | CI train workflow |
| `models/ml_*_metrics.json` | JSON | Model performance metrics | CI train workflow |

### 13.2 Git-ignored (data/cache/ — generated at runtime)

| Pattern | Content | Cache duration |
|---|---|---|
| `data/cache/*.pkl` | yfinance cached responses | 24-720h per type |
| `data/ai_cache/ai_*.md` | Cached AI analysis | Content-addressed |
| `data/piotroski_snapshots/*.json` | Historical F-Score data | 365 days |
| `data/history/snapshot_*.csv` | Score history snapshots | — |

### 13.3 Retention policy

- Reports >14 days deleted by CI (`daily_scan.yml` step "Rensa gamla rapporter")
- Markdown reports >7 days deleted
- `_cleanup_old_reports(max_days=60)` in pipeline also cleans
- `scan_log.json` truncated to 90 entries in `logger.py`
- Cache stale cleanup in `logger.clear_stale_cache(max_age_hours=48)`

---

## 14. Tests — Complete Reference

### 14.1 Test files

| File | Tests | What it covers | CI |
|---|---|---|---|
| `tests/test_scoring.py` | **56 tests** | ALL 8 factor scores, helpers, region-neutralization, holding/commodity discounts, full pipeline | ✅ |
| `tests/test_config.py` | 9 tests | Universe integrity, factor weights sum to 1.0, smallcap weights, API keys defined | ✅ |
| `tests/test_data_fetcher.py` | 5 tests | RSI calculation (flat, gains, losses, too few, mixed) | ✅ |
| `tests/test_filters.py` | 3 tests | Strike idempotency (same day), strike increment (new day), never_blacklist protection | ✅ |
| `tests/test_logger.py` | 8 tests | Log events, context manager, consecutive failures, cache cleanup, auto-remediation | ✅ |
| `tests/test_ml_paper_trading.py` | 5 tests | Signal recording, idempotency, summary, open positions, universe separation | ✅ |
| `tests/test_ml_predictor.py` | 5 tests | Feature computation, short series, RSI neutral, trending, load/predict | ✅ |

**Note:** scoring.py had ZERO tests before this document was created (56 tests were added).

### 14.2 Test patterns

- All tests use **synthetic data** — no API calls, no filesystem (except tmp_path)
- Config tests use static imports
- Scoring tests use `_FactorTestHelper._make_base()` for consistent test data
- Filter/logger tests use `tmp_path` + `monkeypatch` for isolation
- Runs in CI via `pytest tests/ -v --tb=short` (`.github/workflows/tests.yml`)

---

## 15. Debugging & Monitoring

### 15.1 What exists

| Feature | Location | Description |
|---|---|---|
| Pipeline log | `data/scan_log.json` | Every run: type, status, OK/ERROR, elapsed, error msg |
| Auto-remediation | `core/logger.py:auto_remediate()` | Cache cleanup on 429, corrupted JSON fix, pickle errors |
| Failure email | `core/email_template.py:send_failure_alert()` | Sent by CI when pipeline fails |
| Strike system | `core/filters.py:update_ticker_health()` | Auto-blacklist tickers after 3 failed fetches |
| Diagnose failure | `core/filters.py:diagnose_failure()` | Per-ticker failure analysis |
| Debug flag | `core/news_alerts.py` | `--debug` flag for dry-run |
| Debug page | `web/pages/admin_page.py:_render_debug_tab()` | **NEW** — admin-only debug dashboard |
| API key check | Debug page | Red/green per API key |
| Data coverage | Debug page | % coverage per factor |
| Pipeline status | Debug page | Last run status, error history |
| Blacklist | Debug page + data/blacklist.json | All blacklisted tickers |
| Strikes | Debug page + data/strike_list.json | Tickers on warning |
| FAQ | Debug page | 6 common errors with solutions |

### 15.2 What's missing (improvement ideas)

- **Log persistence:** Logger only writes to `data/scan_log.json` — no per-run log files
- **No alerting for data stale**: No warning when cache data is near expiry
- **No scoring drift monitoring**: Scores change silently between runs
- **CI logs not accessible from Streamlit**: Must go to GitHub Actions web UI

---

## 16. Known Weaknesses & Technical Debt

### 16.1 Code quality

| Issue | Severity | Location | Notes |
|---|---|---|---|
| `daily_pipeline.py` 81KB | MEDIUM | `core/daily_pipeline.py` | Does data loading, scoring, reporting, email — but already partially split into pipeline_report.py + pipeline_alerts.py |
| `admin_page.py` 80KB + `admin.py` 79KB | MEDIUM | `web/pages/` | Tab-based single-page pattern, hard to navigate |
| `portfolio.py` page 92KB | LOW | `web/pages/portfolio.py` | Single largest Streamlit page, but logically cohesive |
| `config.py` 26KB | LOW | `core/config.py` | Mostly ticker lists, few constants |
| `streamlit_app.py` 51KB | LOW | `web/streamlit_app.py` | 51KB with sidebar logic + page routing |
| `ai_analysis.py` 70KB | LOW | `core/ai_analysis.py` | Many functions but each is well-isolated |
| `data_fetcher.py` 45KB | LOW | `core/data_fetcher.py` | Dense but logically structured |

### 16.2 Functional gaps

| Gap | Impact | Notes |
|---|---|---|
| No SQL database | MEDIUM | All file-based — no query, no concurrent access, no history |
| No notification when a trigger score changes dramatically | MEDIUM | Score deltas tracked but no push notification |
| No deduplication of scoring code | LOW | `score_universe_sector_neutralized()` duplicates `score_universe()` logic |
| No comprehensive integration test | MEDIUM | Pipeline end-to-end not testable without API keys |
| Manual ticker universe maintenance | LOW | Now in `data/universe.json` (editable via admin), still hand-curated |
| Point-in-time reconstruction impossible | MEDIUM | Backtesting has look-ahead bias risk |
| No metrics scraping | LOW | No Grafana/Prometheus for pipeline health |
| ~~Nordic holdings get no news alerts~~ | DONE ✅ | Fixed 2026-05-31 — `news_alerts` faller tillbaka till `fetch_company_news()` |
| ~~Email exposes all recipients in To:~~ | DONE ✅ | Fixed 2026-05-31 — BCC via envelope |

### 16.4 Misstänkta / overifierade problem (`[MISSTÄNKT]` — verifiera innan fix)

| Observation | Impact | Var | Status |
|---|---|---|---|
| `[MISSTÄNKT]` news_alerts scrapar Google/DDG/Nasdaq per nordisk ticker var 30:e min | LOW-MED | `core/news_fetcher.py` | Dedup minskar mail-spam men inte web-anropen. Överväg cache på fetch_company_news-resultatet om rate-limiting blir problem. |
| `[MISSTÄNKT]` Delistade tickers (MAN.DE, VATTENFALL.ST, NYFOSA.ST m.fl.) retryas varje scan tills 3-strike-blacklist | LOW | `data/universe.json` + `core/filters.py` | Blacklist persisteras nu (fixat) → självläker över ~3 körningar. Kan snabbas upp genom att rensa dem ur universe.json. |
| `[MISSTÄNKT]` "LÄNSFÖRSÄKRINGAR GLOBAL INDEX" som ticker i watchlist/custom_universe | LOW | användardata | Fond-namn, ej giltig yfinance-ticker → genererar 404 varje körning. Bör filtreras bort i UI vid inmatning. |
| `[MISSTÄNKT]` `news_alerts.yml` använder `git push \|\| true` för state-commit | LOW | `.github/workflows/news_alerts.yml` | Medvetet (icke-kritisk state), men race mellan körningar kan tappa enstaka dedup-poster. |

### 16.3 Design decisions (not debt)

These are deliberate choices, not oversights:
- **File-based storage** — git history = full versioning, Streamlit reads directly
- **No database** — zero infrastructure, all data committed to git
- **Static ticker universe** — hand-curated for quality over automation
- **Streamlit Cloud ephemeral filesystem** — all writes must be GitHub-committed to persist
- **Percentile scoring** — relative ranking, not absolute valuation
- **No fundamentals in ML** — point-in-time integrity over feature richness

---

## 17. Improvement Ideas (Living List)

All ideas discovered during system analysis. Add to this section as you find more.

### 17.1 Quick wins (day)

| Idea | Summary | Impact | Files to change |
|---|---|---|---|
| **Score decay warning** | Warning in admin when last scored_universe is >48h old | Low | `web/pages/admin_page.py` |
| **Better pipeline error messages** | Log WHICH tickers failed and why | Medium | `core/data_fetcher.py` |
| **Per-ticker debug page** | Show WHY a stock got its score (factor breakdown) | High | New page in `web/pages/` |
| **CI log link in dashboard** | Link to GitHub Actions run from admin | Low | `core/daily_pipeline.py` |

### 17.2 Medium-term (week)

| Idea | Summary | Impact | Prerequisite |
|---|---|---|---|
| **Unified data quality dashboard** | Show missing data per ticker, per factor, over time | High | — |
| **Score change alerts** | Email/Push when a watched stock changes score by >10 | High | — |
| **Calendar-based event reminders** | Earnings + macro, auto-email N days ahead | High | — |
---

## 18. Andringslogg (uppdateras av varje AI vid varje andring)

> Lagg nyaste overst. Format: `YYYY-MM-DD — beskrivning (fil:rad)`.

### 2026-06-01 — Per-sektor ML-modeller (handel, banker, industri, …)

Sektor-*inferensen* fanns redan (`predict_returns_sector` med fallback) men sektor-modellerna
tränades aldrig och datasetet saknade `sector`-kolumn → all prediktion föll tillbaka på
universe-modellen. Nu tränas en egen modell per sektor:

- ✅ **`build_ml_dataset.py`**: `_build_sector_map()` bygger ticker→sektor från senaste
  `scored_universe_*.csv` (inga extra yfinance-anrop); varje träningsrad taggas med `sector`.
- ✅ **`ml_predictor.train_sector_models(parquet)`**: tränar en modell per sektor i
  `SECTOR_MODELS` med ≥ `MIN_SECTOR_ROWS` (2000) rader, sparar `ml_sector_<key>.pkl` +
  metrics. Använder samma tvärsnittliga target + CPCV (demeaning sker då inom sektor-datum =
  "relativ styrka inom sektorn"). `train_with_cpcv` tar nu valfri `df`-param.
- ✅ **`train_ml.py --sectors`** + **`train_ml.yml`** kör sektor-träning efter universe-modellen.
- Sektorer i `SMALL_SECTORS` (Real Estate/Utilities/Energy) eller med för få rader använder
  universe-modellen som fallback (oförändrat). Syntetiskt test: 2 sektorer med distinkt signal
  → IC 0.65 var.
- **Nästa steg (CI):** kör `train_ml.yml` (dispatch) för att bygga dataset med sektor-kolumn +
  träna sektor-modellerna. predict_returns_sector plockar automatiskt upp dem.

### 2026-06-01 — Övriga batch-fixar (BL, auto-flagga, drift-larm, mail-attribution)

- ✅ **P0.2 BL-fix** (`web/pages/portfolio.py`): Korrelation & Rebalans-fliken kraschade —
  `black_litterman_weights` anropades med fel argument + lästa kolumner fanns inte. Nu korrekt
  anrop + nuvarande-vs-föreslagna vikter beräknade från holdings.
- ✅ **P1.3 Auto-flagga delistade** (`core/config.py` + `daily_pipeline.py`): blacklistade
  tickers exkluderas vid universe-load; `update_ticker_health()` wirad efter fetch → 3 strikes
  → auto-blacklist.
- ✅ **P1.4 Score-drift-larm** (`core/pipeline_alerts.py`): `send_score_drift_alerts()` jämför
  två senaste snapshots, larmar vid |Δscore| ≥ 10 på bevakade/innehavda aktier. State-fil
  `data/score_drift_state.json`. Wirad i daily_pipeline efter snapshot.
- ✅ **P1.1 Faktor-attribution i mail** (`core/pipeline_report.py`):
  `format_factor_attribution_md()` visar per-faktor-breakdown under varje topp-10-pick i
  veckomailet.

### 2026-06-01 — ML-modellen omarbetad (near-zero IC → tvärsnittlig signal)

**Diagnos:** Universe-modellens IC var 0.0023 (≈ noll), hit-rate ~50%. Grundorsak:
modellen tränades på *absolut* `forward_return_30d` poolad över alla datum → marknadsbreda
rörelser dominerade och dränkte den tvärsnittliga urvalssignalen.

- ✅ **P0.1 — 8 saknade feature-hjälpfunktioner implementerade** (`core/ml_predictor.py`):
  `_log_return`, `_hurst_exponent` (R/S), `_serial_corr`, `_volume_price_corr`,
  `_klinger_oscillator`, `_max_drawdown`, `_consecutive_direction`, `_rsi_divergence`.
  Commit 4871bc5 deklarerade 11 features men glömde funktionerna → de blev tyst NaN →
  modellen tränades bara på 15 features. Regressionstest tillagt (`tests/test_ml_predictor.py`).
- ✅ **Tvärsnittlig target** (`_add_cross_sectional_target`): tränar nu på `target_cs` =
  forward-return demeanad PER DATUM. Tar bort marknadsfaktorn → modellen lär sig RELATIV
  styrka. A/B-test (syntetiskt, dominerande marknad): per-datum-IC +48 % (0.41 → 0.61).
  Inference oförändrad (predicted_return rankas redan tvärsnittligt → ml_rank).
- ✅ **Per-datum-IC** (`_per_date_ic`): headline-IC mäts nu per datum (Spearman inom varje
  datum, medelvärde) istället för poolat — det meningsfulla urvalsmåttet. Poolad IC behålls
  som referens (`ic_pooled`).
- ✅ **CPCV-träning aktiverad** (`scripts/train_ml.py` → `train_with_cpcv`) för ärligare
  validering (purge=30d + embargo). Final-modell + DSR tränas också på `target_cs`.
- **Nästa steg (CI):** kör om `train_ml.yml` (manuell dispatch eller söndagsschema) för att
  bygga om dataset med de 11 features + träna med ny target. Kontrollera att `ic` i
  `models/*_metrics.json` lyfter från ~0 mot ett positivt per-datum-IC.

### 2026-06-01 — Batch 2: Kreditspread, options flow, ML-features, HRP, per-sector ML

**Fas 1 — Quick wins:**
- ✅ **Short interest som ny scoring-faktor (vikt 3%)** — `calc_short_interest_score()` i
  `core/scoring.py` använder `short_pct_float`/`short_ratio` (hämtades sedan länge men var oanvänt).
  Contrarian-boost om >20% av float är blankat. `FACTOR_WEIGHTS` rescalades (sum=1.0) i `core/config.py`.
- ✅ **Earnings surprise i growth-score** — `earnings_surprise_pct` (earningsForecastsGrowthRate)
  läggs in som ytterligare komponent i `calc_growth_score()` (PEAD-signal). `core/scoring.py`.
- ✅ **Data-färskhetsvarning** — Orange/röd banner i sidebar-footern om senaste `scored_universe_*`
  är >48h (info) eller >72h (warning). `web/streamlit_app.py`.
- ✅ **Ticker-validering vid inmatning** — `validate_ticker()` i `web/pages/admin.py` avvisar
  fond-namn med mellanslag (t.ex. "LÄNSFÖRSÄKRINGAR GLOBAL INDEX"), kopplad till watchlist-formuläret.
- ✅ **36 delistade tickers rensade** ur `data/universe.json` — MAN.DE, VATTENFALL.ST, NYFOSA.ST
  m.fl. som failade 404 vid varje scan. 
- ✅ **Transaktionskostnader + slippage i paper trading** — `COMMISSION_PCT=0.10%` + `SLIPPAGE_PCT=0.05%`
  appliceras vid köp (effektivt pris × 1.0015) och sälj (× 0.9985). `portfolio/paper_trading.py`.

**Fas 2 — Hemsida/UX:**
- ✅ **Score-breakdown panel** — `_score_breakdown()` i `web/stock_detail.py` visar varje faktors
  poäng som färgad progress-bar + de viktigaste underliggande nyckeltalen. Svar på "varför fick
  aktien denna poäng?". Visas bredvid radar-chartet på aktie­detalj-sidan.
- ✅ **Bollinger Bands (20d, ±2σ)** — Ritade i candlestick-chartet i `web/stock_detail.py`.
  `bb_position` beräknades redan men visualiserades aldrig.
- ✅ **Ny "Korrelation & Rebalans"-tab i portföljsidan** — `_tab_rebalans()` i
  `web/pages/portfolio.py` med: korrelationsmatris (heatmap + auto-varning vid >0.80 par),
  diversifieringsförslag (via befintlig `suggest_diversifiers()`), Black-Litterman-optimering
  (via befintlig `black_litterman_weights()`) med nuvarande vs föreslagna vikter som stapeldiagram.

**Fas 3 — Point-in-time backtest:**
- ✅ **`backtesting/backtest_snapshots.py`** (ny fil) — `save_snapshot()` sparar en tunn
  scoring-snapshot efter varje veckoscan i `data/bt_snapshots/`; `run_snapshot_backtest()`
  backtestas mot dessa riktiga historiska rekommendationer (inget look-ahead bias).
- ✅ **`core/daily_pipeline.py`** — anropar `save_snapshot()` efter varje lyckad veckoscan.
- ✅ **`web/pages/backtesting_page.py`** — ny sektion "Point-in-time Backtest" med UI för att
  konfigurera och köra snapshot-backtesten; visar equity-kurva + per-period-avkastning vs benchmark.
  Informationsmeddelande när <3 snapshots finns (byggs upp löpande).

**Notering:** Snapshot-backtesten byggs upp automatiskt — varje veckoscan lägger till ett datapunkt.
Meningsfull historik finns efter 6–12 veckor.

### 2026-05-31 — Reliability-pass (data-persistens, scans, nyhetslarm)

**Data försvann vid Streamlit Cloud-omstart (ephemeral filsystem):**
- ✅ Seed-filer skapade så de alltid finns efter checkout: `data/email_subscribers.json`,
  `data/paper_trades.json`, `data/ml_paper_universe.json`, `data/ml_paper_smallcap.json`,
  `data/ai_trade_journal.json`, `data/news_alert_state.json`.
- ✅ GitHub-commit tillagd i fler spar-vägar som tidigare bara skrev lokalt:
  `_save_konton()` (`web/pages/portfolio.py`), `_save_journal()` (`web/pages/ai_journal.py`),
  `_update_user_password()` (`web/streamlit_app.py` — lösenordsbyten försvann annars).
- ✅ `settings_page.py` visar nu tydlig varning om `GITHUB_TOKEN` saknas/commit misslyckas.

**GitHub Actions — push-fel maskerades:**
- ✅ `permissions: contents: write` tillagd i `daily_scan.yml`, `smallcap_scan.yml`,
  `train_ml.yml`, `news_alerts.yml` (default-token saknade skrivrättighet → tyst push-fail).
- ✅ `git push || true` ersatt med `git pull --rebase` + `git push` (fel syns nu).
- ✅ `git add` uppdelat per fil-grupp med `2>/dev/null || true` — ett saknat fil
  (`data/watchlist.json` när WATCHLIST_JSON-secret saknas) avbröt annars hela `git add`,
  vilket gav `error: cannot pull with rebase: unstaged changes` (exit 128) i alla scans.
- ✅ `daily_scan.yml` committar nu även `blacklist.json`, `strike_list.json`,
  `stark_alert_state.json` (uppdaterades varje körning men persisterades aldrig).

**Scoring/pipeline:**
- ✅ `_region_neutralize_fundamentals()` tvingar numerisk typ (`pd.to_numeric(coerce)`) —
  yfinance returnerar strängen `"Infinity"` för P/E vid vinst ≈ 0, vilket kraschade
  groupby-median med `TypeError` och stoppade hela weekly-scannen (`core/scoring.py`).
- ✅ `data_quality` skyddad mot division-med-noll om alla metric-kolumner saknas (`scoring.py`).
- ✅ `n_pt`-räkning i `daily_pipeline.py` fixad: `len(dict)` gav alltid 2; läser nu
  `len(result["trades"])`.

**Email:**
- ✅ Integritetsläcka: alla mottagare exponerades i `To:`-headern → nu BCC via envelope
  (`core/email_template.py:send_email`).
- ✅ AI-analys kapades till `[:500]` (~70 ord) mitt i mening i larmmail → trunkering borttagen
  (`core/news_alerts.py`).
- ✅ `smallcap_scan.yml` satte `EMAIL_USER/EMAIL_PASS` men koden läser
  `EMAIL_SENDER/EMAIL_PASSWORD` → måndagsmailet skickades aldrig. Rättat.

**AI:**
- ✅ Symmetrisk fallback DeepSeek→Gemini i `_provider_call` (`core/ai_analysis.py`). Tidigare
  fanns bara Gemini→DeepSeek; när default-provider var DeepSeek och den failade (402/429)
  fick weekly-rapporten bara feltext trots giltig GEMINI_API_KEY.

**Nyhetslarm (ny funktion):**
- ✅ `news_alerts._fetch_news()` faller nu tillbaka till
  `core.news_fetcher.fetch_company_news()` (Google News RSS + Nasdaq Nordic + DuckDuckGo)
  för icke-US-tickers. Tidigare fick nordiska innehav (.ST/.HE) ALDRIG nyhetslarm
  (Finnhub company-news stödjer bara US-symboler).
- ✅ Daglig dedup-state (`data/news_alert_state.json`): varje nyhet/prisrörelse larmas max
  en gång per dag; committas mellan 30-min-körningar (`news_alerts.yml`).

**Robusthet:**
- ✅ `config._load_universe()` fångar nu `JSONDecodeError/ValueError/OSError` (inte bara
  `FileNotFoundError`). En trasig `data/universe.json` kraschade annars config-importen →
  hela appen + alla pipelines (`core/config.py`).
- ✅ Felplacerad `@st.cache_data`-dekorator på `_get()` borttagen (`web/utils.py`).
- ✅ `core/currency.py` ffill/bfill begränsad till 5 dagar (känd FX-100x-buggklass).
- ✅ 6 st `except: pass` → `except Exception: pass` (fångade tidigare även SystemExit/
  KeyboardInterrupt): earnings_calendar, extra_data, macro_regime, relative_strength,
  sector_momentum, portfolio_analysis.

**Infrastruktur:**
- ✅ `keep_alive.yml` skapad — pingar Streamlit-appen var 20:e min så den inte somnar.

---

## Appendix A: Key Functions Quick Reference

```
core/daily_pipeline.py:
  run_pipeline(mode)                 # Central orchestrator
  run_targeted(tickers)              # Refresh specific tickers
  run_refresh_missing()              # Find + fix missing data
  _latest_report(pattern)            # Find newest report file
  _load_latest_scored(pattern)       # Load latest scored universe
  _save_scored(df, path)             # Save parquet + csv atomically
  _enrich_holdings(holdings, scored) # Enrich with scan data
  _get_score_deltas(today, yesterday) # Compare runs
  _get_opportunities(scored)         # Rule-based opportunities
  _get_top_bottom(scored)            # Top/bottom N

core/scoring.py:
  score_universe(df, regime)         # Main scoring pipeline
  score_universe_sector_neutralized()  # Sector-neutral variant
  calc_value_score(df)               # FCF yield + EV/EBITDA + fallback
  calc_fcf_yield_score(df)           # FCF / EV
  calc_quality_score(df)             # ROE + margins
  calc_momentum_score(df)            # Returns + 52w high
  calc_growth_score(df)              # Revenue + earnings growth
  calc_risk_score(df)                # D/E + current_ratio + volatility
  calc_size_score(df)                # Log market cap (inverted)
  calc_dividend_score(df)            # Yield + payout sanity
  calc_sentiment_score(df)           # Finnhub + insider boost
  get_dynamic_weights(regime, base)  # Regime-adjusted weights
  _region_neutralize_fundamentals()  # Subtrahera regionmedian
  percentile_rank(series, ascending) # 0-100 ranking
  winsorize(series)                  # Clip extremes (2%/98%)
  _try_rank(series, ascending)       # Winsorize + rank with guard

core/data_fetcher.py:
  fetch_universe_data(tickers)       # Main data fetch
  fetch_prices_only(tickers)         # Price-only refresh
  extract_metrics(ticker, info, hist) # ~45 fields from yfinance
  update_scored_with_prices(df)      # Re-score with new prices

core/macro_regime.py:
  detect_regime()                    # SPY+VIX+breadth+yield → TJUR/BJÖRN/OSÄKER

core/filters.py:
  apply_all_filters(df)              # Quality + trend + confidence + entry
  apply_trend_filter(df)             # MA50/MA200-based trend
  calc_confidence(df)                # Factor agreement
  calc_entry_signal(df)              # STARK/OK/VÄNTA/EJ AKTUELL
  calc_piotroski(initial, final)     # Per-ticker F-Score
  update_ticker_health(...)          # Strike system
  diagnose_failure(ticker, row)      # Why did a ticker fail?

core/ai_analysis.py:
  ai_chat(prompt, provider, depth)   # Universal AI chat
  analyze_stock(ticker, df)          # Per-stock analysis
  analyze_portfolio(holdings, scored) # Portfolio analysis
  generate_morning_brief(...)        # Full morning AI report
  generate_weekly_ai_analysis(...)   # Weekly deep analysis
  generate_news_alert_analysis(...)   # News evaluation

core/email_template.py:
  send_email(subject, body_md, ...)  # Send formatted HTML email
  send_failure_alert(workflow)       # Pipeline failure notification

portfolio/paper_trading.py:
  record_daily_signals(scored)       # Top-N virtual buys
  update_positions()                 # Price update + stop/TP check

smallcap/scanner.py:
  main()                             # CLI entry point
  fetch_data(tickers)                # yfinance fetch for smallcaps
  score_universe(df)                 # Smallcap-specific scoring
```

## Appendix B: Data Flow Diagram (Text)

```
yfinance ──→ data_fetcher ──→ cache (data/cache/*.pkl)
  │                               │
  │                               ▼
  └─────→ fetch_universe_data() ──→ raw DataFrame (45+ columns)
                                       │
                                       ▼
                                  scoring.py
                                  region-neutralize
                                  percentile-rank → 8 factor scores
                                  weight → score_total
                                  holding/commodity discount
                                  low_liquidity flag
                                       │
                                       ▼
                                  filters.py
                                  trend filter (MA50/MA200)
                                  confidence calc
                                  entry signal (STARK/OK/VÄNTA/EJ AKTUELL)
                                       │
                                       ▼
                                  daily_pipeline.py
                                  ┌─────────────────────┐
                                  │  portfolio enrich    │
                                  │  score deltas        │
                                  │  opportunities       │
                                  │  ML predict          │
                                  │  paper trading       │
                                  │  AI analysis         │
                                  │  email               │
                                  └─────────────────────┘
                                       │
                                       ▼
                                  reports/scored_*.parquet
                                  reports/scored_*.csv
                                  reports/*.md
                                       │
                                       ▼
                                  Streamlit Cloud
                                  ┌──────────────────┐
                                  │  20 pages         │
                                  │  data from .csv   │
                                  │  AI from cache    │
                                  └──────────────────┘
                                       │
                                       ▼
                                  GitHub Actions (CI)
                                  ┌──────────────────┐
                                  │  pytest tests/    │
                                  │  commit reports   │
                                  │  keep-alive       │
                                  └──────────────────┘
```
