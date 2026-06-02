"""
strategy/strategies/factor_strategy.py
=======================================
Faktorbaserade strategier som utnyttjar scoring-faktorer direkt.

Innehåller:
- FactorCompositeStrategy: använd scoring-faktorer direkt
- TopNStrategy: top-N efter scoring
- SectorRotationStrategy: sektorrotation baserat på momentum
- FactorTimingStrategy: faktor-timing baserat på regim
"""

import numpy as np
import pandas as pd

from strategy.base import Strategy


class FactorCompositeStrategy(Strategy):
    """
    Använder scoring-faktorer direkt från MarketScan-systemet.
    Förväntar sig en DataFrame med faktorkolumner som score_value, score_momentum, etc.

    Parametrar:
        scoring_weights: Dict med faktor -> vikt
                         Ex: {"score_momentum": 0.4, "score_value": 0.3, "score_quality": 0.3}
        top_pct:         Andel aktier att allokera till (default 0.2 = 20%)
        rebalance_freq:  Rebalanseringsfrekvens (default "ME" = månad)
    """

    def __init__(self, name="FactorCompositeStrategy", params=None):
        params = params or {}
        params.setdefault("scoring_weights", {})
        params.setdefault("top_pct", 0.2)
        params.setdefault("rebalance_freq", "ME")
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        weights = self.params["scoring_weights"]
        top_pct = self.params["top_pct"]

        # Om data är multi-asset (flera kolumner med priser)
        if isinstance(close, pd.DataFrame) and close.shape[1] > 1:
            return self._multi_asset_signals(data, close, weights, top_pct)

        # Single asset: använd faktorer från data om de finns
        signal = pd.Series(0.0, index=close.index)

        # Beräkna compositescore från tillgängliga faktorer
        score = pd.Series(0.0, index=close.index)
        total_weight = 0.0
        for col, w in weights.items():
            if col in data.columns:
                # Percentil-rank inom rullande fönster
                ranked = data[col].rolling(window=252, min_periods=20).rank(pct=True)
                score += w * ranked.fillna(0.5)
                total_weight += w

        if total_weight > 0:
            score /= total_weight

        # Signal: 1 om score över 60:e percentilen
        threshold = score.rolling(window=252, min_periods=20).quantile(0.6)
        signal[score > threshold] = 1
        signal[score < (1 - threshold.fillna(0.4))] = -1

        return signal

    def _multi_asset_signals(self, data: pd.DataFrame, prices: pd.DataFrame,
                              weights: dict, top_pct: float) -> pd.Series:
        """Hantera multi-asset signaler."""
        signals = pd.Series(0.0, index=prices.index)

        # Gruppera efter rebalansperioder
        rebalance_freq = self.params.get("rebalance_freq", "ME")
        groups = prices.resample(rebalance_freq)

        for _, group in groups:
            if group.empty:
                continue
            # Senaste raden i gruppen
            last_idx = group.index[-1]

            # Beräkna compositescore för varje tillgång
            scores = {}
            for col in prices.columns:
                asset_weight = 0.0
                total_w = 0.0
                for factor, w in weights.items():
                    if factor in data.columns:
                        val = data.loc[last_idx, factor] if last_idx in data.index else 50
                        asset_weight += w * val
                        total_w += w
                scores[col] = asset_weight / total_w if total_w > 0 else 50

            score_series = pd.Series(scores)
            n_top = max(1, int(len(score_series) * top_pct))
            top_assets = score_series.nlargest(n_top).index.tolist()

            # Sätt signal för hela gruppen
            for idx in group.index:
                for asset in top_assets:
                    signals.loc[idx] = 1.0 / n_top

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class TopNStrategy(Strategy):
    """
    Välj alltid de N högst rankade aktierna.
    För multi-asset data: skapa likaviktad portfölj av topp-N.

    Parametrar:
        n:               Antal aktier att välja (default 10)
        rebalance_freq:  Rebalanseringsfrekvens (default "weekly")
        score_column:    Kolumn att ranka på (default "score_total")
    """

    def __init__(self, name="TopNStrategy", params=None):
        params = params or {}
        params.setdefault("n", 10)
        params.setdefault("rebalance_freq", "weekly")
        params.setdefault("score_column", "score_total")
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        n = self.params["n"]
        score_col = self.params.get("score_column", "score_total")

        # Multi-asset med score-kolumn
        if isinstance(close, pd.DataFrame) and score_col in close.columns:
            signals = pd.Series(0.0, index=close.index)
            top_assets = close[score_col].nlargest(n).index.tolist()
            for asset in top_assets:
                if asset in close.columns:
                    signals += close[asset] * (1.0 / n)
            return signals

        # Single asset
        return pd.Series(1.0, index=close.index)

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class SectorRotationStrategy(Strategy):
    """
    Sektorrotation baserat på momentum.
    Väljer de sektorer med starkast momentum och allokerar kapital.

    Parametrar:
        sector_momentum: Dict med sektor -> momentumvärde
                         Alternativt: DataFrame med sektor-data
        top_sectors:     Antal sektorer att investera i (default 3)
        lookback:        Lookback för momentum (default 63 dagar)
    """

    def __init__(self, name="SectorRotationStrategy", params=None):
        params = params or {}
        params.setdefault("top_sectors", 3)
        params.setdefault("lookback", 63)
        params.setdefault("sector_momentum", {})
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        lookback = self.params["lookback"]
        top_sectors = self.params["top_sectors"]
        sector_momentum = self.params.get("sector_momentum", {})

        signals = pd.Series(0, index=close.index)

        # Om sektor-data finns i DataFrame
        if "sector" in data.columns and "ticker" in data.columns:
            # Beräkna momentum per sektor
            ret = close.pct_change(lookback)
            if isinstance(ret, pd.DataFrame):
                sector_ret = pd.DataFrame({"ret": ret.iloc[-1] if len(ret) > 0 else {},
                                           "sector": data["sector"]})
                top_sectors_found = sector_ret.groupby("sector")["ret"].mean().nlargest(top_sectors).index
                top_tickers = data[data["sector"].isin(top_sectors_found)]["ticker"].tolist()
                signals[:] = 1.0 / max(len(top_tickers), 1)
            return signals

        # Single asset: använd sektor-momentum om angivet
        if sector_momentum:
            sorted_sectors = sorted(sector_momentum.items(), key=lambda x: x[1], reverse=True)
            top = [s for s, _ in sorted_sectors[:top_sectors]]
            signals[:] = 1.0 if len(top) > 0 else 0

        return signals

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}


