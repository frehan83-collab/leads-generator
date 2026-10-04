"""Lead-score product surface: dashboard widget, /scores, profile, exports."""

import src.database.db as db_module


def _client(monkeypatch):
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _seed(tmp_path, monkeypatch, domain="acme.no", score=None):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    pid = db_module.insert_job_posting(
        {
            "external_id": "x1",
            "title": "Daglig leder",
            "company_name": "Acme AS",
            "company_domain": domain,
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO prospects (job_posting_id, full_name, email, company_domain,"
            " company_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, "Ann A", f"a@{domain}", domain, "Acme AS", "2024-01-01T09:00:00"),
        )
        prid = cur.lastrowid
    if score is not None:
        db_module.upsert_lead_score(
            domain, score, "hot" if score >= 70 else "warm", "{}"
        )
    return prid


def test_dashboard_hot_widget_uses_v2(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, score=85)
    html = _client(monkeypatch).get("/").data.decode()
    assert "85" in html


def test_dashboard_falls_back_without_scores(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, score=None)
    resp = _client(monkeypatch).get("/")
    assert resp.status_code == 200
    assert "Hot Prospects" in resp.data.decode()


def test_scores_page_lists_domains_and_calibration(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, domain="acme.no", score=85)
    html = _client(monkeypatch).get("/scores").data.decode()
    assert "acme.no" in html
    assert "85" in html
    assert "Calibration" in html


def test_scores_page_empty_state(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, score=None)
    html = _client(monkeypatch).get("/scores").data.decode()
    assert "No scores yet" in html


def test_profile_shows_score_card(tmp_path, monkeypatch):
    prid = _seed(tmp_path, monkeypatch, score=85)
    html = _client(monkeypatch).get(f"/prospects/{prid}/profile").data.decode()
    assert "Lead Score" in html
    assert "85" in html


def test_export_rows_carry_scores(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, score=85)
    rows = db_module.get_prospects_for_export()
    assert rows[0]["lead_score"] == 85
    assert rows[0]["lead_level"] == "hot"
