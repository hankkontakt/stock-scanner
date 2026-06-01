"""
Test: scoring.py
================
Testar alla faktorscorer, hjälpfunktioner och region-neutralisering.

Dessa tester använder enbart syntetisk data -- inga API-anrop eller filer.
All scoring är pure functions (DataFrame -> DataFrame/Series).

Kör med:
    pytest tests/test_scoring.py -v --tb=short

VIKTIGT: Många scorers använder _try_rank() som kräver
MIN_VALID_OBSERVATIONS (5) observationer för att returnera en rank.
Tester med < 5 rader får därför neutral score (50) istället.
"""

import numpy as np
import pandas as pd
import pytest

from core import scoring as sc


# ══════════════════════════════════════════════════════════════════════════════
# HJÄLPFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════


class TestHelpers:
    """Testar _assign_exchange_group, percentile_rank, winsorize m.fl."""

    def test_assign_exchange_group_us(self):
        """US-tickers (inga suffix) -> US."""
        assert sc._assign_exchange_group("AAPL") == "US"
        assert sc._assign_exchange_group("MSFT") == "US"
        assert sc._assign_exchange_group("NVDA") == "US"

    def test_assign_exchange_group_nordic(self):
        """Nordiska suffix -> Nordic."""
        assert sc._assign_exchange_group("VOLV-B.ST") == "Nordic"
        assert sc._assign_exchange_group("NOVO-B.CO") == "Nordic"
        assert sc._assign_exchange_group("EQNR.OL") == "Nordic"
        assert sc._assign_exchange_group("NOKIA.HE") == "Nordic"

    def test_assign_exchange_group_europe(self):
        """Europeiska suffix -> Europe."""
        assert sc._assign_exchange_group("SAP.DE") == "Europe"
        assert sc._assign_exchange_group("AIR.PA") == "Europe"
        assert sc._assign_exchange_group("ULVR.L") == "UK"

    def test_assign_exchange_group_asia(self):
        """Asiatiska suffix."""
        assert sc._assign_exchange_group("7203.T") == "Japan"
        assert sc._assign_exchange_group("9988.HK") == "Asia"
        assert sc._assign_exchange_group("2330.TW") == "Asia"
        assert sc._assign_exchange_group("005930.KS") == "Asia"

    def test_assign_exchange_group_case_insensitive(self):
        """Ska fungera oavsett case."""
        assert sc._assign_exchange_group("volv-b.st") == "Nordic"

    def test_percentile_rank_ascending(self):
        """percentile_rank ascending: högre värde = högre rank."""
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0])
        ranked = sc.percentile_rank(s, ascending=True)
        assert 0 <= ranked.min() <= ranked.max() <= 100
        assert ranked.iloc[4] == ranked.max()

    def test_percentile_rank_descending(self):
        """percentile_rank descending: lägre värde = högre rank."""
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0])
        ranked = sc.percentile_rank(s, ascending=False)
        assert ranked.iloc[0] == ranked.max()

    def test_percentile_rank_all_equal(self):
        """Alla lika värden -> alla får samma rank."""
        s = pd.Series([5.0, 5.0, 5.0])
        ranked = sc.percentile_rank(s, ascending=True)
        assert ranked.nunique() == 1

    def test_winsorize_clips_extremes(self):
        """winsorize cappar extremvärden."""
        s = pd.Series(list(range(100)) + [10_000, -10_000])
        wins = sc.winsorize(s)
        assert wins.max() < 10_000
        assert wins.min() > -10_000

    def test_winsorize_all_nan(self):
        """Alla NaN -> returneras oförändrat."""
        s = pd.Series([np.nan, np.nan, np.nan])
        result = sc.winsorize(s)
        assert result.isna().all()

    def test_neutral_series(self):
        """_neutral_series returnerar 50.0 för alla entries."""
        s = sc._neutral_series(pd.Index(["A", "B", "C"]))
        assert (s == 50.0).all()

    def test_get_dynamic_weights_bull(self):
        """TJUR-regim: momentum+growth ökar, risk minskar."""
        base = {"momentum": 0.18, "growth": 0.13, "risk": 0.09, "value": 0.22}
        w = sc.get_dynamic_weights("TJUR", base)
        assert abs(sum(w.values()) - 1.0) < 0.001
        assert w["momentum"] > base["momentum"]
        assert w["risk"] < base["risk"]

    def test_get_dynamic_weights_bear(self):
        """BJÖRN-regim: quality+risk+value ökar, momentum minskar."""
        base = {"momentum": 0.18, "quality": 0.18, "risk": 0.09, "value": 0.22, "growth": 0.13}
        w = sc.get_dynamic_weights("BJÖRN", base)
        assert abs(sum(w.values()) - 1.0) < 0.001
        assert w["quality"] > base["quality"]
        assert w["momentum"] < base["momentum"]

    def test_get_dynamic_weights_uncertain(self):
        """OSÄKER-regim: base weights normaliserade till 1.0."""
        base = {"momentum": 0.18, "value": 0.22, "quality": 0.18}
        w = sc.get_dynamic_weights("OSÄKER", base)
        assert abs(sum(w.values()) - 1.0) < 0.001


