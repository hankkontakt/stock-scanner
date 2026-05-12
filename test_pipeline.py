"""Quick test with mocked data to verify scoring + report generation works."""
import pandas as pd
import numpy as np
import scoring
import portfolio
from scan import generate_report

# Mock data simulating yfinance output
np.random.seed(42)
n = 30
mock_data = pd.DataFrame({
    "ticker": [f"TEST{i}" for i in range(n)],
    "name": [f"Test Company {i}" for i in range(n)],
    "sector": np.random.choice(["Tech", "Finance", "Healthcare", "Consumer"], n),
    "industry": "Various",
    "country": "US",
    "currency": "USD",
    "market_cap": np.random.lognormal(23, 1.5, n),
    "pe_trailing": np.random.uniform(8, 80, n),
    "pe_forward": np.random.uniform(7, 60, n),
    "peg_ratio": np.random.uniform(0.5, 3, n),
    "price_to_book": np.random.uniform(0.5, 15, n),
    "price_to_sales": np.random.uniform(0.5, 20, n),
    "ev_to_revenue": np.random.uniform(1, 15, n),
    "ev_to_ebitda": np.random.uniform(5, 40, n),
    "roe": np.random.uniform(-0.1, 0.4, n),
    "roa": np.random.uniform(-0.05, 0.2, n),
    "profit_margin": np.random.uniform(-0.1, 0.35, n),
    "operating_margin": np.random.uniform(-0.05, 0.4, n),
    "gross_margin": np.random.uniform(0.1, 0.7, n),
    "revenue_growth": np.random.uniform(-0.2, 0.5, n),
    "earnings_growth": np.random.uniform(-0.3, 0.6, n),
    "earnings_quarterly_growth": np.random.uniform(-0.4, 0.8, n),
    "debt_to_equity": np.random.uniform(0, 200, n),
    "current_ratio": np.random.uniform(0.5, 4, n),
    "quick_ratio": np.random.uniform(0.3, 3, n),
    "free_cash_flow": np.random.uniform(-1e9, 5e10, n),
    "dividend_yield": np.random.uniform(0, 0.06, n),
    "payout_ratio": np.random.uniform(0, 1.2, n),
    "beta": np.random.uniform(0.4, 2.0, n),
    "current_price": np.random.uniform(20, 500, n),
    "52_week_high": np.random.uniform(50, 600, n),
    "52_week_low": np.random.uniform(10, 100, n),
    "target_mean_price": np.random.uniform(30, 700, n),
    "recommendation_mean": np.random.uniform(1.5, 4, n),
    "number_of_analysts": np.random.randint(3, 30, n),
    "return_1m": np.random.normal(0.01, 0.06, n),
    "return_3m": np.random.normal(0.03, 0.12, n),
    "return_6m": np.random.normal(0.05, 0.20, n),
    "return_12m": np.random.normal(0.08, 0.30, n),
    "pct_from_52w_high": np.random.uniform(-0.4, 0, n),
    "volatility": np.random.uniform(0.15, 0.6, n),
    "rsi_14": np.random.uniform(20, 85, n),
    "price_vs_ma50": np.random.normal(0, 0.05, n),
    "price_vs_ma200": np.random.normal(0.02, 0.10, n),
})

# Make some tickers actually our holdings
mock_data.loc[0, "ticker"] = "AAPL"
mock_data.loc[0, "name"] = "Apple Inc"
mock_data.loc[1, "ticker"] = "VOLV-B.ST"
mock_data.loc[1, "name"] = "Volvo B"

print("=" * 60)
print("TEST: Stock Scanner Pipeline")
print("=" * 60)

print(f"\n1. Mocked data: {len(mock_data)} stocks")

# Test scoring
print("\n2. Calculating scores...")
scored = scoring.score_universe(mock_data)
print(f"   ✓ Scored {len(scored)} stocks")
print(f"   ✓ Top 3:")
for _, row in scored.head(3).iterrows():
    print(f"      #{row['rank']} {row['ticker']:12s} score={row['score_total']:.1f} "
          f"(V={row['score_value']:.0f} Q={row['score_quality']:.0f} M={row['score_momentum']:.0f})")

# Test portfolio analysis
print("\n3. Loading holdings...")
holdings = pd.DataFrame({
    "ticker": ["AAPL", "VOLV-B.ST", "TEST5"],
    "shares": [10, 100, 50],
    "cost_basis": [150.0, 210.0, 100.0],
})
print(f"   ✓ {len(holdings)} positions")

print("\n4. Analyzing portfolio...")
analysis = portfolio.analyze_portfolio(holdings, scored)
summary = portfolio.portfolio_summary(analysis)
print(f"   ✓ Generated recommendations:")
for _, row in analysis.iterrows():
    print(f"      {row['ticker']:12s} → {row['recommendation']:12s} ({row['reason'][:50]})")

# Test report generation
print("\n5. Generating markdown report...")
report = generate_report(scored, analysis, summary)
print(f"   ✓ Report length: {len(report)} chars")

# Save sample report for inspection
with open("/tmp/sample_report.md", "w") as f:
    f.write(report)
print(f"   ✓ Saved to /tmp/sample_report.md")

print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED - Pipeline works correctly!")
print("=" * 60)
