"""Sales acceleration: heartbeat, deliverability gate, review queue, alerts."""

import src.database.db as db_module


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()


# --- deliverability --------------------------------------------------------------


def test_clean_draft_passes():
    from src.outreach.deliverability import check_draft

    out = check_draft(
        "Rekrutteringspartner for Acme",
        "Hei Ola,\n\nVi hjelper sjømatselskaper med rekruttering. "
        "Kan vi ta en prat neste uke?\n\nHilsen Fredrik",
    )
    assert out["verdict"] == "pass"
    assert out["score"] >= 80


def test_spammy_draft_fails():
    from src.outreach.deliverability import check_draft

    out = check_draft(
        "CONGRATULATIONS!!! YOU WON 100% FREE!!!",
        "Click here now http://a.no http://b.no http://c.no http://d.no "
        "guaranteed winner act now!!!",
    )
    assert out["verdict"] == "fail"
    assert any("Spam-trigger" in i for i in out["issues"])


def test_gate_allows_by_default():
    from src.outreach.deliverability import gate_allows

    assert gate_allows(0) is True
    assert gate_allows(100) is True


def test_gate_blocks_when_configured(monkeypatch):
    import os

    from src.outreach.deliverability import gate_allows

    monkeypatch.setitem(os.environ, "DELIVERABILITY_BLOCK_BELOW", "50")
    assert gate_allows(49) is False
    assert gate_allows(50) is True


# --- review queue ------------------------------------------------------------------


def _seed_review(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    pid = db_module.insert_job_posting(
        {
            "external_id": "x1",
            "title": "T",
            "company_name": "C",
            "company_domain": "hot.no",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, email, company_domain, created_at)"
            " VALUES (?, ?, ?, ?)",
            (pid, "a@hot.no", "hot.no", "2024-01-01T09:00:00"),
        )
        prid_hot = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, email, company_domain, created_at)"
            " VALUES (?, ?, ?, ?)",
            (pid, "b@cold.no", "cold.no", "2024-01-01T09:00:00"),
        )
        prid_cold = cur.lastrowid
    cold = db_module.insert_email_draft(
        {
            "prospect_id": prid_cold,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "cold",
            "body": "b",
            "status": "draft",
        }
    )
    db_module.upsert_lead_score("cold.no", 10, "cold", "{}")
    hot = db_module.insert_email_draft(
        {
            "prospect_id": prid_hot,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "hot",
            "body": "b",
            "status": "draft",
        }
    )
    db_module.upsert_lead_score("hot.no", 90, "hot", "{}")
    return cold, hot


def test_review_next_picks_highest_score(tmp_path, monkeypatch):
    _seed_review(tmp_path, monkeypatch)
    assert db_module.get_next_draft_for_review() is not None
    nxt = db_module.get_next_draft_for_review()
    with db_module.get_connection() as conn:
        subj = conn.execute(
            "SELECT subject FROM email_drafts WHERE id = ?", (nxt,)
        ).fetchone()[0]
    assert subj == "hot"


def test_review_next_empty(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert db_module.get_next_draft_for_review() is None


def test_review_next_route(tmp_path, monkeypatch):
    _seed_review(tmp_path, monkeypatch)
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    resp = app.test_client().get("/campaigns/review-next")
    assert resp.status_code == 302
    assert "/campaigns/" in resp.headers["Location"]


# --- heartbeat -----------------------------------------------------------------------


def test_heartbeat_writes_partial_stats(tmp_path, monkeypatch):
    import os
    from unittest.mock import MagicMock

    from src.pipeline.lead_pipeline import LeadPipeline

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    monkeypatch.setitem(os.environ, "SNOV_CLIENT_ID", "id")
    monkeypatch.setitem(os.environ, "SNOV_CLIENT_SECRET", "secret")
    pipe = LeadPipeline(snov_list_id="L1", sources=["finn"])
    pipe.snov = MagicMock()
    pipe._run_id = db_module.insert_pipeline_run({})
    pipe._stats["postings_new"] = 7
    pipe._heartbeat()
    row = db_module.get_recent_pipeline_runs(1)[0]
    assert row["postings_new"] == 7
    assert row["status"] == "running"  # heartbeat never flips status


# --- hot-lead alert title -----------------------------------------------------------------


def test_hot_leads_webhook_title():
    from unittest.mock import MagicMock, patch

    from src.notifications.webhook import send_pipeline_alert

    with patch.dict("os.environ", {"WEBHOOK_URL": "https://x.test/hook"}):
        with patch("src.notifications.webhook.requests.post") as mock_post:
            mock_post.return_value = MagicMock()
            send_pipeline_alert(
                {}, status="hot_leads", error_message="New hot leads: a.no"
            )
    payload = mock_post.call_args[1]["json"]
    assert "Hot New Leads" in payload["title"]
