"""
strategy/risk.py
================
Riskhanteringsmoduler för strategier.

Innehåller:
- PositionSizer: position sizing (Kelly, volatility, fixed fraction)
- StopLossManager: stop loss-hantering (trailing, time, volatility)
- PortfolioRiskMonitor: portföljriskövervakning
- DrawdownController: stop trading vid drawdown
- CorrelationChecker: korrelationsvarning
"""

import numpy as np
import pandas as pd


class PositionSizer:
    """
    Beräknar positionsstorlek baserat på olika metoder.

    Metoder:
        - "kelly": Kelly-kriteriet (half-Kelly som standard)
        - "volatility": positionsstorlek baserat på ATR
        - "fixed_fraction": fast andel av kapital
        - "equal_weight": likaviktad
    """

    def __init__(self, method: str = "kelly", **kwargs):
        """
        method:   "kelly", "volatility", "fixed_fraction", "equal_weight"
        kwargs:   Parametrar för vald metod
        """
        self.method = method
        self.kwargs = kwargs

    def calculate(self, capital: float, price: float, n_positions: int = 1,
                  win_rate: float = 0.5, win_loss_ratio: float = 1.5,
                  atr: float = None, volatility: float = None) -> dict:
        """
        Beräkna positionsstorlek.

        capital:       Tillgängligt kapital
        price:         Aktuellt pris
        n_positions:   Antal positioner i portföljen
        win_rate:      Historisk win rate (för Kelly)
        win_loss_ratio: Genomsnittlig vinst/förlust-kvot (för Kelly)
        atr:           Average True Range (för volatility-baserad)
        volatility:    Daglig volatilitet (för volatility-baserad)

        Return: dict med shares, capital_used, pct_of_capital, method
        """
        if self.method == "kelly":
            return self._kelly_sizing(capital, price, win_rate, win_loss_ratio)
        elif self.method == "volatility":
            return self._volatility_sizing(capital, price, atr, volatility)
        elif self.method == "fixed_fraction":
            fraction = self.kwargs.get("fraction", 0.1)
            return self._fixed_fraction(capital, price, fraction)
        elif self.method == "equal_weight":
            return self._equal_weight(capital, price, n_positions)
        else:
            return self._fixed_fraction(capital, price, 0.1)

    def _kelly_sizing(self, capital: float, price: float,
                      win_rate: float, win_loss_ratio: float) -> dict:
        """Kelly-kriterium med half-Kelly-begränsning."""
        if win_loss_ratio <= 0:
            return self._fixed_fraction(capital, price, 0.02)

        # Full Kelly
        kelly = win_rate - (1 - win_rate) / win_loss_ratio
        # Half-Kelly med cap
        half_kelly = max(0.01, min(0.25, kelly * 0.5))

        capital_used = capital * half_kelly
        shares = int(capital_used / price) if price > 0 else 0

        return {
            "shares": max(1, shares),
            "capital_used": round(shares * price, 2),
            "pct_of_capital": round(half_kelly * 100, 2),
            "method": "kelly",
            "kelly_raw": round(kelly, 4),
            "kelly_capped": round(half_kelly, 4),
        }

    def _volatility_sizing(self, capital: float, price: float,
                           atr: float = None, volatility: float = None) -> dict:
        """Volatilitetsbaserad position sizing."""
        risk_per_trade = self.kwargs.get("risk_per_trade", 0.01)  # 1% risk per trade
        risk_per_share = atr or (price * volatility) if volatility else price * 0.02

        if risk_per_share <= 0:
            return self._fixed_fraction(capital, price, 0.05)

        # Antal aktier baserat på riskbudget
        risk_budget = capital * risk_per_trade
        shares = int(risk_budget / risk_per_share)
        capital_used = shares * price

        return {
            "shares": max(1, shares),
            "capital_used": round(capital_used, 2),
            "pct_of_capital": round(capital_used / capital * 100, 2) if capital > 0 else 0,
            "method": "volatility",
            "risk_per_share": round(risk_per_share, 4),
            "risk_budget": round(risk_budget, 2),
        }

    def _fixed_fraction(self, capital: float, price: float, fraction: float) -> dict:
        """Fast andel av kapital."""
        fraction = max(0.01, min(1.0, fraction))
        capital_used = capital * fraction
        shares = int(capital_used / price) if price > 0 else 0

        return {
            "shares": max(1, shares),
            "capital_used": round(shares * price, 2),
            "pct_of_capital": round(fraction * 100, 2),
            "method": "fixed_fraction",
        }

    def _equal_weight(self, capital: float, price: float, n_positions: int) -> dict:
        """Likaviktad position."""
        n = max(1, n_positions)
        fraction = 1.0 / n
        return self._fixed_fraction(capital, price, fraction)


