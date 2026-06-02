"""
Pytest-konfiguration och fixtures for stock-scanner.

Innehaller omfattande fixtures for alla testmoduler:
- sample_scored_df: 20 syntetiska aktier med scoring-kolumner
- sample_holdings_df: 5 holdings med varierande data
- sample_news_data: 10 syntetiska nyhetsartiklar
- mock_yfinance: mocka yfinance.Ticker
- tmp_cache_dir: temporar cache-katalog
- sample_trades_data: 50 syntetiska trades
- empty_df: tom DataFrame
- sample_macro_data: syntetisk makrodata
- sample_options_chain: syntetisk optionskedja
"""
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import pytest


# ── Projektrot i sys.path ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# SCORING-FIXTURES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_scored_df() -> pd.DataFrame:
    """Returnerar en DataFrame med 20 syntetiska aktier med alla scoring-kolumner."""
    np.random.seed(42)
    n = 20
    tickers = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
        "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD", "DIS", "NFLX", "ADBE", "CRM"
    ]
    df = pd.DataFrame({"ticker": tickers[:n]})

    # Grunddata
    df["name"] = [f"Company {t}" for t in tickers[:n]]
    df["sector"] = np.random.choice(["Technology", "Finance", "Healthcare", "Consumer"], n)
    df["industry"] = np.random.choice(["Software", "Banking", "Pharma", "Retail", "Semiconductors"], n)
    df["current_price"] = np.random.uniform(50, 500, n).round(2)
    df["market_cap"] = np.random.uniform(1e9, 3e12, n)
    df["currency"] = np.random.choice(["USD", "SEK", "EUR"], n)

    # Scoring-kolumner
    df["pe_trailing"] = np.random.uniform(8, 40, n).round(1)
    df["pe_forward"] = np.random.uniform(8, 35, n).round(1)
    df["price_to_book"] = np.random.uniform(0.5, 15, n).round(2)
    df["ev_to_ebitda"] = np.random.uniform(3, 25, n).round(1)
    df["enterprise_value"] = np.random.uniform(1e9, 2e12, n)
    df["free_cash_flow"] = np.random.uniform(-5e8, 5e9, n)
    df["total_debt"] = np.random.uniform(0, 1e11, n)
    df["total_cash"] = np.random.uniform(0, 5e10, n)
    df["roe"] = np.random.uniform(-0.1, 0.4, n).round(4)
    df["roa"] = np.random.uniform(-0.05, 0.2, n).round(4)
    df["profit_margin"] = np.random.uniform(-0.05, 0.3, n).round(4)
    df["operating_margin"] = np.random.uniform(-0.05, 0.35, n).round(4)
    df["gross_margin"] = np.random.uniform(0.2, 0.7, n).round(4)
    df["debt_to_equity"] = np.random.uniform(0, 3, n).round(2)
    df["current_ratio"] = np.random.uniform(0.5, 5, n).round(2)
    df["dividend_yield"] = np.random.uniform(0, 0.08, n).round(4)
    df["payout_ratio"] = np.random.uniform(0, 1.5, n).round(2)
    df["revenue_growth"] = np.random.uniform(-0.2, 0.5, n).round(4)
    df["earnings_growth"] = np.random.uniform(-0.3, 0.6, n).round(4)
    df["earnings_quarterly_growth"] = np.random.uniform(-0.3, 0.5, n).round(4)
    df["return_12m"] = np.random.uniform(-0.3, 0.8, n).round(4)
    df["return_6m"] = np.random.uniform(-0.2, 0.5, n).round(4)
    df["return_3m"] = np.random.uniform(-0.15, 0.3, n).round(4)
    df["volatility"] = np.random.uniform(0.1, 0.6, n).round(4)
    df["beta"] = np.random.uniform(0.5, 2.0, n).round(2)
    df["avg_volume"] = np.random.randint(100000, 50000000, n)
    df["avg_volume_10d"] = np.random.randint(100000, 50000000, n)
    df["short_pct_float"] = np.random.uniform(0.01, 0.25, n).round(4)
    df["short_ratio"] = np.random.uniform(0.5, 8, n).round(2)
    df["sentiment_raw"] = np.random.uniform(-1, 1, n).round(3)
    df["pct_from_52w_high"] = np.random.uniform(-0.3, 0, n).round(4)
    df["insider_executive_buy"] = np.random.choice([True, False], n)
    df["insider_cluster"] = np.random.choice([True, False], n, p=[0.1, 0.9])
    df["insider_recent_date"] = datetime.now().strftime("%Y-%m-%d")
    df["options_flow_signal"] = np.random.uniform(0.1, 0.9, n).round(3)
    df["earnings_surprise"] = np.random.uniform(-0.5, 1.0, n).round(3)
    df["earnings_revision_rate"] = np.random.uniform(-0.2, 0.3, n).round(4)
    df["price_vs_ma200"] = np.random.uniform(-0.15, 0.25, n).round(4)
    df["price_vs_ma50"] = np.random.uniform(-0.1, 0.15, n).round(4)

    # Scoringsresultat (lite korrelerade med varandra)
    raw_scores = np.random.uniform(20, 95, (n, 10))
    df["score_value"] = raw_scores[:, 0].round(1)
    df["score_quality"] = raw_scores[:, 1].round(1)
    df["score_momentum"] = raw_scores[:, 2].round(1)
    df["score_growth"] = raw_scores[:, 3].round(1)
    df["score_risk"] = raw_scores[:, 4].round(1)
    df["score_size"] = raw_scores[:, 5].round(1)
    df["score_dividend"] = raw_scores[:, 6].round(1)
    df["score_sentiment"] = raw_scores[:, 7].round(1)
    df["score_short_interest"] = raw_scores[:, 8].round(1)
    df["score_options_flow"] = raw_scores[:, 9].round(1)
    df["score_fcf_yield"] = np.random.uniform(10, 90, n).round(1)

    # Composite
    df["score_total"] = df[["score_value", "score_quality", "score_momentum",
                            "score_growth", "score_risk", "score_size",
                            "score_dividend", "score_sentiment"]].mean(axis=1).round(1)
    df["rank"] = df["score_total"].rank(ascending=False, method="min").astype("Int64")
    df["entry_signal"] = np.random.choice(["STARK", "OK", "VÄNTA"], n, p=[0.2, 0.5, 0.3])

    # Piotroski
    df["piotroski_f"] = np.random.randint(0, 10, n)
    df["piotroski_label"] = df["piotroski_f"].apply(
        lambda x: "STARK" if x >= 7 else "NEUTRAL" if x >= 4 else "SVAG"
    )
    df["piotroski_boost"] = df["piotroski_label"].map({"STARK": 8, "NEUTRAL": 0, "SVAG": -8}).fillna(0)

    # ML
    df["predicted_return"] = np.random.uniform(-0.1, 0.15, n).round(4)
    df["ml_rank"] = df["predicted_return"].rank(ascending=False, pct=True).mul(100).astype(int)

    # Övrigt
    df["company_type"] = np.random.choice(["standard", "holding", "commodity"], n, p=[0.8, 0.1, 0.1])
    df["est_daily_turnover_usd"] = np.random.randint(10000, 5000000, n)
    df["low_liquidity"] = df["est_daily_turnover_usd"] < 50000
    df["data_quality"] = np.random.uniform(0.5, 1.0, n).round(2)
    df["exchange_group"] = df["ticker"].apply(lambda t: "US" if "." not in t else "Nordic")

    return df


