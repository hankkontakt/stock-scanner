# AI-Driven Stock Scanner — Architecture Brief for Deep Research

## Purpose of this document

This is a technical description of a personal quantitative stock-scanning system built in Python. I am asking for a deep research review focused on:
1. Which parts of the architecture have the largest measurable impact on risk-adjusted returns (Sharpe/Sortino)?
2. What are the most evidence-based improvements I could implement next?
3. Where does the current design introduce the most bias, data leakage, or signal decay?

---

## 1. System Overview

A fully automated, multi-factor quantitative stock scanner running locally on Windows. It covers a global equity universe (~1,000–1,200 tickers), scores every stock daily against 8 factor categories, generates AI-written narrative analysis, manages a real portfolio, runs parallel paper-trading, and produces weekly PDF/markdown reports. The user is a private investor, not an institution.

**Tech stack:** Python 3.12, yfinance (primary data), FMP API (fallback fundamentals), Finansinspektionen open data (Swedish insider transactions), DeepSeek / Gemini LLMs, XGBoost / sklearn HistGradientBoosting, Streamlit + Flask web UI.

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

A `custom_universe.json` allows adding tickers dynamically from the UI. Deduplication is handled with `dict.fromkeys()`.

**Known gap:** Universe is static and hand-curated. No automatic addition of IPOs, spin-offs, or newly listed stocks. No exclusion of penny stocks, suspended trading, or stocks below minimum liquidity thresholds at the universe level (liquidity is scored, but not used as a hard filter for the main universe).

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

### 3.2 FMP Fallback (Financial Modeling Prep)

`_get_fmp_fundamentals(ticker)` calls `/api/v3/key-metrics-ttm/{ticker}`. Fields filled when yfinance returns `None`: P/E (trailing), P/B, ROE, ROA, EV/EBITDA, revenue growth. Free tier: 250 calls/day. 720h cache makes this usable for ~1,000 stocks at ~33 calls/day.

### 3.3 Finansinspektionen (Swedish insider transactions)

`core/fi_insider_fetcher.py` queries FI's public search register (`marknadssok.fi.se`) for `.ST` tickers. All Swedish listed companies must report insider trades to FI within 3 business days under EU MAR. The module:
- Converts ticker → company name via yfinance, strips legal suffixes
- Tries JSON XHR endpoint, falls back to HTML table parsing
- Detects VD/CFO buying and cluster buying (≥3 distinct insiders in 30 days)
- 24h cache

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

---

## 4. Scoring Engine

`core/scoring.py` — converts raw metrics to a 0–100 composite score using **percentile ranking within the universe** (not absolute thresholds). This means scores are relative: a stock at the 80th percentile gets ~80 regardless of its absolute P/E.

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

**FCF Yield scoring:** `calc_fcf_yield_score()` uses `free_cash_flow / enterprise_value`. Falls back to (market_cap + debt − cash) when `enterprise_value` is missing. Blended 50/50 with EV/EBITDA in the value score.

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

### 4.4 Smallcap scanner (separate module)

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

`core/ml_predictor.py` — gradient-boosted regression model. XGBoost if installed, sklearn `HistGradientBoostingRegressor` as fallback.

**Two separate models:** `models/ml_universe.pkl` (large-cap universe) and `models/ml_smallcap.pkl` (Swedish small-caps).

**Features (technical only, 15 features):**
```
ret_1m, ret_3m, ret_6m, ret_12m, rsi_14, macd_signal (bool),
vs_ma50, vs_ma200, volume_ratio, volatility, bb_position,
price_vs_52w_high, momentum_3m_rank, momentum_6m_rank, pct_from_52w_high
```

Fundamentals are excluded to avoid point-in-time problems in backtesting.

**Target:** `forward_return_30d` — actual 30-calendar-day return.

**Training:** `train_with_cpcv()` uses **Combinatorial Purged Cross-Validation** (Lopez de Prado). 6 folds, purge window = 30 days (matches forward return horizon), embargo = 1% of dataset. Evaluates information coefficient (IC, Spearman correlation between predicted and actual returns) per fold plus hit rate. Final model is trained on all data.

**Output columns added to scored DataFrame:**
- `predicted_return` — model's forward return estimate
- `ml_rank` — percentile rank 0–100 within universe

**Known limitations:** Features are all derived from the same price series that also determines the target. The model has no alpha from fundamentals. Training dataset is generated from the live universe's historical data — survivorship bias is present because only currently-covered tickers are in the training set.

---

## 6. AI Analysis Layer

`core/ai_analysis.py` — wraps LLM calls with caching, retry, and provider fallback.

**Providers:** DeepSeek (default, paid, stable) and Gemini (free, rate-limited at 15 req/min). Provider selection is configurable per task: `AI_TASK_MODE = "hybrid"` routes light tasks to Gemini and heavy tasks to DeepSeek.

