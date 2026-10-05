"""Suppression list + unified send-queue guards + Resend retry."""

from unittest.mock import MagicMock

import pytest

import src.database.db as db_module


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()


def _seed_draft(email="a@acme.no", status="approved", **extra):
    pid = db_module.insert_job_posting(
        {
            "external_id": "x1",
            "title": "T",
            "company_name": "C",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, email, created_at) VALUES (?, ?, ?)",
            (pid, email, "2024-01-01T09:00:00"),
        )
        prospect_id = cur.lastrowid
    data = {
        "prospect_id": prospect_id,
        "job_posting_id": pid,
        "template_name": "t",
        "subject": "s",
        "body": "b",
        "status": status,
    }
    data.update(extra)
    return db_module.insert_email_draft(data), prospect_id


# --- suppression helpers ------------------------------------------------


def test_suppression_roundtrip():
    assert db_module.is_suppressed("a@acme.no") is False
    db_module.add_suppression("A@acme.no", "bounce")
    assert db_module.is_suppressed("a@acme.no") is True  # case-insensitive
    db_module.add_suppression("a@acme.no", "bounce")  # idempotent
    assert len(db_module.get_suppressions()) == 1


# --- webhook bounce → suppression ----------------------------------------


def _web_client(monkeypatch):
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_bounce_webhook_suppresses(monkeypatch):
    draft_id, _prospect_id = _seed_draft()
    db_module.update_email_draft(draft_id, {"resend_id": "re_123"})
    client = _web_client(monkeypatch)
    resp = client.post(
        "/webhooks/resend",
        json={
            "type": "email.bounced",
            "data": {"email_id": "re_123", "to": ["a@acme.no"], "bounce_type": "hard"},
        },
    )
    assert resp.status_code == 200
    assert db_module.is_suppressed("a@acme.no") is True


def test_complaint_webhook_suppresses(monkeypatch):
    draft_id, _prospect_id = _seed_draft()
    db_module.update_email_draft(draft_id, {"resend_id": "re_9"})
    client = _web_client(monkeypatch)
    resp = client.post(
        "/webhooks/resend",
        json={
            "type": "email.complained",
            "data": {"email_id": "re_9", "to": ["a@acme.no"]},
        },
    )
    assert resp.status_code == 200
    assert db_module.is_suppressed("a@acme.no") is True


def test_open_webhook_does_not_suppress(monkeypatch):
    draft_id, _prospect_id = _seed_draft()
    db_module.update_email_draft(draft_id, {"resend_id": "re_7"})
    client = _web_client(monkeypatch)
    client.post(
        "/webhooks/resend",
        json={
            "type": "email.opened",
            "data": {"email_id": "re_7"},
        },
    )
    assert db_module.is_suppressed("a@acme.no") is False


def test_bounce_unknown_draft_still_suppresses(monkeypatch):
    client = _web_client(monkeypatch)
    resp = client.post(
        "/webhooks/resend",
        json={
            "type": "email.bounced",
            "data": {"email_id": "unknown-id", "to": ["ghost@x.no"]},
        },
    )
    assert resp.status_code == 200
    assert db_module.is_suppressed("ghost@x.no") is True


# --- senders honor suppression + schedule --------------------------------


def test_resend_sender_refuses_suppressed(monkeypatch):
    import src.outreach.email_sender as es_mod
    from src.config import Settings
    from src.outreach import email_sender

    monkeypatch.setattr(es_mod, "settings", Settings(resend_sending_enabled=True))
    draft_id, _ = _seed_draft()
    db_module.add_suppression("a@acme.no", "bounce")
    result = email_sender.send_email_direct(draft_id)
    assert result["success"] is False
    assert "suppressed" in result["error"]


def test_snov_sender_skips_suppressed_and_scheduled(monkeypatch):
    import src.outreach.sender as sender_mod
    from src.config import Settings

    monkeypatch.setattr(sender_mod, "settings", Settings(snov_list_id="L1"))

    ok_id, _ = _seed_draft(email="ok@acme.no")
    sup_id, _ = _seed_draft(email="sup@acme.no")
    db_module.insert_job_posting(
        {
            "external_id": "x2",
            "title": "T",
            "company_name": "C",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    sched_id, _ = _seed_draft(email="later@acme.no")
    db_module.update_email_draft(sched_id, {"scheduled_for": "2999-01-01T00:00:00"})
    db_module.add_suppression("sup@acme.no", "bounce")

    mock_snov = MagicMock()
    mock_snov.add_prospect_to_list.return_value = True
    monkeypatch.setattr(sender_mod, "SnovClient", lambda: mock_snov)

    stats = sender_mod.send_approved_drafts()
    assert stats["sent"] == 1
    assert stats["skipped_suppressed"] == 1
    assert stats["skipped_scheduled"] == 1
    mock_snov.add_prospect_to_list.assert_called_once()


# --- Resend retry ----------------------------------------------------------


def test_resend_retry_then_success(monkeypatch):
    import resend
    from resend.exceptions import RateLimitError

    from src.outreach import email_sender

    draft_id, _ = _seed_draft()
    calls = []

    def fake_send(params):
        calls.append(params)
        if len(calls) == 1:
            raise RateLimitError("slow down", "rate_limit_exceeded", 429)
        return {"id": "re_1"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)
    import src.outreach.email_sender as es_mod
    from src.config import Settings as S

    # settings is frozen: replace the module attribute instead
    monkeypatch.setattr(
        es_mod, "settings", S(resend_api_key="re_test", resend_sending_enabled=True)
    )
    result = email_sender.send_email_direct(draft_id)
    assert result["success"] is True
    assert len(calls) == 2


def test_resend_validation_error_no_retry(monkeypatch):
    import resend
    from resend.exceptions import ValidationError

    import src.outreach.email_sender as es_mod
    from src.config import Settings as S
    from src.outreach import email_sender

    draft_id, _ = _seed_draft()
    calls = []

    def fake_send(params):
        calls.append(params)
        raise ValidationError("bad", "validation_error", 422)

    monkeypatch.setattr(resend.Emails, "send", fake_send)
    monkeypatch.setattr(
        es_mod, "settings", S(resend_api_key="re_test", resend_sending_enabled=True)
    )
    result = email_sender.send_email_direct(draft_id)
    assert result["success"] is False
    assert len(calls) == 1


# --- audit log ---------------------------------------------------------------


def test_audit_roundtrip():
    assert db_module.get_audit_log() == []
    db_module.log_audit("boss", "draft.approve", "email_draft", 7, "a@acme.no")
    rows = db_module.get_audit_log()
    assert len(rows) == 1
    assert rows[0]["actor"] == "boss"
    assert rows[0]["action"] == "draft.approve"
    assert rows[0]["entity_id"] == "7"


def test_approve_route_writes_audit(monkeypatch):
    import base64

    draft_id, _ = _seed_draft(status="draft")
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(
        app_module, "settings", Settings(dashboard_user="u", dashboard_pass="p")
    )
    app = app_module.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    creds = base64.b64encode(b"u:p").decode()
    resp = client.post(
        f"/campaigns/{draft_id}/approve",
        headers={"Authorization": f"Basic {creds}"},
    )
    assert resp.status_code == 302
    rows = db_module.get_audit_log()
    assert any(r["action"] == "draft.approve" and r["actor"] == "u" for r in rows)
