"""
Pipeline run tests with all network/API calls mocked.
Covers: website→Snov merge logic, Snov fallback, fatal-error abort,
zero-balance guard, and the bounded parallel path.
"""

import dataclasses
import os

import pytest
from unittest.mock import patch, MagicMock

import src.database.db as db_module
from src.config import Settings
from src.pipeline.lead_pipeline import LeadPipeline
from src.snov.errors import SnovOutOfCredits


POSTING = {
    "source": "finn",
    "external_id": "fin1",
    "title": "Daglig leder",
    "company_name": "Acme AS",
    "location": "Oslo",
    "url": "https://finn.no/job/ad/1",
    "keyword_matched": "seafood",
    "published_at": None,
    "scraped_at": "2024-01-01T09:00:00",
}


@pytest.fixture
def pipe(monkeypatch, tmp_path, request):
    """Pipeline with temp DB, fake creds, and all I/O mocked."""
    workers = getattr(request, "param", 1)
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    monkeypatch.setitem(os.environ, "SNOV_CLIENT_ID", "id")
    monkeypatch.setitem(os.environ, "SNOV_CLIENT_SECRET", "secret")

    pipeline = LeadPipeline(snov_list_id="L1", sources=["finn"])
    pipeline.snov = MagicMock()
    pipeline.snov.get_balance.return_value = {"data": {"balance": 500}}
    pipeline.snov.verify_email.return_value = "valid"
    pipeline.snov.add_prospect_to_list.return_value = True

    monkeypatch.setattr(
        "src.config.settings",
        dataclasses.replace(Settings(), pipeline_workers=workers),
    )

    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.scrape_finn",
        lambda keywords, known_ids=None, browser=None: [dict(POSTING)],
    )
    monkeypatch.setattr(LeadPipeline, "_resolve_domain", lambda self, *a, **k: "acme.no")
    monkeypatch.setattr(LeadPipeline, "_enrich_with_brreg", lambda self, *a, **k: None)
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.auto_draft_for_new_prospect", lambda *a, **k: 99
    )
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.auto_export_after_run", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.send_pipeline_alert", lambda *a, **k: None
    )
    monkeypatch.setattr("src.pipeline.lead_pipeline.BrowserManager", MagicMock)
    return pipeline


def _prospect_emails():
    with db_module.get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT email FROM prospects").fetchall()]


def _last_run():
    runs = db_module.get_recent_pipeline_runs(limit=1)
    return runs[0] if runs else None


def test_website_store_skips_snov_fallback(pipe, monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.scrape_emails_from_website",
        lambda *a, **k: [{"email": "a@acme.no", "title": "CEO", "name": "Ann A"}],
    )
    stats = pipe.run(["seafood"])
    assert stats["postings_new"] == 1
    assert stats["emails_verified"] == 1
    assert stats["drafts_created"] == 1
    assert _prospect_emails() == ["a@acme.no"]
    # Website stored a prospect → paid Snov domain search must not run
    pipe.snov.get_domain_email_count.assert_not_called()
    pipe.snov.get_prospects_by_domain.assert_not_called()
    assert _last_run()["status"] == "completed"


def test_snov_fallback_when_website_empty(pipe, monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.scrape_emails_from_website", lambda *a, **k: []
    )
    pipe.snov.get_domain_email_count.return_value = 3
    pipe.snov.get_prospects_by_domain.return_value = [
        {"first_name": "Kari", "last_name": "Nordmann", "position": "CEO"}
    ]
    pipe.snov.find_email_by_name_domain.return_value = {
        "email": "kari@acme.no", "smtp_status": "valid",
    }
    stats = pipe.run(["seafood"])
    assert stats["emails_verified"] == 1
    assert _prospect_emails() == ["kari@acme.no"]
    pipe.snov.get_domain_email_count.assert_called_once_with("acme.no")


def test_zero_balance_aborts_run(pipe):
    pipe.snov.get_balance.return_value = {"data": {"balance": 0}}
    with pytest.raises(SnovOutOfCredits):
        pipe.run(["seafood"])
    assert _last_run()["status"] == "failed"


def test_fatal_snov_error_fails_run(pipe, monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.scrape_emails_from_website",
        lambda *a, **k: [{"email": "a@acme.no", "title": "", "name": ""}],
    )
    pipe.snov.verify_email.side_effect = SnovOutOfCredits("empty")
    with pytest.raises(SnovOutOfCredits):
        pipe.run(["seafood"])
    run = _last_run()
    assert run["status"] == "failed"
    assert "SnovOutOfCredits" in (run["error_message"] or "")


@pytest.mark.parametrize("pipe", [2], indirect=True)
def test_parallel_workers_same_result(pipe, monkeypatch):
    postings = [
        dict(POSTING, external_id=f"fin{i}", url=f"https://finn.no/job/ad/{i}",
             company_name=f"Acme{i} AS")
        for i in range(4)
    ]
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.scrape_finn",
        lambda keywords, known_ids=None, browser=None: postings,
    )
    monkeypatch.setattr(
        LeadPipeline, "_resolve_domain",
        lambda self, name, posting, **k: f"{name.split()[0].lower()}.no",
    )
    inboxes = [
        [{"email": f"p{i}@acme{i}.no", "title": "", "name": ""}] for i in range(4)
    ]
    monkeypatch.setattr(
        "src.pipeline.lead_pipeline.scrape_emails_from_website",
        lambda *a, **k: inboxes.pop(0),
    )
    stats = pipe.run(["seafood"])
    assert stats["postings_new"] == 4
    assert sorted(_prospect_emails()) == [f"p{i}@acme{i}.no" for i in range(4)]
    assert _last_run()["status"] == "completed"
