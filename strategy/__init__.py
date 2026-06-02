"""
strategy/__init__.py
====================
Strategimotor för MarketScan.
Exporterar huvudklasser och funktioner.
"""

# Basramverk
from strategy.base import (
    Strategy,
    StrategyResult,
    run_backtest,
    run_parameter_sweep,
)

# Förbyggda strategier
from strategy.strategies.momentum_strategy import (
    TimeSeriesMomentum,
    CrossSectionalMomentum,
    DualMomentum,
    SeasonalityStrategy,
)
from strategy.strategies.mean_reversion_strategy import (
    BollingerMeanReversion,
    RSIMeanReversion,
    PairsTrading,
    MovingAverageCrossover,
    MACDStrategy,
)
from strategy.strategies.trend_following_strategy import (
    TrendFollowing,
    DonchianBreakout,
    SupertrendStrategy,
    ParabolicSARStrategy,
)
from strategy.strategies.factor_strategy import (
    FactorCompositeStrategy,
    TopNStrategy,
    SectorRotationStrategy,
    FactorTimingStrategy,
)

# Optimering
from strategy.optimizer import (
    GridSearchCV,
    RandomSearchCV,
    GeneticOptimizer,
    WalkForwardOptimization,
)

# Performance
from strategy.performance import (
    calculate_returns,
    brinson_attribution,
    carhart_attribution,
    performance_summary,
)

# Kostnadsmodeller
from strategy.costs import (
    FixedCommission,
    PercentageCommission,
    TieredCommission,
    SlippageModel,
    VolumeBasedSlippage,
    MarketImpactAlmgren,
    apply_costs,
)

# Riskhantering
from strategy.risk import (
    PositionSizer,
    StopLossManager,
    PortfolioRiskMonitor,
    DrawdownController,
    CorrelationChecker,
)

# DSL
from strategy.dsl import (
    parse_strategy,
    run_dsl_strategy,
    validate_strategy,
    dsl_to_yaml,
)

__all__ = [
    # Bas
    "Strategy",
    "StrategyResult",
    "run_backtest",
    "run_parameter_sweep",
    # Momentum
    "TimeSeriesMomentum",
    "CrossSectionalMomentum",
    "DualMomentum",
    "SeasonalityStrategy",
    # Mean reversion
    "BollingerMeanReversion",
    "RSIMeanReversion",
    "PairsTrading",
    "MovingAverageCrossover",
    "MACDStrategy",
    # Trend following
    "TrendFollowing",
    "DonchianBreakout",
    "SupertrendStrategy",
    "ParabolicSARStrategy",
    # Factor
    "FactorCompositeStrategy",
    "TopNStrategy",
    "SectorRotationStrategy",
    "FactorTimingStrategy",
    # Optimering
    "GridSearchCV",
    "RandomSearchCV",
    "GeneticOptimizer",
    "WalkForwardOptimization",
    # Performance
    "calculate_returns",
    "brinson_attribution",
    "carhart_attribution",
    "performance_summary",
    # Costs
    "FixedCommission",
    "PercentageCommission",
    "TieredCommission",
    "SlippageModel",
    "VolumeBasedSlippage",
    "MarketImpactAlmgren",
    "apply_costs",
    # Risk
    "PositionSizer",
    "StopLossManager",
    "PortfolioRiskMonitor",
    "DrawdownController",
    "CorrelationChecker",
    # DSL
    "parse_strategy",
    "run_dsl_strategy",
    "validate_strategy",
    "dsl_to_yaml",
]
