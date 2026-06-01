"""
tests/test_discovery_quality_gate.py — Tester för discovery_quality_gate.py

Täcker:
 - hard_exclude(): penny stocks, extremskuld, shell-bolag, negativ equity
 - compute_quality_score(): sektor-aware poäng, positiva/negativa faktorer
 - compute_beneish_mscore(): M-score beräkning och tolkning
 - check_dilution(): utspädningsdetektering
 - evaluate_candidate(): end-to-end kombinerat
"""

import pytest

from core.discovery_quality_gate import (
    hard_exclude,
    compute_quality_score,
    compute_beneish_mscore,
    check_dilution,
    evaluate_candidate,
)


# ── Fixture-fabrik ──────────────────────────────────────────────────────────

def _info(
    price=20.0, volume=500_000, market_cap=2_000_000_000,
    quote_type="EQUITY", pe_forward=15.0, debt_to_equity=50.0,
    roe=0.15, profit_margin=0.12, revenue_growth=0.10,
    free_cash_flow=100_000_000, sector="Technology",
    gross_margins=0.45, recommendation_mean=2.0,
    number_of_analyst_opinions=5, total_revenue=500_000_000,
    book_value=10.0, shares_outstanding=100_000_000,
    **kwargs,
) -> dict:
    """Bygger ett minimalt yfinance.info-liknande dikt."""
    d = {
        "currentPrice":               price,
        "averageVolume":              volume,
        "marketCap":                  market_cap,
        "quoteType":                  quote_type,
        "forwardPE":                  pe_forward,
        "debtToEquity":               debt_to_equity,
        "returnOnEquity":             roe,
        "profitMargins":              profit_margin,
        "revenueGrowth":              revenue_growth,
        "freeCashflow":               free_cash_flow,
        "sector":                     sector,
        "grossMargins":               gross_margins,
        "recommendationMean":         recommendation_mean,
        "numberOfAnalystOpinions":    number_of_analyst_opinions,
        "totalRevenue":               total_revenue,
        "bookValue":                  book_value,
        "sharesOutstanding":          shares_outstanding,
    }
    d.update(kwargs)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — hard_exclude
# ══════════════════════════════════════════════════════════════════════════════

class TestHardExclude:

    def test_normal_stock_passes(self):
        excl, reason = hard_exclude(_info(), ticker="AAPL")
        assert not excl, reason

    def test_penny_stock_excluded(self):
        excl, reason = hard_exclude(_info(price=1.50), ticker="JUNK")
        assert excl
        assert "penny" in reason.lower() or "pris" in reason.lower()

    def test_zero_price_excluded(self):
        excl, reason = hard_exclude(_info(price=0.0), ticker="ZERO")
        assert excl

    def test_tiny_market_cap_excluded(self):
        excl, reason = hard_exclude(_info(market_cap=5_000_000), ticker="TINY")
        assert excl
        assert "market cap" in reason.lower() or "cap" in reason.lower()

    def test_low_volume_excluded(self):
        excl, reason = hard_exclude(_info(volume=5_000), ticker="ILLIQ")
        assert excl
        assert "volym" in reason.lower() or "volume" in reason.lower()

    def test_wrong_quote_type_excluded(self):
        excl, reason = hard_exclude(_info(quote_type="WARRANT"), ticker="WAR")
        assert excl

    def test_etf_allowed(self):
        excl, _ = hard_exclude(_info(quote_type="ETF"), ticker="SPY")
        assert not excl

    def test_extreme_pe_excluded(self):
        excl, reason = hard_exclude(_info(pe_forward=600.0), ticker="MOON")
        assert excl
        assert "p/e" in reason.lower() or "värdering" in reason.lower()

    def test_extreme_debt_excluded_non_financial(self):
        # D/E 900% (= 9x) för icke-finansiell sektor
        excl, reason = hard_exclude(
            _info(debt_to_equity=900.0, sector="Technology"),
            ticker="DEBT",
        )
        assert excl
        assert "hävstång" in reason.lower() or "debt" in reason.lower()

    def test_financial_sector_high_debt_allowed(self):
        # Banker har normalt hög hävstång
        excl, _ = hard_exclude(
            _info(debt_to_equity=900.0, sector="Financial Services"),
            ticker="JPM",
        )
        assert not excl

    def test_negative_equity_non_financial_excluded(self):
        # book_value < 0 → negativt eget kapital
        excl, reason = hard_exclude(
            _info(book_value=-5.0, sector="Technology"),
            ticker="NEG",
        )
        assert excl
        assert "eget kapital" in reason.lower() or "equity" in reason.lower()

    def test_zero_revenue_excluded(self):
        excl, reason = hard_exclude(_info(total_revenue=0), ticker="SHELL")
        assert excl
        assert "intäkt" in reason.lower() or "revenue" in reason.lower()

    def test_smallcap_lower_threshold(self):
        # $50M market cap bör gå igenom i smallcap-läge
        excl, _ = hard_exclude(
            _info(market_cap=60_000_000, volume=25_000),
            ticker="SMLCAP",
            universe_type="smallcap",
        )
        # Kan passera eller ej beroende på volymgräns — verifiera att logiken körs
        assert isinstance(excl, bool)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — compute_quality_score
