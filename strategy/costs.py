"""
strategy/costs.py
=================
Slippage- och provisionsmodeller för backtesting.

Innehåller:
- FixedCommission: fast provision per trade
- PercentageCommission: procentuell provision
- TieredCommission: volymbaserad provisionstrappa
- SlippageModel: fast slippage i bps
- VolumeBasedSlippage: slippage baserat på volym
- MarketImpactAlmgren: Almgren-Chriss market impact-modell
- apply_costs: applicera kostnader på en backtest
"""

import numpy as np
import pandas as pd

from strategy.base import StrategyResult


class FixedCommission:
    """
    Fast provision per trade.

    per_trade: Kostnad per trade (default $10)
    per_share: Kostnad per aktie (default 0, override per_trade)
    """

    def __init__(self, per_trade: float = 10.0, per_share: float = 0.0):
        self.per_trade = per_trade
        self.per_share = per_share

    def calculate(self, trade_row: dict) -> float:
        """Beräkna provision för en trade."""
        shares = trade_row.get("shares", 0)
        if self.per_share > 0:
            return self.per_share * abs(shares)
        return self.per_trade

    def __repr__(self) -> str:
        if self.per_share > 0:
            return f"FixedCommission(per_share=${self.per_share:.2f})"
        return f"FixedCommission(per_trade=${self.per_trade:.2f})"


class PercentageCommission:
    """
    Procentuell provision per trade.

    pct: Procentandel per trade (default 0.001 = 0.1%)
    min: Minimiprovision
    max: Maximiprovision
    """

    def __init__(self, pct: float = 0.001, min_commission: float = 0.0, max_commission: float = float("inf")):
        self.pct = pct
        self.min_commission = min_commission
        self.max_commission = max_commission

    def calculate(self, trade_row: dict) -> float:
        """Beräkna provision baserat på trade-värde."""
        value = abs(trade_row.get("value", 0))
        commission = value * self.pct
        return max(self.min_commission, min(commission, self.max_commission))

    def __repr__(self) -> str:
        return f"PercentageCommission({self.pct*100:.2f}%)"


class TieredCommission:
    """
    Volymbaserad provisionstrappa.
    Lägre provision för högre volymer.

    tiers: Dict med volymgräns -> provision per aktie
           Ex: {100000: 0.01, 500000: 0.005, float("inf"): 0.003}
    """

    def __init__(self, tiers: dict = None):
        self.tiers = tiers or {100000: 0.01, 500000: 0.005, float("inf"): 0.003}

    def calculate(self, trade_row: dict) -> float:
        """Beräkna provision baserat på trade-volym."""
        volume = abs(trade_row.get("value", 0))
        for threshold, rate in sorted(self.tiers.items()):
            if volume <= threshold:
                return volume * rate
        return volume * 0.003

    def __repr__(self) -> str:
        return f"TieredCommission(tiers={self.tiers})"


class SlippageModel:
    """
    Fast slippage-modell.

    fixed_bps: Slippage i baspunkter (default 5 bps = 0.05%)
    """

    def __init__(self, fixed_bps: float = 5.0):
        self.fixed_bps = fixed_bps

    def calculate(self, trade_row: dict) -> float:
        """Beräkna slippage-kostnad."""
        value = abs(trade_row.get("value", 0))
        return value * self.fixed_bps / 10000

    def __repr__(self) -> str:
        return f"SlippageModel({self.fixed_bps} bps)"


class VolumeBasedSlippage:
    """
    Volymbaserad slippage.
    Ju större trade i förhållande till volym, desto mer slippage.

    participation_rate: Maximal andel av daglig volym (default 0.1 = 10%)
    """

    def __init__(self, participation_rate: float = 0.1):
        self.participation_rate = participation_rate

    def calculate(self, trade_row: dict) -> float:
        """Beräkna slippage baserat på volym."""
        value = abs(trade_row.get("value", 0))
        volume = abs(trade_row.get("avg_daily_volume", 0))
        price = abs(trade_row.get("price", 1))

        if volume <= 0 or price <= 0:
            return value * 0.001  # fallback 10 bps

        # Andel av daglig volym
        participation = value / (volume * price)
        # Slippage ökar med participation rate
        slippage_bps = min(100, participation / self.participation_rate * 10)
        return value * slippage_bps / 10000

    def __repr__(self) -> str:
        return f"VolumeBasedSlippage(participation={self.participation_rate:.0%})"


