"""Database backups + daily action list."""

import src.database.db as db_module


def _client(monkeypatch):
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


# --- backups ---------------------------------------------------------------------


def test_backup_roundtrip(tmp_path, monkeypatch):
    from src.database import backup as backup_mod

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "leads.db")
    monkeypatch.setattr(backup_mod, "backup_dir", lambda: tmp_path / "backups")
    db_module.init_db()
    db_module.insert_job_posting(
        {
            "external_id": "1",
            "title": "T",
            "company_name": "C",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    path = backup_mod.backup_database(keep=3)
    assert path is not None
    import sqlite3

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0] == 1
    conn.close()


def test_backup_prunes_old(tmp_path, monkeypatch):
    import time as _time

    from src.database import backup as backup_mod

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "leads.db")
    monkeypatch.setattr(backup_mod, "backup_dir", lambda: tmp_path / "backups")
    db_module.init_db()
    for _ in range(4):
        assert backup_mod.backup_database(keep=2) is not None
        _time.sleep(1.05)  # distinct mtimes for prune order
    import pathlib

    assert len(list(pathlib.Path(tmp_path / "backups").glob("*.db"))) == 2


def test_backup_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "leads.db")
    db_module.init_db()
    import main as main_mod

    monkeypatch.setattr("src.database.backup.backup_dir", lambda: tmp_path / "backups")
    main_mod.cmd_backup()  # must not raise


# --- actions -----------------------------------------------------------------------


def _seed_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    pid = db_module.insert_job_posting(
        {
            "external_id": "x1",
            "title": "T",
            "company_name": "Acme",
            "company_domain": "acme.no",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, full_name, email, company_domain,"
            " position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, "Eng Aged", "eng@acme.no", "acme.no", "CEO", "2024-01-01T09:00:00"),
        )
        engaged = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, full_name, email, company_domain,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, "Cold Fish", "cold@acme.no", "acme.no", "2024-01-01T09:00:00"),
        )
        cold = cur.lastrowid
    did = db_module.insert_email_draft(
        {
            "prospect_id": engaged,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "Hello",
            "body": "b",
            "status": "sent",
        }
    )
    db_module.update_email_draft(
        did, {"sent_at": "2024-01-02T10:00:00", "resend_id": "re_1"}
    )
    db_module.insert_email_event(
        {"draft_id": did, "resend_id": "re_1", "event_type": "opened", "payload": "{}"}
    )
    db_module.upsert_lead_score("acme.no", 90, "hot", "{}")
    return engaged, cold


def test_actions_sections(tmp_path, monkeypatch):
    from src.actions.today import get_today_actions

    _seed_actions(tmp_path, monkeypatch)
    actions = get_today_actions()
    assert [c["email"] for c in actions["call_now"]] == ["eng@acme.no"]
    assert actions["call_now"][0]["engaged_subject"] == "Hello"
    # cold prospect has no draft at all -> not in review; add one
    with db_module.get_connection() as conn:
        prid = conn.execute(
            "SELECT id FROM prospects WHERE email='cold@acme.no'"
        ).fetchone()[0]
        pid = conn.execute("SELECT id FROM job_postings LIMIT 1").fetchone()[0]
    db_module.insert_email_draft(
        {
            "prospect_id": prid,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "Review me",
            "body": "b",
            "status": "draft",
        }
    )
    actions = get_today_actions()
    assert [d["subject"] for d in actions["review"]] == ["Review me"]


def test_actions_page_renders(tmp_path, monkeypatch):
    _seed_actions(tmp_path, monkeypatch)
    html = _client(monkeypatch).get("/actions").data.decode()
    assert "Call now" in html
    assert "Eng Aged" in html
    assert "Review drafts" in html
