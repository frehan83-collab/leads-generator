"""Lead scoring v2 tests: components, levels, persistence, calibration."""

import json

import src.database.db as db_module
from src.scoring.lead_scorer import (
    calibration_report,
    level_for,
    score_company,
    score_domain,
)


def _intent(score=80):
    return {
        "score": score,
        "level": "hot",
        "total_postings": 5,
        "recent_postings": 3,
        "keyword_count": 2,
    }


# --- pure scoring ----------------------------------------------------------


def test_perfect_company_scores_hot():
    company = {
        "employee_count": 50,
        "nace_code": "03.21",
        "website": "https://acme.no",
        "org_number": "123456789",
    }
    out = score_company(
        "acme.no", company, _intent(), 5, {"replied": True}, org_number="123456789"
    )
    assert out["level"] == "hot"
    assert out["components"]["fit"] == 40
    assert out["components"]["engagement"] == 25
    assert out["score"] <= 100


def test_unknown_company_gets_partial_fit():
    out = score_company("x.no", None, _intent(0), None, {}, org_number="1")
    assert out["components"]["fit"] == 15  # org + domain only
    assert out["components"]["demand"] == 0
    assert out["components"]["engagement"] == 0
    assert out["level"] == "cold"


def test_stale_demand_halved():
    fresh = score_company("x.no", None, _intent(100), 5, {})
    stale = score_company("x.no", None, _intent(100), 90, {})
    assert fresh["components"]["demand"] == 35
    assert stale["components"]["demand"] == 18  # 35 / 2 rounded
    assert stale["details"]["demand"]["stale_decay"] is True


def test_engagement_ladder():
    assert (
        score_company("x.no", None, _intent(0), None, {})["components"]["engagement"]
        == 0
    )
    assert (
        score_company("x.no", None, _intent(0), None, {"delivered": 1})["components"][
            "engagement"
        ]
        == 5
    )
    assert (
        score_company("x.no", None, _intent(0), None, {"opened": 1})["components"][
            "engagement"
        ]
        == 10
    )
    assert (
        score_company("x.no", None, _intent(0), None, {"clicked": 1})["components"][
            "engagement"
        ]
        == 15
    )
    assert (
        score_company("x.no", None, _intent(0), None, {"bounced": 1})["components"][
            "engagement"
        ]
        == 0
    )


def test_levels():
    assert level_for(100) == "hot"
    assert level_for(70) == "hot"
    assert level_for(69) == "warm"
    assert level_for(45) == "warm"
    assert level_for(44) == "medium"
    assert level_for(20) == "medium"
    assert level_for(19) == "cold"


# --- persistence + calibration (temp DB) -------------------------------------


def test_score_domain_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()
    db_module.insert_job_posting(
        {
            "external_id": "1",
            "title": "T",
            "company_name": "Acme",
            "company_domain": "acme.no",
            "scraped_at": "2024-01-01T09:00:00",
        }
    )
    out = score_domain("acme.no")
    rows = db_module.get_lead_scores()
    assert len(rows) == 1
    assert rows[0]["domain"] == "acme.no"
    assert rows[0]["score"] == out["score"]
    assert json.loads(rows[0]["components_json"])["components"]["demand"] > 0


def test_calibration_report_bands(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "t.db")
    db_module.init_db()

    def seed(domain, score, stage):
        pid = db_module.insert_job_posting(
            {
                "external_id": domain,
                "title": "T",
                "company_name": "C",
                "company_domain": domain,
                "scraped_at": "2024-01-01T09:00:00",
            }
        )
        with db_module.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO prospects (job_posting_id, email, company_domain, created_at)"
                " VALUES (?, ?, ?, ?)",
                (pid, f"a@{domain}", domain, "2024-01-01T09:00:00"),
            )
            prid = cur.lastrowid
        db_module.upsert_lead_score(domain, score, level_for(score), "{}")
        db_module.set_prospect_stage(prid, stage, "test")

    seed("hot.no", 90, "Won")
    seed("hot2.no", 80, "Lost")
    seed("cold.no", 10, "Lost")
    seed("undecided.no", 50, "Contacted")

    report = {r["band"]: r for r in calibration_report()}
    assert report["hot"]["win_rate"] == 0.5
    assert report["hot"]["won"] == 1
    assert report["cold"]["win_rate"] == 0.0
    assert report["warm"]["win_rate"] is None  # no decided outcomes
