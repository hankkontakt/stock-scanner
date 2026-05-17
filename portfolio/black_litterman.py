"""
black_litterman.py — Black-Litterman Portfolio Optimization Framework
============================================================
Implements the Black-Litterman model for portfolio optimization,
as recommended by the quantitative architecture review.

The Black-Litterman model:
1. Uses market-cap-weighted equilibrium returns as a stable Bayesian prior (Π)
2. Updates with the scanner's views (Q) weighted by rolling Information Coefficient (IC)
3. Produces posterior expected returns that blend equilibrium with signal views
4. Uses Ledoit-Wolf covariance shrinkage to stabilize Σ

This replaces the simple equal-weighted top-N approach with mathematically
optimal portfolio weights.

Usage:
    from portfolio.black_litterman import black_litterman_weights
    weights = black_litterman_weights(scored_df, historical_ic=0.05)
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
# Tau (τ): uncertainty scalar for the prior. Low = strong prior belief.
# Standard range: 0.01–0.05. We use 0.025 as default.
TAU_DEFAULT = 0.025

# Delta (δ (delta): risk aversion coefficient (market price of risk).
# Calculated as (expected market return - risk-free rate) / market variance.
# Default 2.0 implies ~8% equity risk premium at 20% volatility.
DELTA_DEFAULT = 2.0

# Minimum historical IC to use views at all
MIN_IC_THRESHOLD = 0.01

# Cap on single position weight (prevents concentration)
MAX_SINGLE_WEIGHT = 0.15


def _load_historical_ic(universe: str = "universe") -> dict:
    """
    Load rolling 12-month Spearman IC from ML model metrics file.

    Returns dict with:
        ic: float (Spearman rank correlation)
        n_months: int (number of months in calculation)
        rolling_ic: list (monthly IC values)
    """
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

    Π = δ × Σ × w_mkt

    Where:
        Π = implied excess returns (N x 1)
        δ = risk aversion coefficient
        Σ = covariance matrix of excess returns (N x N)
        w_mkt = market-cap weights (N x 1)

    Args:
        market_caps: Array of market capitalizations
        covariance: Covariance matrix of returns (N x N)
        delta: Risk aversion coefficient

    Returns:
        Implied equilibrium returns vector (N,)
    """
    total_mcap = np.sum(market_caps)
    if total_mcap <= 0:
        return np.zeros(len(market_caps))

    w_mkt = market_caps / total_mcap
    implied_returns = delta * covariance @ w_mkt
    return implied_returns


def _ledoit_wolf_shrinkage(returns: np.ndarray) -> np.ndarray:
    """
    Ledoit-Wolf shrinkage estimator for covariance matrix.

    Shrinks sample covariance toward a structured target (constant correlation).
    This reduces estimation error — especially important when N >> with 1,000+ assets
    and limited history.

    Args:
        returns: T x N matrix of historical returns

    Returns:
        Shrunk covariance matrix (N x N)
    """
    T, N = returns.shape
    if T < 2:
        return np.cov(returns, rowvar=False) if N > 1 else np.array([[1.0]])

    # Sample covariance
    sample_cov = np.cov(returns, rowvar=False)

    # Constant correlation target
    volatilities = np.sqrt(np.diag(sample_cov))
    if np.any(volatilities == 0):
        return sample_cov

    corr_matrix = sample_cov / np.outer(volatilities, volatilities)
    mean_corr = (np.sum(corr_matrix) - N) / (N * (N - 1))
    mean_corr = np.clip(mean_corr, -1.0, 1.0)

    target = np.outer(volatilities, volatilities) * mean_corr
    np.fill_diagonal(target, volatilities ** 2)

    # Compute shrinkage intensity (pi - rho) / gamma
    # Using the Ledoit-Wolf oracle approximating shrinkage constant
    returns_centered = returns - returns.mean(axis=0)
    var_sample = np.zeros((N, N))
    for t in range(T):
        var_sample += (np.outer(returns_centered[t], returns_centered[t]) - sample_cov) ** 2
    var_sample /= T

    # Shrinkage intensity
    pi_hat = np.sum(var_sample)
    gamma_hat = np.sum((sample_cov - target) ** 2)
    shrinkage = max(0.0, min(1.0, (pi_hat / gamma_hat) / T if gamma_hat > 0 else 1.0))

    shrunk_cov = shrinkage * target + (1 - shrinkage) * sample_cov
    return shrunk_cov