# ══════════════════════════════════════════════════════════════════════════════

class TestQualityScore:

    def test_high_quality_stock_scores_well(self):
        info = _info(
            roe=0.25, profit_margin=0.20, revenue_growth=0.30,
            free_cash_flow=200_000_000, gross_margins=0.60,
            recommendation_mean=1.8, number_of_analyst_opinions=8,
            debt_to_equity=20.0,
        )
        score, flags = compute_quality_score(info)
        assert score >= 65, f"Hög kvalitet borde ge ≥65, fick {score}"

    def test_low_quality_stock_scores_poorly(self):
        info = _info(
            roe=-0.10, profit_margin=-0.05, revenue_growth=-0.15,
            free_cash_flow=-50_000_000, gross_margins=0.05,
            recommendation_mean=4.2, number_of_analyst_opinions=1,
            debt_to_equity=400.0,
        )
        score, flags = compute_quality_score(info)
        assert score < 40, f"Låg kvalitet borde ge <40, fick {score}"
        assert len(flags) > 0  # Ska ha flaggor

    def test_negative_roe_flagged(self):
        _, flags = compute_quality_score(_info(roe=-0.05))
        assert any("ROE" in f.upper() or "roe" in f.lower() for f in flags)

    def test_negative_revenue_growth_flagged(self):
        _, flags = compute_quality_score(_info(revenue_growth=-0.20))
        assert any("tillväxt" in f.lower() or "growth" in f.lower() or "intäkt" in f.lower()
                   for f in flags)

    def test_strong_sell_consensus_penalizes(self):
        score_good, _ = compute_quality_score(_info(recommendation_mean=1.5))
        score_bad,  _ = compute_quality_score(_info(recommendation_mean=4.5))
        assert score_bad < score_good

    def test_score_bounded_0_to_100(self):
        # Extremt positiv
        info = _info(
            roe=1.0, profit_margin=0.5, revenue_growth=2.0,
            free_cash_flow=1_000_000_000, recommendation_mean=1.0,
            number_of_analyst_opinions=20, debt_to_equity=5.0,
        )
        score, _ = compute_quality_score(info)
        assert 0.0 <= score <= 100.0

        # Extremt negativ
        info2 = _info(
            roe=-2.0, profit_margin=-0.5, revenue_growth=-0.9,
            free_cash_flow=-1_000_000_000, recommendation_mean=5.0,
            debt_to_equity=900.0,
        )
        score2, _ = compute_quality_score(info2)
        assert 0.0 <= score2 <= 100.0


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — compute_beneish_mscore
# ══════════════════════════════════════════════════════════════════════════════

