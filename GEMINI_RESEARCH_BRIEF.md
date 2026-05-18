# AI-Driven Stock Scanner — Architecture Brief for Deep Research

## Purpose of this document

This is a technical description of a personal quantitative stock-scanning system built in Python. I am asking for a deep research review focused on:
1. Which parts of the architecture have the largest measurable impact on risk-adjusted returns (Sharpe/Sortino)?
2. What are the most evidence-based improvements I could implement next?
3. Where does the current design introduce the most bias, data leakage, or signal decay?

---

## 1. System Overview

A fully automated, multi-factor quantitative stock scanner running locally on Windows. It covers a global equity universe (~1,000–1,200 tickers), scores every stock daily against 8 factor categories, generates AI-written narrative analysis, manages a real portfolio, runs parallel paper-trading, produces weekly PDF/markdown reports, and sends real-time news alerts every 30 minutes. The user is a private investor, not an institution.

**Tech stack:** Python 3.12, yfinance (primary data), FMP API (fallback fundamentals), Finansinspektionen open data (Swedish insider transactions), DeepSeek / Gemini LLMs, XGBoost / sklearn HistGradientBoosting, Streamlit + Flask web UI, GitHub Actions (CI/CD pipelines).

---

## 2. Universe

Approximately 1,000–1,200 tickers across 8 regions, defined statically in `config.py`:

| Region | Approx. count | Exchange suffixes |
|---|---|---|
| US Large/Mid/Small Cap | ~400 | none (NYSE/NASDAQ) |
| UK | ~60 | `.L` |
| Germany | ~80 | `.DE` |
| Nordic ex-Sweden | ~60 | `.CO`, `.OL`, `.HE` |
| OMX Sweden | ~80 | `.ST` |
| Europe (broader) | ~180 | `.PA`, `.AS`, `.MC`, `.MI`, `.SW`, `.VI`, `.WA`, `.LS` |
| Asia-Pacific | ~200 | `.T`, `.TW`, `.KS`, `.HK`, `.NS`, `.AX`, `.SI` |
| Canada | ~50 | `.TO` |
| Brazil/LatAm | ~50 | `.SA`, `.MX`, ADRs |

A `custom_universe.json` allows adding tickers dynamically from the UI. Deduplication is handled with `dict.fromkeys()`. Portfolio holdings and watchlist items are automatically synced into the custom universe during the weekly scan so all held stocks get scored regardless of universe membership.


**Known gap:** Universe is static and hand-curated. No automatic addition of IPOs, spin-offs, or newly listed stocks. No exclusion of penny stocks, suspended trading, or stocks below minimum liquidity thresholds at the universe level (liquidity is scored, but not used as a hard filter for the main universe). There is now a **Universe Health Check** module (`core/universe_health.py`) that detects invalid/delisted tickers, suggests replacements, and finds new stocks using AI — but this is run on demand, not automatically integrated into the daily pipeline.

---

## 3. Data Pipeline

### 3.1 Primary: yfinance

`core/data_fetcher.py` — `extract_metrics(ticker, info, history)` is the central function. It extracts ~45 fields from two yfinance calls:
- `yf.Ticker(ticker).info` — fundamentals (P/E, ROE, FCF, etc.), cached 720 hours
- `yf.Ticker(ticker).history(period="1y")` — daily OHLCV, cached 24 hours

Prices are converted to SEK for all non-Swedish tickers using live FX rates from yfinance (`USDSEK=X`, `EURSEK=X`, etc.). FX data has sanity checks (day-over-day ratios outside 0.67–1.5 are flagged and discarded).

**Parallelism:** `ThreadPoolExecutor` with 8 workers + a sliding-window rate limiter (configurable, default ~0.3s per call). An optional async layer using `aiohttp` (not yet wired into the main pipeline) fetches price history via Yahoo Finance's undocumented chart REST API.

**Caching layers:**
- Static fundamentals: 720h (quarterly data)
- Dynamic fundamentals (P/E, analysts, short interest): 48h
- Price history: 24h
- Insider signals: 24h
- FMP key-metrics: 720h
- Macro regime: 6h
- AI responses: content-addressed (MD5 cache key), persistent
- News: 6h (per ticker)
- Company name lookups: 720h

**Two-pass rate-limit retry:** `fetch_universe_data()` now implements a two-pass strategy — on first pass it collects 429-rate-limited tickers, then retries them in a second pass with longer delays. This dramatically reduces failed fetches during full universe scans.

### 3.2 FMP Fallback (Financial Modeling Prep)

`_get_fmp_fundamentals(ticker)` calls `/api/v3/key-metrics-ttm/{ticker}`. Fields filled when yfinance returns `None`: P/E (trailing), P/B, ROE, ROA, EV/EBITDA, revenue growth. Free tier: 250 calls/day. 720h cache makes this usable for ~1,000 stocks at ~33 calls/day.

### 3.3 Finansinspektionen (Swedish insider transactions)

`core/fi_insider_fetcher.py` queries FI's public search register (`marknadssok.fi.se`) for `.ST` tickers. All Swedish listed companies must report insider trades to FI within 3 business days under EU MAR. The module:
- Converts ticker → company name via yfinance, strips legal suffixes
- Tries JSON XHR endpoint, falls back to HTML table parsing
- Detects VD/CFO buying and cluster buying (≥3 distinct insiders in 30 days)
- 24h cache

Rate-limiting has been added: cluster detection is rate-limited to avoid hammering FI's servers. 404 tickers are auto-blacklisted to skip them on subsequent runs.

