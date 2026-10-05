"""Consent ledger + one-click unsubscribe + tracking-off follow-ups."""

import src.database.db as db_module


def _test_settings(**kw):
    """Shared stub settings with a stable signing secret."""
    from src.config import Settings

    kw.setdefault("flask_secret", "test-secret")
    return Settings(**kw)


def _patch_settings(monkeypatch, **kw):
    import src.outreach.email_sender as es_mod

    stub = _test_settings(**kw)
    monkeypatch.setattr("src.config.settings", stub)
    monkeypatch.setattr(es_mod, "settings", stub)
    return stub


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()


def _client(monkeypatch):
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


# --- consent ledger ------------------------------------------------------------------


def test_consent_roundtrip(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db_module.log_consent(
        "a@x.no", "consent", source="phone-call", note="ok 2026-10-05"
    )
    rows = db_module.get_consent_history("A@X.NO")
    assert len(rows) == 1
    assert rows[0]["basis"] == "consent"
    assert rows[0]["source"] == "phone-call"


def test_consent_rejects_bad_basis(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db_module.log_consent("a@x.no", "vibes")
    assert db_module.get_consent_history("a@x.no") == []


# --- tokens + headers -------------------------------------------------------------------


def test_token_roundtrip_and_tamper(monkeypatch):
    from src.outreach.unsubscribe import (
        make_unsubscribe_token,
        verify_unsubscribe_token,
    )

    _patch_settings(monkeypatch)
    token = make_unsubscribe_token("A@X.NO")
    assert verify_unsubscribe_token(token) == "a@x.no"
    assert verify_unsubscribe_token(token + "x") is None
    assert verify_unsubscribe_token("garbage") is None


def test_unsubscribe_url_needs_base(monkeypatch):
    from src.outreach.unsubscribe import unsubscribe_url

    _patch_settings(monkeypatch, app_base_url=None)
    assert unsubscribe_url("a@x.no") is None
    _patch_settings(monkeypatch, app_base_url="https://leads.example.com/")
    url = unsubscribe_url("a@x.no")
    assert url.startswith("https://leads.example.com/unsubscribe/")


def test_headers_shapes(monkeypatch):
    from src.outreach.unsubscribe import unsubscribe_headers

    _patch_settings(
        monkeypatch,
        app_base_url="https://leads.example.com",
        unsubscribe_mailto="unsub@x.no",
    )
    headers = unsubscribe_headers("a@x.no")
    assert "List-Unsubscribe" in headers
    assert "List-Unsubscribe-Post" in headers
    assert "mailto:unsub@x.no" in headers["List-Unsubscribe"]


def test_process_unsubscribe_suppresses(tmp_path, monkeypatch):
    from src.outreach.unsubscribe import (
        make_unsubscribe_token,
        process_unsubscribe_token,
    )

    _db(tmp_path, monkeypatch)
    _patch_settings(monkeypatch)
    assert process_unsubscribe_token(make_unsubscribe_token("a@x.no")) == "a@x.no"
    assert db_module.is_suppressed("a@x.no") is True
    assert process_unsubscribe_token("bogus") is None


# --- route (auth-exempt) ---------------------------------------------------------------------


def test_unsubscribe_route_flow(tmp_path, monkeypatch):
    import base64

    _db(tmp_path, monkeypatch)
    import src.web.app as app_module
    from src.outreach.unsubscribe import make_unsubscribe_token

    stub = _patch_settings(
        monkeypatch,
        dashboard_user="u",
        dashboard_pass="p",
        app_base_url="https://leads.example.com",
    )
    monkeypatch.setattr(app_module, "settings", stub)
    app = app_module.create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    token = make_unsubscribe_token("a@x.no")

    # GET shows confirm even without credentials (auth-exempt)
    assert client.get(f"/unsubscribe/{token}").status_code == 200
    assert db_module.is_suppressed("a@x.no") is False
    # POST honors it — also without credentials
    assert client.post(f"/unsubscribe/{token}").status_code == 200
    assert db_module.is_suppressed("a@x.no") is True
    # dashboard itself still locked
    assert client.get("/").status_code == 401
    creds = base64.b64encode(b"u:p").decode()
    assert (
        client.get("/", headers={"Authorization": f"Basic {creds}"}).status_code == 200
    )


# --- send wiring ------------------------------------------------------------------------------


def test_send_includes_unsub_headers_and_footer(tmp_path, monkeypatch):
    import resend

    import src.outreach.email_sender as es_mod

    _db(tmp_path, monkeypatch)
    stub = _test_settings(
        resend_api_key="re_test",
        resend_sending_enabled=True,
        app_base_url="https://leads.example.com",
        unsubscribe_mailto="unsub@x.no",
    )
    monkeypatch.setattr(es_mod, "settings", stub)
    monkeypatch.setattr("src.config.settings", stub)
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
            (pid, "a@x.no", "2024-01-01T09:00:00"),
        )
        prid = cur.lastrowid
    did = db_module.insert_email_draft(
        {
            "prospect_id": prid,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "Hello",
            "body": "Short body here for length.",
            "status": "approved",
        }
    )
    captured = {}

    def fake_send(params):
        captured.update(params)
        return {"id": "re_1"}

    monkeypatch.setattr(resend.Emails, "send", fake_send)
    result = es_mod.send_email_direct(did)
    assert result["success"] is True
    assert "List-Unsubscribe" in captured["headers"]
    assert "List-Unsubscribe-Post" in captured["headers"]
    assert "leads.example.com/unsubscribe/" in captured["html"]
    assert "Meld deg av" in captured["html"]


# --- follow-ups decoupled from opens ---------------------------------------------------------------


def test_followup_triggers_despite_open(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
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
            (pid, "a@x.no", "2020-01-01T09:00:00"),
        )
        prid = cur.lastrowid
    did = db_module.insert_email_draft(
        {
            "prospect_id": prid,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "s",
            "body": "b",
            "status": "sent",
        }
    )
    with db_module.get_connection() as conn:
        conn.execute(
            "UPDATE email_drafts SET sent_at = ?, resend_id = ? WHERE id = ?",
            ("2020-01-05T09:00:00", "re_1", did),
        )
    db_module.insert_email_event(
        {"draft_id": did, "resend_id": "re_1", "event_type": "opened", "payload": "{}"}
    )
    due = db_module.get_sent_drafts_needing_followup(min_days=3, max_step=3)
    assert [d["id"] for d in due] == [did]  # opened but unreplied still qualifies