class MarketImpactAlmgren:
    """
    Almgren-Chriss market impact-modell.

    Permanent impact: I_perm = a * sigma * (Q / V)^0.3 * sign(Q)
    Temporary impact: I_temp = b * sigma * (Q / V)^0.6 * sign(Q)

    annual_vol:        Årlig volatilitet (decimal, t.ex. 0.2 för 20%)
    avg_daily_volume:  Genomsnittlig daglig volym (i dollar)
    a:                 Permanent impact-koefficient (default 0.1)
    b:                 Temporary impact-koefficient (default 0.2)
    """

    def __init__(self, annual_vol: float = 0.2, avg_daily_volume: float = 1e6,
                 a: float = 0.1, b: float = 0.2):
        self.annual_vol = annual_vol
        self.avg_daily_volume = avg_daily_volume
        self.a = a
        self.b = b

    def calculate(self, trade_row: dict) -> dict:
        """
        Beräkna market impact.

        Return: dict med permanent_impact, temporary_impact, total_impact
        """
        value = abs(trade_row.get("value", 0))
        price = abs(trade_row.get("price", 1))
        direction = np.sign(trade_row.get("value", 0))
        daily_vol = trade_row.get("avg_daily_volume", self.avg_daily_volume)

        # Daglig volatilitet
        daily_sigma = self.annual_vol / np.sqrt(252)

        # Andel av daglig volym
        if daily_vol > 0 and price > 0:
            q_over_v = value / (daily_vol * price)
        else:
            q_over_v = 0.01  # fallback

        q_over_v = max(min(q_over_v, 0.5), 0.001)  # clamp

        # Permanent impact (i andel av pris)
        perm_impact = self.a * daily_sigma * (q_over_v ** 0.3) * direction

        # Temporary impact (i andel av pris)
        temp_impact = self.b * daily_sigma * (q_over_v ** 0.6) * direction

        total_cost_bps = abs(perm_impact + temp_impact) * 10000

        return {
            "permanent_impact_pct": float(perm_impact * 100),
            "temporary_impact_pct": float(temp_impact * 100),
            "total_impact_bps": float(total_cost_bps),
            "cost": float((perm_impact + temp_impact) * value),
        }

    def __repr__(self) -> str:
        return f"MarketImpactAlmgren(vol={self.annual_vol:.0%}, adv=${self.avg_daily_volume:,.0f})"


def apply_costs(strategy_result: StrategyResult,
                commission=None,
                slippage=None,
                market_impact=None) -> StrategyResult:
    """
    Applicera kostnader på ett backtestresultat.

    strategy_result: StrategyResult från run_backtest()
    commission:      Commission-modell (None = ingen)
    slippage:        Slippage-modell (None = ingen)
    market_impact:   Market impact-modell (None = ingen)

    Return: StrategyResult med justerade returns, equity_curve, trades
    """
    import copy

    result = copy.deepcopy(strategy_result)
    trades = result.trades.copy() if result.trades is not None else pd.DataFrame()

    if trades.empty:
        return result

    total_costs = 0.0

    for idx, trade in trades.iterrows():
        trade_cost = 0.0

        # Beräkna trade value
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        direction = trade.get("direction", 0)

        trade_row = {
            "value": direction * entry_price * 100,  # förenklad: 100 aktier
            "shares": 100,
            "price": entry_price,
            "avg_daily_volume": 1_000_000,
        }

        # Commission
        if commission:
            trade_cost += commission.calculate(trade_row)

        # Slippage
        if slippage:
            trade_cost += slippage.calculate(trade_row)

        # Market impact
        if market_impact:
            impact = market_impact.calculate(trade_row)
            trade_cost += impact.get("cost", 0)

        total_costs += trade_cost

        # Justera trade-pnl
        if "pnl" in trades.columns:
            trades.at[idx, "pnl"] = trades.at[idx, "pnl"] - trade_cost
            trades.at[idx, "costs"] = trade_cost

    # Justera returns för totala kostnader (enkel metod: sprid över hela perioden)
    if total_costs > 0 and len(result.returns) > 0:
        avg_cost_per_day = total_costs / len(result.returns)
        total_equity = result.equity_curve.iloc[-1] if len(result.equity_curve) > 0 else 100000
        daily_cost_pct = avg_cost_per_day / total_equity if total_equity > 0 else 0

        result.returns = result.returns - daily_cost_pct
        result.equity_curve = (1 + result.returns).cumprod()
        if len(result.equity_curve) > 0:
            result.equity_curve = result.equity_curve * 100000

    result.trades = trades
    return result
