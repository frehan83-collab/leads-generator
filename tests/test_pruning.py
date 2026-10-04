"""Pruning: age filters, bulk deletes with cascades, route endpoints."""

import src.database.db as db_module


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


def _seed_old_new(tmp_path, monkeypatch):
    """One old (2020) and one far-future posting, each with prospect + draft."""
    _db(tmp_path, monkeypatch)
    ids = {}
    for key, day in (("old", "2020-01-01T09:00:00"), ("new", "2999-01-01T09:00:00")):
        pid = db_module.insert_job_posting(
            {
                "external_id": key,
                "title": "T",
                "company_name": "C",
                "scraped_at": day,
            }
        )
        with db_module.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO prospects (job_posting_id, email, created_at)"
                " VALUES (?, ?, ?)",
                (pid, f"{key}@x.no", day),
            )
            prid = cur.lastrowid
        did = db_module.insert_email_draft(
            {
                "prospect_id": prid,
                "job_posting_id": pid,
                "template_name": "t",
                "subject": "s",
                "body": "b",
                "status": "draft",
            }
        )
        with db_module.get_connection() as conn:
            conn.execute(
                "UPDATE email_drafts SET created_at = ? WHERE id = ?", (day, did)
            )
            conn.execute(
                "INSERT INTO prospect_stages (prospect_id, stage, moved_at)"
                " VALUES (?, 'New', ?)",
                (prid, day),
            )
            conn.execute(
                "INSERT INTO linkedin_messages (prospect_id, message_type,"
                " message_text, status, created_at)"
                " VALUES (?, 'connection_request', 'hi', 'pending', ?)",
                (prid, day),
            )
        ids[key] = (pid, prid, did)
    return ids


# --- age filters -----------------------------------------------------------------


def test_older_than_filters(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    postings, total = db_module.get_job_postings(older_than_days=30)
    assert total == 1
    assert postings[0]["external_id"] == "old"
    prospects, total = db_module.get_prospects_filtered(older_than_days=30)
    assert total == 1
    assert prospects[0]["email"] == "old@x.no"
    drafts, total = db_module.get_email_drafts(older_than_days=30)
    assert total == 1


def test_no_age_filter_returns_all(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    assert db_module.get_job_postings()[1] == 2
    assert db_module.get_prospects_filtered()[1] == 2
    assert db_module.get_email_drafts()[1] == 2


# --- deletes -----------------------------------------------------------------------


def test_delete_prospects_cascades_but_keeps_suppressions(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    db_module.add_suppression("old@x.no", "bounce")
    with db_module.get_connection() as conn:
        prid = conn.execute(
            "SELECT id FROM prospects WHERE email = 'old@x.no'"
        ).fetchone()[0]
    assert db_module.delete_prospects([prid]) == 1
    with db_module.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM prospect_stages").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM linkedin_messages").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM email_events").fetchone()[0] == 0
    assert db_module.is_suppressed("old@x.no") is True


def test_delete_drafts_keeps_prospects(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    with db_module.get_connection() as conn:
        did = conn.execute("SELECT id FROM email_drafts LIMIT 1").fetchone()[0]
    assert db_module.delete_email_drafts([did]) == 1
    with db_module.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0] == 1


def test_delete_postings_no_orphans(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    with db_module.get_connection() as conn:
        pid = conn.execute(
            "SELECT id FROM job_postings WHERE external_id = 'old'"
        ).fetchone()[0]
    assert db_module.delete_job_postings([pid]) == 1
    with db_module.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM prospect_stages").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM linkedin_messages").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM email_events").fetchone()[0] == 0


# --- routes --------------------------------------------------------------------------


def test_prospects_delete_route(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    with db_module.get_connection() as conn:
        prid = conn.execute(
            "SELECT id FROM prospects WHERE email = 'old@x.no'"
        ).fetchone()[0]
    resp = _client(monkeypatch).post(
        "/prospects/delete", data={"prospect_ids": [str(prid)]}
    )
    assert resp.status_code == 302
    with db_module.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0] == 1


def test_campaigns_delete_route(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    with db_module.get_connection() as conn:
        did = conn.execute("SELECT id FROM email_drafts LIMIT 1").fetchone()[0]
    resp = _client(monkeypatch).post(
        "/campaigns/delete", data={"draft_ids": [str(did)]}
    )
    assert resp.status_code == 302
    with db_module.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM email_drafts").fetchone()[0] == 1


def test_age_filter_route(tmp_path, monkeypatch):
    _seed_old_new(tmp_path, monkeypatch)
    html = _client(monkeypatch).get("/prospects?older_than=30").data.decode()
    assert "old@x.no" in html
    assert "new@x.no" not in html
