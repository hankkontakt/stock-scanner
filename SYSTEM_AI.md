# MarketScan – AI System Documentation

## Overview

MarketScan is a multi-factor stock scanner and portfolio management system focused on the Swedish and global equity markets. It scans ~700+ tickers (global) and ~280 Swedish small/micro-cap stocks, scoring them across 8 factor dimensions to generate buy/hold/sell recommendations.

## Project Structure

```
stock-scanner/
├── scans/                    # Main scan entry points
│   ├── scan.py               # Weekly Sunday scan (700+ stocks, full report)
│   ├── morning_scan.py       # Daily morning brief (09:35 CET)
│   ├── evening_scan.py       # Daily evening report (17:30 CET)
│   └── opportunity_scan.py   # Intra-week opportunity detection
├── core/                     # Core framework and analysis modules
│   ├── config.py             # All configuration constants and factor weights
│   ├── data_fetcher.py       # yfinance data fetching with caching/retry
│   ├── scoring.py            # Multi-factor scoring engine (value, quality, momentum, etc.)
│   ├── filters.py            # Entry/exit signal filters + ticker health/strike system
│   ├── sentiment.py          # Finnhub news sentiment analysis
│   ├── alerts.py             # Email alert system (HTML + Markdown)
│   ├── logger.py             # Structured JSON scan logging
│   ├── macro_regime.py       # Market regime detection (bull/bear/uncertain)
│   ├── sector_momentum.py    # Sector ETF momentum scoring
│   ├── sectors.py            # Sector classification and ranking
│   ├── relative_strength.py  # Relative strength calculations
│   ├── piotroski.py          # Piotroski F-Score (financial health)
│   ├── earnings_calendar.py  # Earnings date tracking
│   ├── news_fetcher.py       # Multi-source news (Finnhub, Google RSS, Nasdaq Nordic)
│   ├── currency.py           # Currency conversion utilities
│   ├── extra_data.py         # Finnhub extra data enrichment
│   └── test_pipeline.py      # Quick pipeline integration test
├── portfolio/                # Portfolio management
│   ├── portfolio.py          # Portfolio analysis, P&L, scoring
│   ├── portfolio_analysis.py # Risk parity, sector exposure, recommendations
│   ├── positions.py          # Transaction logging and position tracking
│   ├── watchlist.py          # Watchlist management (JSON-based)
│   └── paper_trading.py      # Paper trading simulation
├── data_management/          # Data import and delta tracking
│   ├── delta_tracker.py      # Week-over-week score change tracking
│   └── avanza_import.py      # Avanza CSV portfolio import
├── reporting/                # Report generation
│   └── report_builder.py     # Markdown report assembly helpers
├── web/                      # Web interfaces
│   ├── app.py                # Flask web server (portfolio, watchlist, Avanza import)
│   ├── streamlit_app.py      # Streamlit interactive dashboard
│   └── templates/            # Flask HTML templates
├── backtesting/              # Backtesting and optimization
│   ├── backtest.py           # Historical backtesting engine
│   ├── walk_forward.py       # Walk-forward analysis for robustness
│   └── factor_optimizer.py   # Bayesian factor weight optimization
├── smallcap/                 # Small-cap subsystem (Swedish)
│   ├── scanner.py            # Small-cap main scanner entry
│   ├── scoring.py            # Small-cap specific scoring
│   ├── universe.py           # Swedish small-cap universe definition
│   ├── filters.py            # Small-cap specific filters
│   ├── report.py             # Small-cap report builder
│   ├── history.py            # Small-cap score history tracking
│   └── insider.py            # Insider transaction data
├── tools/                    # Independent utilities
│   ├── ticker_health.py      # Ticker validation and health monitoring
│   └── __init__.py
├── .github/workflows/        # CI/CD automation
│   ├── morning_scan.yml      # 09:35 CET daily morning scan
│   └── evening_scan.yml      # 17:30 CET daily evening scan
├── data/                     # Runtime data files
│   ├── blacklist.json        # Permanently removed tickers
│   ├── paper_portfolio.json  # Paper trading positions
│   ├── paper_trades.json     # Paper trade history
│   ├── strike_list.json      # Tickers on warning (2 strikes before removal)
│   └── smallcap_scores_prev.json
├── reports/                  # Generated reports (CSV + Markdown)
├── KOMMANDON.md              # User command reference
├── SYSTEM_AI.md              # This file – system architecture overview
└── requirements.txt          # Python dependencies
```

## Scoring Architecture

### Factor Weights (config.FACTOR_WEIGHTS)
- **Value (22%)**: P/E, P/B, EV/EBITDA, PEG ratio – undervalued stocks
- **Quality (18%)**: ROE, profit margins, debt/equity, free cash flow – strong fundamentals
- **Momentum (18%)**: 1m/3m/6m/12m returns, RSI, MA50/MA200 – trending stocks
- **Growth (13%)**: Revenue growth, earnings growth, quarterly growth – expanding companies
- **Risk (9%)**: Beta, volatility, drawdown from 52w high – low-risk preference
- **Sentiment (10%)**: Finnhub news sentiment, analyst ratings – market perception
- **Size (5%)**: Market cap tilt – slight small-cap bias
- **Dividend (5%)**: Dividend yield and payout ratio – income component

