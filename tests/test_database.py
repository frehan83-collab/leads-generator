"""
Tests for the database module.
Uses a temporary in-memory database.
"""

import sqlite3
import pytest
from unittest.mock import patch
from pathlib import Path

import src.database.db as db_module


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Redirect DB to a temp file for each test."""
    temp_db_path = tmp_path / "test_leads.db"
    with patch.object(db_module, "DB_PATH", temp_db_path):
        db_module.init_db()
        yield


def test_init_db_creates_tables():
    with db_module.get_connection() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "job_postings" in tables
    assert "prospects" in tables
    assert "outreach_log" in tables


def test_insert_job_posting():
    data = {
        "finn_id": "12345",
        "title": "Biolog",
        "company_name": "AquaCorp AS",
        "company_domain": "aquacorp.no",
        "location": "Bergen",
        "url": "https://finn.no/job/12345",
        "keyword_matched": "biologi",
        "published_at": None,
        "scraped_at": "2024-01-01T09:00:00",
    }
    row_id = db_module.insert_job_posting(data)
    assert row_id is not None
    assert row_id > 0


def test_insert_job_posting_duplicate_ignored():
    data = {
        "finn_id": "99999",
        "title": "Test",
        "company_name": "Test AS",
        "company_domain": None,
        "location": "",
        "url": "",
        "keyword_matched": "seafood",
        "published_at": None,
        "scraped_at": "2024-01-01T09:00:00",
    }
    id1 = db_module.insert_job_posting(data)
    id2 = db_module.insert_job_posting(data)
    assert id1 is not None
    assert id2 is None  # duplicate ignored


def test_insert_prospect_and_email_exists():
    # Need a job posting first
    db_module.insert_job_posting({
        "finn_id": "55555",
        "title": "Job",
        "company_name": "Corp",
        "company_domain": "corp.no",
        "location": "",
        "url": "",
        "keyword_matched": "seafood",
        "published_at": None,
        "scraped_at": "2024-01-01T00:00:00",
    })

    prospect = {
        "job_posting_id": 1,
        "first_name": "Kari",
        "last_name": "Nordmann",
        "full_name": "Kari Nordmann",
        "email": "kari@corp.no",
        "email_status": "valid",
        "position": "HR Manager",
        "company_name": "Corp",
        "company_domain": "corp.no",
        "linkedin_url": None,
        "snov_prospect_id": None,
        "snov_list_id": None,
        "created_at": "2024-01-01T09:00:00",
    }
    row_id = db_module.insert_prospect(prospect)
    assert row_id is not None
    assert db_module.email_exists("kari@corp.no") is True
    assert db_module.email_exists("other@corp.no") is False


def test_get_prospect_by_email():
    db_module.insert_job_posting({
        "finn_id": "77777",
        "title": "Job",
        "company_name": "Corp2",
        "company_domain": "corp2.no",
        "location": "",
        "url": "",
        "keyword_matched": "seafood",
        "published_at": None,
        "scraped_at": "2024-01-01T00:00:00",
    })
    db_module.insert_prospect({
        "job_posting_id": 1,
        "first_name": "Ole",
        "last_name": "Hansen",
        "full_name": "Ole Hansen",
        "email": "ole@corp2.no",
        "email_status": "valid",
        "position": "CEO",
        "company_name": "Corp2",
        "company_domain": "corp2.no",
        "linkedin_url": None,
        "snov_prospect_id": None,
        "snov_list_id": None,
        "created_at": "2024-01-01T09:00:00",
    })
    result = db_module.get_prospect_by_email("ole@corp2.no")
    assert result is not None
    assert result["first_name"] == "Ole"