@pytest.fixture
def sample_holdings_df() -> pd.DataFrame:
    """Returnerar 5 holdings med varierande data."""
    return pd.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"],
        "shares": [100, 50, 75, 30, 200],
        "cost_basis": [150.0, 300.0, 140.0, 400.0, 250.0],
        "current_price": [175.0, 320.0, 155.0, 450.0, 220.0],
        "name": ["Apple Inc", "Microsoft Corp", "Alphabet Inc", "NVIDIA Corp", "Tesla Inc"],
        "sector": ["Technology", "Technology", "Technology", "Technology", "Consumer"],
    })


@pytest.fixture
def sample_news_data() -> list:
    """Returnerar 10 syntetiska nyhetsartiklar."""
    now = datetime.now()
    articles = []
    for i in range(10):
        age_h = i * 2.5  # 0, 2.5, 5, ...
        dt = now - timedelta(hours=age_h)
        articles.append({
            "headline": f"News article {i+1}: Market update for today {i}",
            "source": ["Finnhub", "Reuters", "Bloomberg", "Google News", "Placera"][i % 5],
            "url": f"https://example.com/news/{i+1}",
            "datetime_str": dt.strftime("%d %b %H:%M"),
            "age_hours": round(age_h, 1),
        })
    return articles


@pytest.fixture
def mock_yfinance(mocker):
    """Mocka yfinance.Ticker for att undvika API-anrop."""
    mock_ticker = mocker.MagicMock()

    # Mock info
    mock_ticker.info = {
        "longName": "Mock Company AB",
        "shortName": "Mock Co",
        "marketCap": 1e10,
        "trailingPE": 15.0,
        "forwardPE": 14.0,
        "priceToBook": 2.5,
        "returnOnEquity": 0.15,
        "returnOnAssets": 0.08,
        "profitMargins": 0.12,
        "operatingMargins": 0.15,
        "grossMargins": 0.45,
        "debtToEquity": 0.8,
        "currentRatio": 2.0,
        "dividendYield": 0.02,
        "payoutRatio": 0.4,
        "revenueGrowth": 0.08,
        "earningsGrowth": 0.10,
        "beta": 1.1,
        "volatility": 0.25,
        "shortPercentOfFloat": 0.03,
        "shortRatio": 1.5,
        "recommendationMean": 2.0,
        "enterpriseValue": 1.2e10,
        "totalDebt": 2e9,
        "totalCash": 5e8,
        "freeCashflow": 1.5e9,
        "sector": "Technology",
        "industry": "Software",
        "currency": "USD",
    }

    # Mock history
    dates = pd.date_range("2024-01-01", periods=500, freq="D")
    mock_history = pd.DataFrame({
        "Open": [100 * (1 + 0.001) ** i for i in range(500)],
        "High": [105 * (1 + 0.001) ** i for i in range(500)],
        "Low": [95 * (1 + 0.001) ** i for i in range(500)],
        "Close": [100 * (1 + 0.001) ** i for i in range(500)],
        "Volume": [1000000] * 500,
    }, index=dates)
    mock_ticker.history.return_value = mock_history

    # Mock other properties
    mock_ticker.insider_transactions = pd.DataFrame()
    mock_ticker.earnings_history = pd.DataFrame()
    mock_ticker.recommendations = pd.DataFrame()
    mock_ticker.options = ()
    mock_ticker.news = []

    # Apply mock
    mocker.patch("yfinance.Ticker", return_value=mock_ticker)

    return mock_ticker


