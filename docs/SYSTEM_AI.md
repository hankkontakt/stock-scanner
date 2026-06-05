# MarketScan — SYSTEM_AI.md
> Komplett teknisk referens för AI-agenter. Uppdateras vid varje kodändring.

---

## 0. Underhållsprotokoll

**Obligatoriskt för alla AI-modeller:**

| Händelse | Skriv i |
|---|---|
| Genomförd kodändring | Relevant sektion (§3–§15) + en rad i §18 Ändringslogg |
| Bugg eller risk | §17 Kända problem |
| Förbättringsidé | §17 |
| Fixat något från §17 | Markera `DONE ✅`, radera inte |

Format ändringslogg: `YYYY-MM-DD — beskrivning (fil:rad)`. Nyaste överst.

---

## 1. Snabbreferens

### 1.1 Vanligaste uppgifter

| Uppgift | Var |
|---|---|
| Lägg till/ta bort ticker | `core/config.py` → `UNIVERSE` |
| Ändra faktorvikter | `core/config.py` → `FACTOR_WEIGHTS` |
| Ny entry-signal-regel | `core/filters.py:calc_entry_signal()` |
| Debugga morning/evening-körning | `core/daily_pipeline.py:run_pipeline()` |
| Se pipeline-fel | `data/scan_log.json`, `data/fetch_errors.json` |
| Se Streamlit-fel | `data/streamlit_errors.jsonl` |
| Se senaste CI-körning | `data/ci_reports/last_daily_scan.json` |
| Starta AI-debug | `python scripts/ai_debug.py --quick` |
| Ändra AI-systemprompter | `core/ai_prompts.py` |
| Ändra e-postschema | `.github/workflows/daily_scan.yml` → cron-sektionen |
| Blacklista ticker | `data/blacklist.json` |

### 1.2 Kritiska gotchas

- **Streamlit skriver aldrig till disk** — all persistent data måste git-committas av CI
- **CSS-klasser via st.markdown injiceras opålitligt** — använd inline `style=` eller `st.metric()`/`st.success()` etc.
- **GitHub Actions vet inget om DST** — scheman kräver dubbla crons (CEST + CET), se §5.3
- **load_smallcap_reports()** läser `.parquet` (prio) + `.csv` (fallback) — inte bara csv
- **entry_signal uppdateras** av `apply_all_filters()` som anropas i `update_scored_with_prices()` — detta är korrekt
- **stock_detail.py** anropar `ai_chat()` med `system_prompt_override=SYSTEM_PROMPT_STOCK_ANALYSIS` — inte SYSTEM_PROMPT_CHAT

---

## 2. Systemöversikt

**Vad:** Automatiserad multi-faktor kvantitativ aktie-scanner. ~1200 globala tickers med nordisk fokus. Kör på GitHub Actions + Streamlit Cloud, ingenting lokalt.

**Stack:** Python 3.11, yfinance, pandas, XGBoost, Streamlit, GitHub Actions, DeepSeek/Gemini AI

### 2.1 Designbeslut

| Beslut | Varför |
|---|---|
| Filbaserad lagring (JSON/CSV/Parquet) | Git-historik = versionshantering, Streamlit läser reports/-mappen direkt |
| Percentilrankning inom universum | Relativa poäng 0-100, inte absoluta P/E-tal |
| Region-neutraliserade fundamenta | Nordiskt P/E 15 jämförs inte mot Nasdaq-tech P/E 35 |
| Dubbelt format (Parquet + CSV) | Parquet = snabb läsning, CSV = git-diffbar |
| Atomisk skrivning (tmp → rename) | Förhindrar korrupta filer vid avbrott |
| Inga fundamenta i ML-modellen | Point-in-time-integritet, inga look-ahead bias |

---

## 3. Katalogstruktur