class FactorTimingStrategy(Strategy):
    """
    Faktor-timing baserat på marknadsregim.
    Ök/minska exponering mot olika faktorer beroende på regim.

    Parametrar:
        factors:       Dict med faktor-namn -> faktorinstans eller vikt
        regime_model:  Callable eller dict som mappar regim -> faktor-allokering
                       Ex: {"bull": {"momentum": 0.5, "value": 0.3, "quality": 0.2},
                            "bear": {"quality": 0.5, "low_beta": 0.3, "value": 0.2}}
        lookback_regime: Lookback för regim-detektion (default 252)
    """

    def __init__(self, name="FactorTimingStrategy", params=None):
        params = params or {}
        params.setdefault("factors", {})
        params.setdefault("regime_model", {})
        params.setdefault("lookback_regime", 252)
        super().__init__(name, params)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["Close"]
        lookback = self.params["lookback_regime"]
        regime_model = self.params.get("regime_model", {})
        factors = self.params.get("factors", {})

        # Detektera regim baserat på trend (MA200)
        if len(close) < lookback:
            return pd.Series(0, index=close.index)

        ma200 = close.rolling(200).mean()
        current_regime = "bull" if close.iloc[-1] > ma200.iloc[-1] else "bear"

        # Hämta faktor-allokering för aktuell regim
        allocation = regime_model.get(current_regime, {})
        if not allocation:
            # Default equal-weight
            n_factors = len(factors) if factors else 1
            weight = 1.0 / n_factors if n_factors > 0 else 1.0
            allocation = {f: weight for f in factors}

        # Skapa signal (viktad summa av faktorer)
        signal = pd.Series(0.0, index=close.index)
        for factor_name, factor_weight in allocation.items():
            factor_val = factors.get(factor_name, 50)
            if isinstance(factor_val, (int, float)):
                signal += factor_weight * (factor_val / 100.0)
            elif isinstance(factor_val, pd.Series):
                signal += factor_weight * factor_val.fillna(0.5)

        # Normalisera
        signal = signal.clip(-1, 1)

        return signal

    def calculate_metrics(self, data: pd.DataFrame, signals: pd.Series) -> dict:
        return {}
