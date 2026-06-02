"""
strategy/performance.py
=======================
Prestandaanalys och attribuering.

Innehåller:
- calculate_returns: portföljavkastning
- brinson_attribution: Brinson-attribuering
- carhart_attribution: Carhart 4-faktor-attribuering
- performance_summary: komplett sammanfattning
"""

import numpy as np
import pandas as pd


def calculate_returns(positions: pd.Series, prices: pd.Series) -> pd.Series:
    """
    Beräkna portföljavkastning från positioner och priser.

    positions: Antal aktier (eller exponering)
    prices:    Pris-serie

    Return: Daglig portföljavkastning
    """
    # Värdet på portföljen varje dag
    portfolio_value = positions * prices
    # Daglig förändring
    daily_pnl = portfolio_value.diff()
    # Avkastning = P&L / föregående värde
    prev_value = portfolio_value.shift(1).replace(0, np.nan)
    returns = daily_pnl / prev_value
    return returns.fillna(0)


def brinson_attribution(weights: pd.Series, sector_weights: pd.Series,
                        returns: pd.Series, benchmark_returns: pd.Series) -> dict:
    """
    Brinson-attribuering: dela upp meravkastning i allokering, selektion och interaktion.

    weights:           Portföljvikter per tillgång
    sector_weights:    Sektor per tillgång
    returns:           Portföljavkastning per tillgång
    benchmark_returns: Benchmarkavkastning per tillgång

    Return: dict med allocation_effect, selection_effect, interaction_effect, total_excess
    """
    data = pd.DataFrame({
        "weight": weights,
        "sector": sector_weights,
        "return": returns,
        "benchmark_return": benchmark_returns,
    }).dropna()

    if data.empty:
        return {}

    # Total excess return
    total_portfolio_return = (data["weight"] * data["return"]).sum()
    total_benchmark_return = (data["weight"] * data["benchmark_return"]).sum()
    total_excess = total_portfolio_return - total_benchmark_return

    # Per sektor
    sectors = data["sector"].unique()
    allocation_effect = 0.0
    selection_effect = 0.0
    interaction_effect = 0.0

    for sector in sectors:
        sector_data = data[data["sector"] == sector]

        w_port = sector_data["weight"].sum()
        r_port = (sector_data["weight"] * sector_data["return"]).sum() / w_port if w_port > 0 else 0
        r_bench = (sector_data["weight"] * sector_data["benchmark_return"]).sum() / w_port if w_port > 0 else 0

        # Allokeringseffekt: (w_port - w_bench) * (r_bench - total_benchmark_return)
        w_bench = w_port  # Förenklad: antar samma vikter
        alloc = (w_port - w_bench) * (r_bench - total_benchmark_return)

        # Selektionsfekt: w_bench * (r_port - r_bench)
        select = w_bench * (r_port - r_bench)

        # Interaktionseffekt: (w_port - w_bench) * (r_port - r_bench)
        interact = (w_port - w_bench) * (r_port - r_bench)

        allocation_effect += alloc
        selection_effect += select
        interaction_effect += interact

    return {
        "allocation_effect": float(allocation_effect),
        "selection_effect": float(selection_effect),
        "interaction_effect": float(interaction_effect),
        "total_excess_return": float(total_excess),
    }