```
stock-scanner/
├── .github/workflows/        # 6 CI/CD-workflows
│   ├── daily_scan.yml        # Morning/evening/weekly/smallcap pipeline
│   ├── tests.yml             # pytest + ruff vid varje push
│   ├── train_ml.yml          # ML-träning (manuell trigger)
│   ├── news_alerts.yml       # Nyhetsbevakning var 30:e min vardagar
│   ├── keep_alive.yml        # Streamlit Cloud keep-alive
│   └── diagnose.yml          # Automatisk systemdiagnos
├── core/                     # Central motor (~35 filer)
│   ├── config.py             # ALL konfiguration: universum, vikter, konstanter
│   ├── daily_pipeline.py     # Huvud-orkestrator (CENTRAL FIL)
│   ├── scoring.py            # Faktorscoringmotor
│   ├── filters.py            # Entry/exit-signaler, strike-system
│   ├── data_fetcher.py       # yfinance-hämtning + cache + timeout
│   ├── data_fetcher_batch.py # Batch-hämtning + update_scored_with_prices()
│   ├── ai_analysis.py        # AI-motor (DeepSeek + Gemini + Claude)
│   ├── ai_prompts.py         # Alla system-prompt-konstanter
│   ├── ai_router.py          # Provider-routing med fallback-kedja
│   ├── ml_predictor.py       # XGBoost-modell
│   ├── ml_features.py        # Feature-beräkning (extraherat från ml_predictor)
│   ├── pipeline_report.py    # Markdown-rapportbyggare
│   ├── pipeline_alerts.py    # STARK-signaler + score-drift
│   ├── email_template.py     # E-postmotor (mistune HTML)
│   ├── news_fetcher.py       # Multi-source nyhetsaggregering
│   ├── news_alerts.py        # AI-drivna nyhetsnotiser
│   ├── piotroski.py          # Piotroski F-Score
│   ├── macro_regime.py       # Marknadsregim-detektion
│   ├── sector_momentum.py    # Sektor-ETF-momentum
│   ├── universe_manager.py   # Universum-hantering + kandidat-spårning
│   ├── fi_insider_fetcher.py # Finansinspektionen insider-scraper
│   ├── monitoring/           # health.py, metrics.py, staleness.py, resources.py
│   └── providers/            # deepseek_provider.py, gemini_provider.py, claude_provider.py
├── portfolio/                # Portföljhantering
│   ├── paper_trading.py      # Paper trading-simulation
│   ├── black_litterman.py    # Black-Litterman-optimering
│   ├── hierarchical_risk_parity.py  # Lopez de Prado HRP
│   ├── mean_variance.py      # Medel-varians-optimering
│   ├── kelly.py              # Kelly-kriteriet
│   ├── monte_carlo.py        # Monte Carlo-simulering
│   └── portfolio.py          # Innehavsanalys
├── web/
│   ├── streamlit_app.py      # Huvud-Streamlit-app (routing, sidebar, auth)
│   ├── stock_detail.py       # Per-aktie djupanalys
│   ├── utils.py              # Delade web-helpers (load_scan_reports osv.)
│   ├── app.py                # Flask REST API (ej Streamlit)
│   ├── ui/                   # Återanvändbara UI-komponenter
│   │   ├── components.py     # metric_card, kpi_grid, page_header, data_table osv.
│   │   ├── css.py            # Centralt CSS-designsystem
│   │   ├── tokens.py         # Design-tokens (färger, typsnitt)
│   │   ├── charts.py         # Plotly-chart-bibliotek
│   │   ├── screener_utils.py # Snabbfilter, kolumnväljare, paginering, export
│   │   └── experience_mode.py # Nybörjar/Expert-läge
│   └── pages/                # 19 Streamlit-sidor
│       ├── overview.py       # Översikt/cockpit
│       ├── weekly_scan.py    # Veckoranking
│       ├── smallcap.py       # Småbolag
│       ├── stock_comparison.py # Jämför 2-5 aktier
│       ├── portfolio.py      # Portföljhantering (stor, ~110KB)
│       ├── ai_page.py        # AI-analys + ensemble
│       ├── ai_journal.py     # AI-rekommendationshistorik
│       ├── alerts.py         # Larm & notiser
│       ├── admin_page.py     # Admin-layout (5 flikar)
│       ├── admin.py          # Admin data-services
│       └── admin_tabs/       # tab_system, tab_pipeline, tab_universe, tab_settings, tab_metrics
├── smallcap/                 # Småbolagssubsystem (scanner, universe, scoring, filters)
├── backtesting/              # Backtesting-motor + walk-forward + faktoroptimering
├── strategy/                 # Strategy-motor (DSL, optimizer, pre-built strategies)
├── tests/                    # Testsuite (~430 tester)
├── scripts/                  # ai_debug.py, diagnose.py, fetch_ci_logs.py, train_ml.py
├── data/                     # Runtime-data (git-committad)
├── reports/                  # Genererade scan-rapporter
├── models/                   # Tränade ML-modeller
└── docs/                     # SYSTEM_AI.md, KOMMANDON.md, AI_QUICKSTART.md
```

---

## 4. Scoring-motor

### 4.1 De 10 faktorerna

| # | Faktor | Vikt | Nyckelinputs | Funktion |
|---|---|---|---|---|
| 1 | Value | 21.3% | FCF Yield (70%), EV/EBITDA (30%), fallback P/E→P/B→P/S | `calc_value_score()` |
| 2 | Quality | 17.5% | ROE, ROA, vinstmarginal, rörelsemarginal | `calc_quality_score()` |
| 3 | Momentum | 17.5% | return_12m/6m/3m, pct_from_52w_high | `calc_momentum_score()` |
| 4 | Growth | 12.6% | revenue_growth, earnings_growth, earnings_surprise | `calc_growth_score()` |
| 5 | Risk | 8.7% | D/E (inverterat), current_ratio, volatilitet (inv), beta (inv) | `calc_risk_score()` |
| 6 | Sentiment | 9.7% | sentiment_raw, insider_executive_buy (+20), insider_cluster (+30) | `calc_sentiment_score()` |
| 7 | Size | 4.85% | market_cap (log, inverterat — mindre är bättre) | `calc_size_score()` |
| 8 | Dividend | 4.85% | dividend_yield (cap 15%), payout_ratio-straff | `calc_dividend_score()` |
| 9 | Short interest | 3% | short_pct_float / short_ratio | `calc_short_interest_score()` |
| 10 | Options flow | 2% | options_flow_signal (put/call) | `calc_options_flow_score()` |