### 3.4 Computed fields in extract_metrics()

In addition to raw yfinance fields, the pipeline computes:
- `return_1m/3m/6m/12m` — from OHLCV history (21/63/126/252 days)
- `rsi_14` — standard RSI from close prices
- `price_vs_ma50/ma200` — relative distance from moving averages
- `volatility` — annualized daily return std dev
- `macd_above_signal` — bool, 12/26/9 EMA crossover
- `bb_position` — Bollinger Band position (0=lower band, 0.5=middle, 1=upper)
- `volume_ratio` — last day volume / 20-day average
- `market_cap` — refreshed as shares_outstanding × current_price (not stale info.marketCap)
- `enterprise_value` — from yfinance `info.get("enterpriseValue")`
- `insider_cluster`, `insider_executive_buy` — from `_get_insider_signal()`

### 3.5 Multi-Source News System (NEW)

`core/news_fetcher.py` implements a sophisticated multi-source news aggregation system with cascading fallbacks:

**Source priority order for any ticker:**
1. **Finnhub** (API key required) — best for US/global stocks, `company-news` endpoint
2. **Google News RSS** — Swedish search (using real company name for best results)
3. **Google News RSS** — English search (fallback for international coverage)
4. **Nasdaq Nordic** — Official exchange announcements for `.ST` stocks (free API, no key required)
5. **Yahoo Finance** — `yf.Ticker(ticker).news` (last resort, free)

**Key functions:**
- `fetch_company_news(ticker, days_back, company_name)` — orchestrates all sources with deduplication and merging
- `fetch_news(ticker, api_key, days)` — Finnhub company news
- `fetch_global_market_news(api_key)` — general market news via Finnhub + Google News RSS
- `fetch_swedish_market_news()` — Swedish market news from Placera, DI, Realtid RSS feeds
- `fetch_google_news_rss(company_name, lang)` — Google News RSS search (no API key needed)
- `fetch_nasdaq_nordic_news(market)` — Official exchange announcements for Nordic markets
- `fetch_yfinance_news(ticker)` — Yahoo Finance news as last-resort fallback
- `format_news_section_md()` — builds markdown with clickable links and age indicators

**News is integrated into every pipeline run** — the morning, evening, weekly, and smallcap pipelines all fetch live news for portfolio holdings, watchlist items, and top-5 scored stocks before generating the AI analysis. AI is forced to cite news in its summaries.

**News caching:** 6-hour cache per ticker via pickle files. Individual component caches (Finnhub, Google, Nasdaq) are separate from the merged result to avoid locking in empty results.

**Weekly factoids:** `get_weekly_factoid()` returns a rotating educational market fact based on week number.

---

## 4. Scoring Engine

`core/scoring.py` — converts raw metrics to a 0–100 composite score using **percentile ranking within the universe** (not absolute thresholds). This means scores are relative: a stock at the 80th percentile gets ~80 regardless of its absolute P/E.

**Minimum observations.

**Minimum observations:** Any factor with fewer than 5 non-null values gets replaced by NEUTRAL_SCORE=50.

### 4.1 The 8 factors and their default weights

| Factor | Weight | Key inputs |
|---|---|---|
| `value` | 22% | P/E, P/B, EV/EBITDA, PEG, P/S; also FCF Yield (50/50 blend with EV/EBITDA) |
| `quality` | 18% | ROE, ROA, profit margin, Piotroski F-Score (0–9), current ratio, D/E |
| `momentum` | 18% | 1m/3m/6m/12m returns, RSI, MACD signal, vs MA200, BB position |
| `growth` | 13% | Revenue growth, earnings growth, quarterly earnings growth |
| `risk` | 9% | Volatility (inverted), beta (inverted), short ratio (inverted) |
| `size` | 5% | Market cap — small cap is rewarded (small-cap premium) |
| `dividend` | 5% | Dividend yield (capped at 15%), payout sustainability, 5-year avg yield |
| `sentiment` | 10% | Analyst recommendation mean, number of analysts, insider ownership %, insider executive buy boost (+20 pts, capped 95), insider cluster boost (+30 pts, capped 98) |

**FCF Yield scoring:** `calc_fcf_yield_score()` uses `free_cash_flow / enterprise_value`. Falls back to `(market_cap + debt − cash)` when `enterprise_value` is missing. Blended 50/50 with EV/EBITDA in the value score.

**Piotroski F-Score:** 9-point binary score in `core/piotroski.py`. Inputs: ROA delta, OCF, accruals, leverage delta, current ratio delta, shares issued, gross margin delta, asset turnover delta.

**Final composite:** weighted average of all 8 factors + optional Piotroski adjustment.

### 4.2 Industry discounts

Applied in `score_universe()`:
- Holding companies / investment trusts: ×0.85
- Commodity/raw materials: ×0.90

### 4.3 Dynamic factor weights (macro regime overlay)

`core/macro_regime.py` detects market regime from 5 signals with continuous 0–1 scoring:
- SPY vs MA200 (weight 35%)
- VIX level (weight 25%)
- SPY 3-month momentum (weight 20%)
- Market breadth RSP/SPY ratio vs 60-day avg (weight 10%)
- Yield curve: 10y−3m Treasury spread (weight 10%)

Regime thresholds: composite ≥ 0.62 = BULL, ≤ 0.38 = BEAR, else UNCERTAIN.

In BULL: momentum +5%, growth +5%, risk −5%, value −5%.
In BEAR: quality +15%, value +10%, dividend +5%, momentum −15%, growth −15%.

### 4.4 Signals and Filters (NEW)

