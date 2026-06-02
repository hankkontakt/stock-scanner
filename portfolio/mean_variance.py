"""
mean_variance.py -- Mean-Variance Optimization (Markowitz)
=======================================================
Implementerar klassisk Mean-Variance optimering enligt Markowitz portföljteori:

1. max Sharpe ratio (tangency portfolio)
2. Global minimum variance portfolio
3. Efficient frontier (hela kurvan)
4. Sektor-neutrala constraints och factor exposure limits

Använder scipy.optimize för all optimering -- inga extra dependencies.

Användning:
    from portfolio.mean_variance import MeanVarianceOptimizer
    opt = MeanVarianceOptimizer()
    weights = opt.max_sharpe(returns, cov_matrix)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize, Bounds, LinearConstraint

logger = logging.getLogger(__name__)


class MeanVarianceOptimizer:
    """
    Mean-Variance portföljoptimerare.

    Optimerar portföljvikter för att maximera risk-justerad avkastning
    (Sharpe ratio) eller minimera volatilitet, med stöd för:
      - Long-only constraints (min/max vikt per asset)
      - Sektor-neutrala constraints
      - Factor exposure limits
    """

    def __init__(self, risk_free_rate: float = 0.02):
        """
        Args:
            risk_free_rate: Årlig riskfri ränta (t.ex. 0.02 = 2%)
        """
        self.risk_free_rate = risk_free_rate

    # ── Hjälpfunktioner ────────────────────────────────────────────────────

    @staticmethod
    def _portfolio_stats(weights: np.ndarray,
                         returns: np.ndarray,
                         cov_matrix: np.ndarray) -> tuple:
        """
        Beräknar portföljens förväntade avkastning och volatilitet.

        Args:
            weights: Viktvektor (N,)
            returns: Förväntad avkastning per asset (N,)
            cov_matrix: Kovariansmatris (N x N)

        Returns:
            (port_return, port_volatility)
        """
        port_return = np.dot(weights, returns)
        port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        return port_return, port_vol

    def _neg_sharpe(self, weights: np.ndarray,
                    returns: np.ndarray,
                    cov_matrix: np.ndarray) -> float:
        """Negativa Sharpe ratio (för minimering)."""
        port_return, port_vol = self._portfolio_stats(weights, returns, cov_matrix)
        if port_vol == 0:
            return 0.0
        return -(port_return - self.risk_free_rate) / port_vol

    @staticmethod
    def _portfolio_vol(weights: np.ndarray, cov_matrix: np.ndarray) -> float:
        """Portföljvolatilitet (för minimering av varians)."""
        return np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))

    # ── Constraint-byggare ─────────────────────────────────────────────────

    def _build_constraints(self, n_assets: int,
                           sector_map: Optional[dict] = None,
                           sector_bounds: Optional[dict] = None,
                           factor_exposures: Optional[dict] = None,
                           factor_limits: Optional[dict] = None) -> list:
        """
        Bygger optimerings-constraints.

        Args:
            n_assets: Antal tillgångar
            sector_map: {sektor: [index_list]} mapping
            sector_bounds: {sektor: (min, max)} per sektor
            factor_exposures: {faktor: np.ndarray(N,)} exposures per faktor
            factor_limits: {faktor: (min, max)} per faktor

        Returns:
            Lista med constraints för scipy.optimize
        """
        constraints = [
            # Vikterna måste summera till 1.0 (fully invested)
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        ]

        # Sektor-constraints
        if sector_map and sector_bounds:
            for sector, indices in sector_map.items():
                if sector in sector_bounds:
                    s_min, s_max = sector_bounds[sector]
                    constraints.append({
                        "type": "ineq",
                        "fun": lambda w, idx=indices, smin=s_min: np.sum(w[idx]) - smin
                    })
                    constraints.append({
                        "type": "ineq",
                        "fun": lambda w, idx=indices, smax=s_max: smax - np.sum(w[idx])
                    })

        # Factor exposure constraints (via LinearConstraint)
        if factor_exposures and factor_limits:
            for factor, exposures in factor_exposures.items():
                if factor in factor_limits:
                    f_min, f_max = factor_limits[factor]
                    # exposures @ weights måste vara inom [f_min, f_max]
                    constraints.append({
                        "type": "ineq",
                        "fun": lambda w, e=exposures, fm=f_min: np.dot(e, w) - fm
                    })
                    constraints.append({
                        "type": "ineq",
                        "fun": lambda w, e=exposures, fx=f_max: fx - np.dot(e, w)
                    })

        return constraints

    # ── Huvud-optimering ───────────────────────────────────────────────────

    def optimize(self,
                 returns: np.ndarray,
                 cov_matrix: np.ndarray,
                 risk_tolerance: float = 0.5,
                 min_weight: float = 0.01,
                 max_weight: float = 0.25,
                 sector_map: Optional[dict] = None,
                 sector_bounds: Optional[dict] = None,
                 factor_exposures: Optional[dict] = None,
                 factor_limits: Optional[dict] = None,
                 initial_guess: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Optimerar portföljen för maximerad risk-justerad avkastning.

        Målfunktionen balanserar avkastning mot risk baserat på risk_tolerance:
            max: w'R - (1/risk_tolerance) * w'Σw

        Args:
            returns: Förväntad avkastning (N,)
            cov_matrix: Kovariansmatris (N x N)
            risk_tolerance: 0.0 (helt risk-avers) -> 1.0 (helt risk-sökande)
            min_weight: Minimi-vikt per asset (t.ex. 0.01)
            max_weight: Maximi-vikt per asset (t.ex. 0.25)
            sector_map: {sektor_namn: [index_list]}
            sector_bounds: {sektor_namn: (min_vikt, max_vikt)}
            factor_exposures: {faktor_namn: np.ndarray(N,) av exposures}
            factor_limits: {faktor_namn: (min, max)}
            initial_guess: Startgissning för vikter (om None -> equal weight)

        Returns:
            Optimerad viktvektor (N,)
        """
        n_assets = len(returns)

        # Sätt bounds
        bounds = Bounds([min_weight] * n_assets, [max_weight] * n_assets)

        # Initial guess
        if initial_guess is None:
            initial_guess = np.array([1.0 / n_assets] * n_assets)

        # Bygg constraints
        constraints = self._build_constraints(
            n_assets, sector_map, sector_bounds,
            factor_exposures, factor_limits
        )

        # Målfunktion: negativ utility (för minimering)
        # Utility = w'R - (1/risk_tolerance) * w'Σw
        def _neg_utility(w):
            ret, vol = self._portfolio_stats(w, returns, cov_matrix)
            risk_penalty = (1.0 / max(risk_tolerance, 0.01)) * (vol ** 2)
            return -(ret - risk_penalty)

        # Optimera
        result = minimize(
            _neg_utility,
            initial_guess,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-9}
        )

        if not result.success:
            logger.warning(f"Optimering konvergerade inte: {result.message}")
            # Fallback: returnera constrained equal weight
            weights = np.clip(initial_guess, min_weight, max_weight)
            return weights / np.sum(weights)

        weights = result.x
        # Säkerställ att bounds hålls
        weights = np.clip(weights, min_weight, max_weight)
        weights = weights / np.sum(weights)
        return weights

    # ── Efficient Frontier ─────────────────────────────────────────────────

    def efficient_frontier(self,
                           returns: np.ndarray,
                           cov_matrix: np.ndarray,
                           n_points: int = 100,
                           min_weight: float = 0.01,
                           max_weight: float = 0.25) -> pd.DataFrame:
        """
        Beräknar hela efficient frontier-kurvan.

        Returnerar DataFrame med kolumner: [return, volatility, sharpe, weight_1...weight_N]

        Args:
            returns: Förväntad avkastning (N,)
            cov_matrix: Kovariansmatris (N x N)
            n_points: Antal punkter på kurvan
            min_weight: Minimi-vikt per asset
            max_weight: Maximi-vikt per asset

        Returns:
            DataFrame med n_points rader, en per portfölj på efficient frontier
        """
        n_assets = len(returns)
        bounds = Bounds([min_weight] * n_assets, [max_weight] * n_assets)
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        ]

        # Hitta min och max möjlig avkastning
        ret_min = np.min(returns)
        ret_max = np.max(returns)

        # Skapa mål-avkastningar över intervallet
        target_returns = np.linspace(ret_min, ret_max, n_points)

        frontier_data = []
        for target_ret in target_returns:
            # Minimera volatilitet för given mål-avkastning
            ret_constraint = {
                "type": "eq",
                "fun": lambda w, t=target_ret: np.dot(w, returns) - t
            }
            all_constraints = constraints + [ret_constraint]

            result = minimize(
                self._portfolio_vol,
                np.array([1.0 / n_assets] * n_assets),
                args=(cov_matrix,),
                method="SLSQP",
                bounds=bounds,
                constraints=all_constraints,
                options={"maxiter": 1000, "ftol": 1e-9}
            )

            if result.success:
                w = result.x
                port_ret, port_vol = self._portfolio_stats(w, returns, cov_matrix)
                sharpe = (port_ret - self.risk_free_rate) / port_vol if port_vol > 0 else 0

                row = {"return": port_ret, "volatility": port_vol, "sharpe": sharpe}
                for i in range(n_assets):
                    row[f"weight_{i}"] = w[i]
                frontier_data.append(row)

        return pd.DataFrame(frontier_data)

    # ── Min Volatility ─────────────────────────────────────────────────────

    def min_volatility(self,
                       returns: np.ndarray,
                       cov_matrix: np.ndarray,
                       min_weight: float = 0.01,
                       max_weight: float = 0.25) -> np.ndarray:
        """
        Global minimum variance portfolio -- portföljen med lägst volatilitet.

        Args:
            returns: Förväntad avkastning (N,)
            cov_matrix: Kovariansmatris (N x N)
            min_weight, max_weight: viktbegränsningar

        Returns:
            Viktvektor (N,)
        """
        n_assets = len(returns)
        bounds = Bounds([min_weight] * n_assets, [max_weight] * n_assets)
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        ]

        result = minimize(
            self._portfolio_vol,
            np.array([1.0 / n_assets] * n_assets),
            args=(cov_matrix,),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-9}
        )

        if not result.success:
            logger.warning(f"GMV optimering konvergerade inte: {result.message}")
            return np.array([1.0 / n_assets] * n_assets)

        weights = result.x
        weights = np.clip(weights, min_weight, max_weight)
        return weights / np.sum(weights)

    # ── Max Sharpe ─────────────────────────────────────────────────────────

    def max_sharpe(self,
                   returns: np.ndarray,
                   cov_matrix: np.ndarray,
                   min_weight: float = 0.01,
                   max_weight: float = 0.25) -> np.ndarray:
        """
        Tangency portfolio -- portföljen med högst Sharpe ratio.

        Args:
            returns: Förväntad avkastning (N,)
            cov_matrix: Kovariansmatris (N x N)
            min_weight, max_weight: viktbegränsningar

        Returns:
            Viktvektor (N,)
        """
        n_assets = len(returns)
        bounds = Bounds([min_weight] * n_assets, [max_weight] * n_assets)
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
        ]

        result = minimize(
            self._neg_sharpe,
            np.array([1.0 / n_assets] * n_assets),
            args=(returns, cov_matrix),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-9}
        )

        if not result.success:
            logger.warning(f"MaxSharpe optimering konvergerade inte: {result.message}")
            return np.array([1.0 / n_assets] * n_assets)

        weights = result.x
        weights = np.clip(weights, min_weight, max_weight)
        return weights / np.sum(weights)

    # ── Constraint-hjälpare ────────────────────────────────────────────────

    @staticmethod
    def constrain_weights(weights: np.ndarray,
                          min_weight: float = 0.01,
                          max_weight: float = 0.25) -> np.ndarray:
        """
        Säkerställer long-only, diversifierings-constraints.

        Clippar vikter till [min_weight, max_weight] och re-normaliserar.

        Args:
            weights: Råa vikter (N,)
            min_weight: Minimi-vikt per asset
            max_weight: Maximi-vikt per asset

        Returns:
            Constrained viktvektor (N,)
        """
        w = np.asarray(weights, dtype=float)

        # Clippa
        w = np.clip(w, min_weight, max_weight)

        # Sätt negativa till minimum
        w[w < 0] = min_weight

        # Renormalisera
        total = np.sum(w)
        if total > 0:
            w = w / total
        else:
            w = np.ones(len(w)) / len(w)

        return w

    @staticmethod
    def sector_neutral_weights(weights: np.ndarray,
                                sector_indices: list) -> np.ndarray:
        """
        Justerar vikter för sektor-neutralitet.

        Varje sektor får samma totalvikt (1/antal_sektorer).

        Args:
            weights: Nuvarande vikter (N,)
            sector_indices: Lista av listor, en per sektor med asset-index

        Returns:
            Sektor-neutrala vikter
        """
        w = weights.copy()
        n_sectors = len(sector_indices)
        target_per_sector = 1.0 / n_sectors

        for indices in sector_indices:
            current = np.sum(w[indices])
            if current > 0:
                scale = target_per_sector / current
                w[indices] = w[indices] * scale

        return w / np.sum(w)


