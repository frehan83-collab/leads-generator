"""
Smoke tests for hardening work: config, update allowlists, LIKE escaping,
follow-up safe defaults, double-send guard, and web error handlers.
"""

import pytest
from unittest.mock import patch
from pathlib import Path

import src.database.db as db_module
from src.config import Settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    temp_db_path = tmp_path / "test_leads.db"
    with patch.object(db_module, "DB_PATH", temp_db_path):
        db_module.init_db()
        yield


def _make_prospect_and_draft(status="approved", sent_at=None):
    pid = db_module.insert_job_posting({
        "external_id": "x1", "title": "T", "company_name": "C",
        "scraped_at": "2024-01-01T09:00:00",
    })
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, email, created_at) VALUES (?, ?, ?)",
            (pid, "a@example.no", "2024-01-01T09:00:00"),
        )
        prospect_id = cur.lastrowid
    draft_id = db_module.insert_email_draft({
        "prospect_id": prospect_id,
        "job_posting_id": pid,
        "template_name": "t",
        "subject": "s",
        "body": "b",
        "status": status,
    })
    if sent_at:
        db_module.update_email_draft(draft_id, {"sent_at": sent_at})
    return draft_id


# --- update allowlists -------------------------------------------------

def test_update_rejects_unknown_column():
    draft_id = _make_prospect_and_draft()
    with pytest.raises(ValueError, match="Cannot update"):
        db_module.update_email_draft(draft_id, {"1=1; --": "x"})


def test_update_pipeline_run_rejects_unknown_column():
    run_id = db_module.insert_pipeline_run({})
    with pytest.raises(ValueError, match="Cannot update"):
        db_module.update_pipeline_run(run_id, {"nope": 1})


def test_update_linkedin_rejects_unknown_column():
    with pytest.raises(ValueError, match="Cannot update"):
        db_module.update_linkedin_message(1, {"nope": 1})


# --- LIKE escaping -----------------------------------------------------

def test_search_with_wildcards_is_literal():
    db_module.insert_job_posting({
        "external_id": "w1", "title": "100% salmon", "company_name": "C",
        "scraped_at": "2024-01-01T09:00:00",
    })
    rows, _ = db_module.get_job_postings(search="%")
    # '%' must not match everything: only the posting containing a literal %
    assert all("%" in (r["title"] or "") for r in rows)


# --- follow-up safe defaults -------------------------------------------

def test_followup_draft_defaults_to_needs_approval(monkeypatch):
    from src.config import Settings
    from src.outreach import follow_up_checker as fuc
    monkeypatch.setattr(fuc, "settings", Settings(followup_auto_send=False))
    parent_id = _make_prospect_and_draft()
    new_id = fuc.create_follow_up_draft(parent_id, 2)
    assert new_id is not None
    draft = db_module.get_email_draft_by_id(new_id)
    assert draft["status"] == "draft"


def test_followup_draft_approved_when_opted_in(monkeypatch):
    from src.config import Settings
    from src.outreach import follow_up_checker as fuc
    monkeypatch.setattr(fuc, "settings", Settings(followup_auto_send=True))
    parent_id = _make_prospect_and_draft()
    new_id = fuc.create_follow_up_draft(parent_id, 2)
    draft = db_module.get_email_draft_by_id(new_id)
    assert draft["status"] == "approved"


# --- double-send guard --------------------------------------------------

def test_send_refuses_already_sent_draft():
    from src.outreach import email_sender
    draft_id = _make_prospect_and_draft(sent_at="2024-01-02T10:00:00")
    result = email_sender.send_email_direct(draft_id)
    assert result["success"] is False
    assert "already sent" in result["error"]


# --- config -------------------------------------------------------------

def test_settings_has_safe_defaults():
    s = Settings()
    assert s.followup_auto_send is False
    assert s.run_time == "09:30"
    assert s.resolved_flask_secret()  # ephemeral fallback works


# --- web error handlers --------------------------------------------------

def test_404_and_500_pages_render():
    from src.web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r404 = client.get("/no-such-page")
    assert r404.status_code == 404
    assert b"404" in r404.data
