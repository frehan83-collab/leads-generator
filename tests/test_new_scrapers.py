"""
Tests for the new scrapers (karrierestart.no and jobbnorge.no).
Tests URL building, ID extraction, and deduplication logic.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.scraper.karrierestart_scraper import (
    _build_search_url as ks_build_url,
    _extract_job_id as ks_extract_id,
    scrape_all_keywords as ks_scrape_all,
)
from src.scraper.jobbnorge_scraper import (
    _build_search_url as jn_build_url,
    _extract_job_id as jn_extract_id,
    scrape_all_keywords as jn_scrape_all,
)


class TestKarrierestart:
    """Tests for karrierestart.no scraper."""

    def test_build_search_url_basic(self):
        url = ks_build_url("HR")
        assert "karrierestart.no" in url
        assert "q=HR" in url
        assert "page" not in url

    def test_build_search_url_page(self):
        url = ks_build_url("rekruttering", page=3)
        assert "page=3" in url

    def test_build_search_url_spaces(self):
        url = ks_build_url("human resources")
        assert "q=human+resources" in url

    def test_extract_job_id_numeric(self):
        url = "https://karrierestart.no/ledig-stilling/123456"
        assert ks_extract_id(url) == "123456"

    def test_extract_job_id_with_query(self):
        url = "https://karrierestart.no/ledig-stilling/789012?utm_source=google"
        assert ks_extract_id(url) == "789012"

    def test_extract_job_id_slug(self):
        url = "https://karrierestart.no/ledig-stilling/hr-manager-oslo"
        assert ks_extract_id(url) == "hr-manager-oslo"

    def test_scrape_all_keywords_deduplicates(self):
        """Same job ID from two keywords should only appear once."""
        fake_posting = {
            "external_id": "ks-111",
            "source": "karrierestart",
            "title": "HR Manager",
            "company_name": "TestCorp",
            "company_domain": None,
            "org_number": None,
            "location": "Oslo",
            "url": "https://karrierestart.no/ledig-stilling/ks-111",
            "keyword_matched": "HR",
            "published_at": None,
        }

        with patch("src.scraper.karrierestart_scraper.scrape_keyword") as mock_scrape:
            mock_scrape.return_value = iter([fake_posting])
            results = list(ks_scrape_all(["HR", "rekruttering"]))

        assert len(results) == 1
        assert results[0]["external_id"] == "ks-111"
        assert results[0]["source"] == "karrierestart"
        assert "scraped_at" in results[0]


class TestJobbnorge:
    """Tests for jobbnorge.no scraper."""

    def test_build_search_url_basic(self):
        url = jn_build_url("HR")
        assert "jobbnorge.no" in url
        assert "q=HR" in url
        assert "page" not in url

    def test_build_search_url_page(self):
        url = jn_build_url("rekruttering", page=2)
        assert "page=2" in url

    def test_extract_job_id_numeric(self):
        url = "https://www.jobbnorge.no/en/available-jobs/job/654321/professor"
        assert jn_extract_id(url) == "654321"

    def test_extract_job_id_trailing_slash(self):
        url = "https://www.jobbnorge.no/job/999999/"
        assert jn_extract_id(url) == "999999"

    def test_scrape_all_keywords_deduplicates(self):
        """Same job ID from two keywords should only appear once."""
        fake_posting = {
            "external_id": "jn-222",
            "source": "jobbnorge",
            "title": "Professor",
            "company_name": "UiO",
            "company_domain": None,
            "org_number": None,
            "location": "Oslo",
            "url": "https://www.jobbnorge.no/job/jn-222",
            "keyword_matched": "professor",
            "published_at": None,
        }

        with patch("src.scraper.jobbnorge_scraper.scrape_keyword") as mock_scrape:
            mock_scrape.return_value = iter([fake_posting])
            results = list(jn_scrape_all(["professor", "forsker"]))

        assert len(results) == 1
        assert results[0]["external_id"] == "jn-222"
        assert results[0]["source"] == "jobbnorge"
        assert "scraped_at" in results[0]