@pytest.fixture
def tmp_cache_dir(tmp_path) -> Path:
    """Skapar en temporar cache-katalog."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


@pytest.fixture
def sample_trades_data() -> pd.DataFrame:
    """Returnerar 50 syntetiska trades for paper trading-tester."""
    np.random.seed(42)
    n = 50
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
               "JPM", "V", "JNJ", "WMT", "PG", "MA", "UNH", "HD",
               "DIS", "NFLX", "ADBE", "CRM", "INTC"]

    trades = []
    for i in range(n):
        ticker = np.random.choice(tickers)
        entry_price = np.random.uniform(50, 500)
        shares = np.random.randint(10, 1000)
        exit_price = entry_price * np.random.uniform(0.7, 1.5)

        entry_date = datetime.now() - timedelta(days=np.random.randint(1, 60))

        trade = {
            "ticker": ticker,
            "entry_date": entry_date.strftime("%Y-%m-%d"),
            "entry_price": round(entry_price, 2),
            "shares": shares,
            "side": np.random.choice(["BUY", "SELL"], p=[0.7, 0.3]),
        }

        if np.random.random() > 0.3:  # 70% closed
            exit_date = entry_date + timedelta(days=np.random.randint(1, 30))
            trade["exit_date"] = exit_date.strftime("%Y-%m-%d")
            trade["exit_price"] = round(exit_price, 2)
            trade["pnl"] = round((exit_price - entry_price) * shares, 2)
            trade["pnl_pct"] = round((exit_price / entry_price - 1) * 100, 2)

        trades.append(trade)

    return pd.DataFrame(trades)


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Returnerar en tom DataFrame."""
    return pd.DataFrame()