class TestExchangeGroups:
    """Testar _add_exchange_groups och _region_neutralize_fundamentals."""

    def test_add_exchange_groups_from_column(self):
        """Lägger till exchange_group från ticker-kolumn."""
        df = pd.DataFrame({"ticker": ["AAPL", "VOLV-B.ST", "SAP.DE"]})
        result = sc._add_exchange_groups(df)
        assert list(result["exchange_group"]) == ["US", "Nordic", "Europe"]

    def test_region_neutralize_subtracts_median(self):
        """Region-neutralisering subtraherar regionmedian."""
        df = pd.DataFrame({
            "ticker": ["US1", "US2", "NORDIC1.ST", "NORDIC2.ST"],
            "pe_trailing": [25.0, 35.0, 15.0, 13.0],
            "roe": [0.20, 0.25, 0.12, 0.14],
        })
        result = sc._region_neutralize_fundamentals(df)
        # Båda regionernas median borde vara nära 0 efter justering
        for grp in ["US", "Nordic"]:
            subset = result[result["exchange_group"] == grp]
            assert abs(subset["pe_trailing"].median()) < 1.0

    def test_region_neutralize_ignores_momentum(self):
        """Momentum-kolumner (return_*) neutraliseras INTE."""
        df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT", "VOLV-B.ST", "ERIC-B.ST"],
            "return_12m": [0.5, 0.4, 0.3, 0.2],
        })
        original = df["return_12m"].copy()
        result = sc._region_neutralize_fundamentals(df)
        pd.testing.assert_series_equal(result["return_12m"], original)


# ══════════════════════════════════════════════════════════════════════════════
# FAKTORSCORER -- kräver >=5 rader pga MIN_VALID_OBSERVATIONS
# ══════════════════════════════════════════════════════════════════════════════


