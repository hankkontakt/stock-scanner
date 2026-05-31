"""
hierarchical_risk_parity.py – Hierarchical Risk Parity (Lopez de Prado, 2016)

HRP distribuerar risk hierarkiskt genom kluster av tillgangar istallet for att
invertera kovariansmatrisen. Till skillnad fran Black-Litterman kraver HRP:

  1. Ingen matrisinversion — fungerar stabilt aven med 800+ tillgangar
  2. Hanterar korrelationskluster naturligt (alla tech-aktier ror sig tillsammans)
  3. Kraver inga forvantad-avkastning-estimat — optimerar bara risk
  4. Fungerar med bara 60 dagars historik

Usage:
    from portfolio.hierarchical_risk_parity import hrp_weights
    weights = hrp_weights(returns_df, max_weight=0.15)
"""

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    """Konvertera kovariansmatris till korrelationsmatris."""
    std = np.sqrt(np.diag(cov))
    corr = cov / np.outer(std, std)
    corr = np.clip(corr, -1, 1)
    return corr


def _corr_to_dist(corr: np.ndarray) -> np.ndarray:
    """Konvertera korrelation till distans (0=nara, 1=längt bort)."""
    return np.sqrt((1 - corr) / 2)


def _get_quasi_diag(link: np.ndarray) -> list:
    """
    Hamta quasi-diagonal ordning fran hierarkisk klustring.
    Ordnar tillgangar sa att liknande tillgangar blir granne.
    """
    link = link.astype(int)
    n = link.shape[0] + 1
    sorted_idx = []
    stack = [link[-1, 0], link[-1, 1]]
    while stack:
        node = stack.pop()
        if node < n:
            sorted_idx.append(int(node))
        else:
            stack.append(link[node - n, 1])
            stack.append(link[node - n, 0])
    return sorted_idx


def _recursive_bisection(cov: np.ndarray) -> np.ndarray:
    """
    Rekursiv bisection av varians langs den quasi-diagonala ordningen.
    Forst storklustret, sen mindre och mindre tills enskilda tillgangar.
    """
    n = cov.shape[0]
    weights = np.ones(n)

    def _bisect(assets: list[int]) -> np.ndarray:
        if len(assets) == 1:
            return np.array([1.0])

        mid = len(assets) // 2
        left = assets[:mid]
        right = assets[mid:]

        cov_slice = cov[np.ix_(assets, assets)]

        def _cluster_var(indices: list[int]) -> float:
            """Varians for en del av klustret med lika vikter."""
            w = np.ones(len(indices)) / len(indices)
            idx_in_slice = [assets.index(a) for a in indices]
            sub_cov = cov_slice[np.ix_(idx_in_slice, idx_in_slice)]
            return float(w @ sub_cov @ w)

        left_var = _cluster_var(left)
        right_var = _cluster_var(right)

        # Inverse-variance allocation mellan de tva sub-klustren
        alpha = 1 - left_var / (left_var + right_var) if (left_var + right_var) > 0 else 0.5
        alpha = np.clip(alpha, 0.0, 1.0)

        left_weights = _bisect(left)
        right_weights = _bisect(right)

        return np.concatenate([left_weights * (1 - alpha), right_weights * alpha])

    return _bisect(list(range(n)))


def hrp_weights(
    returns: pd.DataFrame,
    linkage_method: str = "ward",
    max_weight: float = 0.15,
) -> pd.Series:
    """
    Berakna Hierarchical Risk Parity-vikter.

    Args:
        returns: DataFrame med avkastning (kolumner = tickers, index = datum).
                 Rekommenderar minst 60 perioder for stabil kovarians.
        linkage_method: Metod for hierarkisk klustring.
                        'ward' (default) minimerar variants inom kluster.
                        'single' for nearest-neighbor, 'complete' for farthest.
        max_weight: Maximal vikt per tillgang (None for obegransat).

    Returns:
        pd.Series med ticker-index och vikt-varden (summerar till 1.0).
    """
    if returns.empty or len(returns.columns) < 2:
        if len(returns.columns) == 1:
            return pd.Series(1.0, index=returns.columns)
        return pd.Series(index=getattr(returns, "columns", []), dtype=float)

    # Berakna kovarians (Ledoit-Wolf shrinkage for stabilitet)
    try:
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf().fit(returns.values)
        cov = lw.covariance_
    except ImportError:
        cov = returns.cov().values

    tickers = returns.columns.tolist()
    n = len(tickers)

    # Korrelation -> distans -> hierarkisk klustring
    corr = _cov_to_corr(cov)
    dist = _corr_to_dist(corr)

    try:
        link = linkage(squareform(dist), method=linkage_method)
    except Exception:
        # Om klustring misslyckas, fall tillbaka till lika vikter
        weights = pd.Series(1.0 / n, index=tickers)
        if max_weight is not None and max_weight < 1.0 / n:
            weights = weights.clip(upper=max_weight)
        return weights / weights.sum()

    # Quasi-diagonal ordering och rekursiv bisection
    sorted_idx = _get_quasi_diag(link)
    raw_weights = _recursive_bisection(cov)

    # Mappa tillbaka till ticker-index
    weights = pd.Series(0.0, index=tickers)
    for i, idx in enumerate(sorted_idx):
        if idx < n:
            weights.iloc[idx] = raw_weights[i]

    weights = weights / weights.sum()

    # Applicera max-vikt-begransning
    if max_weight is not None:
        over = weights > max_weight
        if over.any():
            excess = (weights[over] - max_weight).sum()
            weights[over] = max_weight
            under = ~over
            if under.any() and excess > 0:
                weights[under] += excess * weights[under] / weights[under].sum()

    return weights / weights.sum()