class StopLossManager:
    """
    Hanterar olika typer av stop-loss.

    Typer:
        - "fixed": fast procentuell stop
        - "trailing": trailing stop
        - "volatility": ATR-baserad stop
        - "time": tidsbaserad stop (stäng efter X dagar)
    """

    def __init__(self, stop_type: str = "trailing", **kwargs):
        """
        stop_type: "fixed", "trailing", "volatility", "time"
        kwargs:    Parametrar för vald stop-typ
        """
        self.stop_type = stop_type
        self.kwargs = kwargs

    def calculate_stop(self, entry_price: float, current_price: float,
                       highest_price: float = None, atr: float = None) -> dict:
        """
        Beräkna stop-loss-nivå.

        entry_price:   Ingångspris
        current_price: Aktuellt pris
        highest_price: Högsta pris sedan entry (för trailing)
        atr:           ATR (för volatility stop)

        Return: dict med stop_price, stop_pct, triggered, stop_type
        """
        if self.stop_type == "fixed":
            pct = self.kwargs.get("stop_pct", 0.05)  # 5% default
            stop_price = entry_price * (1 - pct)
            triggered = current_price <= stop_price

        elif self.stop_type == "trailing":
            trail_pct = self.kwargs.get("trail_pct", 0.07)  # 7% default
            high = highest_price or current_price
            stop_price = high * (1 - trail_pct)
            triggered = current_price <= stop_price

        elif self.stop_type == "volatility":
            mult = self.kwargs.get("atr_multiplier", 2.5)
            atr_val = atr or current_price * 0.02
            stop_price = current_price - atr_val * mult
            triggered = current_price <= stop_price

        elif self.stop_type == "time":
            max_hold = self.kwargs.get("max_hold_days", 30)
            stop_price = 0  # Stäng oavsett pris
            triggered = False  # Hanteras externt

        else:
            stop_price = entry_price * 0.95
            triggered = current_price <= stop_price

        stop_pct = (stop_price / current_price - 1) * 100 if current_price > 0 else 0

        return {
            "stop_price": round(stop_price, 2),
            "stop_pct": round(stop_pct, 2),
            "triggered": bool(triggered),
            "stop_type": self.stop_type,
        }


class PortfolioRiskMonitor:
    """
    Övervakar portföljrisk.

    Övervakar:
        - Koncentration: största positionens andel
        - Hävstång: total exponering vs kapital
        - VaR: Value at Risk
        - Beta: portfölj-beta
    """

    def __init__(self, max_concentration: float = 0.25, max_leverage: float = 1.0,
                 var_confidence: float = 0.95):
        self.max_concentration = max_concentration
        self.max_leverage = max_leverage
        self.var_confidence = var_confidence

    def analyze(self, holdings: pd.DataFrame, returns: pd.Series = None) -> dict:
        """
        Analysera portföljrisk.

        holdings: DataFrame med ticker, value, weight
        returns:  Daglig portföljavkastning (för VaR)

        Return: dict med risk-mått
        """
        if holdings.empty:
            return {}

        total_value = holdings["value"].sum() if "value" in holdings.columns else 1
        weights = holdings["value"] / total_value if "value" in holdings.columns else pd.Series(1.0 / len(holdings))

        # Koncentration
        max_weight = weights.max()
        top3_concentration = weights.nlargest(3).sum()

        # Hävstång
        leverage = total_value / (holdings["capital"].sum() if "capital" in holdings.columns else total_value)

        # VaR
        var = 0.0
        cvar = 0.0
        if returns is not None and len(returns) > 20:
            var = float(np.percentile(returns, (1 - self.var_confidence) * 100))
            cvar = float(returns[returns <= var].mean()) if (returns <= var).any() else 0.0

        # Varningar
        warnings = []
        if max_weight > self.max_concentration:
            warnings.append(f"Hög koncentration: {max_weight:.1%} i en position")
        if leverage > self.max_leverage:
            warnings.append(f"Hög hävstång: {leverage:.2f}x")

        return {
            "n_positions": len(holdings),
            "max_weight": float(max_weight),
            "top3_concentration": float(top3_concentration),
            "leverage": float(leverage),
            "var_95": round(var * 100, 2),
            "cvar_95": round(cvar * 100, 2),
            "var_confidence": self.var_confidence,
            "warnings": warnings,
        }