**Model settings:** Temperature 0.3, max tokens varies by depth. DeepSeek model: `deepseek-chat`. Gemini model: `gemini-2.5-flash`.

**Depth levels (control WHAT data is sent, not just response length):**

| Depth | Data sent to LLM | System prompt addon |
|---|---|---|
| Snabb | 6 key fields only: P/E, ROE, Momentum, Revenue Growth, Piotroski F-Score, Entry Signal | Max 3 sentences |
| Normal | All standard fields | No addon |
| Djup | All fields + FCF Yield, EV/EBITDA, Bollinger Band, insider ownership, RSI, MACD, returns | Deep analysis with sector comparison + buy/sell recommendation |
| Extra djup | All fields + ROA, Operating/Gross Margin, Institution %, D/E, Beta, Volatility | Institutional-style: FCF analysis, scenario analysis (bull/base/bear), position sizing + entry/exit |

Swedish stock caveat: For `Djup` and `Extra djup` on `.ST` tickers, a note is appended: "K3/K2 Swedish accounting — untaxed reserves (obeskattade reserver) reduce reported earnings, ROA and margins are likely understating actual profitability."

**Analysis functions:** `analyze_stock()`, `analyze_portfolio()`, `analyze_sector()`, `analyze_news()`, `compare_stocks()`, `generate_market_summary()`, `generate_morning_brief()`, `generate_weekly_ai_analysis()`. All have `depth` in their cache key.

---

## 7. Portfolio Management

`portfolio/portfolio.py` — analyzes actual holdings vs. scored universe.

**Recommendation logic (percentile-based):**
- Top 20% of universe → `KÖP MER` (Buy More), unless RSI > 75 → downgrade to `BEHÅLL`
- Top 20–50% → `BEHÅLL` (Hold), unless 3m return < −15% → downgrade to `BEVAKA`
- Bottom 50% + 3m return < −10% → `SÄLJ/MINSKA` (Sell/Reduce)
- Bottom 50% + percentile > 75 → `SÄLJ/MINSKA`
- Otherwise → `BEVAKA` (Watch)

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

`get_kelly_inputs(min_trades=20)` exports win_rate, win_loss_ratio, n_trades from closed trade history for Half-Kelly calculation in the portfolio module.

Two separate paper-trading instances: one for the main universe, one for small-caps.

---

## 9. Reporting

**`reporting/report_builder.py`:** Generates Markdown weekly reports with top 10 recommendations, portfolio analysis, sector breakdown, macro regime summary, AI narrative.

**Morning scan (`morning_scan.py`):** Runs at market open, scans for overnight catalysts, entry signals, earnings surprises. Sends email via SMTP.

**Evening scan (`evening_scan.py`):** End-of-day update, position review, ATR stop checks.

**Delta tracker (`data_management/delta_tracker.py`):** Tracks score changes between runs, surfaces stocks with largest score improvements (potential entry signals).

**Earnings calendar (`core/earnings_calendar.py`):** Tracks upcoming earnings dates from yfinance, flags active holdings with earnings in the next 7 days.

---

## 10. Web UI

Two separate web interfaces:

**Flask app (`web/app.py`, port 5001):**
- Live portfolio manager with autocomplete ticker search
- Add/remove/edit holdings (CSV-backed)
- Live prices and P&L
- Excel export via openpyxl
- GitHub Secrets management (encrypted API key storage)

**Streamlit app (main scanner UI):**
- Runs the full scoring pipeline on demand
- Shows ranked universe with filtering by sector, region, score components
- Individual stock deep-dives with AI analysis
- Portfolio recommendations tab with ATR stops and Kelly sizing
- Smallcap scanner tab
- Correlation matrix visualization
- Paper trading performance tracking
- Macro regime indicator
- AI depth selector (Snabb/Normal/Djup/Extra djup) in sidebar

---

## 11. Configuration

All thresholds and weights in `core/config.py`:
- `FACTOR_WEIGHTS` — 8 factor weights, must sum to 1.0 (assertion enforced)
- `BUY_MORE_PERCENTILE = 80`, `HOLD_PERCENTILE = 50`
- `PARALLEL_WORKERS = 8`, `REQUEST_DELAY_SEC = 0.3`
- `CACHE_HOURS = 720` (fundamentals), `PRICE_CACHE_HOURS = 24`, `DYNAMIC_CACHE_HOURS = 48`
- `SMALLCAP_CONFIG` — complete dict with hard filter thresholds and scoring weights
- `AI_PROVIDER`, `AI_DEEP_PROVIDER`, `AI_TASK_MODE`, `AI_TEMPERATURE = 0.3`

Factor weights are **static** — they are manually configured and not optimized against out-of-sample returns. The macro regime overlay adjusts them dynamically but only via hard-coded deltas.

---

## 12. Known Weaknesses and Open Questions

