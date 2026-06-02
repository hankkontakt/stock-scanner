"""
hrp_optimizer.py -- Hierarchical Risk Parity (HRP)
=================================================
Implementerar Hierarchical Risk Parity enligt López de Prado (2016).

HRP använder hierarkisk klustring för att gruppera tillgångar, och fördelar
sedan risk kapillärt via seriell bisection. Resultatet är en robust
portfölj som är mindre känslig för estimation error än Mean-Variance.

Steg:
1. Tree clustering: korrelationsmatris -> distance matrix -> linkage
2. Seriell bisection: rekursivt dela upp vikter längs dendrogrammet

Användning:
    from portfolio.hrp_optimizer import HRPOptimizer
    hrp = HRPOptimizer()
    weights = hrp.hrp(cov_matrix)
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import squareform

logger = logging.getLogger(__name__)


class HRPOptimizer:
    """
    Hierarchical Risk Parity optimizer.

    Använder hierarkisk klustring + seriell bisection för att skapa en
    diversifierad portfölj där riskbidraget är jämnt fördelat över kluster.
    """

    def __init__(self):
        pass

    # ── Hjälpfunktioner ────────────────────────────────────────────────────

    @staticmethod
    def _cov_to_corr(cov_matrix: np.ndarray) -> np.ndarray:
        """Konverterar kovariansmatris till korrelationsmatris."""
        vol = np.sqrt(np.diag(cov_matrix))
        if np.any(vol == 0):
            return np.eye(len(cov_matrix))
        corr = cov_matrix / np.outer(vol, vol)
        corr = np.clip(corr, -1.0, 1.0)
        return corr

    @staticmethod
    def _corr_to_dist(corr_matrix: np.ndarray) -> np.ndarray:
        """
        Konverterar korrelationsmatris till distance matrix.

        distance = sqrt(2 * (1 - correlation))
        Detta ger en proper Euclidean distance (0 = perfekt korrelerad, sqrt(2) = okorrelerad, 2 = perfekt negativ).
        """
        dist = np.sqrt(2.0 * (1.0 - corr_matrix))
        return dist

    @staticmethod
    def _get_quasi_diag(link: np.ndarray) -> list:
        """
        Quasi-diagonalisering -- ordnar index enligt dendrogrammet.

        Tar linkage-matrisen och returnerar en ordnad lista av
        original-index som följer klusterstrukturen.

        Args:
            link: Linkage-matris från scipy.cluster.hierarchy.linkage

        Returns:
            Ordning av index som följer dendrogrammet
        """
        n_items = link.shape[0] + 1
        idxs = [[i] for i in range(n_items)]

        for row in link:
            i, j = int(row[0]), int(row[1])
            idxs.append(idxs[i] + idxs[j])
            idxs[i] = None
            idxs[j] = None

        return idxs[-1]

    @staticmethod
    def _seriation(link: np.ndarray, order: np.ndarray) -> list:
        """
        Returnerar index-ordning som minimerera summan av avstånd mellan
        närliggande element (optimal leaf ordering approximation).

        Args:
            link: Linkage-matris
            order: Från _get_quasi_diag

        Returns:
            Serierad index-ordning
        """
        result = []
        for i in order:
            if isinstance(i, list):
                result.extend(_seriation_recursive(link, i))
            else:
                result.append(i)
        return result

    # ── Seriell bisection ──────────────────────────────────────────────────

    def _bisect(self,
                cov: np.ndarray,
                sort_idx: list,
                min_weight: float = 0.01,
                max_weight: float = 0.25) -> np.ndarray:
        """
        Seriell bisection -- rekursivt fördela vikter.

        Delar upp tillgångarna i två kluster enligt dendrogram-ordningen
        och fördelar risken (1/diag(cov)) proportionellt.

        Args:
            cov: Kovariansmatris
            sort_idx: Ordnad lista av original-index
            min_weight: Minimi-vikt per asset
            max_weight: Maximi-vikt per asset

        Returns:
            Viktvektor (N,)
        """
        n = len(sort_idx)
        w = pd.Series(1.0, index=sort_idx)

        # Rekursiv bisection
        def _bisect_recursive(items: list, weight: float):
            if len(items) == 1:
                return

            # Dela items i två kluster
            mid = len(items) // 2
            left = items[:mid]
            right = items[mid:]

            # Beräkna varians för varje kluster (inverse-variance allocation)
            cov_arr = np.array(cov)
            left_idx = [items[i] for i in range(mid)]
            right_idx = [items[i] for i in range(mid, len(items))]

            # Klustervarians = spår av kovarians-submatrisen
            left_var = np.trace(cov_arr[np.ix_(left_idx, left_idx)])
            right_var = np.trace(cov_arr[np.ix_(right_idx, right_idx)])

            # Inverse-variance viktfördelning
            if left_var + right_var > 0:
                alpha = 1.0 - left_var / (left_var + right_var)
            else:
                alpha = 0.5

            # Sätt vikter
            for idx in left_idx:
                w[idx] = weight * alpha
            for idx in right_idx:
                w[idx] = weight * (1 - alpha)

            # Rekursera
            _bisect_recursive(left, weight * alpha)
            _bisect_recursive(right, weight * (1 - alpha))

        _bisect_recursive(sort_idx, 1.0)

        weights = w.values
        # Clip och renormalisera
        weights = np.clip(weights, min_weight, max_weight)
        total = np.sum(weights)
        if total > 0:
            weights = weights / total
        else:
            weights = np.ones(n) / n

        return weights

    # ── Huvudmetod ─────────────────────────────────────────────────────────

    def hrp(self,
            cov_matrix: np.ndarray,
            linkage_method: str = "ward",
            min_weight: float = 0.01,
            max_weight: float = 0.25) -> np.ndarray:
        """
        Full HRP-algoritm.

        1. Beräkna korrelationsmatris -> distance matrix
        2. Hierarkisk klustring (linkage)
        3. Quasi-diagonalisering
        4. Seriell bisection

        Args:
            cov_matrix: Kovariansmatris (N x N)
            linkage_method: Metod för linkage ('ward', 'single', 'complete', 'average')
            min_weight: Minimi-vikt per asset
            max_weight: Maximi-vikt per asset

        Returns:
            Viktvektor (N,)
        """
        n = cov_matrix.shape[0]
        if n == 0:
            return np.array([])
        if n == 1:
            return np.array([1.0])

        # Distance matrix
        corr = self._cov_to_corr(cov_matrix)
        dist = self._corr_to_dist(corr)

        # Säkerställ symmetri och ingen negativa avstånd
        dist = (dist + dist.T) / 2
        np.fill_diagonal(dist, 0)
        dist = np.maximum(dist, 0)

        # Konvertera till condensed distance matrix för linkage
        condensed = squareform(dist, checks=False)

        # Hierarkisk klustring
        link = linkage(condensed, method=linkage_method)

        # Quasi-diagonalisering
        sort_idx = self._get_quasi_diag(link)

        # Seriell bisection
        weights = self._bisect(cov_matrix, sort_idx, min_weight, max_weight)

        return weights

    # ── Klusteranalys ──────────────────────────────────────────────────────

    def cluster_assets(self,
                       returns: np.ndarray,
                       n_clusters: int = 5,
                       linkage_method: str = "ward") -> dict:
        """
        Klustrar tillgångar baserat på korrelation.

        Använder hierarkisk klustring för att gruppera tillgångar.

        Args:
            returns: T x N matris av historiska returns
            n_clusters: Antal kluster
            linkage_method: Metod för linkage

        Returns:
            dict med:
                labels: array med kluster-etiketter per asset (N,)
                linkage: linkage-matrisen
                cluster_assets: {cluster_id: [asset_indices]}
        """
        if returns.shape[1] < 2:
            return {"labels": np.zeros(returns.shape[1], dtype=int),
                    "linkage": None,
                    "cluster_assets": {0: list(range(returns.shape[1]))}}

        cov_matrix = np.cov(returns, rowvar=False)
        corr = self._cov_to_corr(cov_matrix)
        dist = self._corr_to_dist(corr)

        # Condensed distance
        condensed = squareform(dist, checks=False)

        # Linkage
        link = linkage(condensed, method=linkage_method)

        # Skär trädet på n_clusters
        labels = fcluster(link, n_clusters, criterion="maxclust")

        # Gruppera
        clusters = {}
        for i, label in enumerate(labels):
            label = int(label)
            if label not in clusters:
                clusters[label] = []
            clusters[label].append(i)

        return {
            "labels": labels,
            "linkage": link,
            "cluster_assets": clusters,
        }

    # ── Dendrogram-visning (returnerar data) ───────────────────────────────

    @staticmethod
    def plot_dendrogram(linkage_matrix: np.ndarray,
                        labels: list) -> dict:
        """
        Generarar dendrogram-data för visualisering med Plotly.

        Args:
            linkage_matrix: Linkage-matris från scipy
            labels: Etiketter för varje asset

        Returns:
            dict med dendrogram-data (x, y, text för Plotly)
            eller tom dict om linkage_matrix är None
        """
        if linkage_matrix is None:
            return {}

        # Räkna ut dendrogram utan att plotta
        from scipy.cluster.hierarchy import dendrogram as _dendro
        ddata = _dendro(
            linkage_matrix,
            labels=labels,
            no_plot=True,
            color_threshold=0,
        )

        # Extrahera koordinater för plotting
        icoord = ddata["icoord"]
        dcoord = ddata["dcoord"]
        ivl = ddata["ivl"]

        return {
            "icoord": icoord,
            "dcoord": dcoord,
            "ivl": ivl,
            "leaves": ddata.get("leaves", []),
        }

    # ── Riskbidrag ─────────────────────────────────────────────────────────

    @staticmethod
    def risk_contribution(weights: np.ndarray,
                          cov_matrix: np.ndarray) -> np.ndarray:
        """
        Beräknar riskbidrag per asset (Risk Contribution / Risk Budget).

        Risk contribution = w_i * (Σw)_i / sqrt(w'Σw)
        dvs. marginal risk contribution * weight.

        Om risk parity fungerar perfekt är alla riskbidrag lika stora.

        Args:
            weights: Viktvektor (N,)
            cov_matrix: Kovariansmatris (N x N)

        Returns:
            Riskbidrag per asset (N,) -- summerar till portföljvolatiliteten
        """
        w = np.asarray(weights)
        port_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))

        if port_vol == 0:
            return np.zeros(len(w))

        # Marginal risk contribution: d(vol)/d(w_i) = (Σw)_i / vol
        mrc = np.dot(cov_matrix, w) / port_vol

        # Risk contribution: w_i * mrc_i
        rc = w * mrc

        return rc

    @staticmethod
    def risk_parity_deviation(weights: np.ndarray,
                              cov_matrix: np.ndarray) -> float:
        """
        Mäter hur mycket portföljen avviker från perfekt risk parity.

        Returnerar standardavvikelsen av riskbidragen.
        0 = perfekt risk parity. Hogre = mer koncentrerad risk.

        Args:
            weights: Viktvektor (N,)
            cov_matrix: Kovariansmatris (N x N)

        Returns:
            Standarddeviation av riskbidragen
        """
        rc = HRPOptimizer.risk_contribution(weights, cov_matrix)
        # Normalisera till andel av total risk
        rc_pct = rc / np.sum(rc) if np.sum(rc) > 0 else rc
        return float(np.std(rc_pct))


# ── Rekursiv hjälp ────────────────────────────────────────────────────────────

def _seriation_recursive(link: np.ndarray, node) -> list:
    """Hjälpfunktion för seriation."""
    result = []
    if isinstance(node, list):
        for sub in node:
            result.extend(_seriation_recursive(link, sub))
    else:
        result.append(node)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# CLI-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Simulera 5 tillgångar med olika korrelation
    np.random.seed(42)
    n = 5
    vol = np.array([0.20, 0.15, 0.25, 0.12, 0.18])
    corr = np.array([
        [1.0, 0.9, 0.3, 0.2, 0.4],
        [0.9, 1.0, 0.2, 0.1, 0.3],
        [0.3, 0.2, 1.0, 0.8, 0.5],
        [0.2, 0.1, 0.8, 1.0, 0.4],
        [0.4, 0.3, 0.5, 0.4, 1.0],
    ])
    cov = np.outer(vol, vol) * corr

    hrp = HRPOptimizer()
    weights = hrp.hrp(cov)
    rc = hrp.risk_contribution(weights, cov)
    dev = hrp.risk_parity_deviation(weights, cov)

    print("HRP-vikter:", np.round(weights, 4))
    print("Riskbidrag:", np.round(rc, 4))
    print(f"Risk parity deviation: {dev:.6f}")
    print(f"Summa vikter: {np.sum(weights):.4f}")