Vikter i `config.FACTOR_WEIGHTS` (summa = 1.0, vaktas av test).

### 4.2 Scoring-pipeline

```
score_universe_sector_neutralized(df, regime)   # Veckovis default
  │
  ├─ _region_neutralize_fundamentals(df)   # Subtrahera REGIONmedian (idempotent-flagga)
  ├─ Sektor-demeaning per sector           # Subtrahera SEKTORmedian (banker jämförs med banker)
  │                                         # Momentum AVSIKTLIGT globalt (ej sektor-demeanat)
  ├─ calc_value/quality/momentum/…/options_flow_score()
  ├─ get_dynamic_weights(regime, FACTOR_WEIGHTS)  # Regimjustering
  ├─ get_sector_weights(sector, w) per rad        # Per-sektor-vikter (config.SECTOR_FACTOR_WEIGHTS)
  ├─ Innehavsrabatt (×0.85) / Råvarurabatt (×0.90)
  └─ rank, data_quality, low_liquidity (<$50k/dag), idempotens-flaggor
```

### 4.3 Entry-signal-regler (`core/filters.py:calc_entry_signal()`)

| Signal | Villkor |
|---|---|
| **STARK** | score ≥ 72 OCH RSI 35-68 OCH pullback 5-18% från 52v-high |
| **OK** | score ≥ 65 OCH RSI 35-68 |
| **VÄNTA** | RSI > 75 (överköpt), < 30 (översålt), = None (ingen data) |
| **EJ AKTUELL** | score < 55 ELLER pris under MA200 |

### 4.4 Dynamiska vikter (regimbaserade)

| Regim | Momentum | Tillväxt | Risk | Kvalitet | Värde |
|---|---|---|---|---|---|
| TJUR | +5% | +5% | -5% | — | -5% |
| BJÖRN | -20% | -15% | +10% | +15% | +10% |
| OSÄKER | — | — | — | — | — |

### 4.5 Nyckelkonstanter (`core/scoring.py:32-44`)

`MIN_VALID_OBSERVATIONS=5` · `NEUTRAL_SCORE=50.0` · `MAX_DIVIDEND_YIELD=0.15` · `HOLDING_DISCOUNT=0.85` · `COMMODITY_DISCOUNT=0.90` · `MIN_DAILY_TURNOVER_USD=50000`

---

## 5. Datapipeline

### 5.1 Körlägen (`core/daily_pipeline.py:run_pipeline(mode)`)

| Läge | Vad som händer |
|---|---|
| `morning` | Hämtar priser för portfölj + topp-picks, skickar morgonmail |
| `evening` | Stängningspriser, kvällsrapport med STARK-signaler |
| `weekly` | Full universe re-fetch + re-scoring + rotation |
| `smallcap` | Småbolagsspecifikt flöde (separat universum/scoring) |
| `targeted` | Uppdaterar specifika tickers (används för saknad data) |
| `refresh_missing` | Hittar + uppdaterar tickers med NaN-data |
| `portfolio_refresh` | Lättvikts prisuppdatering för portföljinnehav |

### 5.2 Pipeline-flöde (weekly)

```
1. Fetch global indices            → core/global_markets.py
2. fetch_universe_data(tickers)    → core/data_fetcher.py
3. Makroregim                      → core/macro_regime.py
4. score_universe_sector_neutral() → core/scoring.py
5. add_piotroski_to_universe()     → core/piotroski.py
6. apply_all_filters()             → core/filters.py  ← entry_signal sätts HÄR
7. ML-prediktion                   → core/ml_predictor.py
8. Score-delta-spårning            → _get_score_deltas()
9. Rapportgenerering               → core/pipeline_report.py
10. AI-analys                      → core/ai_analysis.py
11. Spara + skicka mail             → _save_scored() + core/email_template.py
```

Morning/evening använder `update_scored_with_prices()` i `data_fetcher_batch.py` som:
1. Uppdaterar prisinputs (RSI, returns, MA-avstånd osv.)
2. Kör `score_universe()` (re-scorar)
3. Kör `apply_all_filters()` (uppdaterar entry_signal, trend_signal, confidence_label)

### 5.3 GitHub Actions-schema (DST-säkert sedan 2026-06-05)

Dupla crons per tidskritiskt läge — mode-detektionen kontrollerar `Europe/Stockholm` lokal tid och returnerar `"skip"` om cron triggar utanför giltigt fönster (förhindrar DST-dubblering).

| Workflow | Cron (UTC) | Lokal tid (Stockholm) | Läge |
|---|---|---|---|
| daily_scan.yml | `10 7 * * 1-5` | 09:10 CEST (sommar) | morning |
| daily_scan.yml | `10 8 * * 1-5` | 09:10 CET (vinter) | morning |
| daily_scan.yml | `40 15 * * 1-5` | 17:40 CEST (sommar) | evening |
| daily_scan.yml | `40 16 * * 1-5` | 17:40 CET (vinter) | evening |
| daily_scan.yml | `0 7 * * 6` | ~09:00 lördag | weekly |
| daily_scan.yml | `15 7 * * 1` | ~09:15 måndag | smallcap |
| daily_scan.yml | `0 8,15 * * 1-5` | 10:00 + 17:00 | refresh_missing |
| daily_scan.yml | `10 11 * * 1-5` | 13:10 | portfolio_refresh |
| news_alerts.yml | `*/30 * * * 1-5` | Var 30:e min | nyhetsbevakning |
| keep_alive.yml | `*/20 * * * *` | Var 20:e min | keep-alive |

