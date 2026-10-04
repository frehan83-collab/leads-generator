"""Reply detection: classification, matching, processing, idempotency."""

import src.database.db as db_module
from src.inbox.base import InboxMessage, normalize_subject
from src.inbox.classify import classify_reply


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
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
            "INSERT INTO prospects (job_posting_id, full_name, email, created_at)"
            " VALUES (?, ?, ?, ?)",
            (pid, "Ann Aasen", "a@acme.no", "2024-01-01T09:00:00"),
        )
        prid = cur.lastrowid
    did = db_module.insert_email_draft(
        {
            "prospect_id": prid,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "Rekrutteringspartner for Acme",
            "body": "b",
            "status": "sent",
        }
    )
    db_module.update_email_draft(
        did, {"sent_at": "2024-01-02T10:00:00", "resend_id": "re_1"}
    )
    return prid, did


def _msg(**kw):
    base = {
        "message_id": "m1",
        "from_email": "a@acme.no",
        "subject": "Re: Rekrutteringspartner for Acme",
        "snippet": "Hei, dette høres interessant ut. Kan vi ta et møte?",
    }
    base.update(kw)
    return InboxMessage(**base)


class _FakeProvider:
    def __init__(self, messages):
        self.messages = messages

    def fetch_candidates(self, since_days=7, limit=100):
        return self.messages


# --- classification ---------------------------------------------------------------


def test_classify_human_positive():
    out = classify_reply(
        "Re: hei", "Ja, dette er interessant. Kan vi ta et møte neste uke?"
    )
    assert out["label"] == "human"


def test_classify_auto_reply():
    out = classify_reply("Automatic reply", "I am out of the office until Monday.")
    assert out["label"] == "auto_reply"
    out2 = classify_reply("Re: hei", "Jeg er på ferie denne uken. Autosvar.")
    assert out2["label"] == "auto_reply"


def test_classify_unsubscribe():
    out = classify_reply("Re: x", "Please unsubscribe me from these emails.")
    assert out["label"] == "unsubscribe"


def test_classify_angry_and_headers():
    out = classify_reply("Re: x", "This is spam, stop contacting me.")
    assert out["label"] in ("unsubscribe", "angry")
    out2 = classify_reply("Re: x", "Thanks!", {"Auto-Submitted": "auto-replied"})
    assert out2["label"] == "auto_reply"


def test_normalize_subject():
    assert normalize_subject("Re: SV: Rekruttering") == "rekruttering"
    assert normalize_subject("Re: Re: Møte") == "møte"
    assert normalize_subject("Ang: Møte") == "ang: møte"  # not a reply prefix
    assert normalize_subject("Plain subject") == "plain subject"


# --- processor ----------------------------------------------------------------------


def test_human_reply_moves_crm_and_records(tmp_path, monkeypatch):
    from src.inbox.processor import check_inbox

    prid, did = _seed(tmp_path, monkeypatch)
    stats = check_inbox(_FakeProvider([_msg()]))
    assert stats["human"] == 1
    assert stats["matched"] == 1
    draft = db_module.get_email_draft_by_id(did)
    assert draft["replied_at"]
    with db_module.get_connection() as conn:
        ev = conn.execute(
            "SELECT event_type FROM email_events WHERE draft_id = ?", (did,)
        ).fetchone()
    assert ev[0] == "replied"
    assert db_module.get_prospect_stage(prid)["stage"] == "Replied"


def test_unknown_sender_marked_but_ignored(tmp_path, monkeypatch):
    from src.inbox.processor import check_inbox

    _seed(tmp_path, monkeypatch)
    stats = check_inbox(
        _FakeProvider([_msg(message_id="m2", from_email="stranger@x.no")])
    )
    assert stats["matched"] == 0
    assert db_module.inbox_already_processed("m2") is True


def test_idempotent_rerun(tmp_path, monkeypatch):
    from src.inbox.processor import check_inbox

    _seed(tmp_path, monkeypatch)
    first = check_inbox(_FakeProvider([_msg()]))
    second = check_inbox(_FakeProvider([_msg()]))
    assert first["human"] == 1
    assert second["human"] == 0
    assert second["matched"] == 0


def test_auto_reply_logged_without_side_effects(tmp_path, monkeypatch):
    from src.inbox.processor import check_inbox

    prid, did = _seed(tmp_path, monkeypatch)
    stats = check_inbox(
        _FakeProvider([_msg(subject="Automatic reply", snippet="Out of office")])
    )
    assert stats["auto_reply"] == 1
    assert db_module.get_email_draft_by_id(did).get("replied_at") in (None, "")
    assert db_module.get_prospect_stage(prid) is None


def test_unsubscribe_suppresses(tmp_path, monkeypatch):
    from src.inbox.processor import check_inbox

    _seed(tmp_path, monkeypatch)
    stats = check_inbox(
        _FakeProvider([_msg(snippet="Please remove me from your list, unsubscribe")])
    )
    assert stats["unsubscribed"] == 1
    assert db_module.is_suppressed("a@acme.no") is True


def test_no_provider_configured_skips(monkeypatch, tmp_path):
    from src.config import Settings
    from src.inbox import processor as proc_mod

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    for var in (
        "INBOX_IMAP_HOST",
        "INBOX_IMAP_USER",
        "INBOX_IMAP_PASS",
        "INBOX_IMAP_PORT",
        "INBOX_IMAP_FOLDER",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("src.config.settings", Settings())
    stats = proc_mod.check_inbox()
    assert stats["fetched"] == 0