@pytest.fixture
def sample_macro_data() -> dict:
    """Returnerar syntetisk makrodata for regime-tester."""
    return {
        "regime": "TJUR",
        "spy_vs_ma200": 0.05,
        "vix_level": 14.5,
        "spy_3m_return": 0.04,
        "breadth_delta": 0.02,
        "yield_spread": 0.02,
        "credit_spread_delta": -0.01,
        "composite": 0.72,
        "confidence": 0.8,
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "notes": ["Bullish: SPY over MA200", "Low VIX indicates calm market"],
    }


@pytest.fixture
def sample_options_chain() -> tuple:
    """Returnerar syntetisk optionskedja (calls, puts) for options-tester."""
    np.random.seed(42)
    n_strikes = 20
    base_price = 150.0

    strikes = [base_price + i * 5 for i in range(-5, n_strikes - 5)]

    calls = pd.DataFrame({
        "strike": strikes,
        "lastPrice": [max(0, base_price - s + np.random.uniform(0.5, 2)) for s in strikes],
        "bid": np.random.uniform(0.1, 5, n_strikes),
        "ask": np.random.uniform(0.1, 5.5, n_strikes),
        "openInterest": np.random.randint(100, 50000, n_strikes),
        "volume": np.random.randint(0, 10000, n_strikes),
        "impliedVolatility": np.random.uniform(0.2, 0.6, n_strikes),
    })

    puts = pd.DataFrame({
        "strike": strikes,
        "lastPrice": [max(0, s - base_price + np.random.uniform(0.5, 2)) for s in strikes],
        "bid": np.random.uniform(0.1, 5, n_strikes),
        "ask": np.random.uniform(0.1, 5.5, n_strikes),
        "openInterest": np.random.randint(100, 50000, n_strikes),
        "volume": np.random.randint(0, 10000, n_strikes),
        "impliedVolatility": np.random.uniform(0.2, 0.6, n_strikes),
    })

    return calls, puts


@pytest.fixture
def sample_piotroski_row() -> dict:
    """En syntetisk rad med Piotroski-data."""
    return {
        "roa": 0.08,
        "free_cash_flow": 1e9,
        "operating_cashflow": 1.2e9,
        "market_cap": 1e10,
        "price_to_book": 2.5,
        "debt_to_equity": 0.5,
        "current_ratio": 2.0,
        "gross_margin": 0.45,
        "operating_margin": 0.15,
        "revenue_growth": 0.10,
        "earnings_growth": 0.12,
        "insider_pct": 0.05,
    }


@pytest.fixture
def mock_requests_get(mocker):
    """Mock requests.get for all API-anrop."""
    mock_resp = mocker.MagicMock()
    mock_resp.status_code = 200

    def mock_json_side_effect(*args, **kwargs):
        # Returnerar tom data som standard
        return {"data": []}

    mock_resp.json.side_effect = mock_json_side_effect
    return mocker.patch("requests.get", return_value=mock_resp)