### Data quality
- yfinance `info` dict frequently returns `None` for Nordic/Asian stocks. FMP partially fills this. No Börsdata integration (€25–€59/month, Swedish market leader).
- Swedish insider transaction quality from yfinance is poor — now partially addressed by Finansinspektionen integration but HTML parsing is fragile.
- `enterprise_value` from yfinance is often stale (quarterly filing delay). Used in FCF yield.
- Earnings surprise data (`earningsForecastsGrowthRate`) is noisy and often missing.
- No point-in-time fundamental database — backtests of value factors will have look-ahead bias.

### Scoring architecture
- Factor weights are not validated against out-of-sample IC (Information Coefficient). They are based on financial theory and intuition, not empirical optimization on this specific universe.
- Percentile ranking within a heterogeneous global universe (mixing US tech large-caps with Swedish small-caps) makes the scores less meaningful — a "top 20%" stock in the universe could be ranked highly purely due to sector/region composition effects, not stock-specific alpha.
- No sector neutralization — sector momentum effects can dominate stock selection.
- The sentiment factor's insider boost (+20/+30 points to an already-computed score) is ad hoc and not back-tested.
- The Piotroski adjustment uses binary scoring but research suggests F-Score is most predictive for small-caps in value situations, not broadly across a large global universe.

### ML predictor
- Only technical features — no fundamental alpha captured.
- Survivorship bias in training data (only currently-covered tickers).
- The 30-day forward return target overlaps with training windows in adjacent folds even after CPCV purging, because price momentum features themselves contain information about past returns.
- XGBoost without regularization tuning on this dataset size may overfit.
- No walk-forward out-of-sample validation beyond CPCV IC metric.
- The `ml_rank` column is blended into the composite score without empirical evidence of additive alpha over the multi-factor score.

### Portfolio management
- ATR stop-loss multiplier (2.5×) is fixed — not calibrated to the actual loss tolerance or the historical win/loss distribution.
- Half-Kelly defaults (win_rate=0.55, win_loss_ratio=1.5) are used until 20 trades close, which means early position sizing advice is based on generic assumptions.
- No tax-aware selling logic (Swedish: 30% capital gains, loss harvesting rules).
- Correlation analysis uses raw Pearson correlation — may be less useful than DCC-GARCH for time-varying correlations, especially during market stress.

### Pipeline
- The async layer (`aiohttp`) is implemented but not yet wired into the main scan pipeline — still uses `ThreadPoolExecutor` with 8 workers.
- No formal unit/integration test suite for data quality checks — `MIN_DATA_QUALITY = 0.5` threshold is a blunt instrument.
- No monitoring for data freshness (a cached result from 699 hours ago looks the same as one from 1 hour ago).

---

## 13. Research Questions for Gemini Deep Research

1. **Factor construction:** What is the empirical evidence for and against combining a global (US + European + Asian) universe in a single percentile-ranked multi-factor model? What is the best practice for neutralizing sector and country effects before ranking?

2. **Information Coefficient optimization:** What methods (e.g., Bayesian shrinkage, Black-Litterman, minimum-variance factor weights) are most appropriate for a private investor with ~1,000 stocks but limited historical backtest data?

3. **Insider signal quality:** What does peer-reviewed literature say about the predictive power of insider transactions? Is cluster buying or executive buying more predictive? How many days/weeks is the signal active before decaying?

4. **FCF Yield vs EV/EBITDA:** Under what market conditions does FCF yield outperform EV/EBITDA as a value factor, and vice versa? Is a 50/50 blend supported empirically?

5. **ATR stop-loss calibration:** What multiplier (1.5×, 2×, 2.5×, 3×) of ATR14 empirically produces the best Sharpe ratio for medium-term (30–90 day) holding periods? What is the literature on volatility-adjusted stops vs. fixed percentage stops?

6. **ML feature engineering:** What technical features have shown the most persistent, non-decaying IC in academic literature for 30-day forward return prediction? Is there evidence that mixing technical and fundamental features in gradient boosting helps, given the point-in-time problem?

7. **Swedish small-cap specifics:** What factors have historically produced alpha in the Swedish small-cap market specifically? Is the Piotroski F-Score as effective in Scandinavian markets as in US markets where it was developed?

8. **Macro regime overlays:** What is the evidence for and against dynamically adjusting factor weights based on market regime? Does this improve risk-adjusted returns or just add complexity and overfitting risk?

9. **Data source:** For a private investor trading primarily Swedish and Nordic stocks, what is the cost-benefit of Börsdata Pro+ API (€25–€59/month) versus free alternatives (yfinance + FI open data + FMP free tier)? What data quality gaps exist and which gaps actually matter for returns?

10. **Position sizing:** How does Half-Kelly position sizing perform empirically vs. equal-weight and full-Kelly in a retail multi-factor portfolio context? What are the typical adjustments professional quants make to Kelly for estimation error?