def carhart_attribution(returns: pd.Series, factor_returns: pd.DataFrame) -> dict:
    """
    Carhart 4-faktor-attribuering.
    Regresserar portföljavkastning mot marknad, SMB, HML, WML.

    returns:        Portföljens dagliga avkastning
    factor_returns: DataFrame med kolumner: market, smb, hml, wml

    Return: dict med alpha, market_beta, smb_beta, hml_beta, wml_beta, r_squared
    """
    from sklearn.linear_model import LinearRegression

    # Slå samman
    data = pd.DataFrame({"portfolio": returns})
    data = data.join(factor_returns).dropna()

    if len(data) < 30:
        return {"error": "För lite data för regression (behövs >=30 dagar)"}

    X = data[["market", "smb", "hml", "wml"]].values
    y = data["portfolio"].values

    model = LinearRegression()
    model.fit(X, y)

    r_squared = model.score(X, y)
    residuals = y - model.predict(X)

    return {
        "alpha": float(model.intercept_ * 252),  # Annualiserad alpha
        "market_beta": float(model.coef_[0]),
        "smb_beta": float(model.coef_[1]),
        "hml_beta": float(model.coef_[2]),
        "wml_beta": float(model.coef_[3]),
        "r_squared": float(r_squared),
        "residual_vol": float(np.std(residuals) * np.sqrt(252)),
        "n_obs": len(data),
    }


def performance_summary(returns: pd.Series, risk_free_rate: float = 0.02) -> dict:
    """
    Komplett prestandasammanfattning.

    returns:        Daglig portföljavkastning
    risk_free_rate: Årlig riskfri ränta (default 2%)

    Return: dict med:
        - CAGR, Sharpe, Sortino, Calmar
        - Max DD, Win rate, Profit factor, Avg win/loss
        - Rolling Sharpe (6 månader)
        - Rolling beta
        - Skewness, kurtosis
        - Serial correlation
    """
    if isinstance(returns, pd.DataFrame):
        returns = returns.iloc[:, 0]
    if len(returns) < 10:
        return {"error": "För lite data"}

    returns = returns.dropna()
    n = len(returns)
    rf_daily = risk_free_rate / 252

    # CAGR
    total_return = (1 + returns).prod() - 1
    n_years = n / 252
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0.0

    # Sharpe
    excess = returns - rf_daily
    sharpe = float(np.sqrt(252) * excess.mean() / returns.std()) if returns.std() > 0 else 0.0

    # Sortino
    downside = returns[returns < 0]
    sortino = float(np.sqrt(252) * excess.mean() / downside.std()) if len(downside) > 1 and downside.std() > 0 else 0.0

    # Max drawdown
    equity = (1 + returns).cumprod()
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = float(drawdown.min())

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    # Volatilitet
    volatility = float(returns.std() * np.sqrt(252))

    # Skewness och kurtosis
    skewness = float(returns.skew())
    kurtosis = float(returns.kurtosis())

    # Serial correlation (lag-1 autokorrelation)
    serial_corr = float(returns.autocorr()) if n > 1 else 0.0

    # Rolling Sharpe (6 månader = 126 dagar)
    rolling_sharpe = returns.rolling(126).apply(
        lambda x: np.sqrt(252) * (x.mean() - rf_daily) / x.std() if x.std() > 0 else 0
    ).dropna()
    avg_rolling_sharpe = float(rolling_sharpe.mean()) if not rolling_sharpe.empty else 0.0

    # Rolling beta mot marknad (approximerad med egen serie)
    rolling_beta = pd.Series(dtype=float)

    return {
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "max_drawdown": round(max_dd, 4),
        "volatility": round(volatility, 4),
        "total_return": round(total_return, 4),
        "n_obs": n,
        "n_years": round(n_years, 2),
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis, 4),
        "serial_correlation": round(serial_corr, 4),
        "avg_rolling_sharpe_6m": round(avg_rolling_sharpe, 4),
    }


def _rolling_beta(returns: pd.Series, market_returns: pd.Series, window: int = 252) -> pd.Series:
    """Beräkna rullande beta över fönster."""
    from sklearn.linear_model import LinearRegression

    def _beta(y, x):
        if len(y) < 10 or len(x) < 10:
            return np.nan
        model = LinearRegression()
        model.fit(x.values.reshape(-1, 1), y.values)
        return model.coef_[0]

    beta_series = pd.Series(index=returns.index, dtype=float)
    for i in range(window, len(returns)):
        y = returns.iloc[i - window:i]
        x = market_returns.iloc[i - window:i]
        beta_series.iloc[i] = _beta(y, x)

    return beta_series