# ══════════════════════════════════════════════════════════════════════════════
# CLI-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Simulera 5 tillgångar
    np.random.seed(42)
    n = 5
    mean_returns = np.array([0.12, 0.08, 0.15, 0.06, 0.10])
    vol = np.array([0.20, 0.15, 0.25, 0.12, 0.18])
    corr = np.array([
        [1.0, 0.3, 0.6, 0.1, 0.4],
        [0.3, 1.0, 0.2, 0.5, 0.3],
        [0.6, 0.2, 1.0, 0.1, 0.5],
        [0.1, 0.5, 0.1, 1.0, 0.2],
        [0.4, 0.3, 0.5, 0.2, 1.0],
    ])
    cov = np.outer(vol, vol) * corr

    opt = MeanVarianceOptimizer(risk_free_rate=0.02)

    # Max Sharpe
    w_max = opt.max_sharpe(mean_returns, cov)
    r, v = opt._portfolio_stats(w_max, mean_returns, cov)
    print(f"Max Sharpe: ret={r:.4f}, vol={v:.4f}, sharpe={(r-0.02)/v:.4f}")
    print(f"Vikter: {np.round(w_max, 4)}")

    # Min Vol
    w_min = opt.min_volatility(mean_returns, cov)
    r, v = opt._portfolio_stats(w_min, mean_returns, cov)
    print(f"\nMin Vol: ret={r:.4f}, vol={v:.4f}")
    print(f"Vikter: {np.round(w_min, 4)}")

    # Efficient Frontier
    ef = opt.efficient_frontier(mean_returns, cov, n_points=20)
    print(f"\nEfficient Frontier: {len(ef)} punkter")
    print(ef.head())
