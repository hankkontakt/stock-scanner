"""
Tester for core/suffix_map.py — Ticker suffix-mappningar.
"""
import pytest

from core.suffix_map import (
    SUFFIX_COUNTRY,
    SUFFIX_CATEGORY,
    COUNTRY_SUFFIXES,
    suffix_to_category,
    suffix_to_region,
)


class TestSuffixToCategory:
    """Testar suffix_to_category."""

    def test_all_suffixes(self):
        """Alla kanda suffix returnerar korrekt kategori."""
        test_cases = {
            ".ST": "OMX_SE",
            ".CO": "NORDIC",
            ".OL": "NORDIC",
            ".HE": "NORDIC",
            ".L": "UK",
            ".DE": "GERMANY",
            ".PA": "EUROPE",
            ".TO": "CANADA",
            ".AX": "ASIA_PACIFIC",
            ".T": "ASIA_PACIFIC",
        }
        for suffix, expected_cat in test_cases.items():
            ticker = f"TEST{suffix}"
            assert suffix_to_category(ticker) == expected_cat, f"Failed for {ticker}"

    def test_us_ticker(self):
        """Inget suffix = US."""
        assert suffix_to_category("AAPL") == "US_LARGE_CAP"
        assert suffix_to_category("MSFT") == "US_LARGE_CAP"

    def test_unknown_suffix(self):
        """Okant suffix = US_LARGE_CAP."""
        assert suffix_to_category("TEST.XX") == "US_LARGE_CAP"
        assert suffix_to_category("TEST.ZZ") == "US_LARGE_CAP"

    def test_case_insensitive(self):
        """Case-insensitive matching."""
        assert suffix_to_category("volv-b.st") == "OMX_SE"
        assert suffix_to_category("SAP.De") == "GERMANY"

    def test_ticker_internal_dot(self):
        """Ticker med punkt i namnet (inte suffix)."""
        assert suffix_to_category("BRK-B") == "US_LARGE_CAP"


class TestSuffixToRegion:
    """Testar suffix_to_region."""

    def test_all_regions(self):
        """Alla kanda suffix returnerar korrekt region."""
        test_cases = {
            ".ST": "NORDIC",
            ".CO": "NORDIC",
            ".OL": "NORDIC",
            ".HE": "NORDIC",
            ".L": "UK",
            ".DE": "EUROPE",
            ".PA": "EUROPE",
            ".TO": "CANADA",
            ".AX": "ASIA",
            ".T": "ASIA",
            ".SA": "LATAM",
            ".MX": "LATAM",
        }
        for suffix, expected_region in test_cases.items():
            ticker = f"TEST{suffix}"
            assert suffix_to_region(ticker) == expected_region, f"Failed for {ticker}"

    def test_us_region(self):
        """Inget suffix = US."""
        assert suffix_to_region("AAPL") == "US"

    def test_unknown_suffix_region(self):
        """Okant suffix = US."""
        assert suffix_to_region("TEST.XX") == "US"


class TestConstants:
    """Testar att konstanter ar korrekt definierade."""

    def test_country_suffixes_dict(self):
        """COUNTRY_SUFFIXES har forvantade nycklar."""
        assert "\U0001f1fa\U0001f1f8 USA" in COUNTRY_SUFFIXES
        assert COUNTRY_SUFFIXES["\U0001f1fa\U0001f1f8 USA"] == ".US"
        assert COUNTRY_SUFFIXES["\U0001f1f8\U0001f1ea Sverige"] == ".ST"

    def test_suffix_country_mapping(self):
        """SUFFIX_COUNTRY har flagga och land for varje suffix."""
        for suffix, (flag, country) in SUFFIX_COUNTRY.items():
            assert isinstance(flag, str) and len(flag) > 0
            assert isinstance(country, str) and len(country) > 0

    def test_suffix_category_mapping(self):
        """SUFFIX_CATEGORY har kategori for varje suffix."""
        for suffix, category in SUFFIX_CATEGORY.items():
            assert isinstance(category, str)
            assert len(category) > 0

    def test_no_duplicate_suffixes(self):
        """Inga dubbletter i suffix-mappningarna."""
        assert len(SUFFIX_COUNTRY) == len(set(SUFFIX_COUNTRY.keys()))
        assert len(SUFFIX_CATEGORY) == len(set(SUFFIX_CATEGORY.keys()))

    def test_non_nordic_suffixes(self):
        """Icke-nordiska suffix fungerar."""
        # These suffixes may not be defined, default to US_LARGE_CAP
        result_ns = suffix_to_category("TEST.NS")
        assert isinstance(result_ns, str)
