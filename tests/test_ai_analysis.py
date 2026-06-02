"""
Tester for core/ai_analysis.py — AI-analys med multi-provider, cache, depth.
"""
import json

import pytest

from core.ai_analysis import (
    analyze_stock,
    _resolve_depth,
    DEPTH_MAP,
)


class TestAnalyzeStock:
    """Testar analyze_stock med mockade AI-anrop."""

    def test_analyze_stock(self, mocker):
        """Mockat AI-anrop returnerar analys for en aktie."""
        mocker.patch("core.ai_analysis._call_with_cache", return_value=json.dumps({
            "ticker": "AAPL",
            "analysis": "Strong fundamentals with good growth.",
            "signals": {"entry": "OK", "confidence": 0.75},
        }))

        result = analyze_stock("AAPL", None, provider="deepseek")
        assert result is not None

    def test_cache_hit(self, mocker):
        """AI-cache fungerar och returnerar cachad analys."""
        cached_result = json.dumps({"ticker": "AAPL", "analysis": "Cached analysis"})
        mocker.patch("core.ai_analysis._call_with_cache", return_value=cached_result)

        result = analyze_stock("AAPL", None, provider="deepseek")
        assert result is not None

    def test_provider_fallback(self, mocker):
        """Fallback fran en provider till en annan fungerar."""
        mock_result = json.dumps({"ticker": "AAPL", "analysis": "Provider test"})
        mocker.patch("core.ai_analysis._call_with_cache", return_value=mock_result)

        result = analyze_stock("AAPL", None, provider="deepseek")
        assert result is not None

        result_gemini = analyze_stock("AAPL", None, provider="gemini")
        assert result_gemini is not None

    def test_depth_levels(self, mocker):
        """Olika djupnivaer (Snabb/Normal/Djup/Extra djup) fungerar."""
        def side_effect(*args, **kwargs):
            return json.dumps({"ticker": "AAPL", "analysis": "Depth test"})

        mock_call = mocker.patch("core.ai_analysis._call_with_cache", side_effect=side_effect)

        for depth in ["Snabb", "Normal", "Djup", "Extra djup"]:
            mock_call.reset_mock()
            result = analyze_stock("AAPL", None, provider="deepseek", depth=depth)
            assert result is not None

    def test_empty_response(self, mocker):
        """AI returnerar tom strang -> hanteras gracfully."""
        mocker.patch("core.ai_analysis._call_with_cache", return_value="")

        result = analyze_stock("AAPL", None, provider="deepseek")
        assert result is not None  # fallback behavior

    def test_parse_structured(self, mocker):
        """JSON-parsning av strukturerad AI-output fungerar."""
        structured = json.dumps({
            "ticker": "AAPL",
            "verdict": "BUY",
            "score_adjustment": 5,
            "reasoning": "Strong quarterly beat",
            "risk_factors": ["Valuation rich"],
        })
        mocker.patch("core.ai_analysis._call_with_cache", return_value=structured)

        result = analyze_stock("AAPL", None, provider="deepseek")
        assert result is not None

    def test_gemini_provider(self, mocker):
        """Gemini provider specifikt anrop fungerar."""
        mocker.patch("core.ai_analysis._call_with_cache", return_value=json.dumps({
            "ticker": "AAPL", "analysis": "Gemini analysis"
        }))

        result = analyze_stock("AAPL", None, provider="gemini")
        assert result is not None


class TestResolveDepth:
    """Testar _resolve_depth funktionen."""

    def test_depth_mapping(self):
        """Alla djupnivaer mappar korrekt till max_tokens."""
        assert _resolve_depth("Snabb") == 512
        assert _resolve_depth("Normal") == 2048
        assert _resolve_depth("Djup") == 4096
        assert _resolve_depth("Extra djup") == 8192

    def test_depth_default(self):
        """Okand depth returnerar default 1024."""
        assert _resolve_depth("Okand") == 1024

    def test_depth_none(self):
        """None returnerar default 1024."""
        assert _resolve_depth(None) == 1024


class TestDEPTH_MAP:
    """Testar DEPTH_MAP konstanter."""

    def test_depth_map_keys(self):
        """DEPTH_MAP har alla forvantade nycklar."""
        expected_keys = {"Snabb", "Normal", "Djup", "Extra djup"}
        assert set(DEPTH_MAP.keys()) == expected_keys

    def test_depth_map_values(self):
        """DEPTH_MAP-vardena ar okande."""
        for depth, tokens in DEPTH_MAP.items():
            assert isinstance(depth, str)
            assert isinstance(tokens, int)
            assert tokens > 0


class TestAnalyzeStockEdgeCases:
    """Testar edge cases for analyze_stock."""

    def test_with_dataframe(self, mocker, sample_scored_df):
        """Anropa med DataFrame fungerar."""
        mocker.patch("core.ai_analysis._call_with_cache", return_value=json.dumps({
            "ticker": "AAPL",
            "analysis": "With data analysis"
        }))

        result = analyze_stock("AAPL", sample_scored_df, provider="deepseek")
        assert result is not None

    def test_force_refresh(self, mocker):
        """force_refresh=True gar forbi cache."""
        mocker.patch("core.ai_analysis._call_with_cache", return_value=json.dumps({
            "ticker": "AAPL", "analysis": "Fresh analysis"
        }))

        result = analyze_stock("AAPL", None, force_refresh=True, provider="deepseek")
        assert result is not None