---

## 6. Datahämtning

### 6.1 Fetch-strategi

`core/data_fetcher.py:fetch_universe_data(tickers)`:
- **Pass 1:** ThreadPoolExecutor (8 workers), hämtar alla tickers
- **Pass 2:** Retry rate-limitade tickers med längre delay
- **3-lagers timeout:** socket(7s) → requests-patch(3/5s) → thread-watchdog(12s)

### 6.2 Cache-TTL

| Datatyp | TTL |
|---|---|
| Statiska fundamenta (namn, sektor, ROE) | 720h (30 dagar) |
| Dynamiska fundamenta (P/E, analytiker) | 48h |
| Prishistorik | 24h |
| Insider-signaler | 24h |
| AI-analys (content-hash) | Tills data ändras |

### 6.3 Strike-system

Failed fetch → strike räknas (max 1/dag). 3 strikes → auto-blacklist. `NEVER_BLACKLIST`-lista skyddar kritiska tickers (SPY, OMX osv.).

### 6.4 Insider-data

`core/fi_insider_fetcher.py` — scraper för `marknadssok.fi.se`. Returnerar `insider_cluster` (≥3 insiders 30d), `insider_executive_buy` (VD/CFO). Browser-emulations-headers krävs. 24h cache.

---

## 7. AI-analys

### 7.1 Providers

| Provider | Modell | Användning |
|---|---|---|
| DeepSeek | deepseek-chat | Default, daglig körning (~$3/mån) |
| Gemini | gemini-2.5-flash | Fallback + hybridläge |
| Claude | claude-opus/sonnet | Ensemble-alternativ |

Routing-kedja: `core/ai_router.py` → deepseek → gemini → claude

### 7.2 Djupnivåer

| Djup | max_tokens | Data |
|---|---|---|
| Snabb | 512 | 6 nyckelfält (P/E, ROE, Momentum, Piotroski, Entry, Tillväxt) |
| Normal | 2048 | Alla standardfält |
| Djup | 4096 | Alla + FCF Yield, EV/EBITDA, Bollinger, returns |
| Extra djup | 8192 | Allt |

### 7.3 Systemprompt-hierarki

Alla promptar i `core/ai_prompts.py`:
- `SYSTEM_PROMPT_STOCK_ANALYSIS` — används av `analyze_stock()` OCH `_ai_analysis_panel()` i stock_detail.py (via `system_prompt_override`). Inkluderar: entry-signal-tolkning, faktorvikter, 4-horisont avkastningstabell (1v/1m/6m/1år), rekkommendationsformat.
- `SYSTEM_PROMPT_PORTFOLIO` — portföljanalys
- `SYSTEM_PROMPT_WEEKLY_REPORT` — veckorapport
- `SYSTEM_PROMPT_CHAT` — fri chatt (INTE för aktieanalys i stock_detail)
- `SYSTEM_PROMPT_SECTOR_ANALYSIS` — sektoranalys
- `SYSTEM_PROMPT_MORNING_BRIEF` — morgonbrev

**OBS:** `SYSTEM_PROMPT_COMPARISON` är definierad men oanvänd — `compare_stocks()` använder inline-prompt.

### 7.4 Caching

Content-addressed: MD5-hash av (prompt + data + djup) = cache-nyckel. Sparas i `data/ai_cache/` som `.md`-filer.

---

## 8. ML-modell

### 8.1 Arkitektur

- **Algoritm:** XGBoost regressor (fallback: HistGradientBoostingRegressor)
- **Target:** 30-dagars forward-return **demeanad per datum** (tvärsnittlig signal, inte absolut avkastning)
- **26 tekniska features** (point-in-time-säkra): `ret_1m/3m/6m/12m`, RSI, MACD, MA50/MA200-avstånd, volatilitet, volym-ratio, Bollinger, Hurst-exponent, serial-korrelation, max drawdown, osv.
- **Inga fundamenta** — point-in-time-rekonstruktion omöjlig utan look-ahead bias
- **Träning:** Combinatorial Purged CV (6 folds, purge=30d)
- **Modeller:** `models/ml_universe.pkl` + `models/ml_smallcap.pkl` + per-sektor-modeller

### 8.2 Nuvarande modellkvalitet (2026-06-03)

| Mått | Värde | Kommentar |
|---|---|---|
| IC (Information Coefficient) | 0.027 | Branschstandard > 0.05 |
| Hit rate | 52.3% | Knappt över slumpen |
| DSR (Deflated Sharpe Ratio) | 0.0 | Ingen statistisk signifikans |

**Konsekvens:** ML-ranken är en indikation, inte ett tillförlitligt köpsignal. Hög klassisk score + låg ML-rank = potentiell värdefälla (billig aktie med negativt momentum). Varning visas i UI.