class _FactorTestHelper:
    """Gör en enkel DataFrame med n rader som är tydligt rangordnad.
    Varje subklass lägger till sina egna kolumner."""

    N = 6

    @classmethod
    def _make_base(cls) -> pd.DataFrame:
        return pd.DataFrame({
            "ticker": [f"T{i}" for i in range(cls.N)],
            "pe_trailing": [8, 12, 15, 20, 25, 35],
            "pe_forward": [7, 11, 14, 19, 24, 33],
            "price_to_book": [0.8, 1.2, 1.5, 2.0, 3.0, 4.0],
            "price_to_sales": [0.5, 0.8, 1.0, 1.5, 2.5, 4.0],
            "ev_to_ebitda": [4, 6, 8, 10, 14, 20],
            "roe": [0.30, 0.25, 0.20, 0.15, 0.10, 0.05],
            "roa": [0.15, 0.12, 0.10, 0.08, 0.04, 0.01],
            "profit_margin": [0.25, 0.20, 0.15, 0.10, 0.05, 0.01],
            "operating_margin": [0.30, 0.25, 0.18, 0.12, 0.06, 0.02],
            "gross_margin": [0.70, 0.60, 0.50, 0.40, 0.30, 0.15],
            "return_12m": [0.50, 0.30, 0.15, 0.00, -0.15, -0.30],
            "return_6m": [0.30, 0.20, 0.10, 0.00, -0.10, -0.20],
            "return_3m": [0.15, 0.10, 0.05, 0.00, -0.08, -0.15],
            "pct_from_52w_high": [-0.02, -0.05, -0.10, -0.15, -0.25, -0.40],
            "revenue_growth": [0.30, 0.20, 0.15, 0.10, 0.00, -0.10],
            "earnings_growth": [0.40, 0.25, 0.15, 0.05, -0.05, -0.20],
            "earnings_quarterly_growth": [0.25, 0.15, 0.10, 0.05, -0.02, -0.10],
            "debt_to_equity": [0.1, 0.3, 0.5, 1.0, 2.0, 4.0],
            "current_ratio": [3.5, 2.5, 2.0, 1.5, 1.0, 0.5],
            "volatility": [0.12, 0.15, 0.20, 0.25, 0.35, 0.50],
            "beta": [0.6, 0.8, 1.0, 1.2, 1.5, 2.0],
            "market_cap": [1e12, 5e11, 1e11, 5e10, 1e10, 1e9],
            "dividend_yield": [0.06, 0.04, 0.03, 0.02, 0.01, 0.001],
            "free_cash_flow": [500, 300, 100, 50, 10, -50],
            "enterprise_value": [2000, 2000, 1000, 1000, 500, 500],
            "sentiment_raw": [0.8, 0.5, 0.2, 0.0, -0.3, -0.6],
            "payout_ratio": [0.3, 0.4, 0.5, 0.6, 1.5, 2.0],
            "avg_volume_10d": [10_000_000, 5_000_000, 1_000_000, 500_000, 100_000, 10_000],
            "current_price": [200, 150, 100, 50, 20, 10],
            "industry": ["Tech", "Tech", "Finance", "Finance", "Healthcare", "Healthcare"],
        })


class TestValueScore:
    """Testar calc_value_score inklusive FCF-flöde och fallback."""

    def test_value_score_with_fcf(self):
        """FCF Yield + EV/EBITDA -> rankad score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_value_score(df)
        assert scores.between(0, 100).all()
        assert scores.isna().sum() == 0

    def test_value_score_fallback_no_fcf(self):
        """När FCF saknas -> fallback till P/E/PB/PS."""
        df = _FactorTestHelper._make_base().drop(columns=["free_cash_flow", "enterprise_value"])
        scores = sc.calc_value_score(df)
        assert scores.between(0, 100).all()
        assert scores.isna().sum() == 0

    def test_value_score_preserves_ordering(self):
        """Lägre multiplar borde generellt ge högre value-score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_value_score(df)
        # T0 har lägst P/E, högst FCF -> bör ha högst value score (ascending=False på P/E)
        assert scores.iloc[0] > scores.iloc[-1]

    def test_value_score_all_missing_fcf_and_ev(self):
        """All data saknas -> neutral score (50)."""
        df = pd.DataFrame({
            "pe_forward": [np.nan, np.nan],
            "pe_trailing": [np.nan, np.nan],
            "price_to_book": [np.nan, np.nan],
            "price_to_sales": [np.nan, np.nan],
            "ev_to_ebitda": [np.nan, np.nan],
        })
        scores = sc.calc_value_score(df)
        assert (scores == 50.0).all()


class TestFcfYieldScore:
    """Testar calc_fcf_yield_score."""

    def test_fcf_yield_basic(self):
        """Högre FCF/EV -> högre score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_fcf_yield_score(df)
        assert scores.between(0, 100).all()
        assert scores.notna().all()

    def test_fcf_yield_fallback_ev_approximation(self):
        """När enterprise_value saknas -> approximera från MC+debt-cash."""
        df = _FactorTestHelper._make_base().drop(columns=["enterprise_value"])
        df["total_debt"] = [500] * len(df)
        df["total_cash"] = [200] * len(df)
        scores = sc.calc_fcf_yield_score(df)
        assert scores.notna().all()

    def test_fcf_yield_no_fcf_returns_neutral(self):
        """free_cash_flow saknas -> neutral."""
        df = pd.DataFrame({"ticker": ["A"]})
        scores = sc.calc_fcf_yield_score(df)
        assert (scores == 50.0).all()


class TestQualityScore:
    """Testar calc_quality_score."""

    def test_quality_score_basic(self):
        """Högre ROE/marginaler -> högre quality score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_quality_score(df)
        assert scores.between(0, 100).all()
        assert scores.iloc[0] > scores.iloc[-1]

    def test_quality_score_no_columns(self):
        """Inga quality-kolumner -> neutral."""
        df = pd.DataFrame({"ticker": ["A", "B"]})
        assert (sc.calc_quality_score(df) == 50.0).all()


