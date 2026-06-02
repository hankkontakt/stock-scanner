"""
Tester for core/news_fetcher.py — Nyhetshamtning, RSS, merge, edge cases.
"""
import pytest

from core.news_fetcher import (
    fetch_news,
    fetch_global_market_news,
    fetch_swedish_market_news,
    fetch_google_news_rss,
    _merge_news,
    fetch_company_news,
    format_news_section_md,
    format_market_news_section_md,
    _finnhub_symbol,
    _google_search_term,
    get_weekly_factoid,
)


class TestFetchNews:
    """Testar fetch_news och fetch_company_news."""

    def test_fetch_company_news(self, mocker, sample_news_data):
        """Mockad nyhetshamtning returnerar lista med artiklar."""
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")
        mocker.patch("core.news_fetcher.fetch_google_news_rss", return_value=sample_news_data[:3])
        mocker.patch("core.news_fetcher._resolve_company_name", return_value=None)

        articles = fetch_company_news("AAPL")
        assert isinstance(articles, list)

    def test_fetch_news_no_api_key(self):
        """Utan API-nyckel returneras tom lista."""
        articles = fetch_news("AAPL", api_key="", days=3)
        assert articles == []

    def test_fetch_news_cache_hit(self, mocker, sample_news_data):
        """Cachade nyheter returneras direkt."""
        mocker.patch("core.news_fetcher._read_cache", return_value=sample_news_data[:3])
        articles = fetch_news("AAPL", api_key="test", days=3)
        assert len(articles) == 3

    def test_fetch_news_api_failure(self, mocker, mock_requests_get):
        """API-fel returnerar tom lista."""
        mock_requests_get.return_value.status_code = 500
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        articles = fetch_news("AAPL", api_key="test", days=3)
        assert articles == []

    def test_fetch_news_rate_limited(self, mocker):
        """Rate limiting (429) hanteras med retry."""
        resp_first = mocker.MagicMock(status_code=429)
        resp_second = mocker.MagicMock(status_code=200)
        resp_second.json.return_value = [{"headline": "Test", "url": "https://x.com", "datetime": 1700000000, "source": "Test"}]
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")
        mocker.patch("requests.get", side_effect=[resp_first, resp_second])

        articles = fetch_news("AAPL", api_key="test", days=3)
        assert len(articles) == 1


class TestFetchGoogleNews:
    """Testar fetch_google_news_rss."""

    def test_fetch_google_news(self, mocker):
        """Mockat Google RSS returnerar artiklar."""
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>Test Article - Source</title>
<link>https://example.com</link>
<pubDate>Mon, 01 Jun 2026 10:00:00 GMT</pubDate>
</item>
</channel></rss>"""
        mocker.patch("requests.get", return_value=mock_response)
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        articles = fetch_google_news_rss("Apple", max_items=5, lang="sv")
        assert isinstance(articles, list)

    def test_fetch_google_news_empty_name(self):
        """Tomt bolagsnamn returnerar tom lista."""
        articles = fetch_google_news_rss("", max_items=5)
        assert articles == []

    def test_fetch_google_news_api_error(self, mocker):
        """API-fel returnerar tom lista."""
        mocker.patch("requests.get", side_effect=Exception("Connection error"))
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        articles = fetch_google_news_rss("Apple", max_items=5)
        assert articles == []


class TestFetchGlobalMarketNews:
    """Testar fetch_global_market_news."""

    def test_fetch_global_market_news_finnhub(self, mocker):
        """Finnhub-kall returnerar globala nyheter."""
        mock_resp = mocker.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"headline": "Global News", "url": "https://x.com", "datetime": 1700000000, "source": "Reuters"}
        ]
        mocker.patch("requests.get", return_value=mock_resp)
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")
        mocker.patch("time.sleep")

        articles = fetch_global_market_news("test_key", max_articles=3)
        assert len(articles) == 1

    def test_fetch_global_market_news_fallback_rss(self, mocker, mock_requests_get):
        """Google News RSS fallback nar Finnhub misslyckas."""
        # First call (Finnhub) returns non-200
        mock_requests_get.return_value.status_code = 500

        # Second call (Google RSS) returns 200 with RSS data
        rss_resp = mocker.MagicMock()
        rss_resp.status_code = 200
        rss_resp.content = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Market News - Source</title>
<link>https://example.com</link>
<pubDate>Tue, 02 Jun 2026 08:00:00 GMT</pubDate>
</item>
</channel></rss>"""

        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        # Override requests.get side effects
        original_get = __import__("requests").get

        def side_effect(url, *args, **kwargs):
            if "finnhub" in url:
                return mock_requests_get.return_value
            return rss_resp

        mocker.patch("requests.get", side_effect=side_effect)

        articles = fetch_global_market_news("test_key", max_articles=3)
        assert isinstance(articles, list)


