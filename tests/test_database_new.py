"""
Tests for new database functions: website caching, incremental scraping, pipeline trends.
Uses a temporary database for each test.
"""

import json
import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import src.database.db as db_module


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Redirect DB to a temp file for each test."""
    temp_db_path = tmp_path / "test_leads.db"
    with patch.object(db_module, "DB_PATH", temp_db_path):
        db_module.init_db()
        yield


class TestGetExistingExternalIds:
    """Tests for get_existing_external_ids function."""

    def test_returns_empty_set_when_no_postings(self):
        result = db_module.get_existing_external_ids("finn")
        assert result == set()

    def test_returns_ids_for_source(self):
        # Insert two finn postings
        db_module.insert_job_posting({
            "finn_id": "100", "external_id": "100", "source": "finn",
            "title": "Job A", "company_name": "Corp A", "company_domain": None,
            "location": "Oslo", "url": "https://finn.no/100",
            "keyword_matched": "HR", "published_at": None,
            "scraped_at": "2024-01-01T00:00:00",
        })
        db_module.insert_job_posting({
            "finn_id": "200", "external_id": "200", "source": "finn",
            "title": "Job B", "company_name": "Corp B", "company_domain": None,
            "location": "Bergen", "url": "https://finn.no/200",
            "keyword_matched": "HR", "published_at": None,
            "scraped_at": "2024-01-01T00:00:00",
        })
        # Insert a nav posting
        db_module.insert_job_posting({
            "finn_id": "300", "external_id": "300", "source": "nav",
            "title": "Job C", "company_name": "Corp C", "company_domain": None,
            "location": "Tromsø", "url": "https://nav.no/300",
            "keyword_matched": "HR", "published_at": None,
            "scraped_at": "2024-01-01T00:00:00",
        })

        finn_ids = db_module.get_existing_external_ids("finn")
        assert finn_ids == {"100", "200"}

        nav_ids = db_module.get_existing_external_ids("nav")
        assert nav_ids == {"300"}

        karrierestart_ids = db_module.get_existing_external_ids("karrierestart")
        assert karrierestart_ids == set()


class TestWebsiteCache:
    """Tests for get_cached_contacts and cache_contacts functions."""

    def test_returns_none_for_uncached_domain(self):
        result = db_module.get_cached_contacts("unknown.no")
        assert result is None

    def test_cache_and_retrieve(self):
        contacts = [
            {"email": "hr@corp.no", "name": "Kari", "title": "HR Manager"},
            {"email": "ceo@corp.no", "name": "Ole", "title": "CEO"},
        ]
        db_module.cache_contacts("corp.no", contacts)

        result = db_module.get_cached_contacts("corp.no")
        assert result is not None
        assert len(result) == 2
        assert result[0]["email"] == "hr@corp.no"
        assert result[1]["name"] == "Ole"

    def test_cache_empty_list(self):
        db_module.cache_contacts("empty.no", [])

        result = db_module.get_cached_contacts("empty.no")
        assert result is not None
        assert result == []

    def test_expired_cache_returns_none(self):
        """Contacts cached more than ttl_days ago should return None."""
        contacts = [{"email": "old@corp.no", "name": "Old"}]
        # Insert with an old timestamp
        old_time = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)).isoformat()
        with db_module.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO website_cache (domain, contacts_json, cached_at) VALUES (?, ?, ?)",
                ("old.no", json.dumps(contacts), old_time),
            )

        result = db_module.get_cached_contacts("old.no", ttl_days=7)
        assert result is None

    def test_fresh_cache_within_ttl(self):
        """Contacts cached within ttl_days should be returned."""
        contacts = [{"email": "new@corp.no", "name": "New"}]
        db_module.cache_contacts("new.no", contacts)

        result = db_module.get_cached_contacts("new.no", ttl_days=7)
        assert result is not None
        assert len(result) == 1

    def test_cache_updates_existing(self):
        """Caching same domain should overwrite."""
        db_module.cache_contacts("corp.no", [{"email": "v1@corp.no"}])
        db_module.cache_contacts("corp.no", [{"email": "v2@corp.no"}])

        result = db_module.get_cached_contacts("corp.no")
        assert len(result) == 1
        assert result[0]["email"] == "v2@corp.no"


class TestGetPipelineRunTrends:
    """Tests for get_pipeline_run_trends function."""

    def test_returns_empty_list_when_no_runs(self):
        result = db_module.get_pipeline_run_trends(30)
        assert result == []

    def test_returns_aggregated_trends(self):
        # Insert some pipeline runs
        today = datetime.now(timezone.utc).replace(tzinfo=None)
        yesterday = today - timedelta(days=1)

        with db_module.get_connection() as conn:
            # Today's run
            conn.execute(
                """INSERT INTO pipeline_runs
                   (started_at, finished_at, status, postings_scraped, prospects_found)
                   VALUES (?, ?, 'completed', 50, 10)""",
                (today.isoformat(), today.isoformat()),
            )
            # Yesterday's run
            conn.execute(
                """INSERT INTO pipeline_runs
                   (started_at, finished_at, status, postings_scraped, prospects_found)
                   VALUES (?, ?, 'completed', 30, 5)""",
                (yesterday.isoformat(), yesterday.isoformat()),
            )
            # Yesterday's second run
            conn.execute(
                """INSERT INTO pipeline_runs
                   (started_at, finished_at, status, postings_scraped, prospects_found)
                   VALUES (?, ?, 'completed', 20, 3)""",
                (yesterday.isoformat(), yesterday.isoformat()),
            )

        trends = db_module.get_pipeline_run_trends(30)
        assert len(trends) == 2  # Two distinct days

        # Yesterday should be aggregated
        yesterday_trend = [t for t in trends if t["day"] == yesterday.strftime("%Y-%m-%d")]
        assert len(yesterday_trend) == 1
        assert yesterday_trend[0]["total_scraped"] == 50  # 30 + 20
        assert yesterday_trend[0]["total_prospects"] == 8  # 5 + 3
        assert yesterday_trend[0]["run_count"] == 2

    def test_excludes_failed_runs(self):
        today = datetime.now(timezone.utc).replace(tzinfo=None)
        with db_module.get_connection() as conn:
            conn.execute(
                """INSERT INTO pipeline_runs
                   (started_at, status, postings_scraped, prospects_found)
                   VALUES (?, 'failed', 100, 0)""",
                (today.isoformat(),),
            )

        trends = db_module.get_pipeline_run_trends(30)
        assert trends == []  # Failed runs excluded


class TestWebsiteCacheTable:
    """Test that the website_cache table exists after init_db."""

    def test_table_exists(self):
        with db_module.get_connection() as conn:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "website_cache" in tables