class TestMomentumScore:
    """Testar calc_momentum_score."""

    def test_momentum_basic(self):
        """Högre avkastning -> högre momentum score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_momentum_score(df)
        assert scores.between(0, 100).all()
        assert scores.iloc[0] > scores.iloc[-1]

    def test_momentum_no_data(self):
        """Inga return-kolumner -> neutral."""
        df = pd.DataFrame({"ticker": ["A", "B"]})
        assert (sc.calc_momentum_score(df) == 50.0).all()


class TestGrowthScore:
    """Testar calc_growth_score."""

    def test_growth_basic(self):
        """Högre tillväxt -> högre growth score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_growth_score(df)
        assert scores.between(0, 100).all()
        assert scores.iloc[0] > scores.iloc[-1]

    def test_growth_no_columns(self):
        """Inga growth-kolumner -> neutral."""
        df = pd.DataFrame({"ticker": ["A"]})
        assert (sc.calc_growth_score(df) == 50.0).all()


class TestRiskScore:
    """Testar calc_risk_score."""

    def test_risk_basic(self):
        """Lägre skuldsättning/volatilitet -> högre risk score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_risk_score(df)
        assert scores.between(0, 100).all()
        assert scores.iloc[0] > scores.iloc[-1]

    def test_risk_negative_debt_handled(self):
        """Negativ D/E (net cash) -> hanteras utan fel."""
        df = _FactorTestHelper._make_base().copy()
        df["debt_to_equity"] = [-0.5, -0.3, 0.0, 0.5, 1.0, 2.0]
        scores = sc.calc_risk_score(df)
        assert scores.between(0, 100).all()

    def test_risk_no_columns(self):
        """Inga risk-kolumner -> neutral."""
        df = pd.DataFrame({"ticker": ["A", "B"]})
        assert (sc.calc_risk_score(df) == 50.0).all()


class TestSizeScore:
    """Testar calc_size_score."""

    def test_smaller_is_higher(self):
        """Mindre market cap -> högre size score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_size_score(df)
        assert scores.between(0, 100).all()
        # Minst bolag (T5) ska ha högst score
        assert scores.iloc[-1] > scores.iloc[0]

    def test_size_no_market_cap(self):
        """Inget market_cap -> neutral."""
        df = pd.DataFrame({"ticker": ["A"]})
        assert (sc.calc_size_score(df) == 50.0).all()