`core/filters.py` computes three derived signals on top of the composite score:

**`entry_signal`** (via `calc_entry_signal()`):
| Signal | Logic |
|---|---|
| `"STARK"` | Score ≥ 72, RSI 35–68, AND pullback 5–18% from 52w high |
| `"OK"` | Score ≥ 65, RSI 35–68 |
| `"VÄNTA"` | RSI > 75 (overbought), RSI < 30 (oversold), or score 55–64 |
| `"EJ AKTUELL"` | Below MA200 or score < 55 |

**`trend_signal`** (via `apply_trend_filter()`):
| Value | Condition |
|---|---|
| `"UPPTREND"` | Price above MA200 |
| `"NEDTREND"` | Price below MA200 → sets `trend_capped = True` |
| `"VARNING"` | Price below MA50 but above MA200 |

**`confidence_label`** (via `calc_confidence()`): Counts how many of 7 score sub-factors are ≥ 60. Returns `"HÖG"` ≥ 70%, `"MEDEL"` 45–69%, `"LÅG"` < 45%, `"OKÄND"` if no score columns exist.

All three are combined by `apply_all_filters()` which runs: quality filter → trend filter → confidence → entry signal.

### 4.5 Sector-Neutralized Scoring (NEW)

The weekly pipeline supports an optional sector-neutral scoring mode (`SCORE_MODE = "sector_neutral"` in config). When enabled, `score_universe_sector_neutralized()` computes each factor score **within sector groups** rather than globally. This prevents tech stocks from systematically overranking and value stocks from underranking purely due to sector composition effects.

### 4.6 Smallcap scanner (separate module)

`smallcap/` is a separate scanner for Swedish small-caps (market cap 30 MSEK–10 GSEK, daily turnover ≥ 500k SEK). Different scoring weights, stricter hard filters:

| Factor | Weight |
|---|---|
| Insider (ownership + transactions) | 18% |
| FCF yield | 16% |
| Piotroski F-Score | 15% |
| Revenue growth | 13% |
| Balance sheet (D/E + current ratio) | 12% |
| Valuation (EV/EBITDA or P/B) | 12% |
| Momentum (relative strength 6–12m) | 9% |
| Liquidity (daily turnover, exit risk) | 5% |

Hard filters eliminate: cash runway < 12 months, Piotroski ≤ 2, share dilution > 20%/year, D/E > 300%, current ratio < 0.5.

---

## 5. ML Predictor

`core/ml_predictor.py` — gradient-boosted regression model. XGBoost if installed, sklearn `HistGradientBoostingRegressor` as fallback (with `max_iter=500` and early stopping for HGBT).

**Two separate models:** `models/ml_universe.pkl` (large-cap universe) and `models/ml_smallcap.pkl` (Swedish small-caps).

**Features (technical only, 15 features):**
```
ret_1m, ret_3m, ret_6m, ret_12m, rsi_14, macd_signal (bool),
vs_ma50, vs_ma200, volume_ratio, volatility, bb_position,
price_vs_52w_high, momentum_3m_rank, momentum_6m_rank, pct_from_52w_high
```

Fundamentals are excluded to avoid point-in-time problems in backtesting.

**Target:** `forward_return_30d` — actual 30-calendar-day return.

**Training:** `train_with_cpcv()` uses **Combinatorial Purged Cross-Validation** (Lopez de Prado). 6 folds, purge window = 30 days (matches forward return horizon), embargo = 1% of dataset. Evaluates information coefficient (IC, Spearman correlation between predicted and actual returns) per fold plus hit rate. Final model is trained on all data. Training includes **time-decay weighting** for HGBT (sample weights = weeks ago^2) so recent observations matter more.

**Output columns added to scored DataFrame:**
- `predicted_return` — model's forward return estimate
- `ml_rank` — percentile rank 0–100 within universe

**ML paper trading (NEW):** `core/ml_paper_trading.py` — records the top-10 picks from the ML model each day as virtual trades. Tracks ATR-based stop-losses, 30-day max holding period. Tracks separate win/loss statistics per ML model (universe vs smallcap). Exported via `get_kelly_inputs()` for position sizing. This runs automatically in the daily pipeline when a trained model exists.

**Black-Litterman integration (NEW):** `portfolio/black_litterman.py` — implements the full Black-Litterman model that blends ML-predicted returns (as views) with market-cap-weighted equilibrium priors:

1. **Prior (Π)** — Market-cap-weighted equilibrium returns via reverse optimization: `Π = δ × Σ × w_mkt`
2. **Views (Q)** — `score_total` values normalized to expected returns (±5% cap) as absolute views. Confidence scaled by historical Information Coefficient (IC) from `models/ml_universe_metrics.json`
3. **Covariance (Σ)** — Ledoit-Wolf shrinkage estimator. Falls back to identity covariance (20% vol) if price data unavailable
4. **Posterior** — Standard BL formula: `μ_posterior = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ × [(τΣ)⁻¹Π + P'Ω⁻¹Q]`; weights via `w* = (δΣ)⁻¹ × μ_posterior`
5. **Constraints** — Long-only, max 15% per position, re-normalized to sum to 1

Key functions: `black_litterman_posterior()`, `ledoit_wolf_covariance()`, `equilibrium_prior()`, `bl_optimize()`. Integrated via daily pipeline's ML prediction step.

**Known limitations:** Features are all derived from the same price series that also determines the target. The model has no alpha from fundamentals. Training dataset is generated from the live universe's historical data — survivorship bias is present because only currently-covered tickers are in the training set.

