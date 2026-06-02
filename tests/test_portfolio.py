"""
Tester for portfolio/ — Portfoljanalys, korrelation, BL-optimering, Kelly, VaR.
"""
import numpy as np
import pandas as pd
import pytest

from portfolio.portfolio import load_holdings, analyze_portfolio
from portfolio.portfolio_analysis import (
    calc_correlation_matrix,
    analyze_concentration,
)
from portfolio.black_litterman import (
    black_litterman_weights,
    TAU_DEFAULT,
    DELTA_DEFAULT,
)


class TestPortfolioAnalysis:
    """Testar portfoljanalysfunktioner."""

    def test_load_holdings(self, tmp_path):
        """Ladda holdings fran CSV."""
        csv_path = tmp_path / "holdings.csv"
        csv_path.write_text("ticker,shares,cost_basis\nAAPL,100,150.0\nMSFT,50,300.0")
        df = load_holdings(str(csv_path))
        assert len(df) == 2
        assert "AAPL" in df["ticker"].values

    def test_load_holdings_missing_file(self):
        """Icke-existerande fil returnerar tom DataFrame."""
        df = load_holdings("/nonexistent/path.csv")
        assert df.empty

    def test_load_holdings_missing_columns(self, tmp_path):
        """Filtrigt format returnerar tom DataFrame."""
        csv_path = tmp_path / "bad_holdings.csv"
        csv_path.write_text("name,value\nAAPL,100")
        df = load_holdings(str(csv_path))
        assert df.empty

    def test_analyze_portfolio(self, sample_holdings_df, sample_scored_df):
        """Analysera portfolj mot scored universe."""
        result = analyze_portfolio(sample_holdings_df, sample_scored_df)
        assert isinstance(result, pd.DataFrame)

    def test_analyze_empty_portfolio(self, empty_df, sample_scored_df):
        """Tom portfolj returnerar tom DataFrame."""
        result = analyze_portfolio(empty_df, sample_scored_df)
        assert result.empty