Each factor produces a 0–100 score. The weighted average gives `score_total` (0–100).

### Signal Generation
- **entry_signal**: STARK (≥70), OK (55–69), VÄNTA (40–54), EJ AKTUELL (<40)
- **confidence_label**: HÖG, MEDEL, LÅG (composite of data quality + score consistency)
- **trend_signal**: UPPTREND, NEUTRAL, NEDTREND (based on MA50/MA200 cross + RSI)
- **trend_capped**: Boolean – true if below both MA50 and MA200

### Special Adjustments
- **Holding companies** (investment entities): score discounted by 15%
- **Commodity companies**: score discounted by 10%
- **Bear market regime**: STARK→OK downgrade for scores < 75
- **Sector cap**: max 2 stocks per sector in Top-N recommendations
- **Piotroski F-Score**: minimum 2 required for Top-N inclusion
- **Volatility filter**: score_risk < 25 excluded from Top-N
- **Strike system**: 3 failed fetches → permanent blacklist

## Data Pipeline

```
1. FETCH: yfinance → raw DataFrame (700+ tickers, ~2 min with 8 workers)
   ├── Stock info (PE, PB, ROE, margins, debt, growth rates)
   ├── Price history (1mo/3mo/6mo/12mo returns, volatility)
   └── Technical indicators (RSI, MA50, MA200, 52w high/low)

2. SENTIMENT: Finnhub API → sentiment scores (if API key configured)

3. SCORE: scoring.py → scored DataFrame (0-100 per factor + total)

4. ENRICH:
   ├── Sector momentum adjustment
   ├── Piotroski F-Score
   ├── Extra data (Finnhub fundamentals)
   └── Ticker health (strike system)

5. FILTER: filters.py → entry signals, confidence, trend

6. SECTOR ANALYSIS: sectors.py → sector rankings and relatve strength

7. DELTA TRACKING: compare with previous week's scores

8. PORTFOLIO: analyze holdings, generate recommendations

9. NEWS: Finnhub + Google News RSS + Nasdaq Nordic

10. REPORT: build_report() → Markdown report + CSV export
```

## Automation (GitHub Actions)

- **Morning scan**: Weekdays 09:35 CET (`scans/morning_scan.py`) → 30 min timeout
  - Market overview, stoploss alerts, daily P&L, opportunities from Top 50
- **Evening scan**: Weekdays 17:30 CET (`scans/evening_scan.py`) → 30 min timeout
  - Portfolio dashboard, hold/sell analysis, paper trading update
- **Weekly scan**: Sunday (`scans/scan.py`) → 100 min watchdog timeout
  - Full universe scan, complete report with executive summary + Top N recommendations
- **Small-cap scan**: Triggered manually or via separate workflow
  - Swedish small/micro-cap focused analysis

## Configuration (config.py)

Key parameters:
- `UNIVERSE`: List of ~700 ticker symbols (global)
- `FACTOR_WEIGHTS`: 8-factor scoring weights (sum = 1.0)
- `MIN_DATA_QUALITY`: 0.3 (tickers below this are excluded)
- `TOP_N_RECOMMENDATIONS`: 20 (number of stocks in Top-N list)
- `BUY_MORE_PERCENTILE`: 0.90, `HOLD_PERCENTILE`: 0.50
- `CACHE_HOURS`: 4 (data caching duration)
- `PARALLEL_WORKERS`: 8 (fetch concurrency)
- `FINNHUB_PARALLEL_WORKERS`: 3, `FINNHUB_CALLS_PER_MINUTE`: 30

## Key Design Decisions

1. **Flat scoring architecture** – factors are additive with fixed weights, not ML-based. This provides transparency and debuggability.

2. **Swedish-first approach** – OMXS30 benchmarks, Swedish RSS news, Nasdaq Nordic regulatory data. However, the system supports global tickers.

3. **Strike system** – self-healing: tickers that fail to fetch data 3 times are automatically blacklisted. Protects against dead/delisted tickers.

4. **Sector diversification** – max 2 stocks per sector in Top-N prevents concentration risk.

5. **Pessimistic by default** – holding/commodity companies penalized, bear market raises thresholds, volatility filtered.

6. **Paper trading** – simulates strategy performance with weekly pick recording and price updates.

## Dependencies

Core: pandas, numpy, yfinance, requests, curl_cffi
Email: smtplib (stdlib)
Web: flask, streamlit
News: feedparser, beautifulsoup4
Optimization: optuna, scipy
Sentiment: Finnhub API