### 8.3 ML paper trading

`core/ml_paper_trading.py` — registrerar topp-10 ML-picks som virtuella affärer, ATR-baserade stop-loss, 30 dagars max-innehav. Outputs: `data/ml_paper_universe.json`, `data/ml_paper_smallcap.json`.

---

## 9. E-postsystem

### 9.1 E-posttyper

| Typ | Ämne | Frekvens |
|---|---|---|
| Morgonbrev | 🌅 MarketScan Morgonbrief | Vardagar 09:10 + pipeline-tid |
| Kvällsbrev | 🌆 MarketScan Kvällsbrev | Vardagar 17:40 + pipeline-tid |
| Veckorapport | 📊 MarketScan Veckorapport | Lördag |
| Småbolagsrapport | 🏦 MarketScan Småbolag | Måndag |
| STARK-larm | ⚡ STARK-signaler | Vid signal |
| Felinformation | 🚨 Pipeline-fel | Vid CI-krasch |

### 9.2 Schema-förklaring

10 minuter efter börsöppning/stängning = startpunkt för pipeline. Lägg till ~10 min pipeline-tid = faktisk e-postankomst. Se §5.3 för exakta cron-tider.

---

## 10. Streamlit-dashboard

### 10.1 Sidor

| # | Sida | Fil | Notering |
|---|---|---|---|
| 1 | 📊 Översikt | `overview.py` | Cockpit: globala index, portfölj, topp-picks |
| 2 | 🔍 Veckoscanner | `weekly_scan.py` | Full universum-ranking + ML-ranking-läge |
| 3 | 🏦 Småbolag | `smallcap.py` | Småbolag-ranking, stars, insider, ML-prediktion |
| 4 | 🔍 Aktie-sök | (stock_detail) | Sök → `render_stock_detail()` |
| 5 | 📈 Jämförelse | `stock_comparison.py` | 2-5 aktier, sök på namn eller ticker |
| 6 | 💼 Portfölj | `portfolio.py` | Innehav, P&L, optimering (BL/HRP/MV/Kelly) |
| 7 | 🌍 Globala marknader | `global_markets.py` | 17 index, FX, räntekurvor |
| 8 | 🏭 Sektorrotation | `sector_rotation.py` | Sektor-heatmap + AI |
| 9 | 📈 Backtesting | `backtesting_page.py` | Backtest-motor + equity-kurva |
| 10 | 📄 Paper Trading | `paper_trading_page.py` | Virtuell portfölj |
| 11 | 🤖 AI | `ai_page.py` | AI-analys, ensemble, chatt |
| 12 | 📓 AI Journal | `ai_journal.py` | AI-rekommendationshistorik |
| 13 | 🚨 Larm | `alerts.py` | Stop-loss, nyheter, prisarm |
| 14 | ⚙️ Inställningar | `settings_page.py` | E-postprenumeration |
| 15 | 🔧 Admin | `admin_page.py` + `admin.py` | System, Pipeline, Universe, Inställningar, Metrics |

### 10.2 Admin-sidan (5 flikar, ombyggd 2026-06-04)

| Flik | Fil | Innehåll |
|---|---|---|
| 🟢 System | `tab_system.py` | `st.success/warning/error()` statusbanner, 4× `st.metric()` KPI, GitHub Actions-monitor, API-nyckelstatus |
| ▶️ Pipeline | `tab_pipeline.py` | Kör 7 scan-lägen (confirm-flöde), körningshistorik, cache-hantering |
| 🌐 Universe | `tab_universe.py` | Täckning, kandidater (godkänn/avvisa), strikes & blacklist, datakvalitet |
| ⚙️ Inställningar | `tab_settings.py` | Faktorvikter, feature flags, API-nycklar, användare, e-post |
| 📊 Metrics | `tab_metrics.py` | Pipeline-prestanda, AI-tokens, score-distribution |

**CSS-notering:** Använd aldrig `class="..."` i `st.markdown(unsafe_allow_html=True)` för styling — Streamlit Cloud applicerar vit containerbakgrund som gör rgba-transparens vit. Använd `st.metric()`, `st.success()`, `st.warning()`, `st.error()`, eller direkt `style="..."` med hårdkodade färger.

### 10.3 Aktiedetaljvy (`web/stock_detail.py`)

`render_stock_detail(ticker, row, df)`:
- **Snabb-kort (8st):** Score, Entry, Trend, RSI, P/E, ROE, Piotroski, + "🤖 ML 30d" om `predicted_return` finns
- Plotly candlestick (MA50/MA200, Bollinger, volym, RSI, MACD)
- Radar-chart (8-faktorsprofil)
- Detaljdata i 5 flikar (Värdering, Kvalitet, Momentum, Tillväxt, Sentiment)
- AI-analys: `ai_chat()` med `system_prompt_override=SYSTEM_PROMPT_STOCK_ANALYSIS`
- Nyhetssektion

### 10.4 Dataladdning

`web/utils.py`:
- `load_scan_reports()` — `{datum: DataFrame}` för scored_universe (parquet + csv)
- `load_smallcap_reports()` — samma för smallcap (parquet prio, csv fallback)
- `load_portfolio()` — läser `data/holdings.csv`
- `load_watchlist()` — läser `data/watchlist.json`
Alla cachas 300s med `@st.cache_data`.

