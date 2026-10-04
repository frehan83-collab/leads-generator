"""Posting lifecycle: revalidation, expiry guards, live-only signals."""

from unittest.mock import MagicMock, patch

import src.database.db as db_module
import src.outreach.sender as sender_mod
from src.config import Settings
from src.outreach import email_sender
from src.outreach import follow_up_checker as fuc


def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()


def _resp(status=200, text=""):
    mock = MagicMock()
    mock.status_code = status
    mock.ok = status < 400
    mock.text = text
    return mock


# --- schema --------------------------------------------------------------------


def test_lifecycle_columns_exist(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    with db_module.get_connection() as conn:
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(job_postings)").fetchall()
        }
    assert {"status", "last_checked_at"} <= cols


def test_insert_defaults_active(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    pid = db_module.insert_job_posting(
        {
            "external_id": "1",
            "title": "T",
            "company_name": "C",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM job_postings WHERE id = ?", (pid,)
        ).fetchone()
    assert row[0] == "active"


# --- checker ---------------------------------------------------------------------


def test_check_active_page():
    from src.scraper.revalidate import check_posting_active

    html = "<html><body><h1>Selger</h1><p>Vi søker selger. Søknadsfrist 01.12.2026</p></body></html>"
    with patch("src.scraper.revalidate.requests.get", return_value=_resp(200, html)):
        assert check_posting_active("https://finn.no/job/ad/1") is True


def test_check_404_expired():
    from src.scraper.revalidate import check_posting_active

    with patch("src.scraper.revalidate.requests.get", return_value=_resp(404, "")):
        assert check_posting_active("https://finn.no/job/ad/1") is False


def test_check_marker_expired():
    from src.scraper.revalidate import check_posting_active

    for body in (
        "<h1>Annonsen er utløpt</h1>",
        "<p>This job posting has expired</p>",
        "<div>Stillingen er fjernet</div>",
    ):
        with patch(
            "src.scraper.revalidate.requests.get", return_value=_resp(200, body)
        ):
            assert check_posting_active("https://x.no/1") is False, body


def test_check_unknown_on_block_or_error():
    from src.scraper.revalidate import check_posting_active

    with patch("src.scraper.revalidate.requests.get", return_value=_resp(403, "")):
        assert check_posting_active("https://x.no/1") is None
    with patch("src.scraper.revalidate.requests.get", side_effect=Exception("down")):
        assert check_posting_active("https://x.no/1") is None
    assert check_posting_active("") is None


def test_revalidate_one_persists(tmp_path, monkeypatch):
    from src.scraper.revalidate import revalidate_one

    _db(tmp_path, monkeypatch)
    pid = db_module.insert_job_posting(
        {
            "external_id": "1",
            "title": "T",
            "company_name": "C",
            "url": "https://x.no/1",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with patch("src.scraper.revalidate.requests.get", return_value=_resp(404, "")):
        assert revalidate_one(pid, "https://x.no/1", "finn") == "expired"
    assert db_module.posting_is_expired(pid) is True


# --- queue + guards ---------------------------------------------------------------


def _posting(tmp_path=None, **kw):
    base = {
        "external_id": kw.pop("external_id", "1"),
        "title": "T",
        "company_name": "C",
        "scraped_at": "2024-01-01T09:00:00",
    }
    base.update(kw)
    return db_module.insert_job_posting(base)


def test_revalidation_queue(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    fresh = _posting(external_id="fresh")
    db_module.update_job_posting(
        fresh, {"status": "active", "last_checked_at": "2999-01-01T00:00:00"}
    )
    dead = _posting(external_id="dead")
    db_module.update_job_posting(dead, {"status": "expired"})
    never = _posting(external_id="never")
    queue = db_module.get_postings_for_revalidation(limit=10, older_than_days=7)
    ids = [q["id"] for q in queue]
    assert never in ids  # never checked: queued
    assert dead not in ids  # expired: excluded
    assert fresh not in ids  # freshly checked: excluded


def test_posting_is_expired_semantics(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    assert db_module.posting_is_expired(None) is False
    assert db_module.posting_is_expired(999) is False
    pid = _posting()
    assert db_module.posting_is_expired(pid) is False  # active default
    db_module.update_job_posting(pid, {"status": "expired"})
    assert db_module.posting_is_expired(pid) is True


def _seed_draft(tmp_path, monkeypatch, posting_id=None):
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, email, created_at) VALUES (?, ?, ?)",
            (posting_id, "a@x.no", "2024-01-01T09:00:00"),
        )
        prid = cur.lastrowid
    return db_module.insert_email_draft(
        {
            "prospect_id": prid,
            "job_posting_id": posting_id,
            "template_name": "t",
            "subject": "s",
            "body": "b",
            "status": "approved",
        }
    )


def test_senders_refuse_expired_posting(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    pid = _posting()
    db_module.update_job_posting(pid, {"status": "expired"})
    draft_id = _seed_draft(tmp_path, monkeypatch, pid)

    result = email_sender.send_email_direct(draft_id)
    assert result["success"] is False
    assert "expired" in result["error"]

    monkeypatch.setattr(sender_mod, "settings", Settings(snov_list_id="L1"))
    mock_snov = MagicMock()
    monkeypatch.setattr(sender_mod, "SnovClient", lambda: mock_snov)
    stats = sender_mod.send_approved_drafts()
    assert stats["sent"] == 0
    assert stats["skipped_expired"] == 1
    mock_snov.add_prospect_to_list.assert_not_called()


def test_followup_skipped_for_expired_posting(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    monkeypatch.setattr(fuc, "settings", Settings(followup_auto_send=True))
    pid = _posting()
    db_module.update_job_posting(pid, {"status": "expired"})
    parent = _seed_draft(tmp_path, monkeypatch, pid)
    assert fuc.create_follow_up_draft(parent, 2, auto_approve=True) is None


def test_intent_counts_only_live_postings(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    live = _posting(
        external_id="live", company_domain="acme.no", scraped_at="2999-01-01T09:00:00"
    )
    dead = _posting(
        external_id="dead", company_domain="acme.no", scraped_at="2999-01-01T09:00:00"
    )
    db_module.update_job_posting(dead, {"status": "expired"})
    signals = db_module.get_company_intent_signals("acme.no")
    assert signals["total_postings"] == 1
    assert live and dead
