"""
black_litterman.py -- Black-Litterman Portfolio Optimization Framework
======================================================================
Implements the Black-Litterman model for portfolio optimization.

The Black-Litterman model:
1. Uses market-cap-weighted equilibrium returns as a stable Bayesian prior (Pi)
2. Updates with the scanner's views (Q) weighted by rolling Information Coefficient (IC)
3. Produces posterior expected returns that blend equilibrium with signal views
4. Uses Ledoit-Wolf covariance shrinkage to stabilize Sigma

Usage:
    # Simple API (legacy)
    from portfolio.black_litterman import black_litterman_weights
    weights = black_litterman_weights(scored_df, historical_ic=0.05)

    # Class-based API
    from portfolio.black_litterman import BlackLittermanOptimizer
    blo = BlackLittermanOptimizer()
    weights = blo.optimize_posterior(scored_df)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
TAU_DEFAULT = 0.025          # Prior uncertainty scalar
DELTA_DEFAULT = 2.0          # Risk aversion coefficient
MIN_IC_THRESHOLD = 0.01      # Minimum IC to use views
MAX_SINGLE_WEIGHT = 0.15     # Max weight per position


def _load_historical_ic(universe: str = "universe") -> dict:
    """Load rolling IC from ML model metrics file."""
    metrics_path = Path(__file__).parent.parent / "models" / f"ml_{universe}_metrics.json"
    if not metrics_path.exists():
        return {"ic": 0.0, "n_months": 0, "rolling_ic": []}

    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
        ic = float(data.get("cpcv_avg_ic", data.get("ic", 0.0)))
        return {
            "ic": ic,
            "n_months": int(data.get("n_folds", 0)),
            "rolling_ic": data.get("rolling_ic", []),
        }
    except Exception as e:
        logger.warning(f"Could not load IC metrics: {e}")
        return {"ic": 0.0, "n_months": 0, "rolling_ic": []}


def _compute_implied_returns(market_caps: np.ndarray,
                              covariance: np.ndarray,
                              delta: float = DELTA_DEFAULT) -> np.ndarray:
    """
    Compute implied equilibrium returns using reverse optimization.
    Pi = delta x Sigma x w_mkt
    """
    total_mcap = np.sum(market_caps)
    if total_mcap <= 0:
        return np.zeros(len(market_caps))
    w_mkt = market_caps / total_mcap
    implied_returns = delta * covariance @ w_mkt
    return implied_returns


def _ledoit_wolf_shrinkage(returns: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf shrinkage estimator for covariance matrix."""
    T, N = returns.shape
    if T < 2:
        return np.cov(returns, rowvar=False) if N > 1 else np.array([[1.0]])

    sample_cov = np.cov(returns, rowvar=False)
    volatilities = np.sqrt(np.diag(sample_cov))
    if np.any(volatilities == 0):
        return sample_cov

    corr_matrix = sample_cov / np.outer(volatilities, volatilities)
    mean_corr = (np.sum(corr_matrix) - N) / (N * (N - 1))
    mean_corr = np.clip(mean_corr, -1.0, 1.0)
    target = np.outer(volatilities, volatilities) * mean_corr
    np.fill_diagonal(target, volatilities ** 2)

    returns_centered = returns - returns.mean(axis=0)
    var_sample = np.zeros((N, N))
    for t in range(T):
        var_sample += (np.outer(returns_centered[t], returns_centered[t]) - sample_cov) ** 2
    var_sample /= T

    pi_hat = np.sum(var_sample)
    gamma_hat = np.sum((sample_cov - target) ** 2)
    shrinkage = max(0.0, min(1.0, (pi_hat / gamma_hat) / T if gamma_hat > 0 else 1.0))

    shrunk_cov = shrinkage * target + (1 - shrinkage) * sample_cov
    return shrunk_cov


def _build_view_matrix(scored_df: pd.DataFrame, ic: float = 0.05) -> tuple:
    """Build BL views from scanner scores."""
    N = len(scored_df)
    scores = scored_df["score_total"].values.astype(float)
    scores_norm = (scores - scores.mean()) / (scores.std() + 1e-8)
    view_returns = np.clip(scores_norm * 0.02, -0.05, 0.05)

    P = np.eye(N)
    Q = view_returns
    tau = TAU_DEFAULT
    ic_eff = max(abs(ic), MIN_IC_THRESHOLD)
    omega_diag = tau * np.ones(N) / ic_eff
    omega_diag *= np.abs(Q) + 0.01
    Omega = np.diag(omega_diag)
    return P, Q, Omega