---

## 11. Småbolagssystem

Separat subsystem i `smallcap/`:
- **Universum:** ~280 svenska micro/small-cap (First North, Nasdaq SM Small, Spotlight, Nordic SME)
- **Scoring:** Annat viktsystem — Insider 18%, FCF 16%, Piotroski 15%, Tillväxt 13%, Balansräkning 12%, Värdering 12%, Momentum 9%, Likviditet 5%
- **Hårdfilter:** Cash runway < 12mån, Piotroski ≤ 2, utspädning > 20%/år, D/E > 300%, Current Ratio < 0.5
- **Entry-punkt:** `smallcap/scanner.py:main()`
- **CI:** `daily_scan.yml` mode=`smallcap` (måndag 09:15)

---

## 12. Konfiguration

`core/config.py` (~350 rader tickers + ~100 konstanter):

| Variabel | Default | Beskrivning |
|---|---|---|
| `FACTOR_WEIGHTS` | se §4.1 | Vikter summa = 1.0 (testvaktat) |
| `UNIVERSE` | ~1200 tickers | Kombinerad lista av alla regioner |
| `PARALLEL_WORKERS` | 8 | Fetch-parallellism |
| `CACHE_HOURS` | 720 | Statiska fundamenta-cache |
| `PRICE_CACHE_HOURS` | 24 | Pris-cache |
| `SCORE_MODE` | "sector_neutral" | Scoringläge |
| `AI_PROVIDER` | "deepseek" | Primär AI-leverantör |
| `SITE_PASSWORD` | env/secret | Streamlit-lösenord |
| `ADMIN_PASSWORD` | env/secret | Admin-lösenord |

---

## 13. Datafiler

### 13.1 Git-committade (överlever Streamlit-omstarter)

| Fil | Format | Innehåll | Uppdateras av |
|---|---|---|---|
| `reports/scored_universe_YYYY-MM-DD.parquet` | Parquet | Full scored universe | CI pipeline |
| `reports/smallcap_scored_YYYY-MM-DD.parquet` | Parquet | Småbolagspoäng | CI pipeline |
| `data/blacklist.json` | JSON | Permanent borttagna tickers | CI + manuellt |
| `data/strike_list.json` | JSON | Strike-räknare per ticker | CI pipeline |
| `data/scan_log.json` | JSON | Pipeline-körningslogg | CI pipeline |
| `data/fetch_errors.json` | JSON | Fetch-feldetaljer per körning | CI pipeline |
| `data/holdings.csv` | CSV | Portföljinnehav | Portfölj-UI + CI |
| `data/email_subscribers.json` | JSON | E-postprenumeranter | Settings UI + CI |
| `data/users_config.json` | JSON | Användarlösenord (bcrypt) | Admin UI + CI |
| `data/health/health_YYYY-MM-DD.json` | JSON | Systemhälsa per dag | CI pipeline |
| `data/ci_reports/last_daily_scan.json` | JSON | Senaste CI-körning | CI pipeline |
| `data/ci_reports/last_test_run.json` | JSON | Senaste testresultat | CI tests |
| `data/streamlit_errors.jsonl` | JSONL | Streamlit-sidkraschar | Streamlit app |
| `models/ml_universe.pkl` | Pickle | Tränad XGBoost | CI train workflow |

### 13.2 Git-ignorerade (genereras vid körning)

- `data/cache/*.pkl` — yfinance-cache (24-720h)
- `data/ai_cache/ai_*.md` — AI-analys-cache (content-addressed)

### 13.3 Retentionspolicy

- Parquet/CSV-rapporter > 14 dagar tas bort av CI
- Markdown-rapporter > 7 dagar tas bort
- `scan_log.json` trunkeras till 90 poster

---

## 14. Tester

```bash
pytest tests/              # Kör alla (~430 tester)
pytest tests/ -m "not slow"  # Hoppa över prestandatester
python -m ruff check core/ tests/ portfolio/ web/ smallcap/ scripts/  # Lint
```

| Fil | Tester | Täcker |
|---|---|---|
| `test_scoring.py` | 60 | Alla faktorer, sektor-neutralisering, idempotens |
| `test_config.py` | 9 | Universum-integritet, viktsummor |
| `test_filters.py` | 3 | Strike-idempotens, NEVER_BLACKLIST |
| `test_chaos.py` | 11 | Timeout, NaN, korrupt JSON, backoff |
| `test_property_based.py` | 10 | Hypothesis: poäng alltid 0-100, viktsummor |
| `test_daily_pipeline.py` | ~15 | Pipeline-canaries |
| Övriga | ~320 | data_fetcher, ml, portfolio, integration osv. |

**3 pre-existenta fel** i `test_chaos.py` (TestNetworkFailures, TestMalformedData) — ej orsakade av pågående arbete, kvarstår.

---

## 15. Felsökning

### 15.1 Diagnostikverktyg