---

## 6. AI Analysis Layer

`core/ai_analysis.py` — wraps LLM calls with caching, retry, exponential backoff, and provider fallback.

**Providers:** DeepSeek (default, paid, stable) and Gemini (free, rate-limited at 15 req/min). Provider selection is configurable per task: `AI_TASK_MODE = "hybrid"` routes light tasks to Gemini and heavy tasks to DeepSeek. Exponential backoff retry for DeepSeek (handles 429/5xx/timeout). Gemini has automatic model fallback on 404 (deprecation).

**Model settings:** Temperature 0.3, max tokens varies by depth. DeepSeek model: `deepseek-chat`. Gemini model: `gemini-2.5-flash`.

**Depth levels (control WHAT data is sent, not just response length):**

| Depth | Data sent to LLM | System prompt addon |
|---|---|---|
| Snabb | 6 key fields only: P/E, ROE, Momentum, Revenue Growth, Piotroski F-Score, Entry Signal | Max 3 sentences |
| Normal | All standard fields | No addon |
| Djup | All fields + FCF Yield, EV/EBITDA, Bollinger Band, insider ownership, RSI, MACD, returns | Deep analysis with sector comparison + buy/sell recommendation |
| Extra djup | All fields + ROA, Operating/Gross Margin, Institution %, D/E, Beta, Volatility | Institutional-style: FCF analysis, scenario analysis (bull/base/bear), position sizing + entry/exit |

Swedish stock caveat: For `Djup` and `Extra djup` on `.ST` tickers, a note is appended: "K3/K2 Swedish accounting — untaxed reserves (obeskattade reserver) reduce reported earnings, ROA and margins are likely understating actual profitability."

**Analysis functions:** `analyze_stock()`, `analyze_portfolio()`, `analyze_sector()`, `analyze_news()`, `compare_stocks()`, `generate_market_summary()`, `generate_morning_brief()`, `generate_weekly_ai_analysis()`. All have `depth` in their cache key. Additional functions: `generate_news_alert_analysis()`, `generate_vad_stack_ut_analysis()`. All have `depth` in their cache key.

**News-aware AI (NEW):** The pipeline now injects live news context into every AI analysis call. The `_add_news()` helper appends fetched news to the JSON context using a separator that `ai_chat` recognizes. The morning/evening/weekly system prompts explicitly instruct the AI to cite news (section templates mention "Nyheter finns bifogade – väg in dem"). This is also applied in the stock detail page's custom AI questions.

**"Vad stack ut idag?" (NEW):** A lazy-load AI summary on the alerts page that aggregates the day's most important events. Uses lazy expanders so the AI is only called when the user expands the section. The summary forces AI to cite specific news headlines.

---

## 7. Portfolio Management

`portfolio/portfolio.py` — analyzes actual holdings vs. scored universe.

**Recommendation logic (percentile-based):**
- Top 20% of universe → `KÖP MER` (Buy More), unless RSI > 75 → downgrade to `BEHÅLL`
- Top 20–50% → `BEHÅLL` (Hold), unless 3m return < −15% → downgrade to `BEVAKA`
- Bottom 50% + 3m return < −10% → `SÄLJ/MINSKA` (Sell/Reduce)
- Bottom 50% + percentile > 75 → `SÄLJ/MINSKA`
- Otherwise → `BEVAKA` (Watch)

**Universe-aware recommendations (NEW):** The portfolio module now merges the main universe and smallcap universe for recommendations, so holdings across both universes get scored. Holdings not in either universe get a live price and calculated RSI/trend/entry from historical data via `_calc_tech_fallback()`.

**ATR-based stop-loss (for KÖP MER only):**
`_atr_stop(ticker, price, mult=2.5)` — fetches 1 month of daily OHLCV via yfinance, computes ATR14 (Average True Range over 14 days using True Range = max(H−L, |H−prev_C|, |L−prev_C|)). Stop = current_price − 2.5 × ATR14. Presented as price level and percentage below current price.

**Half-Kelly position sizing:**
`_half_kelly(portfolio_value)` uses win rate and win/loss ratio from closed paper trades:
- Kelly% = win_rate − (1 − win_rate) / win_loss_ratio
- Half-Kelly = Kelly × 0.5, clamped to [2%, 10%] of portfolio value
- Default values (win_rate=0.55, win_loss_ratio=1.5) used until ≥20 closed trades

**Correlation analysis:**
`analyze_correlation()` downloads 6 months of price data, computes pairwise Pearson correlation matrix, calculates average pairwise correlation and highest correlated pair. Diversification score = (1 − max(0, avg_corr)) × 100.

---

## 8. Paper Trading System

`portfolio/paper_trading.py` — parallel virtual trading on the same recommendations.

Records entry signals from the scored universe. Tracks open trades with:
- Entry date, ticker, entry price
- ATR14-based dynamic stop-loss (2× ATR, recalculated on exit check)
- 30-day maximum holding period
- Exit triggers: stop-loss hit, holding period expired, or sell recommendation

**Paper trading v2 features:** Stop-loss, take-profit, partial sell, DCA (dollar-cost averaging), trailing stop, AI-generated stop-loss suggestions.

`get_kelly_inputs(min_trades=20)` exports win_rate, win_loss_ratio, n_trades from closed trade history for Half-Kelly calculation in the portfolio module.

Two separate paper-trading instances: one for the main universe, one for small-caps.

**Paper trading dashboard:** Streamlit UI shows equity curve, exit pie chart, P&L histogram, stacked bar chart, DCA statistics, and KPI cards (win rate, profit factor, average return, Sharpe ratio).

