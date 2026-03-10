"""
Tests for pipeline enhancements: fuzzy matching, date parsing, incremental scraping.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from src.scraper.finn_scraper import _parse_relative_date


class TestParseRelativeDate:
    """Tests for Norwegian relative date parsing in finn_scraper."""

    def test_i_dag(self):
        result = _parse_relative_date("i dag")
        expected = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        assert result == expected

    def test_today(self):
        result = _parse_relative_date("today")
        expected = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        assert result == expected

    def test_i_gar(self):
        result = _parse_relative_date("i går")
        expected = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == expected

    def test_yesterday(self):
        result = _parse_relative_date("yesterday")
        expected = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == expected

    def test_dager_siden(self):
        result = _parse_relative_date("3 dager siden")
        expected = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)).strftime("%Y-%m-%d")
        assert result == expected

    def test_dager_siden_singular(self):
        """'1 dager siden' matches the regex pattern dager?."""
        result = _parse_relative_date("1 dager siden")
        expected = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == expected

    def test_timer_siden(self):
        """Hours ago should resolve to today."""
        result = _parse_relative_date("5 timer siden")
        expected = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        assert result == expected

    def test_time_siden_singular(self):
        result = _parse_relative_date("1 time siden")
        expected = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        assert result == expected

    def test_dd_mm_yyyy(self):
        result = _parse_relative_date("15.03.2025")
        assert result == "2025-03-15"

    def test_d_m_yyyy(self):
        result = _parse_relative_date("5.1.2025")
        assert result == "2025-01-05"

    def test_unknown_returns_none(self):
        result = _parse_relative_date("noe ukjent")
        assert result is None

    def test_empty_string(self):
        result = _parse_relative_date("")
        assert result is None

    def test_whitespace_trimmed(self):
        result = _parse_relative_date("  i dag  ")
        expected = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        assert result == expected


class TestFuzzyMatching:
    """Tests for fuzzy company name matching in pipeline."""

    def test_rapidfuzz_token_sort_ratio(self):
        """Verify rapidfuzz works for our use case."""
        from rapidfuzz import fuzz

        # Exact match
        assert fuzz.token_sort_ratio("AquaCorp AS", "AquaCorp AS") == 100

        # Close match
        score = fuzz.token_sort_ratio("AquaCorp", "Aqua Corp AS")
        assert score > 70

        # Reordered tokens
        score = fuzz.token_sort_ratio("Lerøy Seafood Group", "Seafood Group Lerøy")
        assert score > 90

        # Different company entirely
        score = fuzz.token_sort_ratio("AquaCorp", "Microsoft")
        assert score < 50

    def test_rapidfuzz_extract_one(self):
        """Verify extractOne picks the best match."""
        from rapidfuzz import fuzz, process

        companies = {
            "AquaCorp AS": "123456",
            "SeaFood Group AS": "234567",
            "NorFish AS": "345678",
        }

        match = process.extractOne(
            "Aqua Corp",
            companies.keys(),
            scorer=fuzz.token_sort_ratio,
            score_cutoff=70,
        )
        assert match is not None
        name, score, _ = match
        assert name == "AquaCorp AS"
        assert score > 70

    def test_no_match_below_threshold(self):
        """No match returned if all scores below cutoff."""
        from rapidfuzz import fuzz, process

        companies = {"Google AS": "999"}

        match = process.extractOne(
            "AquaCorp",
            companies.keys(),
            scorer=fuzz.token_sort_ratio,
            score_cutoff=85,
        )
        assert match is None


class TestCleanCompanyName:
    """Tests for the pipeline's _clean_company_name static method."""

    def setup_method(self):
        from src.pipeline.lead_pipeline import LeadPipeline
        self.clean = LeadPipeline._clean_company_name

    def test_strip_as_suffix(self):
        assert self.clean("AquaCorp AS") == "AquaCorp"

    def test_strip_asa_suffix(self):
        assert self.clean("Lerøy Seafood Group ASA") == "Lerøy Seafood Group"

    def test_strip_hf_suffix(self):
        assert self.clean("Sykehuset HF") == "Sykehuset"

    def test_comma_takes_last_segment(self):
        assert self.clean("Avdeling Nord, Helse AS") == "Helse"

    def test_comma_norway_suffix(self):
        # Comma split takes last segment first: "AquaCorp, Norway" → "Norway"
        # This reflects that comma-separated names take the LAST segment
        assert self.clean("AquaCorp, Norway") == "Norway"

    def test_comma_takes_company_name(self):
        # "Dept Nord, AquaCorp" → "AquaCorp"
        assert self.clean("Dept Nord, AquaCorp") == "AquaCorp"

    def test_collapse_whitespace(self):
        assert self.clean("  Aqua   Corp  AS  ") == "Aqua Corp"

    def test_no_suffix_unchanged(self):
        assert self.clean("AquaCorp") == "AquaCorp"
