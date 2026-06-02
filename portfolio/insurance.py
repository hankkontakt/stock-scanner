"""
insurance.py -- Portfolio Insurance & Risk Metrics
==================================================
Riskhanteringsverktyg för portföljen:

1. Value at Risk (VaR) -- parametrisk + historisk
2. Conditional VaR (Expected Shortfall)
3. Max Drawdown-analys
4. Beta mot benchmark
5. Stress-test-scenarier (2008, COVID, rate hike, inflation)

Användning:
    from portfolio.insurance import (calculate_var, calculate_cvar,
                                      calculate_max_drawdown, stress_test)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Value at Risk ────────────────────────────────────────────────────────────

def calculate_var(returns: np.ndarray,
                  confidence_level: float = 0.95,
                  method: str = "historical") -> dict:
    """
    Beräknar Value at Risk (VaR).

    VaR svarar på frågan: "Vad är den maximala förlusten inom en given
    tidsperiod med X% konfidens?"

    Exempel: 95% VaR = -2% betyder att det är 5% sannolikhet att förlusten
    överstiger 2% under en given period.

    Args:
        returns: Array av historiska avkastningar
        confidence_level: Konfidensnivå (t.ex. 0.95 = 95%)
        method: 'historical' (percentil) eller 'parametric' (normal-fördelning)

    Returns:
        dict med:
            var: Value at Risk (negativt tal = förlust)
            confidence_level: Använd konfidensnivå
            method: Använd metod
            n_obs: Antal observationer
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]

    if len(returns) < 10:
        logger.warning(f"För få observationer för VaR: {len(returns)}")
        return {"var": 0.0, "confidence_level": confidence_level,
                "method": method, "n_obs": len(returns)}

    if method == "historical":
        # Historisk VaR: (1-confidence_level)-percentilen
        alpha = 1.0 - confidence_level
        var = float(np.percentile(returns, alpha * 100))
    elif method == "parametric":
        # Parametrisk VaR: μ - z * σ
        mu = float(np.mean(returns))
        sigma = float(np.std(returns, ddof=1))
        from scipy.stats import norm
        z = norm.ppf(1.0 - confidence_level)
        var = mu + z * sigma
    else:
        logger.warning(f"Okänd metod: {method}, använder historical")
        alpha = 1.0 - confidence_level
        var = float(np.percentile(returns, alpha * 100))

    return {
        "var": round(var, 6),
        "confidence_level": confidence_level,
        "method": method,
        "n_obs": len(returns),
    }


# ── Conditional VaR (Expected Shortfall) ────────────────────────────────────

