"""
kelly.py -- Kelly Criterion Position Sizing
==========================================
Implementerar Kelly Criterion för optimal positionsstorlek.

Innehåller:
1. Standard Kelly-fraction: f* = p - (1-p)/R
2. Fractional Kelly: conservative variant (t.ex. 25% Kelly)
3. Edge-estimering från historiska trades
4. Multi-asset Kelly för portföljer
5. Score-baserad position sizing guide

Referens: Ed Thorp (The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market)

Användning:
    from portfolio.kelly import KellyCalculator
    kc = KellyCalculator()
    f = kc.kelly_fraction(0.6, 2.0)  # 60% win chance, 2:1 reward
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class KellyCalculator:
    """
    Kelly Criterion-kalkylator för positionsstorleksättning.

    Stöder:
      - Standard Kelly
      - Fractional Kelly (conservative)
      - Edge-estimering från trade history
      - Multi-asset Kelly
      - Score-baserad sizing guide
    """

    def __init__(self):
        pass

    # ── Standard Kelly ─────────────────────────────────────────────────────

    @staticmethod
    def kelly_fraction(win_prob: float,
                       win_loss_ratio: float) -> float:
        """
        Beräknar standard Kelly-fraction.

        f* = p - (1-p) / R

        där:
          p = sannolikhet för vinst
          R = win/loss ratio (average win / average loss)

        Args:
            win_prob: Sannolikhet för vinst (0.0 - 1.0)
            win_loss_ratio: Genomsnittlig vinst / genomsnittlig förlust

        Returns:
            Optimal Kelly-fraction (0.0 - 1.0)
            Returnerar 0.0 om edge är negativ.
        """
        if win_prob <= 0 or win_loss_ratio <= 0:
            return 0.0

        if win_prob >= 1.0:
            return 1.0  # Risk-free

        f = win_prob - (1.0 - win_prob) / win_loss_ratio
        return max(0.0, f)

    # ── Fractional Kelly ───────────────────────────────────────────────────

    @staticmethod
    def fractional_kelly(win_prob: float,
                         win_loss_ratio: float,
                         fraction: float = 0.25) -> float:
        """
        Fractional Kelly -- multiplicerar standard Kelly med en fraction.

        Fractional Kelly (t.ex. 25%) minskar risken dramatiskt medan
        det mesta av den optimala tillväxten behålls.

        Args:
            win_prob: Sannolikhet för vinst
            win_loss_ratio: Win/loss ratio
            fraction: Andel av full Kelly (0.0 - 1.0)

        Returns:
            Fractional Kelly positionsstorlek
        """
        full_kelly = KellyCalculator.kelly_fraction(win_prob, win_loss_ratio)
        return full_kelly * fraction

    # ── Edge från trades ───────────────────────────────────────────────────

    @staticmethod
    def optimal_f_from_trades(trade_history: list) -> dict:
        """
        Estimerar optimal Kelly-fraction från historiska trades.

        Använder Maximum Likelihood-estimering:
          f* = (avg_return) / (avg_return_squared)

        Args:
            trade_history: Lista av trade-P&L i procent (t.ex. [0.05, -0.03, 0.02, ...])

        Returns:
            dict med:
                optimal_f: Kelly-estimat
                mean_return: Genomsnittlig trade-return
                std_return: Standardavvikelse på returns
                sharpe: Sharpe-liknande mått
                n_trades: Antal trades
        """
        if not trade_history or len(trade_history) < 5:
            logger.warning("För få trades för Kelly-estimering (<5)")
            return {
                "optimal_f": 0.0,
                "mean_return": 0.0,
                "std_return": 0.0,
                "sharpe": 0.0,
                "n_trades": len(trade_history) if trade_history else 0,
            }

        returns = np.array(trade_history, dtype=float)
        n = len(returns)

        # Avkastningsstatistik
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns, ddof=1))

        # Kelly via method of moments
        # f* ≈ μ / σ² (för små returns)
        if std_ret > 0:
            optimal_f = mean_ret / (std_ret ** 2)
        else:
            optimal_f = 0.0

        # Normalisera till [0, 1]
        optimal_f = max(0.0, min(1.0, optimal_f))

        # Sharpe (per trade)
        sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

        # Edge: förväntad avkastning per trade
        edge_pct = mean_ret * 100

        return {
            "optimal_f": round(optimal_f, 4),
            "mean_return": round(mean_ret, 4),
            "std_return": round(std_ret, 4),
            "sharpe": round(sharpe, 4),
            "edge_pct": round(edge_pct, 2),
            "n_trades": n,
        }

    # ── Multi-asset Kelly ──────────────────────────────────────────────────

    @staticmethod
    def kelly_for_portfolio(probabilities: np.ndarray,
                            expected_returns: np.ndarray,
                            max_weight: float = 0.2) -> np.ndarray:
        """
        Multi-asset Kelly för att fördela kapital över flera tillgångar.

        Approximerar Kelly genom att varje tillgång behandlas oberoende
        och vikterna normaliseras med max-weight constraint.

        En mer avancerad version skulle använda full kovariansmatris,
        men denna approximation fungerar bra för de flesta praktiska fall.

        Args:
            probabilities: Array av vinstsannolikheter (N,)
            expected_returns: Array av förväntad avkastning (N,)
            max_weight: Maximi-vikt per asset

        Returns:
            Kelly-vikter (N,), summerar till 1.0
        """
        n = len(probabilities)
        if n == 0:
            return np.array([])

        # Beräkna Kelly-fraction per asset
        # Approximera win_loss_ratio från expected return
        kelly_fractions = np.zeros(n)
        for i in range(n):
            p = probabilities[i]
            er = expected_returns[i]

            # Uppskatta win_loss_ratio: om vinst = er/p, förlust = antag 1.0
            if p > 0 and p < 1:
                avg_win = er / p  # E[r] = p * win - (1-p) * loss
                avg_loss = 1.0  # Normaliserad förlust
                if avg_win > 0:
                    wl_ratio = avg_win / avg_loss
                    kelly_fractions[i] = KellyCalculator.kelly_fraction(p, wl_ratio)
                else:
                    kelly_fractions[i] = 0.0
            elif p >= 1.0:
                kelly_fractions[i] = 1.0
            else:
                kelly_fractions[i] = 0.0

        # Normalisera med max-weight constraint
        kelly_fractions = np.clip(kelly_fractions, 0, max_weight)
        total = np.sum(kelly_fractions)
        if total > 0:
            return kelly_fractions / total
        else:
            return np.ones(n) / n

    # ── Score-baserad sizing guide ─────────────────────────────────────────

    @staticmethod
    def sizing_guide(score: float,
                     confidence: float,
                     volatility: float,
                     portfolio_value: float = 100000.0) -> dict:
        """
        Kelly-inspirerad position sizing baserat på score, confidence och volatilitet.

        Mappar score/confidence/volatility till en positionsstorlek.

        Args:
            score: Score_total (0-100)
            confidence: Confidence (0.0 - 1.0)
            volatility: Årlig volatilitet (decimal, t.ex. 0.25 = 25%)
            portfolio_value: Portföljvärde för kronbelopp

        Returns:
            dict med:
                suggested_pct: Föreslagen andel av portföljen (%)
                suggested_sek: Föreslaget kronbelopp
                risk_level: Låg/Medel/Hög
                max_loss_estimate: Uppskattad max-förlust vid stop-loss
                rationale: Kort förklaring
        """
        # Normalisera inputs
        score_norm = max(0, min(100, score)) / 100.0
        conf = max(0.0, min(1.0, confidence))
        vol = max(0.05, volatility)  # Min 5% volatilitet

        # Bas-storlek från score (0-8%)
        base_pct = score_norm * 0.08

        # Confidence multiplier (0.5 - 1.5)
        conf_mult = 0.5 + conf

        # Volatilitetsstraff: hög vol = mindre position
        # Normal volatilitet ~20%, straff vid >30%
        vol_penalty = max(0.3, min(1.0, 0.20 / max(vol, 0.05)))
        vol_penalty = np.clip(vol_penalty, 0.3, 1.0)

        # Kombinera
        suggested_pct = base_pct * conf_mult * vol_penalty
        suggested_pct = max(0.5, min(15.0, suggested_pct))  # 0.5% - 15%

        # Kronbelopp
        suggested_sek = portfolio_value * (suggested_pct / 100.0)

        # Risk level
        if vol > 0.40:
            risk_level = "Hög"
        elif vol > 0.25:
            risk_level = "Medel"
        else:
            risk_level = "Låg"

        # Max loss (2x ATR approximation via vol)
        max_loss_pct = vol * 2.0 * np.sqrt(1.0 / 252) * 100  # ~2 dagars rörelse
        max_loss_sek = suggested_sek * (max_loss_pct / 100.0)

        # Rationale
        rationale = (
            f"Score {score:.0f}/100 ({'stark' if score >= 70 else 'medel' if score >= 50 else 'svag'}), "
            f"confidence {conf:.0%}, volatilitet {vol:.1%} -> {suggested_pct:.1f}% av portföljen"
        )

        return {
            "suggested_pct": round(suggested_pct, 1),
            "suggested_sek": round(suggested_sek, 0),
            "risk_level": risk_level,
            "max_loss_estimate_pct": round(max_loss_pct, 1),
            "max_loss_estimate_sek": round(max_loss_sek, 0),
            "rationale": rationale,
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    kc = KellyCalculator()

    # Standard Kelly
    f = kc.kelly_fraction(0.6, 2.0)
    print(f"Standard Kelly (60% win, 2:1): {f:.4f} = {f*100:.1f}%")

    # Fractional Kelly
    fk = kc.fractional_kelly(0.6, 2.0, 0.25)
    print(f"25% Kelly: {fk:.4f} = {fk*100:.1f}%")

    # Edge från trades
    trades = [0.05, -0.03, 0.07, -0.02, 0.04, 0.06, -0.04, 0.03]
    edge = kc.optimal_f_from_trades(trades)
    print(f"\nEdge estimering ({len(trades)} trades):")
    for k, v in edge.items():
        print(f"  {k}: {v}")

    # Multi-asset Kelly
    probs = np.array([0.6, 0.55, 0.7, 0.5])
    ers = np.array([0.05, 0.03, 0.08, 0.01])
    weights = kc.kelly_for_portfolio(probs, ers)
    print("\nMulti-asset Kelly:")
    for i, w in enumerate(weights):
        print(f"  Asset {i}: {w:.2%}")

    # Sizing guide
    guide = kc.sizing_guide(75, 0.8, 0.28, 100000)
    print("\nSizing guide:")
    for k, v in guide.items():
        print(f"  {k}: {v}")
