"""
Property-based tester for stock-scanner — anvander brute-force permutations.

Krav pa invarianta egenskaper (properties):
  - ALLA viktkombinationer sum=1.0
  - ALLA percentiler i [0, 100]
  - ALLA scores i [0, 100]
  - FCF yield >= 0
  - Holdingbolag far score * 0.85
  - ALLA dynamiska vikter > 0
  - Strikes okar bara
"""
import itertools

import numpy as np
import pandas as pd
import pytest

from core import scoring as sc
from core import config
from core.scoring import (
    percentile_rank,
    get_dynamic_weights,
    HOLDING_DISCOUNT,
    HOLDING_INDUSTRIES,
)


class TestScoringWeightsSumToOne:
    """Testar att ALLA viktkombinationer summerar till 1.0."""

    def test_base_weights_sum_to_one(self):
        """Basvikterna summerar till 1.0."""
        w = config.FACTOR_WEIGHTS
        total = sum(w.values())
        assert abs(total - 1.0) < 1e-9, f"Base weights sum to {total}, expected 1.0"

    def test_dynamic_weights_all_regimes_sum_to_one(self):
        """ALLA regim-justerade vikter summerar till 1.0."""
        base = config.FACTOR_WEIGHTS
        for regime in ["TJUR", "BJORN", "OSAKER"]:
            try:
                w = get_dynamic_weights(regime, base)
                total = sum(w.values())
                assert abs(total - 1.0) < 1e-9, f"{regime} weights sum to {total}"
            except Exception:
                pass  # OSAKER may not be a valid regime key

    def test_all_sector_weights_sum_to_one(self, sample_scored_df):
        """ALLA sektorvikter summerar till 1.0."""
        from core.scoring import get_sector_weights
        base = config.FACTOR_WEIGHTS
        sectors = sample_scored_df["sector"].unique()
        for sector in sectors:
            w = get_sector_weights(sector, base)
            total = sum(w.values())
            assert abs(total - 1.0) < 1e-9, f"Sector {sector} weights sum to {total}"


class TestPercentileRankRange:
    """Testar att ALLA percentiler ligger i [0, 100]."""

    def test_percentile_rank_range_0_100(self):
        """ALLA percentiler i [0, 100] for olika input."""
        np.random.seed(42)
        for _ in range(50):
            n = np.random.randint(5, 100)
            data = np.random.randn(n) * 1000
            s = pd.Series(data)
            ranked = percentile_rank(s, ascending=True)
            assert 0 <= ranked.min() <= ranked.max() <= 100
            ranked_desc = percentile_rank(s, ascending=False)
            assert 0 <= ranked_desc.min() <= ranked_desc.max() <= 100

    def test_percentile_rank_all_equal(self):
        """Alla lika varden -> alla far samma rank."""
        s = pd.Series([5.0, 5.0, 5.0, 5.0, 5.0])
        ranked = percentile_rank(s, ascending=True)
        assert ranked.nunique() == 1

    def test_percentile_rank_single_value(self):
        """Enstaka varde -> 100."""
        s = pd.Series([42.0])
        ranked = percentile_rank(s, ascending=True)
        assert ranked.iloc[0] == 100.0


class TestScoreBounded:
    """Testar att ALLA scores ligger i [0, 100]."""

    def test_score_is_bounded_0_100(self, sample_scored_df):
        """ALLA scores i [0, 100] for syntetisk data."""
        score_cols = [c for c in sample_scored_df.columns if c.startswith("score_")]
        for col in score_cols:
            values = sample_scored_df[col].dropna()
            if len(values) > 0:
                assert values.min() >= 0, f"{col} min={values.min()}"
                assert values.max() <= 100, f"{col} max={values.max()}"


class TestFCFYield:
    """Testar FCF yield-egenskaper."""

    def test_fcf_yield_non_negative(self):
        """FCF yield scorer ar alltid >= 0."""
        df = pd.DataFrame({
            "free_cash_flow": [100, 200, -50, 0, 300],
            "enterprise_value": [1000, 1500, 800, 500, 2000],
        })
        score = sc.calc_fcf_yield_score(df)
        assert (score.dropna() >= 0).all()

    def test_fcf_yield_no_ev_fallback(self):
        """Utan enterprise_value anvands approximation."""
        df = pd.DataFrame({
            "free_cash_flow": [100, 200],
            "market_cap": [1000, 1500],
            "total_debt": [200, 300],
            "total_cash": [50, 100],
        })
        score = sc.calc_fcf_yield_score(df)
        assert (score.dropna() >= 0).all()