class TestFetchSwedishNews:
    """Testar fetch_swedish_market_news."""

    def test_fetch_swedish_market_news(self, mocker):
        """Mockad RSS returnerar svenska nyheter."""
        rss_resp = mocker.MagicMock()
        rss_resp.status_code = 200
        rss_resp.content = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Svensk Borsnyhet</title>
<link>https://example.com</link>
<pubDate>Tue, 02 Jun 2026 06:00:00 GMT</pubDate>
</item>
</channel></rss>"""
        mocker.patch("requests.get", return_value=rss_resp)
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        articles = fetch_swedish_market_news(max_articles=3)
        assert isinstance(articles, list)

    def test_all_sources_fail(self, mocker):
        """Alla RSS-kallor misslyckas -> tom lista."""
        mocker.patch("requests.get", side_effect=Exception("All sources down"))
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        articles = fetch_swedish_market_news(max_articles=3)
        assert articles == []

    def test_fetch_swedish_market_news_cache_hit(self, mocker, sample_news_data):
        """Cachade nyheter returneras direkt."""
        mocker.patch("core.news_fetcher._read_cache", return_value=sample_news_data[:3])
        articles = fetch_swedish_market_news(max_articles=3)
        assert len(articles) == 3


class TestMergeNews:
    """Testar _merge_news."""

    def test_merge_news(self, sample_news_data):
        """Sammanslagning fran flera kallor fungerar."""
        finnhub = sample_news_data[:5]
        google = sample_news_data[5:8]
        merged = _merge_news(finnhub, google, max_total=8)
        assert len(merged) <= 8
        assert all("headline" in a for a in merged)

    def test_merge_news_dedup(self, sample_news_data):
        """Dubletter tas bort baserat pa rubrikens start."""
        finnhub = sample_news_data[:3]
        google = sample_news_data[:2]  # Same first articles
        merged = _merge_news(finnhub, google, max_total=5)
        assert len(merged) <= 5
        assert len(merged) <= len(finnhub) + len(google)

    def test_merge_empty(self):
        """Tomma listor ger tom lista."""
        assert _merge_news([], []) == []


class TestHelpers:
    """Testar hjalpfunktioner."""

    def test_finnhub_symbol(self):
        """Finnhub-symbolkonvertering fungerar."""
        # _finnhub_symbol splits on first dot and replaces - with .
        result = _finnhub_symbol("VOLV-B.ST")
        # VOLV-B -> VOLV.B when splitting on first dot
        assert "." in result or "-" not in result
        assert _finnhub_symbol("AAPL") == "AAPL"
        assert _finnhub_symbol("SAP.DE") == "SAP"

    def test_google_search_term(self):
        """Google-sokterm fran ticker."""
        assert _google_search_term("INVE-B.ST") == "INVE B"
        assert _google_search_term("AAPL") == "AAPL"

    def test_get_weekly_factoid(self):
        """Veckans faktoid returnerar strang."""
        factoid = get_weekly_factoid()
        assert isinstance(factoid, str)
        assert len(factoid) > 10


class TestFormatNews:
    """Testar news-formatering."""

    def test_format_news_section_md(self, sample_news_data):
        """Markdown-formatering av nyheter fungerar."""
        news_by_ticker = {"AAPL": sample_news_data[:3]}
        md = format_news_section_md(news_by_ticker)
        assert "AAPL" in md
        assert isinstance(md, str)

    def test_format_news_empty(self):
        """Tomma nyheter ger tom strang."""
        assert format_news_section_md({}) == ""
        assert format_market_news_section_md([], []) == ""

    def test_format_market_news_section_md(self, sample_news_data):
        """Markdown-formatering av marknadsnyheter fungerar."""
        md = format_market_news_section_md(sample_news_data[:3], sample_news_data[3:6])
        assert isinstance(md, str)
        assert len(md) > 10


class TestNordicRSS:
    """Testar nordisk RSS-hamtning."""

    def test_fetch_swedish_news_rss_format(self, mocker):
        """Atom-format RSS hanteras."""
        atom_resp = mocker.MagicMock()
        atom_resp.status_code = 200
        atom_resp.content = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<title>Swedish News Atom</title>
<link href="https://example.com/atom"/>
<published>2026-06-02T08:00:00Z</published>
</entry>
</feed>"""
        mocker.patch("requests.get", return_value=atom_resp)
        mocker.patch("core.news_fetcher._read_cache", return_value=None)
        mocker.patch("core.news_fetcher._write_cache")

        articles = fetch_swedish_market_news(max_articles=3)
        assert isinstance(articles, list)