def black_litterman_weights(scored_df: pd.DataFrame,
                             historical_ic: Optional[float] = None,
                             universe: str = "universe",
                             delta: float = DELTA_DEFAULT,
                             tau: float = TAU_DEFAULT,
                             max_weight: float = MAX_SINGLE_WEIGHT) -> pd.DataFrame:
    """
    Compute Black-Litterman optimal portfolio weights (legacy API).

    Args:
        scored_df: DataFrame with columns [ticker, score_total, market_cap]
        historical_ic: IC value. If None, loaded from metrics file.
        universe: 'universe' or 'smallcap' -- for IC file lookup
        delta: Risk aversion coefficient
        tau: Prior uncertainty scalar
        max_weight: Maximum weight per position

    Returns:
        DataFrame with columns [ticker, weight, posterior_return, equilibrium_return]
    """
    optimizer = BlackLittermanOptimizer(delta=delta, tau=tau, max_weight=max_weight)
    result = optimizer.optimize_posterior(
        scored_df, historical_ic=historical_ic, universe=universe
    )
    return result


# ══════════════════════════════════════════════════════════════════════════════
# NEW: BlackLittermanOptimizer class
# ══════════════════════════════════════════════════════════════════════════════

class BlackLittermanOptimizer:
    """
    Black-Litterman Portfolio Optimizer.

    Kombinerar market-cap prior med systematiska views (från ML-scoring)
    för att producera posterior expected returns och optimala portföljvikter.

    Användning:
        blo = BlackLittermanOptimizer()
        weights = blo.optimize_posterior(scored_df, historical_ic=0.08)
    """

    def __init__(self,
                 delta: float = DELTA_DEFAULT,
                 tau: float = TAU_DEFAULT,
                 max_weight: float = MAX_SINGLE_WEIGHT,
                 min_weight: float = 0.0,
                 risk_free_rate: float = 0.02):
        """
        Args:
            delta: Risk aversion coefficient (market price of risk)
            tau: Prior uncertainty scalar (low = strong prior)
            max_weight: Maximum weight per position
            min_weight: Minimum weight per position (0 = long-only)
            risk_free_rate: Risk-free rate for Sharpe calculations
        """
        self.delta = delta
        self.tau = tau
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.risk_free_rate = risk_free_rate

    # ── Huvud-optimering ───────────────────────────────────────────────────

    def optimize_posterior(self,
                            scored_df: pd.DataFrame,
                            historical_ic: Optional[float] = None,
                            universe: str = "universe") -> pd.DataFrame:
        """
        Full Black-Litterman optimering.

        Steg:
        1. Market cap prior (Pi)
        2. Covariance estimation (Ledoit-Wolf)
        3. View construction fran scores + IC
        4. Posterior returns (Black-Litterman formula)
        5. Optimal weights from posterior

        Args:
            scored_df: DataFrame med [ticker, score_total, market_cap]
            historical_ic: Information Coefficient. None = ladda fran metrics file.
            universe: 'universe' eller 'smallcap'

        Returns:
            DataFrame med [ticker, weight, posterior_return, equilibrium_return]
            Vikter summerar till 1.0.
        """
        if scored_df is None or scored_df.empty or "ticker" not in scored_df.columns:
            logger.warning("Empty eller ogiltig DataFrame")
            return pd.DataFrame(columns=["ticker", "weight"])

        N = len(scored_df)
        tickers = scored_df["ticker"].tolist()

        # 1. IC
        ic = self._get_ic(historical_ic, universe)

        # 2. Market cap prior
        market_caps = self._get_market_caps(scored_df, N)

        # 3. Covariance
        cov_matrix = self._estimate_covariance(tickers, N)

        # 4. Implied equilibrium returns (prior)
        implied_returns = _compute_implied_returns(market_caps, cov_matrix, self.delta)

        # 5. Build views
        P, Q, Omega = _build_view_matrix(scored_df, ic=ic)

        # 6. Posterior returns (Black-Litterman formula)
        posterior_returns = self.posterior_returns(implied_returns, Q, Omega, cov_matrix, P)

        if posterior_returns is None:
            # Fallback
            weights = np.ones(N) / N
            result = scored_df[["ticker"]].copy()
            result["weight"] = weights
            result["posterior_return"] = 0.0
            result["equilibrium_return"] = 0.0
            return result

        # 7. Optimal weights
        optimal_weights = self._solve_weights(cov_matrix, posterior_returns)

        # 8. Constraints
        optimal_weights = np.maximum(optimal_weights, self.min_weight)
        optimal_weights = np.minimum(optimal_weights, self.max_weight)
        total_weight = optimal_weights.sum()
        if total_weight > 0:
            optimal_weights /= total_weight

        # 9. Build result
        result = scored_df[["ticker"]].copy()
        result["weight"] = np.round(optimal_weights, 6)
        result["posterior_return"] = np.round(posterior_returns, 6)
        result["equilibrium_return"] = np.round(implied_returns, 6)
        result = result.sort_values("weight", ascending=False).reset_index(drop=True)

        n_pos = (result["weight"] > 0).sum()
        logger.info(
            f"BL: {n_pos} positioner, top-1 weight={result['weight'].iloc[0]:.1%}, "
            f"IC={ic:.3f}"
        )

        return result

    # ── Hjälpmetoder ───────────────────────────────────────────────────────

    def _get_ic(self, historical_ic: Optional[float], universe: str) -> float:
        """Hämta IC från parameter eller metrics file."""
        if historical_ic is not None:
            return historical_ic
        ic_data = _load_historical_ic(universe)
        ic = ic_data["ic"]
        logger.info(f"BL: loaded IC={ic:.4f} från {universe} metrics")
        return ic

    @staticmethod
    def _get_market_caps(scored_df: pd.DataFrame, N: int) -> np.ndarray:
        """Extrahera market caps fran DataFrame."""
        market_caps = scored_df.get("market_cap",
                                     pd.Series(1.0 / N, index=scored_df.index))
        market_caps = pd.to_numeric(market_caps, errors="coerce").fillna(1.0)
        if market_caps.sum() <= 0:
            market_caps = pd.Series(1.0 / N, index=scored_df.index)
        return market_caps.values

    def _estimate_covariance(self, tickers: list, N: int) -> np.ndarray:
        """Estimera kovariansmatris fran prishistorik."""
        try:
            from core.data_fetcher import fetch_price_history
            sample_n = min(N, 50)
            sample_tickers = tickers[:sample_n]

            returns_list = []
            valid_tickers = []
            for t in sample_tickers:
                hist = fetch_price_history(t, period="6mo")
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    ret = hist["Close"].pct_change().dropna()
                    returns_list.append(ret)
                    valid_tickers.append(t)

            if len(returns_list) >= 5:
                returns_df = pd.concat(returns_list, axis=1, keys=valid_tickers)
                returns_df = returns_df.dropna(how="any")
                if len(returns_df) > 10:
                    cov = _ledoit_wolf_shrinkage(returns_df.values)
                    n_valid = len(valid_tickers)
                    # Säkerställ alltid N×N output — saknade tickers får mediansignma
                    if n_valid < N:
                        med_var = float(np.median(np.diag(cov))) if cov.size else 0.04
                        full_cov = np.eye(N) * med_var
                        full_cov[:n_valid, :n_valid] = cov
                        cov = full_cov
                    elif N > sample_n:
                        full_cov = np.eye(N) * np.median(np.diag(cov))
                        full_cov[:sample_n, :sample_n] = cov
                        cov = full_cov
                    logger.info(f"BL: computed {n_valid}/{sample_n} Ledoit-Wolf cov → {N}×{N}")
                    return cov
        except Exception as e:
            logger.debug(f"BL: covariance estimation failed: {e}")

        # Fallback
        logger.info("BL: using identity covariance (fallback)")
        return np.eye(N) * 0.04

    def _solve_weights(self, cov_matrix: np.ndarray,
                       posterior_returns: np.ndarray) -> np.ndarray:
        """Los optimala vikter: w* = (delta x Sigma)^(-1) x mu_posterior."""
        try:
            return np.linalg.solve(self.delta * cov_matrix, posterior_returns)
        except np.linalg.LinAlgError:
            logger.warning("BL: weight solve failed -- using posterior returns")
            return posterior_returns

    # ── Posterior Returns (Black-Litterman formula) ────────────────────────

    def posterior_returns(self,
                           prior: np.ndarray,
                           views: np.ndarray,
                           uncertainty: np.ndarray,
                           cov_matrix: np.ndarray,
                           P: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """
        Beräknar posterior expected returns enligt Black-Litterman formula.

        mu_posterior = [(tau x Sigma)^(-1) + P'Omega^(-1)P]^(-1)
                       x [(tau x Sigma)^(-1) x Pi + P'Omega^(-1) x Q]

        Args:
            prior: Prior returns (Pi) -- equilibrium returns (N,)
            views: View returns (Q) -- fran scores (N,)
            uncertainty: View uncertainty matrix (Omega) -- diagonal (N x N)
            cov_matrix: Covariance matrix (Sigma) (N x N)
            P: Pick matrix (N x N). If None, uses identity.

        Returns:
            Posterior expected returns (N,) eller None vid fel.
        """
        if P is None:
            P = np.eye(len(prior))

        try:
            tau = self.tau
            tau_sigma_inv = np.linalg.inv(tau * cov_matrix)
            omega_inv = np.linalg.inv(uncertainty)

            posterior_precision = tau_sigma_inv + P.T @ omega_inv @ P
            posterior_cov = np.linalg.inv(posterior_precision)

            posterior_mean = posterior_cov @ (
                tau_sigma_inv @ prior + P.T @ omega_inv @ views
            )
            return posterior_mean
        except np.linalg.LinAlgError as e:
            logger.warning(f"BL: posterior returns failed: {e}")
            return None

    # ── View Conflict Measure ──────────────────────────────────────────────

    def view_conflict_measure(self,
                               prior: np.ndarray,
                               posterior: np.ndarray,
                               views: np.ndarray) -> dict:
        """
        Mäter hur mycket views divergerar fran market prior.

        Hog konflikt = hog osakerhet = signalerna gar emot marknaden.

        Args:
            prior: Prior (equilibrium) returns (N,)
            posterior: Posterior returns (N,)
            views: View returns (N,)

        Returns:
            dict med:
                conflict_score: 0-1 (0 = perfekt alignment, 1 = maximal konflikt)
                mean_abs_deviation: Genomsnittlig absolut avvikelse
                n_conflicting: Antal assets dar view gar emot prior
                view_pct: Andel assets med samma riktning som views
                description: Textuell beskrivning
        """
        prior = np.asarray(prior, dtype=float)
        posterior = np.asarray(posterior, dtype=float)
        views = np.asarray(views, dtype=float)

        n = len(prior)
        if n == 0:
            return {"conflict_score": 0.0, "description": "Ingen data"}

        # Riktning: view vs prior
        prior_sign = np.sign(prior)
        view_sign = np.sign(views)
        # 0-tolerans: returns exakt 0 raknas som neutral
        prior_sign[np.abs(prior) < 1e-8] = 0
        view_sign[np.abs(views) < 1e-8] = 0

        # Konflikt: view och prior gar at olika hall
        conflicting = (prior_sign * view_sign) < 0
        n_conflicting = int(np.sum(conflicting))

        # Genomsnittlig absolut avvikelse (posterior vs prior)
        deviation = np.abs(posterior - prior)
        mean_dev = float(np.mean(deviation))

        # View alignment: andel dar view och prior har samma riktning
        aligned = (prior_sign * view_sign) > 0
        n_aligned = int(np.sum(aligned))
        # Neutrala (där prior eller view ar 0) raknet som varken eller
        active = n - int(np.sum(prior_sign == 0) + np.sum(view_sign == 0) -
                         int(np.sum((prior_sign == 0) & (view_sign == 0))))
        view_pct = n_aligned / active if active > 0 else 1.0

        # Conflict score (0-1)
        conflict_score = n_conflicting / max(n, 1)

        # Beskrivning
        if conflict_score > 0.5:
            description = (
                f"Hog konflikt: {n_conflicting}/{n} tillgangar har views "
                f"som gar emot marknaden. Signalerna ar kontrariska."
            )
        elif conflict_score > 0.2:
            description = (
                f"Medel konflikt: {n_conflicting}/{n} tillgangar divergerar "
                f"fran market prior."
            )
        else:
            description = (
                f"Lag konflikt: views alignerar val med marknaden "
                f"({n_aligned}/{active} aktiva)."
            )

        return {
            "conflict_score": round(conflict_score, 3),
            "n_conflicting": n_conflicting,
            "n_aligned": n_aligned,
            "n_total": n,
            "mean_abs_deviation": round(mean_dev, 6),
            "view_alignment_pct": round(view_pct * 100, 1),
            "description": description,
        }

    # ── Integration med Mean-Variance ──────────────────────────────────────

    def optimize_with_mean_variance(self,
                                     scored_df: pd.DataFrame,
                                     historical_ic: Optional[float] = None,
                                     universe: str = "universe",
                                     risk_tolerance: float = 0.5) -> pd.DataFrame:
        """
        Kombinerar Black-Litterman posterior med Mean-Variance optimering.

        1. Black-Litterman: prior + views -> posterior returns
        2. Mean-Variance: optimera posterior returns med full constraints

        Detta ger BLs estimeringsforbattring + MV flexibilitet.

        Args:
            scored_df: DataFrame med [ticker, score_total, market_cap]
            historical_ic: Information Coefficient
            universe: 'universe' eller 'smallcap'
            risk_tolerance: Risk tolerance for MV (0=risk-averse, 1=risk-seeking)

        Returns:
            DataFrame med vikter
        """
        from portfolio.mean_variance import MeanVarianceOptimizer

        # Steg 1: BL posterior
        N = len(scored_df)
        ic = self._get_ic(historical_ic, universe)
        market_caps = self._get_market_caps(scored_df, N)
        cov_matrix = self._estimate_covariance(scored_df["ticker"].tolist(), N)
        implied_returns = _compute_implied_returns(market_caps, cov_matrix, self.delta)
        P, Q, Omega = _build_view_matrix(scored_df, ic=ic)
        posterior = self.posterior_returns(implied_returns, Q, Omega, cov_matrix, P)

        if posterior is None:
            return scored_df[["ticker"]].assign(
                weight=1.0 / N,
                posterior_return=0.0,
                equilibrium_return=0.0,
            )

        # Steg 2: Mean-Variance optimering
        mv = MeanVarianceOptimizer(risk_free_rate=self.risk_free_rate)
        mv_weights = mv.optimize(
            posterior,
            cov_matrix,
            risk_tolerance=risk_tolerance,
            max_weight=self.max_weight,
            min_weight=max(self.min_weight, 0.001),
        )

        result = scored_df[["ticker"]].copy()
        result["weight"] = np.round(mv_weights, 6)
        result["posterior_return"] = np.round(posterior, 6)
        result["equilibrium_return"] = np.round(implied_returns, 6)
        return result.sort_values("weight", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# CLI USAGE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from pathlib import Path
    logging.basicConfig(level=logging.INFO)

    reports_dir = Path(__file__).parent.parent / "reports"
    csv_files = sorted(reports_dir.glob("scored_universe_*.csv"))
    if not csv_files:
        print("Inga scored universe CSV-filer hittades i reports/")
        sys.exit(1)

    latest = csv_files[-1]
    df = pd.read_csv(latest)

    if "ticker" not in df.columns:
        print("CSV saknar 'ticker'-kolumn")
        sys.exit(1)

    # Test 1: Legacy API
    print(f"\nTestar legacy API...")
    result1 = black_litterman_weights(df)
    print(result1.head(10))

    # Test 2: Class API
    print(f"\nTestar BlackLittermanOptimizer klass...")
    blo = BlackLittermanOptimizer()
    result2 = blo.optimize_posterior(df)
    print(result2.head(10))

    # Test 3: View conflict
    N = min(10, len(df))
    prior_sample = np.random.randn(N) * 0.02
    post_sample = prior_sample + np.random.randn(N) * 0.01
    views_sample = prior_sample + np.random.randn(N) * 0.03
    conflict = blo.view_conflict_measure(prior_sample, post_sample, views_sample)
    print(f"\nView conflict: {conflict['conflict_score']:.2f}")
    print(conflict["description"])