def calculate_cvar(returns: np.ndarray,
                   confidence_level: float = 0.95) -> dict:
    """
    Beräknar Conditional Value at Risk (CVaR / Expected Shortfall).

    CVaR är genomsnittet av alla förluster som överstiger VaR-tröskeln.
    Detta ger en bättre bild av tail risk än VaR.

    Args:
        returns: Array av historiska avkastningar
        confidence_level: Konfidensnivå (t.ex. 0.95)

    Returns:
        dict med:
            cvar: Conditional VaR (negativt tal)
            var_v: Motsvarande VaR-tröskel
            confidence_level: Använd konfidensnivå
            n_tail: Antal observationer i tailen
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]

    if len(returns) < 10:
        logger.warning(f"För få observationer för CVaR: {len(returns)}")
        return {"cvar": 0.0, "var_v": 0.0,
                "confidence_level": confidence_level, "n_tail": 0}

    # Beräkna VaR först
    alpha = 1.0 - confidence_level
    var_v = float(np.percentile(returns, alpha * 100))

    # CVaR = genomsnitt av returns som är <= VaR
    tail = returns[returns <= var_v]
    cvar = float(np.mean(tail)) if len(tail) > 0 else var_v

    return {
        "cvar": round(cvar, 6),
        "var_v": round(var_v, 6),
        "confidence_level": confidence_level,
        "n_tail": len(tail),
    }


# ── Max Drawdown ────────────────────────────────────────────────────────────

def calculate_max_drawdown(returns: np.ndarray) -> dict:
    """
    Beräknar maximum drawdown från en serie avkastningar.

    Max drawdown = största procentuella nedgången från en topp till en botten.

    Args:
        returns: Array av avkastningar (kan vara pris eller returns)

    Returns:
        dict med:
            max_drawdown: Största nedgången (decimal, t.ex. -0.25 = -25%)
            max_drawdown_duration: Antal dagar från topp till återhämtning
            peak_idx: Index för toppen före drawdown
            valley_idx: Index för botten av drawdown
            recovery_idx: Index för återhämtning (None om ej återhämtad)
    """
    returns = np.asarray(returns, dtype=float)
    returns = returns[~np.isnan(returns)]

    if len(returns) < 5:
        logger.warning(f"För få observationer för max drawdown: {len(returns)}")
        return {"max_drawdown": 0.0, "max_drawdown_duration": 0}

    # Om returns är priser, konvertera till kumulativ avkastning
    # Om returns är avkastningar (< 1.0 typiskt), beräkna kumulativ
    if np.max(np.abs(returns)) > 1.0:
        # Förmodligen priser
        cumulative = returns / returns[0] - 1.0
    else:
        # Förmodligen returns
        cumulative = np.cumprod(1 + returns) - 1.0

    # Beräkna drawdown-kurva
    rolling_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative / (1 + rolling_max)  # Korrekt drawdown-beräkning

    # Max drawdown
    min_idx = np.argmin(drawdown)
    max_dd = drawdown[min_idx]

    # Topp före drawdown
    peak_idx = np.argmax(rolling_max[:min_idx + 1])

    # Återhämtning (första gången cumulative > peak efter valley)
    recovery_idx = None
    for i in range(min_idx + 1, len(cumulative)):
        if cumulative[i] >= cumulative[peak_idx]:
            recovery_idx = i
            break

    # Duration
    if recovery_idx is not None:
        duration = recovery_idx - peak_idx
    else:
        duration = len(cumulative) - peak_idx  # Ej återhämtad

    return {
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_duration": duration,
        "peak_idx": int(peak_idx),
        "valley_idx": int(min_idx),
        "recovery_idx": int(recovery_idx) if recovery_idx is not None else None,
        "recovered": recovery_idx is not None,
    }


# ── Beta ─────────────────────────────────────────────────────────────────────

def calculate_beta(returns: np.ndarray,
                   benchmark_returns: np.ndarray) -> dict:
    """
    Beräknar beta mot benchmark.

    Beta = Cov(asset, benchmark) / Var(benchmark)

    Beta > 1: asset är mer volatil än benchmark
    Beta = 1: asset rör sig som benchmark
    Beta < 1: asset är mindre volatil än benchmark
    Beta < 0: asset rör sig mot benchmark

    Args:
        returns: Asset-avkastningar (N,)
        benchmark_returns: Benchmark-avkastningar (N,)

    Returns:
        dict med:
            beta: Beta-värde
            alpha: Jensen's alpha (risk-justerad meravkastning)
            r_squared: Förklaringsgrad (R²)
            correlation: Korrelation med benchmark
            n_obs: Antal observationer
    """
    returns = np.asarray(returns, dtype=float)
    benchmark_returns = np.asarray(benchmark_returns, dtype=float)

    # Rensa NaN
    mask = ~(np.isnan(returns) | np.isnan(benchmark_returns))
    returns = returns[mask]
    benchmark_returns = benchmark_returns[mask]

    if len(returns) < 10:
        logger.warning(f"För få observationer för beta: {len(returns)}")
        return {"beta": 1.0, "alpha": 0.0, "r_squared": 0.0,
                "correlation": 0.0, "n_obs": len(returns)}

    cov_matrix = np.cov(returns, benchmark_returns)
    beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] > 0 else 1.0

    # Alpha = E[asset] - beta * E[benchmark]
    alpha = float(np.mean(returns) - beta * np.mean(benchmark_returns))

    # R² = korrelation²
    corr = float(np.corrcoef(returns, benchmark_returns)[0, 1])
    r_squared = corr ** 2

    return {
        "beta": round(beta, 4),
        "alpha": round(alpha, 6),
        "r_squared": round(r_squared, 4),
        "correlation": round(corr, 4),
        "n_obs": len(returns),
    }


# ── Stress Test ─────────────────────────────────────────────────────────────

def stress_test(portfolio: pd.DataFrame,
                scenarios: Optional[dict] = None) -> pd.DataFrame:
    """
    Stress-testar en portfölj mot olika marknadsscenarier.

    Varje scenario specificerar en förväntad procentuell förändring per sektor,
    och portföljens påverkan beräknas baserat på vikt och beta.

    Inbyggda scenarier:
        - 2008 Financial Crisis
        - COVID-19 Crash
        - Rate Hike (räntehöjnings-chock)
        - Stagflation (hög inflation + låg tillväxt)

    Args:
        portfolio: DataFrame med kolumner [ticker, weight, beta, sector]
                  weight: andel av portföljen (decimal, sum = 1.0)
                  beta: beta-värde per ticker
        scenarios: Dict med scenario-namn -> {sektor: % förändring}
                   Om None, används inbyggda scenarier.

    Returns:
        DataFrame med påverkan per ticker per scenario
    """
    if portfolio.empty:
        return pd.DataFrame()

    required_cols = {"ticker", "weight", "beta"}
    if not required_cols.issubset(portfolio.columns):
        logger.warning(f"Portfolio saknar kolumner: {required_cols - set(portfolio.columns)}")
        return pd.DataFrame()

    # Default-scenarier (sektorbaserad påverkan)
    if scenarios is None:
        scenarios = _default_stress_scenarios()

    result_rows = []
    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        weight = float(row["weight"])
        beta = float(row.get("beta", 1.0))

        # Sektor (default = "General")
        sector = str(row.get("sector", "General"))

        entry = {"Ticker": ticker, "Vikt": weight, "Beta": beta}

        for scenario_name, sector_impacts in scenarios.items():
            # Hämta sektor-påverkan, fallback till generell marknadspåverkan
            impact = sector_impacts.get(sector, sector_impacts.get("_default_", 0.0))

            # Beta-adjusted impact
            adjusted_impact = impact * beta

            # Portfölj-viktad påverkan
            weighted_impact = adjusted_impact * weight

            entry[scenario_name] = round(weighted_impact, 6)

        result_rows.append(entry)

    result = pd.DataFrame(result_rows)

    # Beräkna total portföljpåverkan per scenario
    totals = {"Ticker": "TOTAL PORTRÄTT"}
    for scenario_name in scenarios.keys():
        total_impact = result[scenario_name].sum()
        totals[scenario_name] = round(total_impact, 6)

    totals["Vikt"] = 1.0
    totals["Beta"] = 0.0  # placeholder

    result = pd.concat([result, pd.DataFrame([totals])], ignore_index=True)
    return result


def _default_stress_scenarios() -> dict:
    """
    Returnerar inbyggda stress-scenarier med sektor-påverkan.

    Varje scenario: dict med sektor -> %-förändring
    _default_ används om en sektor inte finns explicit.
    """
    return {
        "2008 Finanskris (-40%)": {
            "_default_": -0.40,
            "Financial Services": -0.55,
            "Real Estate": -0.50,
            "Technology": -0.35,
            "Consumer Cyclical": -0.45,
            "Energy": -0.30,
            "Utilities": -0.20,
            "Healthcare": -0.20,
            "Consumer Defensive": -0.15,
        },
        "COVID-19 (-35%)": {
            "_default_": -0.35,
            "Travel/Hospitality": -0.60,
            "Energy": -0.50,
            "Consumer Cyclical": -0.40,
            "Technology": -0.20,
            "Healthcare": -0.15,
            "Utilities": -0.15,
            "Consumer Defensive": -0.10,
        },
        "Räntechock (+2%)": {
            "_default_": -0.15,
            "Real Estate": -0.35,
            "Utilities": -0.25,
            "Technology (High Growth)": -0.25,
            "Financial Services": +0.05,  # Banker tjänar på högre räntor
            "Energy": -0.05,
        },
        "Stagflation": {
            "_default_": -0.20,
            "Consumer Cyclical": -0.35,
            "Technology": -0.30,
            "Energy": +0.10,  # Energi gynnas av inflation
            "Basic Materials": +0.05,
            "Consumer Defensive": -0.05,
            "Healthcare": -0.05,
            "Utilities": -0.15,
        },
    }


def scenario_analysis_summary(stress_df: pd.DataFrame) -> dict:
    """
    Sammanfattar stress-test-resultat i lättolkad form.

    Args:
        stress_df: DataFrame från stress_test()

    Returns:
        dict med scenario -> {total_impact, worst_asset, best_asset, risk_level}
    """
    if stress_df.empty:
        return {}

    # Ta bort total-raden för asset-analys
    assets_df = stress_df[stress_df["Ticker"] != "TOTAL PORTRÄTT"].copy() if "Ticker" in stress_df.columns else stress_df.copy()

    # Identifiera scenario-kolumner (inte Ticker, Vikt, Beta)
    scenario_cols = [c for c in stress_df.columns
                     if c not in ("Ticker", "Vikt", "Beta")]

    summary = {}
    for col in scenario_cols:
        total = stress_df[col].iloc[-1] if len(stress_df) > 0 else 0
        if len(assets_df) > 0:
            worst_idx = assets_df[col].idxmin()
            worst = assets_df.loc[worst_idx, "Ticker"] if "Ticker" in assets_df.columns else "N/A"
            best_idx = assets_df[col].idxmax()
            best = assets_df.loc[best_idx, "Ticker"] if "Ticker" in assets_df.columns else "N/A"

            # Risk level
            if total < -0.25:
                risk = "Hög"
            elif total < -0.10:
                risk = "Medel"
            else:
                risk = "Låg"
        else:
            worst = "N/A"
            best = "N/A"
            risk = "Okänd"

        summary[col] = {
            "total_impact_pct": round(total * 100, 1),
            "worst_asset": worst,
            "best_asset": best,
            "risk_level": risk,
        }

    return summary


# ══════════════════════════════════════════════════════════════════════════════
# CLI-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Simulera returns
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, 500)

    # VaR
    var_result = calculate_var(returns, 0.95, "historical")
    print(f"VaR (95%, historical): {var_result['var']:.4f}")

    var_p = calculate_var(returns, 0.95, "parametric")
    print(f"VaR (95%, parametric): {var_p['var']:.4f}")

    # CVaR
    cvar_result = calculate_cvar(returns, 0.95)
    print(f"CVaR (95%): {cvar_result['cvar']:.4f} (tail: {cvar_result['n_tail']} obs)")

    # Max Drawdown
    dd = calculate_max_drawdown(returns)
    print(f"Max Drawdown: {dd['max_drawdown']:.2%}")
    print(f"Duration: {dd['max_drawdown_duration']} dagar")
    print(f"Återhämtad: {dd['recovered']}")

    # Beta
    bench = np.random.normal(0.0004, 0.015, 500)
    beta = calculate_beta(returns, bench)
    print(f"\nBeta: {beta['beta']:.2f}, Alpha: {beta['alpha']:.4f}")

    # Stress test
    pf = pd.DataFrame({
        "ticker": ["AAPL", "JPM", "XOM"],
        "weight": [0.5, 0.3, 0.2],
        "beta": [1.2, 1.4, 0.8],
        "sector": ["Technology", "Financial Services", "Energy"],
    })
    stress = stress_test(pf)
    print(f"\nStress-test resultat:")
    print(stress.to_string())