---

## 9. Central Pipeline (NEW — replaces 5 older scripts)

`core/daily_pipeline.py` is the central orchestrator that replaced five older scripts (`morning_scan.py`, `evening_scan.py`, `scan.py`, `opportunity_scan.py`, `ai_weekly_summary.py`). It supports 4 modes:

| Mode | Frequency | What it does |
|---|---|---|
| **morning** | Daily | Overnight global markets, portfolio status, stop-loss warnings, watchlist changes, top picks, opportunities, AI morning brief |
| **evening** | Daily | Day's index moves, portfolio P&L, top/bottom performers, opportunities, look-ahead, AI evening reflection |
| **weekly** | Weekly | Full re-fetch and rescore of entire universe (including custom/portfolio/watchlist tickers), Piotroski F-Score, ML predictions, sector analysis, top-10 buy recs, bottom-5 warnings, AI deep analysis |
| **smallcap** | Daily | Swedish small-cap specific scan, scoring, top picks, AI small-cap analysis |

**Pipeline flow for each mode:**
1. **Load data:** Always fetches global market indices. For morning/evening, loads latest cached scored universe. For weekly, does a full universe fetch + score + Piotroski + filters + ML prediction
2. **Daily re-scoring (morning/evening only):** Fetches fresh prices for up to 100 tickers (rate-limit safe) and updates scores without re-fetching fundamentals
3. **ML prediction:** If model exists, adds `predicted_return` and `ml_rank` columns for both universe and smallcap models
4. **ML paper trading:** Records top-10 ML picks as virtual trades
5. **Portfolio/watchlist sync:** Automatically adds portfolio holdings and watchlist items to `custom_universe.json` so they're included in the weekly scan
6. **Portfolio enrichment:** Enriches holdings with scored data. Holdings outside the universe get live prices + calculated RSI/trend/entry from `_calc_tech_fallback()`
7. **Score delta tracking:** Compares today's vs yesterday's scores → identifies movers_up, movers_down, RSI spikes, big price moves (>4%)
8. **Opportunity detection:** Scans for dips in uptrend, breakouts near 52w high, oversold bounces (all rule-based, no API call)
9. **Report generation:** Builds Markdown report with mode-specific structure + AI analysis
10. **AI analysis with news context:** Fetches live news for portfolio/watchlist/top-5 → injects into AI context → forces AI to cite news
11. **Save + email:** Saves report to disk (Markdown + Parquet + CSV), sends via email with subscription-type routing

**Data persistence:** Parquet (zstd-compressed) + CSV dual format for backwards compatibility. Atomic writes via .tmp + rename to prevent corruption. Old reports >60 days auto-cleaned.

---

## 10. Reporting & Alerting

### 10.1 Email System (NEW — refactored)

`core/email_template.py` — shared email formatting engine used by all pipeline modes and news alerts:
- Converts Markdown → HTML via **mistune 3.x** with a custom `_InlineLexer` override that adds responsive email-safe link rendering and inline code
- Responsive HTML layout with `build_section_header()` for consistent section styling
- Plain-text truncation at sentence boundaries (100k char limit, was 1500 — raised because smallcap reports were truncated to empty)
- **Subscriber management:** `data/email_subscribers.json` stores per-subscription-type recipient lists. Admin UI allows adding/removing recipients per report type (morning, evening, weekly, smallcap)
- **List-Unsubscribe header** added to reduce spam classification
- Password-protected admin UI for subscriber management

**Email types sent:**
| Type | Subject Pattern | Trigger |
|---|---|---|
| Morning brief | 🌅 MarketScan Morgonbrief – YYYY-MM-DD | Daily morning pipeline |
| Evening brief | 🌆 MarketScan Kvällsbrev – YYYY-MM-DD | Daily evening pipeline |
| Weekly report | 📊 MarketScan Veckorapport – v.XX | Weekly pipeline |
| Smallcap report | 🏦 MarketScan Småbolag – YYYY-MM-DD | Daily smallcap pipeline |
| News alerts | 🚨 MarketScan Larm – YYYY-MM-DD (N events) | Every 30 min (news_alerts.yml) |

### 10.2 Real-Time News Alerts (NEW)