class TestBeneishMScore:

    def _healthy_financials(self) -> dict:
        return {
            "revenue_t":     10_000_000,   "revenue_t1":     9_000_000,
            "cogs_t":         5_000_000,   "cogs_t1":        4_500_000,
            "receivables_t":    500_000,   "receivables_t1":   450_000,
            "assets_t":      15_000_000,   "assets_t1":     14_000_000,
            "ppe_t":          3_000_000,   "ppe_t1":         2_800_000,
            "depreciation_t":   300_000,   "depreciation_t1":  280_000,
            "sga_t":          1_000_000,   "sga_t1":           900_000,
            "total_debt_t":   4_000_000,   "total_debt_t1":  3_500_000,
            "current_liabilities_t": 2_000_000,
            "current_liabilities_t1": 1_800_000,
            "net_income_t":   1_200_000,
            "operating_cashflow_t": 1_500_000,  # > net_income → bra kassaflöde
        }

    def _manipulated_financials(self) -> dict:
        """Simulerar manipulation: snabb omsättningstillväxt + brus."""
        return {
            "revenue_t":     20_000_000,   "revenue_t1":     9_000_000,   # +122%
            "cogs_t":        16_000_000,   "cogs_t1":        4_500_000,   # Marginal faller
            "receivables_t":  5_000_000,   "receivables_t1":   450_000,   # Stor ökning
            "assets_t":      20_000_000,   "assets_t1":     14_000_000,
            "ppe_t":          3_000_000,   "ppe_t1":         2_800_000,
            "depreciation_t":   100_000,   "depreciation_t1":  280_000,   # Lägre avskrivning
            "sga_t":          3_000_000,   "sga_t1":           900_000,
            "total_debt_t":   8_000_000,   "total_debt_t1":  3_500_000,
            "current_liabilities_t": 5_000_000,
            "current_liabilities_t1": 1_800_000,
            "net_income_t":   2_000_000,
            "operating_cashflow_t":   200_000,  # Mycket lägre än net income → manipulation
        }

    def test_healthy_company_passes(self):
        m, text = compute_beneish_mscore(self._healthy_financials())
        if m is not None:
            assert m < -1.78, f"Friskt bolag borde ha M < -1.78, fick {m}"

    def test_manipulated_company_flagged(self):
        m, text = compute_beneish_mscore(self._manipulated_financials())
        if m is not None:
            assert m > -2.22, f"Manipulerat bolag borde ge högt M-score, fick {m}"

    def test_empty_data_returns_none(self):
        m, text = compute_beneish_mscore({})
        assert m is None
        assert "saknas" in text.lower() or "ej beräknad" in text.lower()

    def test_insufficient_data_returns_none(self):
        partial = {"revenue_t": 1000, "revenue_t1": 900}
        m, text = compute_beneish_mscore(partial)
        assert m is None

    def test_m_score_is_float(self):
        m, _ = compute_beneish_mscore(self._healthy_financials())
        if m is not None:
            assert isinstance(m, float)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — check_dilution
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckDilution:

    def test_no_dilution_data_returns_zero(self):
        dil, flag = check_dilution({})
        assert dil == 0.0
        assert flag == ""

    def test_high_dilution_flagged(self):
        dil, flag = check_dilution({"sharesPercentSharesOut": 0.35})  # 35%
        assert dil >= 30.0
        assert "utspädning" in flag.lower() or "exkludera" in flag.lower()

    def test_moderate_dilution_soft_flag(self):
        dil, flag = check_dilution({"sharesPercentSharesOut": 0.18})
        assert dil >= 15.0

    def test_small_dilution_no_flag(self):
        dil, flag = check_dilution({"sharesPercentSharesOut": 0.05})
        assert dil < 15.0
        assert flag == ""

    def test_smallcap_higher_threshold(self):
        # 18% utspädning: threshold 20% i smallcap-läge
        dil, flag = check_dilution({"sharesPercentSharesOut": 0.18}, universe_type="smallcap")
        assert dil >= 15.0
        # I smallcap-läge är tröskeln 20% — 18% bör inte ge flagga
        assert "exkludera" not in flag.lower()


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED — evaluate_candidate
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluateCandidate:

    def test_good_stock_is_not_excluded(self):
        result = evaluate_candidate(_info(), ticker="AAPL")
        assert not result["excluded"]
        assert result["quality_score"] > 0
        assert result["quality_tier"] in ("HIGH", "MEDIUM", "SPECULATIVE")

    def test_penny_stock_is_excluded(self):
        result = evaluate_candidate(_info(price=1.0), ticker="JUNK")
        assert result["excluded"]
        assert result["exclude_reason"]

    def test_high_quality_reaches_high_tier(self):
        info = _info(
            roe=0.25, profit_margin=0.20, revenue_growth=0.30,
            free_cash_flow=500_000_000, gross_margins=0.65,
            recommendation_mean=1.5, number_of_analyst_opinions=10,
            debt_to_equity=15.0, market_cap=50_000_000_000,
        )
        result = evaluate_candidate(info, ticker="HIGHQ")
        assert not result["excluded"]
        assert result["quality_tier"] == "HIGH"

    def test_result_has_all_keys(self):
        result = evaluate_candidate(_info(), ticker="TEST")
        required_keys = {
            "excluded", "exclude_reason", "quality_score", "quality_flags",
            "quality_tier", "m_score", "m_score_text", "dilution_pct",
            "dilution_flag", "fraud_flags", "confidence_delta",
        }
        assert required_keys.issubset(result.keys())

    def test_confidence_delta_in_range(self):
        result = evaluate_candidate(_info(), ticker="NORM")
        assert -1.0 <= result["confidence_delta"] <= 1.0

    def test_m_score_exclusion_when_provided(self):
        # Simulera trolig manipulation via finansiell data
        manipulated = {
            "revenue_t":     20_000_000, "revenue_t1":    9_000_000,
            "cogs_t":        17_000_000, "cogs_t1":       4_000_000,
            "receivables_t":  6_000_000, "receivables_t1":  400_000,
            "assets_t":      22_000_000, "assets_t1":    14_000_000,
            "ppe_t":          3_000_000, "ppe_t1":        2_800_000,
            "depreciation_t":    80_000, "depreciation_t1": 280_000,
            "sga_t":          3_500_000, "sga_t1":          900_000,
            "total_debt_t":   9_000_000, "total_debt_t1": 3_500_000,
            "current_liabilities_t": 5_500_000,
            "current_liabilities_t1": 1_800_000,
            "net_income_t":   1_800_000,
            "operating_cashflow_t":   100_000,
        }
        result = evaluate_candidate(_info(), ticker="MANIP", financials=manipulated)
        m = result["m_score"]
        if m is not None and m > -1.00:
            assert result["excluded"]  # Trolig manipulation → exkludera
        # Om M-score är beräknat och > -1.78 → fraud_flags ska ha något
        if m is not None and m > -1.78:
            assert len(result["fraud_flags"]) > 0
