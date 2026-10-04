"""Page-size prefs, lead quality flags, BRREG domain fallback."""

import src.database.db as db_module


def _client(monkeypatch):
    import src.web.app as app_module
    from src.config import Settings

    monkeypatch.setattr(app_module, "settings", Settings())
    app = app_module.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _seed_prospects(n, tmp_path, monkeypatch, domain="acme.no"):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    pid = db_module.insert_job_posting(
        {
            "external_id": "x1",
            "title": "T",
            "company_name": "C",
            "company_domain": domain,
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    with db_module.get_connection() as conn:
        for i in range(n):
            conn.execute(
                "INSERT INTO prospects (job_posting_id, full_name, email, company_domain,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (pid, f"Person {i}", f"p{i}@acme.no", domain, "2024-01-01T09:00:00"),
            )


# --- page size ---------------------------------------------------------------


def test_per_page_param(tmp_path, monkeypatch):
    _seed_prospects(30, tmp_path, monkeypatch)
    client = _client(monkeypatch)
    html25 = client.get("/prospects?per_page=25").data.decode()
    assert "1-25" in html25
    assert "25 / page" in html25 or 'value="25" selected' in html25


def test_per_page_invalid_falls_back(tmp_path, monkeypatch):
    _seed_prospects(60, tmp_path, monkeypatch)
    client = _client(monkeypatch)
    html = client.get("/prospects?per_page=999").data.decode()
    assert "1-50" in html  # default 50 shows 1-50 of 60


def test_per_page_remembered_in_session(tmp_path, monkeypatch):
    _seed_prospects(30, tmp_path, monkeypatch)
    client = _client(monkeypatch)
    client.get("/prospects?per_page=25")
    html = client.get("/prospects").data.decode()
    assert "1-25" in html


# --- lead quality ---------------------------------------------------------------


def test_is_role_address():
    from src.scoring.lead_quality import is_role_address

    assert is_role_address("info@acme.no") is True
    assert is_role_address("support.nordic@acme.no") is True
    assert is_role_address("post@acme.no") is False  # conservative: real target
    assert is_role_address("hr@acme.no") is False
    assert is_role_address("ola.nordmann@acme.no") is False
    assert is_role_address("") is False
    assert is_role_address(None) is False


def test_identity_confidence():
    from src.scoring.lead_quality import identity_confidence

    assert identity_confidence({"first_name": "Ann", "last_name": "Aasen"}) == 2
    assert identity_confidence({"full_name": "frida"}) == 1
    assert identity_confidence({}) == 0
    assert identity_confidence({"first_name": "A"}) == 0


def test_hot_widget_excludes_role_inbox(tmp_path, monkeypatch):
    _seed_prospects(0, tmp_path, monkeypatch)
    with db_module.get_connection() as conn:
        pid = conn.execute("SELECT id FROM job_postings LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO prospects (job_posting_id, full_name, email, company_domain,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, "Boss Person", "boss@acme.no", "acme.no", "2024-01-01T09:00:00"),
        )
        conn.execute(
            "INSERT INTO prospects (job_posting_id, full_name, email, company_domain,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, "Info Desk", "info@acme.no", "acme.no", "2024-01-01T09:00:00"),
        )
    db_module.upsert_lead_score("acme.no", 90, "hot", "{}")
    html = _client(monkeypatch).get("/").data.decode()
    # scope to the Hot Prospects widget (Recent Activity lists everyone)
    widget = html.split("Hot Prospects", 1)[1].split("Recent Activity", 1)[0]
    assert "Boss Person" in widget
    assert "Info Desk" not in widget


# --- BRREG domain fallback ----------------------------------------------------------


def test_get_company_website_by_org(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    with db_module.get_connection() as conn:
        conn.execute(
            "INSERT INTO companies (org_number, name, website, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                "123456789",
                "Acme AS",
                "https://WWW.Acme.NO",
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
            ),
        )
    assert db_module.get_company_website("123456789") == "acme.no"
    assert db_module.get_company_website("000") is None


def test_get_company_website_fuzzy_name(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    with db_module.get_connection() as conn:
        conn.execute(
            "INSERT INTO companies (org_number, name, website, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                "1",
                "Arctic Seafarm Nesna AS",
                "arcticseafarm.no",
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
            ),
        )
    assert (
        db_module.get_company_website(company_name="Arctic Seafarm Nesna")
        == "arcticseafarm.no"
    )


def test_resolve_prefers_brreg_over_snov(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    monkeypatch.setitem(os.environ, "SNOV_CLIENT_ID", "id")
    monkeypatch.setitem(os.environ, "SNOV_CLIENT_SECRET", "secret")
    from unittest.mock import MagicMock

    from src.pipeline.lead_pipeline import LeadPipeline

    pipe = LeadPipeline(snov_list_id="L1", sources=["finn"])
    pipe.snov = MagicMock()
    with db_module.get_connection() as conn:
        conn.execute(
            "INSERT INTO companies (org_number, name, website, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("9", "Mowi ASA", "mowi.com", "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        )
    domain = pipe._resolve_domain(
        "Mowi", {"company_name": "Mowi", "org_number": "9", "url": None}
    )
    assert domain == "mowi.com"
    pipe.snov.find_domain_by_company_name.assert_not_called()