`core/news_alerts.py` — runs every **30 minutes** Monday–Friday 08:00–21:00 UTC via GitHub Actions (`news_alerts.yml`):
- Checks **portfolio holdings**, **watchlist**, and **top-10 scored stocks** for:
  - **News** via Finnhub company-news API (today's date)
  - **Price moves** >5% via yfinance (2-day history)
- Each alert is **AI-evaluated**: `_evaluate_alert()` sends the headline to AI (Snabb depth) which judges relevance and provides a Swedish-language analysis
- Price moves get AI explanation: `_evaluate_price_move()` asks the AI to explain why the stock moved
- Alerts are batched and sent as a single email with AI analysis per event
- **Keyword fallback:** If AI call fails, important keywords (vinstvarning, konkurs, fusion, FDA, etc.) trigger alerts anyway
- Rate-limited to 1.5 seconds between tickers to avoid Finnhub rate limits

### 10.3 Country Flags (NEW)

`core/country_flags.py` — `flag_for_ticker()` maps ticker suffixes to emoji flags:
- `.ST` → 🇸🇪 Sweden, `.HE` → 🇫🇮 Finland, `.CO` → 🇩🇰 Denmark, `.OL` → 🇳🇴 Norway
- `.DE` → 🇩🇪 Germany, `.PA` → 🇫🇷 France, `.L` → 🇬🇧 UK, `.MI` → 🇮🇹 Italy, `.MC` → 🇪🇸 Spain, `.SW` → 🇨🇭 Switzerland
- `.TO` → 🇨🇦 Canada, `.AX` → 🇦🇺 Australia, `.T` → 🇯🇵 Japan, `.TW` → 🇹🇼 Taiwan
- `.KS` → 🇰🇷 South Korea, `.HK` → 🇭🇰 Hong Kong, `.NS` → 🇮🇳 India, `.SI` → 🇸🇬 Singapore
- `.SA` → 🇧🇷 Brazil, no suffix → 🇺🇸 USA, special ADR exceptions mapped to home country

Used in all reports, portfolio tables, watchlist displays, and the web UI ranking table.

### 10.4 Global Markets Module (NEW)

`core/global_markets.py` — tracks 17 global stock indices via yfinance:
- Asia/Pacific: Nikkei 225 (^N225), HSI (^HSI), Shanghai (000001.SS), KOSPI (^KS11), ASX 200 (^AXJO), Sensex (^BSESN), STI (^STI)
- Europe: DAX (^GDAXI), FTSE 100 (^FTSE), CAC 40 (^FCHI), Euro Stoxx 50 (^STOXX50E), OMXS30 (^OMX)
- US: S&P 500 (^GSPC), Nasdaq (^IXIC), Dow Jones (^DJI), VIX (^VIX)

Concurrent fetch via ThreadPoolExecutor (8 workers). Key functions:
- `fetch_global_indices()` → dict of {ticker: {name, change_pct, close, open, prev_close, gap_pct}}
- `format_index_summary(ices)` → formatted text sorted by region with emoji arrows
- `format_index_summary_short(indices)` → token-efficient per-region averages
- `get_global_market_narrative(indices)` → narrative sentence describing market direction per region + VIX interpretation

### 10.5 Sector Rotation (NEW)

`core/sector_momentum.py` — calculates sector momentum from scored universe:
- Groups by sector, computes average score and score change
- Identifies leading/lagging sectors
- Streamlit UI shows sector heatmap, momentum table, AI sector analysis

### 10.6 Universe Health Check (NEW)

`core/universe_health.py` — AI-driven universe maintenance:
- `detect_invalid_tickers(df)` — checks tickers against yfinance (quoteType, exchange, recent price) + blacklist
- `suggest_replacements(ticker, df, top_n=5)` — finds same-sector alternatives sorted by score
- `find_new_stocks(provider="auto")` — uses AI to suggest 5 new stocks in JSON format
- `run_health_check(df)` — orchestrates full health check, loads latest scored universe automatically

### 10.7 Delta Tracker

`data_management/delta_tracker.py` — tracks score changes between runs, surfaces stocks with largest score improvements (potential entry signals). Used in the morning/evening pipeline's `_get_score_deltas()`.

### 10.8 FX Impact & Interest Rate (NEW)

`core/fx_impact.py` — tracks major FX pairs (USDSEK, EURSEK, GBPSEK, NOKSEK) via yfinance. Computes impact on portfolio holdings with FX exposure.

`core/interest_rate.py` — tracks yield curves (Sweden, US, EU) and 10y-3m spreads. Used in macro regime detection.

---

## 11. Backtesting Framework (NEW)

### 11.1 Historical Backtest Engine

`backtesting/backtest.py` — simulates monthly rebalancing of a multi-factor portfolio:
- `fetch_all_prices(tickers, years)` — downloads adjusted close prices via yfinance with rate limiting, filters tickers with <70% data
- `score_at_date(prices, date)` — computes technical momentum score using only data available before that date (no look-ahead bias): 12m momentum (40%), 6m momentum (30%), 3m momentum (20%), distance from 52w high (10%)
- `run_backtest(tickers, years, top_n, benchmark)` — monthly rebalance loop with transaction costs (0.20% per turned-over position), SPY benchmark comparison. Returns cumulative return, Sharpe ratio, max drawdown, win rate, monthly return distribution

### 11.2 Factor Optimizer

`backtesting/factor_optimizer.py` — grid search over factor weight combinations to maximize out-of-sample Sharpe. Uses walk-forward validation with expanding windows. Evaluates IC (Information Coefficient) per factor across time.

### 11.3 Walk-Forward Validation

`backtesting/walk_forward.py` — time-series cross-validation for ML model evaluation. Splits data into expanding training windows and sliding test windows. Validates that the ML signal persists out-of-sample (not just overfit to training data).

---

## 12. Web UI

### 12.1 Streamlit App (Main UI — major expansion)

A comprehensive Streamlit dashboard with modular page structure (`web/pages/` modules split from a 5332-line monolith):

**Pages/Views:**
- **📊 Översikt (Overview):** Global indices table, macro regime indicator, portfolio snapshot, top/bottom stocks with country flags
- **🔍 Sök & Analysera (Search & Analyze):** Ticker search with autocomplete, live price chart (candlestick with MA50/MA200), 16+ metric detail data organized in tabs, radar chart of 8-factor profile, AI analysis at 4 depth levels, custom AI chat with news context injection
- **🔄 Backtesting:** Historical backtest with equity curve, histogram, per-period table, CSV export, AI analysis
- **🏭 Sektorrotation (Sector Rotation):** Sector heatmap, momentum table, AI sector analysis
- **🏦 Smallcap:** Smallcap scanner results, scoring breakdown
- **🚨 Larm & Notiser (Alerts):** Stop-loss alerts, price alerts, news alerts with AI analysis, "Vad stack ut idag?" lazy-load AI summary
- **📈 Paper Trading:** Equity curve, exit pie chart, P&L histogram, stacked bar chart, DCA statistics, KPI cards
- **💼 Min Portfölj (My Portfolio):** Holdings management, add/remove/edit positions, live P&L, portfolio recommendations with ATR stops and Kelly sizing, correlation matrix
- **⭐ Bevakningar (Watchlist):** Watchlist management, quick-add/remove
- **🌍 Globala marknader (Global Markets):** 17 global indices with FX rates and yield curves
- **📰 Nyheter (News):** Multi-source news display
- **ℹ️ Guide & Hjälp (Guide & Help):** User documentation for new users
- **🔧 Admin:** Portfolio management, watchlist editing, scan triggers via GitHub Actions, Avanza CSV import, subscriber management, password protection

**Key features:**
- Password-protected site (`SITE_PASSWORD`) and admin page
- **Country flags** on all tickers in ranking tables, portfolio, and reports
- **24-hour movers** filter on the overview page
- **Macro calendar** for upcoming economic events
- **Tooltips/help** on all metrics explaining calculations
- **Clickable ticker names** that navigate to stock detail in Top-5 cards
- **Side-by-side ranking view** for comparing universe and smallcap
- **Lazy news expanders** — news is only loaded when the user expands the section (saves API calls)
- **AI chat with news context** — custom AI questions inject live news into stock detail are augmented with live news

### 12.2 Flask App

`web/app.py` (port 5001) — lightweight portfolio management:
- Live portfolio manager with autocomplete ticker search
- Add/remove/edit holdings (CSV-backed)
- Live prices and P&L
- Excel export via openpyxl
- GitHub Secrets management (encrypted API key storage)

### 12.3 Stock Detail Page (NEW — major expansion)

`web/stock_detail.py` — comprehensive per-stock deep-dive in Streamlit:
- **Quick Data Cards:** 7 metric cards (Score, Entry, Trend, RSI, P/E, ROE, Piotroski F-Score) with tooltips
- **Price Chart:** Interactive Plotly candlestick chart with selectable periods (1m–Max), MA50/MA200, color-coded volume bars
- **Radar Chart:** Spider chart of 8-factor profile on 0–100 scale
- **Detail Data Table:** 5 tabs of full financial data:
  - Värdering (Valuation): P/E, P/B, P/S, EV/EBITDA, EV/Revenue, FCF Yield
  - Kvalitet (Quality): ROE, ROA, profit margin, operating margin, gross margin
  - Momentum & Teknisk: RSI, MACD, Bollinger Bands, MA distances, volatility
  - Tillväxt (Growth): Revenue growth (1y/3y/5y), earnings growth, quarterly earnings growth
  - Sentiment: Analyst ratings, insider ownership, insider transactions, institutions
- **AI Analysis:** Full depth selector (Snabb/Normal/Djup/Extra djup) with live news context
- **Custom AI Chat:** Ask your own questions about the stock — automatically injects live news context into the AI response
- **News Section:** Multi-source news with clickable links, categorized by freshness

---

## 13. CI/CD & Deployment

### GitHub Actions Workflows:

| Workflow | Schedule | Purpose |
|---|---|---|
| `daily_scan.yml` | 06:30 AM (morning), 18:30 PM (evening) UTC | Morning/evening pipeline runs |
| `daily_scan.yml` | Sunday 08:00 UTC | Weekly full universe scan |
| `daily_scan.yml` | Daily (separate job) | Smallcap scan |
| `news_alerts.yml` | Every 30 min, Mon-Fri 08:00–21:00 UTC | Real-time alerts |
| `train_ml.yml` | On demand | ML model training with CPCV |
| `dependabot.yml` | Weekly | Dependency updates |

All workflows commit scored CSV/ report CSVs back to the repo for Streamlit Cloud to read. Secrets: FINNHUB_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY, email credentials.

**Deployment:** Streamlit Cloud (community tier) reads the committed CSV/Parquet files from the repo. The Flask app runs locally.

---

## 14. Configuration (Updated)

All thresholds and weights in `core/config.py`:
- `FACTOR_WEIGHTS` — 8 factor weights, must sum to 1.0 (assertion enforced)
- `BUY_MORE_PERCENTILE = 80`, `HOLD_PERCENTILE = 50`
- `PARALLEL_WORKERS = 8`, `REQUEST_DELAY_SEC = 0.3`
- `CACHE_HOURS = 720` (fundamentals), `PRICE_CACHE_HOURS = 24`, `DYNAMIC_CACHE_HOURS = 48`
- `SMALLCAP_CONFIG` — complete dict with hard filter thresholds and scoring weights
- `AI_PROVIDER`, `AI_DEEP_PROVIDER`, `AI_TASK_MODE`, `AI_TEMPERATURE = 0.3`
- `SCORE_MODE = "standard"` — can be set to `"sector_neutral"` for sector-neutralized scoring

Factor weights are **static** — they are manually configured and not optimized against out-of-sample returns. The macro regime overlay adjusts them dynamically but only via hard-coded deltas.

---

## 15. Known Weaknesses and Open Questions

### Data quality
- yfinance `info` dict frequently returns `None` for Nordic/Asian stocks. FMP partially fills this. No Börsdata integration (€25–€59/month, Swedish market leader).
- Swedish insider transaction quality from yfinance is poor — now partially addressed by Finansinspektionen integration but HTML parsing is fragile.
- `enterprise_value` from yfinance is often stale (quarterly filing delay). Used in FCF yield.
- Earnings surprise data (`earningsForecastsGrowthRate`) is noisy and often missing.
- No point-in-time fundamental database — backtests of value factors will have look-ahead bias.

### Scoring architecture
- Factor weights are not validated against out-of-sample IC (Information Coefficient). They are based on financial theory and intuition, not empirical optimization on this specific universe.
- Percentile ranking within a heterogeneous global universe (mixing US tech large-caps with Swedish small-caps) makes the scores less meaningful — a "top 20%" stock in the universe could be ranked highly purely due to sector/region composition effects, not stock-specific alpha. **Mitigation:** optional sector-neutral scoring mode.
- The sentiment factor's insider boost (+20/+30 points to an already-computed score) is ad hoc and not back-tested.
- The Piotroski adjustment uses binary scoring but research suggests F-Score is most predictive for small-caps in value situations, not broadly across a large global universe.

### ML predictor
- Only technical features — no fundamental alpha captured.
- Survivorship bias in training data (only currently-covered tickers).
- The 30-day forward return target overlaps with training windows in adjacent folds even after CPCV purging, because price momentum features themselves contain information about past returns.
- XGBoost without regularization tuning on this dataset size may overfit.
- No walk-forward out-of-sample validation beyond CPCV IC metric.
- The `ml_rank` column is blended into the composite score without empirical evidence of additive alpha over the multi-factor score.
- **Black-Litterman integration** helps but depends on the IC estimate itself being stable.

### Portfolio management
- ATR stop-loss multiplier (2.5×) is fixed — not calibrated to the actual loss tolerance or the historical win/loss distribution.
- Half-Kelly defaults (win_rate=0.55, win_loss_ratio=1.5) are used until 20 trades close, which means early position sizing advice is based on generic assumptions.
- No tax-aware selling logic (Swedish: 30% capital gains, loss harvesting rules).
- Correlation analysis uses raw Pearson correlation — may be less useful than DCC-GARCH for time-varying correlations, especially during market stress.

### Pipeline
- The async layer (`aiohttp`) is implemented but not yet wired into the main scan pipeline — still uses `ThreadPoolExecutor` with 8 workers.
- No formal unit/integration test suite for data quality checks — `MIN_DATA_QUALITY = 0.5` threshold is a blunt instrument.
- No monitoring for data freshness (a cached result from 699 hours ago looks the same as one from 1 hour ago).
- **News alerts** rely on Finnhub free tier (limited coverage for European stocks) and Google News RSS (fragile, subject to rate limiting and HTML structure changes).

---

## 16. Research Questions for Gemini Deep Research

1. **Factor construction:** What is the empirical evidence for and against combining a global (US + European + Asian) universe in a single percentile-ranked multi-factor model? What is the best practice for neutralizing sector and country effects before ranking?

2. **Information Coefficient optimization:** What methods (e.g., Bayesian shrinkage, Black-Litterman, minimum-variance factor weights) are most appropriate for a private investor with ~1,000 stocks but limited historical backtest data?

3. **Insider signal quality:** What does peer-reviewed literature say about the predictive power of insider transactions? Is cluster buying or executive buying more predictive? How many days/weeks is the signal active before decaying?

4. **FCF Yield vs EV/EBITDA:** Under what market conditions does FCF yield outperform EV/EBITDA as a value factor, and vice versa? Is a 50/50 blend supported empirically?

5. **ATR stop-loss calibration:** What multiplier (1.5×, 2×, 2.5×, 3×) of ATR14 empirically produces the best Sharpe ratio for medium-term (30–90 day) holding patterns? What is the literature on volatility-adjusted stops vs. fixed percentage stops?

6. **ML feature engineering:** What technical features have shown the most persistent, non-decaying IC in academic literature for 30-day forward return prediction? Is there evidence that mixing technical and fundamental features in gradient boosting helps, given the point-in-time problem?

7. **Swedish small-cap specifics:** What factors have historically produced alpha in the Swedish small-cap market specifically? Is the Piotroski F-Score as effective in Scandinavian markets as in US markets where it was developed?

8. **Macro regime overlays:** What is the evidence for and against dynamically adjusting factor weights based on market regime? Does this improve risk-adjusted returns or just add complexity and overfitting risk?

9. **Data source:** For a private investor trading primarily Swedish and Nordic stocks, what is the cost-benefit of Börsdata Pro+ API (€25–€59/month) versus free alternatives (yfinance + FI open data + FMP free tier + multi-source news)? What data quality gaps exist and which gaps actually matter for returns?

10. **Position sizing:** How does Half-Kelly position sizing perform empirically vs. equal-weight and full-Kelly in a retail multi-factor portfolio context? What are the typical adjustments professional quants make to Kelly for estimation error?

11. **News signal integration (NEW):** What is the evidence for incorporating news sentiment as a factor in quantitative stock selection? How should news signals be decayed and combined with traditional factors? Is multi-source news aggregation (Finnhub + Google RSS + Nasdaq + Yahoo) adding alpha, or just noise?

12. **Sector-neutral vs. absolute scoring (NEW):** For a heterogeneous global universe mixing US mega-caps with European small-caps, does sector-neutralized scoring empirically improve or degrade the information coefficient of the multi-factor model compared to absolute percentile ranking?

13. **Real-time alert AI evaluation (NEW):** What is the false-positive rate of AI-based news alert filtering? Does the AI add value over simple keyword-based filtering for a private investor's portfolio? Is the 30-minute polling interval appropriate, or should it be event-driven?