class TestDividendScore:
    """Testar calc_dividend_score."""

    def test_dividend_basic(self):
        """Högre yield -> högre dividend score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_dividend_score(df)
        assert scores.between(0, 100).all()
        assert scores.iloc[0] > scores.iloc[-1]

    def test_dividend_no_data(self):
        """Ingen dividend_yield -> neutral."""
        df = pd.DataFrame({"ticker": ["A"]})
        assert (sc.calc_dividend_score(df) == 50.0).all()


class TestSentimentScore:
    """Testar calc_sentiment_score."""

    def test_sentiment_basic(self):
        """Positivt sentiment -> högre score."""
        df = _FactorTestHelper._make_base()
        scores = sc.calc_sentiment_score(df)
        assert scores.between(0, 100).all()
        assert scores.iloc[0] > scores.iloc[-1]

    def test_sentiment_no_data(self):
        """sentiment_raw saknas -> neutral (men insider-boost kan fortfarande verka)."""
        df = pd.DataFrame({"ticker": ["A", "B"]})
        scores = sc.calc_sentiment_score(df)
        assert (scores == 50.0).all()

    def test_sentiment_insider_boost(self):
        """Insider executive buy -> boost på +20 (cappad vid 95)."""
        df = _FactorTestHelper._make_base().copy()
        df["insider_executive_buy"] = [True, True, False, False, False, False]
        scores = sc.calc_sentiment_score(df)
        # Insider-boostade rader ska ha högre score
        assert scores.iloc[0] > scores.iloc[2]

    def test_sentiment_insider_cluster_boost(self):
        """Cluster-köp -> boost på +30 (cappad vid 98)."""
        df = _FactorTestHelper._make_base().copy()
        df["insider_cluster"] = [True, True, False, False, False, False]
        df["insider_executive_buy"] = [False] * len(df)
        scores = sc.calc_sentiment_score(df)
        assert scores.iloc[0] > scores.iloc[2]


class TestInsiderDecay:
    """Testar _insider_decay_weight."""

    def test_insider_decay_fresh_full_weight(self):
        """Ny insider (0 dagar) -> weight = 1.0."""
        df = pd.DataFrame({
            "insider_recent_date": [pd.Timestamp.now().strftime("%Y-%m-%d")],
        })
        assert sc._insider_decay_weight(df).iloc[0] == 1.0

    def test_insider_decay_old_zero_weight(self):
        """Gammal insider (>=180 dagar) -> weight = 0.0."""
        df = pd.DataFrame({
            "insider_recent_date": [(pd.Timestamp.now() - pd.Timedelta(days=200)).strftime("%Y-%m-%d")],
        })
        assert sc._insider_decay_weight(df).iloc[0] == 0.0

    def test_insider_decay_no_date_fallback(self):
        """Inget datum -> weight = 1.0 (bakåtkompatibelt)."""
        df = pd.DataFrame({"ticker": ["A"]})
        assert sc._insider_decay_weight(df).iloc[0] == 1.0


# ══════════════════════════════════════════════════════════════════════════════
# HUVUDFUNKTIONER
# ══════════════════════════════════════════════════════════════════════════════


class TestScoreUniverse:
    """Testar score_universe -- hela pipeline-flödet."""

    def test_score_universe_returns_expected_columns(self):
        """score_universe lägger till alla score-kolumner."""
        df = _FactorTestHelper._make_base()
        result = sc.score_universe(df)
        expected = [
            "score_value", "score_quality", "score_momentum",
            "score_growth", "score_risk", "score_size",
            "score_dividend", "score_sentiment", "score_fcf_yield",
            "score_total", "rank", "data_quality", "exchange_group",
        ]
        for col in expected:
            assert col in result.columns, f"Saknar kolumn: {col}"

    def test_score_universe_scores_in_range(self):
        """Alla score-kolumner är 0-100."""
        df = _FactorTestHelper._make_base()
        result = sc.score_universe(df)
        score_cols = [c for c in result.columns if c.startswith("score_")]
        for col in score_cols:
            vals = result[col].dropna()
            assert vals.between(0, 100).all(), f"{col} har värden utanför 0-100: {vals.tolist()}"

    def test_score_total_is_weighted_average(self):
        """score_total är ett viktat medelvärde och ligger inom faktorspannet."""
        df = _FactorTestHelper._make_base()
        result = sc.score_universe(df)
        factor_cols = ["score_value", "score_quality", "score_momentum",
                       "score_growth", "score_risk", "score_size",
                       "score_dividend", "score_sentiment"]
        # Jämför bara rader där alla faktorvärden finns
        valid = result[factor_cols].notna().all(axis=1)
        factor_min = result.loc[valid, factor_cols].min(axis=1)
        factor_max = result.loc[valid, factor_cols].max(axis=1)
        total = result.loc[valid, "score_total"]
        assert (total >= factor_min).all()
        assert (total <= factor_max).all()

    def test_score_universe_rank_is_monotonic(self):
        """Högre score_total -> lägre rank (1 = bäst)."""
        df = _FactorTestHelper._make_base()
        result = sc.score_universe(df)
        # Ta bort rader med NaN score_total (extremfallen kan få NaN)
        valid = result.dropna(subset=["score_total"])
        sorted_by_score = valid.sort_values("score_total", ascending=False)
        expected_ranks = list(range(1, len(sorted_by_score) + 1))
        assert list(sorted_by_score["rank"]) == expected_ranks, \
            f"Ranks: {list(sorted_by_score['rank'])} != {expected_ranks}"

    def test_score_universe_data_quality(self):
        """data_quality reflekterar andelen ifyllda fält."""
        df = _FactorTestHelper._make_base()
        # Sätt en rad till NaN i viktiga kolumner
        df.loc[0, "pe_trailing":"roe"] = np.nan
        result = sc.score_universe(df)
        assert result["data_quality"].iloc[0] < result["data_quality"].iloc[1]

    def test_score_universe_exchange_group_assignment(self):
        """exchange_group sätts korrekt baserat på ticker-suffix."""
        df = _FactorTestHelper._make_base()
        df.loc[0, "ticker"] = "AAPL"
        df.loc[1, "ticker"] = "VOLV-B.ST"
        df.loc[2, "ticker"] = "SAP.DE"
        result = sc.score_universe(df)
        assert result.loc[result["ticker"] == "AAPL", "exchange_group"].iloc[0] == "US"
        assert result.loc[result["ticker"] == "VOLV-B.ST", "exchange_group"].iloc[0] == "Nordic"
        assert result.loc[result["ticker"] == "SAP.DE", "exchange_group"].iloc[0] == "Europe"

    def test_score_universe_missing_columns(self):
        """DataFrame med minimal data -> scores 0-100 med neutrala fallbacks."""
        df = pd.DataFrame({
            "ticker": ["AAPL", "MSFT", "GOOG", "NVDA", "META", "TSLA"],
            "ev_to_ebitda": [15, 20, 18, 25, 12, 30],
            "pe_forward": [20, 25, 22, 30, 18, 35],
            "pe_trailing": [18, 23, 20, 28, 16, 33],
            "price_to_book": [5, 4, 6, 7, 3, 8],
            "price_to_sales": [2, 3, 4, 5, 1.5, 6],
            "industry": ["Tech"] * 6,
        })
        result = sc.score_universe(df)
        assert "score_total" in result.columns
        for col in [c for c in result.columns if c.startswith("score_")]:
            vals = result[col].dropna()
            assert vals.between(0, 100).all(), f"{col} utanför range"


class TestScoreUniverseSectorNeutralized:
    """Testar score_universe_sector_neutralized."""

    def test_sector_neutralized_has_all_columns(self):
        """score_universe_sector_neutralized har förväntade kolumner."""
        df = _FactorTestHelper._make_base()
        result = sc.score_universe_sector_neutralized(df)
        for col in ["score_total", "rank", "low_liquidity", "score_value"]:
            assert col in result.columns

    def test_sector_neutralized_sorted_by_score(self):
        """score_universe_sector_neutralized sorterar på score_total fallande."""
        df = _FactorTestHelper._make_base()
        result = sc.score_universe_sector_neutralized(df)
        valid = result.dropna(subset=["score_total"])
        assert valid["score_total"].is_monotonic_decreasing


class TestHoldingCommodityDiscount:
    """Testar rabatter för holding- och råvarubolag."""

    def test_holding_discount_applied(self):
        """Holdingbolag får 15% rabatt efter scoring.
        Vi skapar ett holdingbolag med IDENTISKA fundamentals som ett vanligt
        bolag, så den enda skillnaden är rabatten."""
        base = _FactorTestHelper._make_base()
        # Rad 0 = holding, Rad 1 = normal (identiska)
        base.loc[0, "ticker"] = "HOLD"
        base.loc[0, "industry"] = "Asset Management"
        # Gör rad 1 identisk med rad 0 (så den enda skillnaden är industry)
        for col in base.columns:
            if col not in ("ticker", "industry"):
                base.loc[1, col] = base.loc[0, col]
        base.loc[1, "ticker"] = "NORMAL"
        base.loc[1, "industry"] = "Technology"
        result = sc.score_universe(base)
        holding = result.loc[result["ticker"] == "HOLD", "score_total"].iloc[0]
        normal = result.loc[result["ticker"] == "NORMAL", "score_total"].iloc[0]
        assert holding == pytest.approx(normal * 0.85, rel=0.01), \
            f"Holding {holding:.2f} borde vara ~{normal * 0.85:.2f}"

    def test_commodity_discount_applied(self):
        """Råvarubolag får 10% rabatt efter scoring."""
        base = _FactorTestHelper._make_base()
        base.loc[0, "ticker"] = "GOLD"
        base.loc[0, "industry"] = "Gold"
        for col in base.columns:
            if col not in ("ticker", "industry"):
                base.loc[1, col] = base.loc[0, col]
        base.loc[1, "ticker"] = "NORMAL"
        base.loc[1, "industry"] = "Technology"
        result = sc.score_universe(base)
        gold = result.loc[result["ticker"] == "GOLD", "score_total"].iloc[0]
        normal = result.loc[result["ticker"] == "NORMAL", "score_total"].iloc[0]
        assert gold == pytest.approx(normal * 0.90, rel=0.01), \
            f"Gold {gold:.2f} borde vara ~{normal * 0.90:.2f}"

    def test_company_type_tracking(self):
        """score_universe sätter company_type korrekt."""
        df = _FactorTestHelper._make_base()
        df.loc[0, "industry"] = "Asset Management"
        df.loc[1, "industry"] = "Gold"
        result = sc.score_universe(df)
        assert result["company_type"].iloc[0] == "holding"
        assert result["company_type"].iloc[1] == "commodity"
        assert result["company_type"].iloc[2] == "standard"


class TestSectorRelativeScoring:
    """Testar sektor-relativ scoring: per-sektor-vikter + sektor-neutralisering."""

    def test_get_sector_weights_adjusts_financials(self):
        """Banker ska vikta kvalitet/värde högre och tillväxt lägre än default."""
        from core import config
        base = config.FACTOR_WEIGHTS
        bank_w = sc.get_sector_weights("Financial Services", base)
        assert bank_w["quality"] > base["quality"]
        assert bank_w["growth"] < base["growth"]
        assert abs(sum(bank_w.values()) - 1.0) < 1e-6  # normaliserad

    def test_get_sector_weights_unknown_sector_unchanged(self):
        """Okänd sektor -> basvikterna oförändrade."""
        from core import config
        base = config.FACTOR_WEIGHTS
        assert sc.get_sector_weights("Nonexistent Sector", base) == base

    def test_sector_neutralized_does_not_punish_bank_leverage(self):
        """Banker ska inte kollektivt straffas för normal (hög) hävstång."""
        rows = []
        for i in range(4):
            rows.append(dict(ticker=f"BANK{i}", sector="Financial Services",
                industry="Banks", pe_trailing=10 + i, price_to_book=1.0,
                debt_to_equity=3.0, roe=0.13, return_12m=0.1, return_6m=0.05,
                return_3m=0.02, current_ratio=1.2, volatility=0.18, beta=0.9,
                market_cap=1e10, current_price=100, avg_volume_10d=1e6,
                sentiment_raw=0.1, revenue_growth=0.03, earnings_growth=0.04,
                dividend_yield=0.04, profit_margin=0.2))
        for i in range(4):
            rows.append(dict(ticker=f"TECH{i}", sector="Technology",
                industry="Software", pe_trailing=35 + i, price_to_book=6.0,
                debt_to_equity=0.2, roe=0.18, return_12m=0.4, return_6m=0.2,
                return_3m=0.1, current_ratio=2.5, volatility=0.4, beta=1.5,
                market_cap=5e10, current_price=200, avg_volume_10d=5e6,
                sentiment_raw=0.3, revenue_growth=0.3, earnings_growth=0.3,
                dividend_yield=0.0, profit_margin=0.25))
        df = pd.DataFrame(rows)
        out = sc.score_universe_sector_neutralized(df, regime="OSÄKER")
        bank_risk = out[out.sector == "Financial Services"]["score_risk"].mean()
        # Bankerna har låg volatilitet/beta och sektor-normal skuld -> risk-score ej kollektivt låg
        assert bank_risk > 40, f"Banker straffas fortfarande för hävstång (risk={bank_risk:.0f})"
        assert out["score_total"].between(0, 100).all()

    def test_neutralization_is_idempotent(self):
        """Re-scoring (morning/evening på sparad CSV) får INTE dubbel-neutralisera."""
        df = _FactorTestHelper._make_base()
        r1 = sc.score_universe(df)
        assert "_fundamentals_neutralized" in r1.columns
        pe1 = r1["pe_trailing"].tolist()
        r2 = sc.score_universe(r1.copy())   # simulerar morning re-score
        pe2 = r2["pe_trailing"].tolist()
        for a, b in zip(pe1, pe2):
            if a == a and b == b:  # ej NaN
                assert abs(a - b) < 1e-9, "fundamentals dubbel-neutraliserades"