class DrawdownController:
    """
    Stoppar trading om drawdown överstiger en tröskel.

    Parametrar:
        max_drawdown_pct:  Maximal tillåten drawdown (default 0.2 = 20%)
        recover_pct:       Återhämtningsnivå för att starta om (default 0.05 = 5%)
        cooldown_days:     Antal dagar att vänta efter trigger (default 5)
    """

    def __init__(self, max_drawdown_pct: float = 0.20, recover_pct: float = 0.05,
                 cooldown_days: int = 5):
        self.max_drawdown_pct = max_drawdown_pct
        self.recover_pct = recover_pct
        self.cooldown_days = cooldown_days
        self._peak = 0.0
        self._stopped = False
        self._stop_day = 0

    def check(self, portfolio_value: float, day_index: int) -> dict:
        """
        Kontrollera om trading ska stoppas.

        portfolio_value: Aktuellt portföljvärde
        day_index:       Aktuell dag (index)

        Return: dict med stopped, drawdown_pct, reason
        """
        self._peak = max(self._peak, portfolio_value)
        dd_pct = (self._peak - portfolio_value) / self._peak if self._peak > 0 else 0

        if self._stopped:
            # Kolla om vi ska starta om
            recover_value = self._peak * (1 - self.max_drawdown_pct + self.recover_pct)
            if portfolio_value >= recover_value:
                self._stopped = False
                return {"stopped": False, "drawdown_pct": dd_pct, "reason": "Återhämtad"}
            return {"stopped": True, "drawdown_pct": dd_pct, "reason": "I cooldown"}

        if dd_pct >= self.max_drawdown_pct:
            self._stopped = True
            self._stop_day = day_index
            return {"stopped": True, "drawdown_pct": dd_pct,
                    "reason": f"Drawdown {dd_pct:.1%} överstiger gräns {self.max_drawdown_pct:.1%}"}

        return {"stopped": False, "drawdown_pct": dd_pct, "reason": "Normal"}

    def reset(self):
        """Återställ kontrollern."""
        self._peak = 0.0
        self._stopped = False
        self._stop_day = 0


class CorrelationChecker:
    """
    Varnar om korrelation mellan strategier/innehav är för hög.

    Parametrar:
        max_correlation:  Max tillåten korrelation (default 0.9)
        window:           Rullande fönster för korrelation (default 63 dagar)
    """

    def __init__(self, max_correlation: float = 0.9, window: int = 63):
        self.max_correlation = max_correlation
        self.window = window

    def check(self, returns_df: pd.DataFrame) -> dict:
        """
        Kontrollera korrelation mellan strategier/tillgångar.

        returns_df: DataFrame med returns för varje strategi/tillgång

        Return: dict med correlation_matrix, warnings, high_corr_pairs
        """
        if returns_df.empty or returns_df.shape[1] < 2:
            return {"correlation_matrix": pd.DataFrame(), "warnings": [], "high_corr_pairs": []}

        # Beräkna rullande korrelation
        corr_matrix = returns_df.corr()
        corr_matrix = corr_matrix.fillna(0)

        warnings = []
        high_corr_pairs = []

        for i in range(len(corr_matrix.columns)):
            for j in range(i + 1, len(corr_matrix.columns)):
                col_i = corr_matrix.columns[i]
                col_j = corr_matrix.columns[j]
                corr_val = corr_matrix.loc[col_i, col_j]

                if abs(corr_val) > self.max_correlation:
                    pair = (str(col_i), str(col_j), float(corr_val))
                    high_corr_pairs.append(pair)
                    warnings.append(
                        f"Hög korrelation ({corr_val:.2f}) mellan '{col_i}' och '{col_j}'"
                    )

        return {
            "correlation_matrix": corr_matrix,
            "n_pairs_checked": len(returns_df.columns) * (len(returns_df.columns) - 1) // 2,
            "high_corr_pairs": high_corr_pairs,
            "n_high_corr_pairs": len(high_corr_pairs),
            "warnings": warnings,
            "max_correlation": self.max_correlation,
        }
