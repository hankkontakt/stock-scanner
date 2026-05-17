# Research Prompt: Which Market Data API Should I Use?

## My situation

I am a private investor in Sweden running a personal quantitative stock scanner in Python. I need help deciding which market data API to use. I want a data-driven comparison — not marketing material.

---

## What I currently use (free stack)

| Source | What I use it for | Limitations I've found |
|---|---|---|
| **yfinance** (unofficial Yahoo Finance) | Primary: price history, fundamentals, insider transactions | Frequently returns `None` for Nordic/Swedish stocks. Insider transaction data is unreliable for Swedish companies. No guaranteed uptime or SLA. |
| **FMP (Financial Modeling Prep) — free tier** | Fallback fundamentals (P/E, P/B, ROE, EV/EBITDA) when yfinance returns None | 250 calls/day limit. Key-metrics endpoint sometimes missing data for European stocks. No Swedish insider data. |
| **Finansinspektionen open data** | Swedish insider transactions (marknadssok.fi.se) | No official API — HTML scraping, fragile. Company name matching is imprecise (ticker → company name → FI search). |

---

## My universe (what stocks I need to cover)

- ~80 Swedish stocks (OMX Stockholm Large/Mid Cap, suffix `.ST`)
- ~60 Nordic stocks (Denmark `.CO`, Norway `.OL`, Finland `.HE`)
- ~200 European stocks (UK `.L`, Germany `.DE`, France `.PA`, Netherlands `.AS`, etc.)
- ~400 US stocks (NYSE/NASDAQ, no suffix)
- ~200 Asia-Pacific stocks (Japan `.T`, Taiwan `.TW`, Korea `.KS`, Hong Kong `.HK`, India `.NS`)
- ~100 Canada/Brazil (`.TO`, `.SA`, ADRs)

**Total: ~1,000–1,200 tickers.**

Primary focus is Swedish and Nordic stocks. Global coverage is secondary but needed for the ranking model to work correctly (I rank stocks relative to each other across the full universe).

---

## What data I actually need

**Must have (system breaks without these):**
1. Daily price history — OHLCV, 1 year back minimum
2. Key fundamentals — P/E, P/B, ROE, ROA, EV/EBITDA, Free Cash Flow, Revenue Growth, Gross/Operating Margin, D/E, Current Ratio, Market Cap
3. Shares outstanding (for market cap calculation)

**High value (directly improves signal quality):**
4. Swedish/Nordic insider transactions — who bought/sold, what role (VD/CFO vs. minor insider), how many shares, date
5. Short interest / short % of float — for European and Nordic stocks
6. Analyst recommendations (consensus, number of analysts, price target)
7. Enterprise value (for FCF yield = FCF/EV calculation)

**Nice to have:**
8. Options flow / put-call ratio
9. Earnings surprise history
10. Institutional ownership %

---

## APIs I want compared

Please research and compare these specific options:

### Option A: Börsdata Pro+ (Swedish provider)
- Website: borsdata.se
- Price: 599 SEK/month (~€52) as of 2025
- Claims: best Nordic data, insider transactions included, REST API
- Questions: How complete is their fundamental data for Swedish small-caps? Do they cover the 80 OMX stocks I need? What about their global coverage — can they replace yfinance for US/EU stocks or is it Nordic-only? Is their insider data the same as Finansinspektionen (government source) or do they add value?

### Option B: EODHD (End of Day Historical Data)
- Website: eodhd.com
- Price: ~€19.99/month (prices only) or ~€59.99/month (fundamentals)
- Claims: 60+ exchanges, fundamental data, insider transactions for US (Form 4)
- Questions: How good is their Nordic/Swedish coverage? Do they have insider data for European/Swedish stocks? How does fundamental data quality compare to yfinance for non-US stocks?

### Option C: FMP paid tier (Financial Modeling Prep)
- Website: financialmodelingprep.com
- Price: $99/month (Starter) or $249/month (Premium)
- I already use their free tier (250 calls/day)
- Questions: Does the paid tier significantly improve coverage for European/Nordic stocks? Do they have insider transactions for Swedish stocks? Is it worth upgrading from free?

### Option D: Polygon.io
- Website: polygon.io
- Price: $29/month (Starter) and up
- Questions: Do they cover European/Nordic stocks or is it US-only? Fundamental data availability? Any insider transaction data?

### Option E: Marketaux / Alpha Vantage / Tiingo
- Mentioned for completeness — please confirm if any of these have meaningful European/Nordic fundamental data and insider transactions, or if they are primarily US-focused.

### Option F: Stay on free stack (yfinance + FMP free + FI scraping)
- The baseline — what am I actually losing in data quality vs. the paid options?

---

## My specific decision criteria (in priority order)

1. **Swedish/Nordic insider transaction quality** — this is the single biggest gap in my current free stack. Finansinspektionen scraping is fragile and imprecise. How reliably does each API deliver VD/CFO transaction data for Swedish listed companies?

2. **Fundamental data completeness for Swedish small-caps** — yfinance frequently returns None for P/E, ROE, EV/EBITDA on smaller Swedish companies (market cap 30–500 MSEK). Which API fills this best?

3. **Global coverage** — I need at least price history + basic fundamentals (P/E, ROE, market cap) for US/EU/Asia to keep my ranking model working. Which APIs cover all regions, not just Nordic?

4. **Cost vs. signal improvement** — I am a private investor, not an institution. My monthly trading profit needs to justify the data cost. At what point (in terms of measurable signal improvement) does a paid API become worth it?

5. **API reliability and rate limits** — I run a daily scan of ~1,000 tickers. I cache fundamentals for 30 days and prices for 24 hours. What are the actual rate limits and how many API calls would I need per day?

---

## What I want from this research

1. **Side-by-side comparison table** of Options A–F across: Nordic/Swedish coverage, global coverage, insider transactions, fundamental data quality, price, rate limits, API quality (REST/JSON, documentation).

2. **Specific answer** to: "For a private Swedish investor running a 1,000-ticker multi-factor model, which single API (or combination of two) gives the best data quality per euro spent?"

3. **Data quality evidence** — not marketing claims. Are there independent comparisons, user reports, or academic papers that evaluate the accuracy of fundamental data from these providers for European/Nordic stocks? What is the known error rate for P/E, ROE, or FCF data from yfinance vs. paid providers?

4. **The free stack question** — is yfinance + FMP free + FI scraping "good enough" for a private investor, or are there systematic errors (wrong fundamentals, missing insider signals) that would materially affect stock selection?

5. **If recommending Börsdata Pro+** — what is the API documentation like? Is there a Python SDK? What endpoints are available and what data can I actually get vs. what the marketing page claims?

---

## Technical context

- Language: Python 3.12
- Caching: local file cache, 720h for fundamentals, 24h for prices
- Call volume: ~1,000 tickers × daily price refresh + ~33 fundamental refreshes/day (30-day cache rotation)
- Already integrated: yfinance, requests (for FMP REST calls), basic HTML parsing
