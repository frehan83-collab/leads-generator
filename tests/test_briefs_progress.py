"""Meeting briefs, A/B winner logic, run-progress endpoint, job state."""

import pytest

import src.database.db as db_module


def _client(monkeypatch):
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    pid = db_module.insert_job_posting(
        {
            "external_id": "x1",
            "title": "Daglig leder",
            "company_name": "Acme AS",
            "company_domain": "acme.no",
            "location": "Oslo",
            "url": "https://x.no/1",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, first_name, last_name, full_name,"
            " email, position, company_name, company_domain, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                "Ann",
                "Aasen",
                "Ann Aasen",
                "a@acme.no",
                "Daglig leder",
                "Acme AS",
                "acme.no",
                "2024-01-01T09:00:00",
            ),
        )
        prid = cur.lastrowid
    did = db_module.insert_email_draft(
        {
            "prospect_id": prid,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "Hallo",
            "body": "b",
            "status": "sent",
        }
    )
    db_module.update_email_draft(
        did, {"sent_at": "2024-01-02T10:00:00", "open_count": 2}
    )
    db_module.upsert_lead_score("acme.no", 80, "hot", "{}")
    return prid, did


# --- briefs ------------------------------------------------------------------


def test_build_brief_assembles_signals(tmp_path, monkeypatch):
    from src.emails.briefing import build_brief

    prid, _ = _seed(tmp_path, monkeypatch)
    brief = build_brief(prid)
    assert brief["prospect"]["full_name"] == "Ann Aasen"
    assert brief["score"]["score"] == 80
    assert len(brief["postings"]) == 1
    assert any(t["kind"] == "opened" for t in brief["timeline"])
    assert len(brief["talking_points"]) >= 3
    assert "Daglig leder" in " ".join(brief["talking_points"])
    assert brief["next_step"]


def test_build_brief_unknown_prospect(tmp_path, monkeypatch):
    from src.emails.briefing import build_brief

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    assert build_brief(999) is None


def test_brief_route_renders(tmp_path, monkeypatch):
    prid, _ = _seed(tmp_path, monkeypatch)
    html = _client(monkeypatch).get(f"/prospects/{prid}/brief").data.decode()
    assert "Ann Aasen" in html
    assert "Talking points" in html
    assert "Suggested next step" in html


def test_brief_route_404(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    assert _client(monkeypatch).get("/prospects/999/brief").status_code == 302


# --- A/B winner ----------------------------------------------------------------


def _seed_ab(tmp_path, monkeypatch):
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
            "INSERT INTO prospects (job_posting_id, email, created_at) VALUES (?, ?, ?)",
            (pid, "a@x.no", "2024-01-01T09:00:00"),
        )
        prid = cur.lastrowid

    def draft(**kw):
        base = {
            "prospect_id": prid,
            "job_posting_id": pid,
            "template_name": "t",
            "subject": "s",
            "body": "b",
            "status": "sent",
        }
        variant_of = kw.pop("variant_of", None)
        base.update(kw)
        did = db_module.insert_email_draft(base)
        if variant_of is not None:
            db_module.update_email_draft(did, {"variant_of": variant_of})
        return did

    parent = draft()
    v1 = draft(variant_of=parent)
    v2 = draft(variant_of=parent)
    return parent, v1, v2


def test_ab_winner_needs_signal(tmp_path, monkeypatch):
    _seed_ab(tmp_path, monkeypatch)
    groups = db_module.get_ab_test_groups()
    assert len(groups) == 1
    assert groups[0]["winner_id"] is None  # zero opens: too early
    assert groups[0]["signal_total"] == 0


def test_ab_winner_reply_weighted(tmp_path, monkeypatch):
    _parent, v1, v2 = _seed_ab(tmp_path, monkeypatch)
    db_module.update_email_draft(v1, {"open_count": 5})
    db_module.update_email_draft(
        v2, {"open_count": 1, "replied_at": "2024-01-03T10:00:00"}
    )
    groups = db_module.get_ab_test_groups()
    assert groups[0]["winner_id"] == v2  # reply (10) beats 5 opens


# --- run progress + job state ----------------------------------------------------


def test_jobstate_roundtrip():
    from src.web import jobstate

    jobstate.set_running("pipeline", True)
    assert jobstate.is_running("pipeline") is True
    assert jobstate.snapshot()["pipeline"] is True
    jobstate.set_running("pipeline", False)
    assert jobstate.is_running("pipeline") is False


def test_run_progress_endpoint(tmp_path, monkeypatch):
    from src.web import jobstate

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    run_id = db_module.insert_pipeline_run({})
    db_module.update_pipeline_run(run_id, {"status": "completed", "postings_new": 4})
    jobstate.set_running("pipeline", True)
    try:
        body = _client(monkeypatch).get("/api/run-progress").get_json()
    finally:
        jobstate.set_running("pipeline", False)
    assert body["jobs"]["pipeline"] is True
    assert body["latest_run"]["status"] == "completed"
    assert body["latest_run"]["postings_new"] == 4


def test_run_progress_empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    body = _client(monkeypatch).get("/api/run-progress").get_json()
    assert body["latest_run"] is None
    assert body["jobs"]["pipeline"] is False


def test_run_progress_marks_stale_run(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    run_id = db_module.insert_pipeline_run({})
    with db_module.get_connection() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00", run_id),
        )
    body = _client(monkeypatch).get("/api/run-progress").get_json()
    assert body["latest_run"]["status"] == "stale"


# --- ops hygiene -----------------------------------------------------------------


def test_mark_stale_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    old = db_module.insert_pipeline_run({})
    with db_module.get_connection() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET started_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00", old),
        )
    current = db_module.insert_pipeline_run({})
    marked = db_module.mark_stale_runs(except_id=current)
    assert marked == 1
    runs = {r["id"]: r["status"] for r in db_module.get_recent_pipeline_runs(5)}
    assert runs[old] == "stale"
    assert runs[current] == "running"


def test_mark_stale_runs_keeps_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    db_module.insert_pipeline_run({})
    assert db_module.mark_stale_runs() == 0
    assert db_module.get_recent_pipeline_runs(1)[0]["status"] == "running"


def test_validate_time():
    from src.config import Settings

    assert Settings.validate_time("09:30", "RUN_TIME") == "09:30"
    for bad in ("9:30", "0930", "25:00", "09:60", "", "nope"):
        with pytest.raises(ValueError):
            Settings.validate_time(bad, "RUN_TIME")


def test_list_recent_exports_empty(tmp_path, monkeypatch):
    import src.export.csv_exporter as csv_exporter

    monkeypatch.setattr(csv_exporter, "_ensure_exports_dir", lambda: tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    assert csv_exporter.list_recent_exports() == []