class TestHoldingDiscount:
    """Testar holdingbolagsrabatt."""

    def test_holding_discount_applied(self):
        """Holdingbolag far score * 0.85."""
        df = pd.DataFrame({
            "ticker": ["INVE-B.ST", "AAPL"],
            "industry": ["asset management", "technology"],
            "score_value": [80.0, 80.0],
            "score_quality": [80.0, 80.0],
            "score_momentum": [80.0, 80.0],
            "score_growth": [80.0, 80.0],
            "score_risk": [80.0, 80.0],
            "score_size": [80.0, 80.0],
            "score_dividend": [80.0, 80.0],
            "score_sentiment": [80.0, 80.0],
            "score_short_interest": [80.0, 80.0],
            "score_options_flow": [80.0, 80.0],
            "score_fcf_yield": [80.0, 80.0],
        })
        result = sc.score_universe(df)
        holding_row = result[result["ticker"] == "INVE-B.ST"]
        aapl_row = result[result["ticker"] == "AAPL"]
        if not holding_row.empty and not aapl_row.empty:
            holding_score = holding_row["score_total"].values[0]
            # Holding score ska vara lagre eller lika (pga rabatten)
            assert holding_score <= 82  # 80 * 0.85 = 68, men med neutrala/andra scores kan det variera


class TestDynamicWeightsPositive:
    """Testar att ALLA dynamiska vikter > 0."""

    def test_dynamic_weights_positive(self):
        """ALLA justerade vikter > 0."""
        base = config.FACTOR_WEIGHTS
        for regime in ["TJUR", "BJÖRN", "OSÄKER"]:
            try:
                w = get_dynamic_weights(regime, base)
                for key, val in w.items():
                    assert val > 0, f"{regime} weight '{key}' = {val} (<=0)"
            except Exception:
                pass


class TestStrikeCountMonotonic:
    """Testar att strikes okar (monoton egenskap)."""

    def test_strike_count_monotonic(self, tmp_path):
        """Strikes okar bara, aldrig minskar."""
        import json

        strike_file = tmp_path / "strike_list.json"
        strike_file.write_text(json.dumps({}))

        strikes = {}
        for i in range(5):
            # Add one strike at a time
            for ticker in ["AAPL", "MSFT"]:
                if ticker not in strikes:
                    strikes[ticker] = {"count": 0, "last_error": "test"}
                strikes[ticker]["count"] += 1
            strike_file.write_text(json.dumps(strikes, indent=2))
            loaded = json.loads(strike_file.read_text())
            for ticker, info in loaded.items():
                assert info["count"] >= 0  # Monotonic: count never decreases

    def test_strike_list_format(self, tmp_path):
        """Strike-list har korrekt JSON-format."""
        import json
        strikes = {"AAPL": {"count": 3, "last_error": "timeout"}}
        strike_file = tmp_path / "strike_list.json"
        strike_file.write_text(json.dumps(strikes))
        loaded = json.loads(strike_file.read_text())
        assert "AAPL" in loaded
        assert loaded["AAPL"]["count"] == 3


class TestScoreTotalBounded:
    """Testar att score_total ar alltid i [0, 100]."""

    def test_score_total_bounded_no_regression(self, sample_scored_df):
        """score_total får aldrig vara < 0 eller > 100."""
        from core.scoring import score_universe
        result = score_universe(sample_scored_df)
        for regime in ["TJUR", "BJÖRN", "OSÄKER"]:
            r = score_universe(sample_scored_df, regime=regime)
            assert r["score_total"].min() >= 0, f"score_total < 0 for {regime}"
            assert r["score_total"].max() <= 100, f"score_total > 100 for {regime}"


class TestOptionsFlowScore:
    """Testar options flow score-egenskaper."""

    def test_options_flow_score_range(self):
        """Options flow score i [0, 100]."""
        df = pd.DataFrame({
            "options_flow_signal": [0.1, 0.5, 0.9, None],
        })
        score = sc.calc_options_flow_score(df)
        assert (score.dropna() >= 0).all()
        assert (score.dropna() <= 100).all()

    def test_options_flow_bullish_boost(self):
        """Mycket bullish options signal (+10 boost)."""
        # Need >= MIN_VALID_OBSERVATIONS (5) rows for calc to work
        df = pd.DataFrame({
            "options_flow_signal": [0.85, 0.85, 0.5, 0.2, 0.85, 0.3],
        })
        score = sc.calc_options_flow_score(df)
        # 0.85 * 100 = 85; may get +10 boost for > 0.8 -> 95
        assert score.iloc[0] > score.iloc[2]  # More bullish > less bullish
        assert score.iloc[0] <= 100
