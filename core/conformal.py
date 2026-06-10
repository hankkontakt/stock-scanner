"""
conformal.py — Split-conformal prediction för kalibrerad konfidens.

Ger garanterad täckningsgrad för prediktionsintervall utan distributionella
antaganden. Används för att kvantifiera osäkerhet i predicted_return.

Teori (split-conformal):
  1. Dela upp i träning + kalibrering (eller använd senaste OOS-fold).
  2. Beräkna |residualer| på kalibreringssetet.
  3. q = (1-alpha)-kvantil av residualerna.
  4. Prediktionsintervall = [point_pred - q, point_pred + q].
  → Garanterad ~(1-alpha) täckning på nya observationer (i medel).

Användning:
    from core.conformal import calibrate, predict_interval
    q = calibrate(residuals, alpha=0.1)
    lower, upper = predict_interval(point_preds, q)
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def calibrate(
    residuals: np.ndarray,
    alpha: float = 0.1,
) -> float:
    """Split-conformal: returnera (1-alpha)-kvantil av |residualer|.

    Kalibreringsresidualer = |actual - pred| från ett kalibreringsset
    (separat från träning). q = kvantil så att ~(1-alpha) av residualerna
    är ≤ q. Använd q för predict_interval().

    Args:
        residuals: Array med absoluta residualer (|actual - pred|).
        alpha: Signifikansnivå (default 0.1 → 90% täckning).

    Returns:
        q: Kvantilvärdet för prediktionsintervall.
    """
    if len(residuals) == 0:
        logger.warning("Empty residuals array — returning 0")
        return 0.0

    q = float(np.quantile(residuals, 1.0 - alpha))
    if np.isnan(q):
        logger.warning("NaN quantile — returning 0")
        return 0.0

    logger.info(
        "Conformal calibration: q(alpha=%.2f)=%.6f based on %d residuals",
        alpha, q, len(residuals),
    )
    return q


def predict_interval(
    point_preds: np.ndarray,
    q: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Skapa prediktionsintervall [point_pred - q, point_pred + q].

    Ger garanterad ~(1-alpha) täckning när q är från calibrate().

    Args:
        point_preds: Punktprediktioner (array).
        q: Kvantil från calibrate().

    Returns:
        (lower, upper): Arrays med nedre och övre intervallgränser.
    """
    lower = point_preds - q
    upper = point_preds + q
    return lower, upper


def estimate_uncertainty(
    point_preds: np.ndarray,
    q: float,
) -> np.ndarray:
    """Uppskatta osäkerhet per prediktion som halva intervallbredden.

    Användbar som feature i rankern eller för UI-visning.

    Args:
        point_preds: Punktprediktioner.
        q: Kvantil från calibrate().

    Returns:
        Array med osäkerhetsmått (samma form som point_preds).
    """
    return np.full_like(point_preds, q)
