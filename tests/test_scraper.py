"""
Tests for the finn.no scraper.
Uses mocked Playwright responses to avoid hitting the live site.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.scraper.finn_scraper import (
    _build_search_url,
    _extract_finn_id,
    scrape_all_keywords,
)


def test_build_search_url_basic():
    url = _build_search_url("seafood")
    assert "finn.no" in url
    assert "seafood" in url
    # page=1 is the default — no param needed in URL
    assert "page" not in url


def test_build_search_url_page():
    url = _build_search_url("aquaculture", page=3)
    assert "page=3" in url


def test_extract_finn_id_from_finnkode():
    url = "https://www.finn.no/job/fulltime/ad.html?finnkode=123456789"
    assert _extract_finn_id(url) == "123456789"


def test_extract_finn_id_from_path():
    url = "https://www.finn.no/job/fulltime/ad.html/987654321"
    assert _extract_finn_id(url) == "987654321"


def test_extract_finn_id_fallback():
    url = "https://example.com/no-id-here"
    result = _extract_finn_id(url)
    assert result  # should not be empty


def test_scrape_all_keywords_deduplicates():
    """Same finn_id from two keywords should only appear once."""
    fake_posting = {
        "finn_id": "111",
        "title": "Fisker",
        "company_name": "AquaCorp",
        "company_domain": None,
        "location": "Bergen",
        "url": "https://finn.no/job/111",
        "keyword_matched": "seafood",
        "published_at": None,
        "scraped_at": "2024-01-01T09:00:00",
    }

    with patch("src.scraper.finn_scraper.scrape_keyword") as mock_scrape:
        mock_scrape.return_value = iter([fake_posting])
        results = list(scrape_all_keywords(["seafood", "sjømat"]))

    # Even though mock returns the same item for each keyword,
    # deduplication should result in exactly 1 item
    assert len(results) == 1
    assert results[0]["finn_id"] == "111"