def _build_view_matrix(scored_df: pd.DataFrame,
                       ic: float = 0.05) -> tuple:
    """
    Build Black-Litterman views from the scanner's scores.

    Views are absolute (not relative): each stock's expected return
    is proportional to its normalized score.

    Args:
        scored_df: DataFrame with score_df with score_total column
        ic: Historical Information Coefficient (determines view confidence)

    Returns:
        (P, Q, Omega) tuple:
            P: Pick matrix (N x N) — identity for absolute views
            Q: View vector (N,) — expected returns from scores
            Omega: View uncertainty matrix (N x N) — diagonal, scaled by IC
    """
    N = len(scored_df)

    # Normalize scores to expected returns
    # Map raw scores (0-100) to expected monthly expected returns (-5% to +5%)
    scores = scored_df["score_total"].values.astype(float)
    scores_norm = (scores - scores.mean()) / (scores.std() + 1e-8)
    view_returns = np.clip(scores_norm * 0.02, -0.05, 0.05)  # ±5% cap

    # Pick matrix: identity (absolute views on each asset)
    P = np.eye(N)

    # Q: the views
    Q = view_returns

    # Omega: uncertainty matrix
    # Higher IC = lower uncertainty = tighter confidence
    # Base uncertainty = TAU * diag(P @ Sigma @ P.T)
    # We approximate with tau * |Q| / (IC + epsilon)
    tau = TAU_DEFAULT
    ic_eff = max(abs(ic), MIN_IC_THRESHOLD)

    # View uncertainty proportional to inverse IC
    omega_diag = tau * np.ones(N) / ic_eff
    # Scale by |view|: stronger views = higher absolute confidence
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
    Compute Black-Litterman optimal portfolio weights.

    The model computes:
        μ_posterior = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ × [(τΣ)⁻¹Π + P'Ω⁻¹Q]

    Then optimal weights:
        w* = (δΣ)⁻¹ × μ_posterior

    Args:
        scored_df: DataFrame with columns [ticker, score_total, market_cap]
        historical_ic: IC value. If None, loaded from metrics file.
        universe: "universe" or "smallcap" — for IC file lookup
        delta: Risk aversion coefficient
        tau: Prior uncertainty scalar
        max_weight: Maximum weight per position

    Returns:
        DataFrame with columns [ticker, weight, posterior_return, equilibrium_return]
        Weights sum to 1.0 (fully invested).
    """
    if scored_df.empty or "ticker" not in scored_df.columns:
        logger.warning("Empty DataFrame passed to black_litterman_weights")
        return pd.DataFrame(columns=["ticker", "weight"])

    N = len(scored_df)
    tickers = scored_df["ticker"].tolist()

    # ── 1. Load or use IC ──────────────────────────────────────────
    if historical_ic is None:
        ic_data = _load_historical_ic(universe)
        ic = ic_data["ic"]
        logger.info(f"  BL: loaded IC={ic:.4f} from {universe} metrics")
    else:
        ic = historical_ic

    # ── 2. Market cap prior ────────────────────────────────────────
    market_caps = scored_df.get("market_cap",
                                pd.Series(1.0 / N, index=scored_df.index))
    market_caps = pd.to_numeric(market_caps, errors="coerce").fillna(1.0)

    # If all market caps are the same or invalid, equal-weight prior
    if market_caps.sum() <= 0:
        market_caps = pd.Series(1.0 / N, index=scored_df.index)

    # ── 3. Historical returns for covariance estimation ────────────
    # If we have cached returns, use them. Otherwise, estimate from
    # score volatility (crude approximation).
    cov_matrix = None
    try:
        # Try to load historical returns from cache
        from core.data_fetcher import fetch_price_history
        # Sample a subset of tickers to build covariance (too many = unstable)
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
                cov_matrix = _ledoit_wolf_shrinkage(returns_df.values)
                # If we have more assets than in sample, pad with identity
                if N > sample_n:
                    full_cov = np.eye(N) * np.median(np.diag(cov_matrix))
                    full_cov[:sample_n, :sample_n] = cov_matrix
                    cov_matrix = full_cov
                logger.info(f"  BL: computed {sample_n}x{sample_n} shrunk covariance")
    except Exception as e:
        logger.debug(f"  BL: covariance estimation failed: {e}")

    # Fallback: identity covariance if estimation fails
    if cov_matrix is None:
        cov_matrix = np.eye(N) * 0.04  # 20% annualized vol → 0.04 variance
        logger.info("  BL: using identity covariance (fallback)")

    # ── 4. Compute implied equilibrium returns ─────────────────────
    implied_returns = _compute_implied_returns(
        market_caps.values, cov_matrix, delta
    )

    # ── 5. Build views ─────────────────────────────────────────────
    P, Q, Omega = _build_view_matrix(scored_df, ic=ic)

    # ── 6. Posterior expected returns (Black-Litterman formula) ────────
    # μ_posterior = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ × [(τΣ)⁻¹Π + P'Ω⁻¹Q]
    try:
        tau_sigma_inv = np.linalg.inv(tau * cov_matrix)

        # P'Ω⁻¹P — for identity P, this is just Ω⁻¹
        omega_inv = np.linalg.inv(Omega)

        # Combine: posterior precision
        posterior_precision = tau_sigma_inv + omega_inv
        posterior_cov = np.linalg.inv(posterior_precision)

        # Posterior mean
        posterior_returns = posterior_cov @ (
            tau_sigma_inv @ implied_returns + omega_inv @ Q
        )
    except np.linalg.LinAlgError as e:
        logger.warning(f"  BL: matrix inversion failed: {e} — falling back to equal weight")
        weights = np.ones(N) / N
        result = scored_df[["ticker"]].copy()
        result["weight"] = weights
        result["posterior_return"] = 0.0
        result["equilibrium_return"] = 0.0
        return result

    # ── 6. Optimal weights ─────────────────────────────────────────
    # w* = (δΣ)⁻¹ × μ_posterior
    try:
        optimal_weights = np.linalg.solve(delta * cov_matrix, posterior_returns)
    except np.linalg.LinAlgError:
        logger.warning("  BL: weight solve failed — using posterior returns directly")
        optimal_weights = posterior_returns

    # ── 7. Constraints ─────────────────────────────────────────────
    # Long-only, max single position
    optimal_weights = np.maximum(optimal_weights, 0)
    optimal_weights = np.minimum(optimal_weights, max_weight)
    total_weight = optimal_weights.sum()
    if total_weight > 0:
        optimal_weights /= total_weight  # Renormalize to sum to 1

    # ── 8. Build result ────────────────────────────────────────────
    result = scored_df[["ticker"]].copy()
    result["weight"] = np.round(optimal_weights, 6)
    result["posterior_return"] = np.round(posterior_returns, 6)
    result["equilibrium_return"] = np.round(implied_returns, 6)

    # Sort by weight descending
    result = result.sort_values("weight", ascending=False).reset_index(drop=True)

    n_positions = (result["weight"] > 0).sum()
    logger.info(f"  BL: {n_positions} positions, "
                f"top-1 weight={result['weight'].iloc[0]:.1%}, "
                f"IC={ic:.3f}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# CLI USAGE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)

    # Load latest scored CSV
    reports_dir = Path(__file__).parent.parent / "reports"
    csv_files = sorted(reports_dir.glob("scored_universe_*.csv"))
    if not csv_files:
        print("No scored universe CSV found in reports/")
        sys.exit(1)

    latest = csv_files[-1]
    print(f"\nBlack-Litterman Optimization")
    print(f"  Input: {latest.name}")
    df = pd.read_csv(latest)

    if "ticker" not in df.columns:
        print("  ✗ CSV missing 'ticker' column")
        sys.exit(1)

    print(f"  Tickers: {len(df)}")
    print(f"  Running Black-Litterman...\n")

    result = black_litterman_weights(df)

    print("\nTop 20 weights:")
    print(f"  {'Ticker':<12} {'Weight':>8} {'Post. Ret':>10} {'Eq. Ret':>10}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*10}")
    for _, row in result.head(20).iterrows():
        print(f"  {row['ticker']:<12} {row['weight']:>7.1%} "
              f"{row['posterior_return']:>+9.4f} {row['equilibrium_return']:>+9.4f}")

    # Save
    out = reports_dir / f"bl_weights_{datetime.now().strftime('%Y-%m-%d')}.csv"
    result.to_csv(out, index=False)
    print(f"\n  Saved: {out.name}")