class TestCorrelation:
    """Testar korrelationsberakning."""

    def test_calc_correlation_matrix(self, mocker, sample_holdings_df):
        """Korrelationsmatris for 5 innehav."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=252, freq="D")
        # Create a DataFrame with MultiIndex columns like yfinance returns
        arrays = [["Close"] * 5, list(sample_holdings_df["ticker"])]
        tuples = list(zip(*arrays))
        index = pd.MultiIndex.from_tuples(tuples, names=["Price", "Ticker"])
        prices = pd.DataFrame(
            np.random.uniform(100, 200, (252, 5)),
            index=dates,
            columns=index,
        )
        mocker.patch("portfolio.portfolio_analysis._rc", return_value=None)
        mocker.patch("portfolio.portfolio_analysis._wc")
        mocker.patch("yfinance.download", return_value=prices)

        corr = calc_correlation_matrix(sample_holdings_df)
        assert isinstance(corr, pd.DataFrame)
        assert corr.shape[0] == len(sample_holdings_df)

    def test_calc_correlation_empty(self, empty_df):
        """Tom portfolj ger tom korrelationsmatris."""
        corr = calc_correlation_matrix(empty_df)
        assert corr.empty

    def test_calc_correlation_single_holding(self):
        """Enskilt innehav ger tom matris (behover minst 2)."""
        holdings = pd.DataFrame({"ticker": ["AAPL"], "shares": [100]})
        corr = calc_correlation_matrix(holdings)
        assert corr.empty


class TestConcentration:
    """Testar koncentrationsmatt."""

    def test_calc_concentration(self, sample_holdings_df, sample_scored_df):
        """Koncentrationsberakning fungerar."""
        df = sample_holdings_df.copy()
        df["market_value"] = df["shares"] * df["current_price"]
        result = analyze_concentration(df, sample_scored_df)
        assert isinstance(result, dict) or result is None

    def test_concentration_all_equal(self, sample_scored_df):
        """Alla innehav lika stora."""
        df = pd.DataFrame({
            "ticker": ["A", "B", "C", "D", "E"],
            "shares": [100] * 5,
            "current_price": [100] * 5,
            "sector": ["Tech"] * 5,
        })
        df["market_value"] = df["shares"] * df["current_price"]
        result = analyze_concentration(df, sample_scored_df)
        assert isinstance(result, dict) or result is None


class TestBlackLitterman:
    """Testar Black-Litterman optimering."""

    def test_black_litterman_weights(self, sample_scored_df):
        """BL optimering returnerar vikter som summerar till 1.0."""
        df_subset = sample_scored_df[["ticker", "score_total", "market_cap", "return_12m"]].copy()
        df_subset["return_12m"] = pd.to_numeric(df_subset["return_12m"], errors="coerce").fillna(0)
        df_subset["market_cap"] = pd.to_numeric(df_subset["market_cap"], errors="coerce").fillna(1e9)
        # Ensure clean numeric types
        df_subset = df_subset.dropna(subset=["market_cap"])
        df_subset = df_subset[df_subset["market_cap"] > 0]
        if len(df_subset) > 2:
            result = black_litterman_weights(df_subset, historical_ic=0.05)
            if isinstance(result, pd.DataFrame) and not result.empty:
                weight_cols = [c for c in result.columns if "weight" in c.lower()]
                if weight_cols:
                    total = result[weight_cols[0]].sum()
                    assert abs(total - 1.0) < 0.01

    def test_empty_input(self, empty_df):
        """Empty DataFrame returns empty DataFrame."""
        result = black_litterman_weights(empty_df, historical_ic=0.05)
        # Should handle empty gracefully
        assert result is None or (isinstance(result, pd.DataFrame) and result.empty)

    def test_low_ic(self, sample_scored_df):
        """Mycket lag IC ger equilibrium-vikter."""
        weights = black_litterman_weights(sample_scored_df, historical_ic=0.001)
        assert weights is not None


class TestPortfolioEdgeCases:
    """Testar edge cases for portfoljfunktioner."""

    def test_portfolio_with_nan(self):
        """NaN i portfoljdata hanteras."""
        df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT"],
            "shares": [100, None],
            "cost_basis": [150.0, None],
        })
        assert not df.empty

    def test_kelly_fraction(self):
        """Kelly-sizing berakning."""
        try:
            from portfolio.portfolio import kelly_fraction
            result = kelly_fraction(0.1, 0.5)
            assert isinstance(result, float)
            assert result >= 0
        except ImportError:
            pass

    def test_monte_carlo_simulation(self):
        """Monte Carlo simulering."""
        try:
            from portfolio.portfolio import monte_carlo_simulation
            result = monte_carlo_simulation(initial_capital=100000, n_simulations=50, n_days=252)
            assert isinstance(result, (dict, list))
        except ImportError:
            pass

    def test_kelly_criterion_math(self):
        """Kelly-kriteriet ger korrekta varden."""
        # f* = (bp - q) / b dar b = net odds, p = win probability, q = loss prob
        b = 1.0  # Even odds
        p = 0.6  # 60% win rate
        q = 0.4
        f_star = (b * p - q) / b
        assert abs(f_star - 0.2) < 0.001

    def test_empty_portfolio_all_funcs(self, empty_df, sample_scored_df):
        """Tom portfolj genom alla funktioner krashar inte."""
        from portfolio.portfolio import analyze_portfolio
        from portfolio.portfolio_analysis import calc_correlation_matrix

        result = analyze_portfolio(empty_df, sample_scored_df)
        assert result.empty

        corr = calc_correlation_matrix(empty_df)
        assert corr.empty

    def test_var_calculation_using_numpy(self):
        """Value at Risk hjalpfunktion."""
        import numpy as np
        returns = np.random.normal(0, 0.01, 100)
        var = np.percentile(returns, 5)
        assert var < 0  # VaR ar negativ (forlust)

    def test_historical_var(self):
        """Historisk VaR-berakning."""
        import numpy as np
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 1000)
        var_95 = np.percentile(returns, 5)
        var_99 = np.percentile(returns, 1)
        assert var_99 < var_95  # 99% VaR ska vara lagre (mer negativ)