```bash
# Starta alltid här — 0.2s, läser repo-filer utan nätverksanrop
python scripts/ai_debug.py --quick

# Med GitHub Actions live-status
python scripts/ai_debug.py --github

# Hämta exakta CI-loggar vid fel
python scripts/fetch_ci_logs.py --save
cat data/ci_reports/latest_failure.txt
cat data/streamlit_errors.jsonl
```

### 15.2 Vanliga felmönster

| Symptom | Rotsak | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'core'` | `PYTHONPATH: .` saknas i CI | Lägg till i workflow env |
| `AttributeError: 'dict' object has no attribute 'empty'` | `fetch_prices_only()` returnerade dict, kod förväntade DataFrame | Kontrollera `run_portfolio_refresh()` |
| `StreamlitDuplicateElementKey` | Samma `key=` används två gånger i samma vy | Lägg till `_suffix`-parameter |
| KPI-kort vita mot mörk bakgrund | `class="kpi-card"` från injicerad CSS ignoreras av Streamlit Cloud | Byt till `st.metric()` / inline `style=` |
| Småbolagssidan visar "håller på att laddas" | `load_smallcap_reports()` hittade inga `.csv` (filer är `.parquet`) | Redan fixat 2026-06-05 |
| Entry-signal stale efter daglig re-scoring | `apply_all_filters()` anropas ej | Redan fixat i `data_fetcher_batch.py:602-608` |
| Morning-mail för sent | DST-problem med cron (UTC ≠ lokal tid) | Dubbla crons + Stockholm-tidkontroll (se §5.3) |

---

## 16. Kända problem & teknisk skuld

| Problem | Allvarlighet | Fil | Notering |
|---|---|---|---|
| `daily_pipeline.py` ~2300 rader | MEDIUM | `core/daily_pipeline.py` | Delvis splittad i pipeline_report.py + pipeline_alerts.py; fortsatt stor |
| `portfolio.py` ~110KB | LÅG | `web/pages/portfolio.py` | Stor men logiskt sammanhållen |
| ML-modell låg kvalitet (IC=0.03, DSR=0.0) | MEDIUM | `models/ml_universe.pkl` | Modellen tränad men behöver mer data/feature-engineering; varning visas i UI |
| Pickle-serialisering av ML-modeller | LÅG | `models/*.pkl` | Risk vid komprometterat repo; byt till XGBoost native JSON |
| Makrokalender hårdkodad till 2025-2026 | LÅG | `core/macro_calendar.py` | Uppdatera manuellt varje år |
| Inga integrationstester utan API-nycklar | MEDIUM | `tests/` | Pipeline end-to-end otestbar i CI |
| Race condition i news_alerts state-commit | LÅG | `.github/workflows/news_alerts.yml` | `git push \|\| true` — enstaka dedup-poster kan tappas |
| `news_alerts.yml` gör web-anrop var 30:e min | LÅG-MEDIUM | `core/news_fetcher.py` | Dedup minskar mail-spam men inte anrop |

---

## 17. Förbättringsidéer

| Idé | Prioritet | Filer |
|---|---|---|
| Öka ML-modellens IC (mer träningsdata, bättre features) | HÖG | `core/ml_predictor.py`, `scripts/build_ml_dataset.py` |
| Byt ML-modeller från pickle till XGBoost JSON-format | MEDIUM | `models/`, `core/ml_predictor.py` |
| Höj pytest-täckning för `core/daily_pipeline.py` (< 15% nu) | MEDIUM | `tests/test_daily_pipeline.py` |
| Migrera Streamlit-navigering till `st.navigation()` (inbyggd) | LÅG | `web/streamlit_app.py` |
| SQLite istf JSON-filer för `scan_log`, `strike_list` (bättre query) | LÅG | `core/logger.py`, `core/filters.py` |
| Automatisk DST-uppdatering av crons (GitHub Actions saknar stöd) | LÅG | `.github/workflows/daily_scan.yml` |
| `universe_explorer.py` — sök bland alla kandidater och historik | LÅG | ny sida |

---

## 18. Ändringslogg

> Nyaste överst. Format: `YYYY-MM-DD — beskrivning (fil)`.

### 2026-06-05 — Enhetliga tabeller + ML-kort i aktiedetaljvy + AI-tidshorisonter
Smallcap-tabell byter `pct_fmt()`-strängar mot `NumberColumn(format="%.1f%%")` + full `column_config` med hjälptexter (matchar weekly scanner). `_quick_data_cards()` i stock_detail visar "🤖 ML 30d"-kort när `predicted_return` finns. `SYSTEM_PROMPT_STOCK_ANALYSIS` utökad med 4-horisont avkastningstabell (1v/1m/6m/1år).
`web/pages/smallcap.py`, `web/stock_detail.py`, `core/ai_prompts.py`

### 2026-06-05 — ML-modellens begränsningar dokumenterade i UI
`weekly_scan.py` visar varning om IC=0.03, DSR=0.0 i ranking-läge-hjälptext + faktortabell-caption.

### 2026-06-05 — Stock Comparison: sök på bolagsnamn
`format_func=lambda t: ticker_label.get(t, t)` i `st.multiselect` — "tesla" hittar nu TSLA.
`web/pages/stock_comparison.py`

### 2026-06-05 — Sidebar: Favoriter och Senaste sidor borttagna
Tog bort `_recent_pages`/`_pinned_pages` session-state + UI-block (~45 rader).
`web/streamlit_app.py`

### 2026-06-05 — Smallcap visar data (load_smallcap_reports parquet-fix)
`load_smallcap_reports()` läste bara `*.csv` — pipelinen sparar `*.parquet`. Lade till parquet prio + CSV fallback.
`web/utils.py:load_smallcap_reports()`

### 2026-06-05 — 9 kroniska felmisslyckanden blacklistade
EXAS, PHNX.L, 6406.T, 0011.HK, TATAMOTORS.NS, BRFS3.SA, EMBR3.SA, AZUL4.SA, CENY.BR — alla 4/4 körningar.
`data/blacklist.json`

### 2026-06-05 — DST-säker schemaläggning (dubbla crons + Stockholm-tidkontroll)
Ersatte `"5 7 * * 1-5"` med par: `"10 7"` (CEST) + `"10 8"` (CET) för morning, `"40 15"` + `"40 16"` för evening. Mode-detektionen kontrollerar `Europe/Stockholm` lokal tid, returnerar `"skip"` vid DST-dubblering.
`.github/workflows/daily_scan.yml`

### 2026-06-05 — AI-prompt: korrekt systemprompt i stock_detail
`_ai_analysis_panel()` använde `SYSTEM_PROMPT_CHAT` (generisk). Bytt till `system_prompt_override=SYSTEM_PROMPT_STOCK_ANALYSIS`.
`web/stock_detail.py:963`

### 2026-06-05 — Dubblettdefinition SYSTEM_PROMPT_SECTOR_ANALYSIS borttagen
`core/ai_prompts.py` definierade variabeln 2 gånger. Tog bort sämre första versionen.

### 2026-06-05 — Admin dark mode: native Streamlit-komponenter ersätter custom HTML
`st.metric()` istf `<div class="kpi-card">`. `st.success/warning/error()` istf rgba-div. CSS-klasser opålitliga i Streamlit Cloud.
`web/pages/admin_tabs/tab_system.py`

### 2026-06-05 — 64 ruff-lint-fel fixade (CI-lint blockerad)
F821 (`np`/`pd` undefined), F823 (lokal `go` re-import), F541 (41 f-strängar utan platshållare), E401 (split-import).
`web/app.py`, `web/pages/portfolio.py`, `web/pages/backtesting_page.py`, `core/daily_pipeline.py` + 13 filer

### 2026-06-05 — StreamlitDuplicateElementKey i overview.py
`_goto("🔍 Veckoscanner")` anropades 2 gånger → identisk key. `_goto()` fick `_suffix: str = ""` param.
`web/pages/overview.py:22`

### 2026-06-04 — Admin-sida ombyggd: 18 flikar → 5 sektioner
Komplett omskrivning till tab_system, tab_pipeline, tab_universe, tab_settings, tab_metrics. 16 gamla filer borttagna. 1984 rader totalt.
`web/pages/admin_page.py`, `web/pages/admin_tabs/`

### 2026-06-04 — Ruff scope utökat till alla kataloger
`ruff check core/ tests/ portfolio/ web/ smallcap/ scripts/` (tidigare bara `core/ tests/`).
`.github/workflows/tests.yml`

### 2026-06-04 — AI/STARK-disconnect och stale entry_signal fixat
`update_scored_with_prices()` anropar nu `apply_all_filters()` efter re-scoring. `stock_detail.py` fick korrekt systemprompt (SYSTEM_PROMPT_STOCK_ANALYSIS).
`core/data_fetcher_batch.py:602`, `web/stock_detail.py`

### 2026-06-03 — ML-modell omtränad
IC = 0.027, hit_rate = 52.3%, DSR = 0.0. 53134 träningsrader, 26 tekniska features, CPCV 6-fold.
`models/ml_universe.pkl`

### 2026-06-02 — Systemaudit: 71 fynd + Sprint 1-11 fixar
Se git-historik (commits 31f6466 → 2a4b60b) för komplett lista. Nyckelfix: atomiska CSV-skrivningar, inner→left join i score_deltas, RSI None → VÄNTA, Finnhub exponentiell backoff.

### 2026-06-01 — Unicode-tecken (–, →, ×, ≥) orsakade SyntaxError i Python 3.12+
90+ Python-filer fixade. Blockerade import av `core/__init__.py`.

### 2026-06-01 — ML-modell: tvärsnittlig target + 11 saknade features
Ny target `target_cs` = forward-return demeanad per datum. IC steg från ~0.002 till 0.027. 11 feature-funktioner implementerade.
`core/ml_predictor.py`, `core/ml_features.py`

### 2026-06-01 — Sektor-relativ scoring som default
`SCORE_MODE = "sector_neutral"`. Banker jämförs med banker, inte Nasdaq-tech.
`core/scoring.py`, `core/config.py`

### 2026-05-31 — Stor reliabilitets-fix (14+ buggfixar)
CI git-push-strategi, seed-filer för Streamlit-persistens, keep_alive.yml, e-post-BCC, 6 bare-except fixade.
