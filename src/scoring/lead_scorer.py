"""
Lead scoring v2 — transparent, component-based company scores (0-100).

Components:
- fit (0-40):        firmographic fit from BRREG data (size, industry, identity)
- demand (0-35):     hiring demand from posting frequency/recency (v1 intent)
- engagement (0-25): observed outreach engagement (opens/clicks/replies/stages)

Scores are stored per company domain in lead_scores with the full component
breakdown, so any score is explainable. calibration_report() measures win
rate per score band from actual CRM outcomes (Won/Lost).
"""

import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# Sweet-spot company size for Sperton recruitment (employees)
SIZE_SWEET_MIN = 10
SIZE_SWEET_MAX = 249

# NACE divisions with full fit weight (seafood value chain + adjacent)
TARGET_NACE_PREFIXES = ("03.", "10.", "46.3", "46.7", "50.2", "52.2")

LEVELS = ((70, "hot"), (45, "warm"), (20, "medium"), (0, "cold"))


def level_for(score: int) -> str:
    for threshold, level in LEVELS:
        if score >= threshold:
            return level
    return "cold"


def _fit_score(
    company: dict | None, domain: str, org_number: str | None
) -> tuple[int, dict]:
    """Firmographic fit from the companies row (BRREG import). Max 40."""
    details: dict = {}
    if not company:
        # No BRREG row: partial credit for validated identity signals only.
        score = 0
        if org_number:
            score += 10
            details["org_validated"] = True
        if domain:
            score += 5
            details["domain_known"] = True
        return min(score, 40), details

    score = 0
    employees = company.get("employee_count") or 0
    if SIZE_SWEET_MIN <= employees <= SIZE_SWEET_MAX:
        score += 15
        details["size_band"] = "sweet_spot"
    elif 1 <= employees < SIZE_SWEET_MIN:
        score += 8
        details["size_band"] = "small"
    elif employees > SIZE_SWEET_MAX:
        score += 10
        details["size_band"] = "large"
    else:
        score += 5
        details["size_band"] = "unknown"

    nace = company.get("nace_code") or ""
    if nace.startswith(TARGET_NACE_PREFIXES):
        score += 10
        details["nace_target"] = True
    else:
        details["nace_target"] = False

    if company.get("website"):
        score += 5
        details["has_website"] = True
    if company.get("org_number") or org_number:
        score += 10
        details["org_validated"] = True
    return min(score, 40), details


def _demand_score(intent: dict, days_since_last: int | None) -> tuple[int, dict]:
    """Hiring demand from v1 intent signals (0-100) rescaled to 0-35,
    halved when the latest posting is stale (>60 days)."""
    base = min(intent.get("score", 0), 100) * 35 / 100
    details = {"intent_v1": intent.get("score", 0)}
    if days_since_last is not None:
        details["days_since_last"] = days_since_last
        if days_since_last > 60:
            base /= 2
            details["stale_decay"] = True
    return round(base), details


def _engagement_score(events: dict) -> tuple[int, dict]:
    """Observed engagement, best-signal-wins. Max 25."""
    if events.get("replied") or events.get("meeting") or events.get("won"):
        return 25, {"best": "reply_or_further"}
    if events.get("clicked"):
        return 15, {"best": "click"}
    if events.get("opened"):
        return 10, {"best": "open"}
    if events.get("delivered"):
        return 5, {"best": "delivered"}
    if events.get("bounced"):
        return 0, {"best": "bounced_only"}
    return 0, {"best": "no_contact"}


def score_company(
    domain: str,
    company: dict | None,
    intent: dict,
    days_since_last: int | None,
    events: dict,
    org_number: str | None = None,
) -> dict:
    """Combine components into a final score dict (pure function, testable)."""
    fit, fit_details = _fit_score(company, domain, org_number)
    demand, demand_details = _demand_score(intent, days_since_last)
    engagement, engagement_details = _engagement_score(events)
    total = min(fit + demand + engagement, 100)
    return {
        "domain": domain,
        "score": total,
        "level": level_for(total),
        "components": {
            "fit": fit,
            "demand": demand,
            "engagement": engagement,
        },
        "details": {
            "fit": fit_details,
            "demand": demand_details,
            "engagement": engagement_details,
        },
        "computed_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }


# ------------------------------------------------------------------
# DB-backed helpers
# ------------------------------------------------------------------


def _company_row(
    domain: str,
    org_number: str | None,
    company_name: str | None = None,
    _names_cache: list[tuple[str, str]] | None = None,
) -> dict | None:
    """Find the BRREG row: exact org → normalized website → fuzzy name."""
    from src.database import db

    domain = (domain or "").lower()
    with db.get_connection() as conn:
        if org_number:
            row = conn.execute(
                "SELECT * FROM companies WHERE org_number = ?", (org_number,)
            ).fetchone()
            if row:
                return dict(row)
        row = conn.execute(
            """SELECT * FROM companies
               WHERE LOWER(website) IN (?, ?) LIMIT 1""",
            (domain, f"www.{domain}"),
        ).fetchone()
        if row:
            return dict(row)
    # Fallback: fuzzy name match (posting names carry AS/ASA suffixes etc.)
    if company_name:
        from rapidfuzz import fuzz, process

        if _names_cache is None:
            with db.get_connection() as conn:
                _names_cache = [
                    (r[0], r[1])
                    for r in conn.execute(
                        "SELECT name, org_number FROM companies"
                    ).fetchall()
                ]
        names = [n for n, _ in _names_cache]
        match = process.extractOne(
            company_name, names, scorer=fuzz.token_sort_ratio, score_cutoff=85
        )
        if match:
            org = dict(zip(names, [o for _, o in _names_cache], strict=True))[match[0]]
            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM companies WHERE org_number = ?", (org,)
                ).fetchone()
                return dict(row) if row else None
    return None


def _engagement_events(domain: str) -> dict:
    """Aggregate best outreach signals for a domain across prospects."""
    from src.database import db

    with db.get_connection() as conn:
        event_rows = conn.execute(
            """SELECT ee.event_type, COUNT(*) FROM email_events ee
               JOIN email_drafts ed ON ee.draft_id = ed.id
               JOIN prospects p ON ed.prospect_id = p.id
               WHERE LOWER(p.company_domain) = ?
               GROUP BY ee.event_type""",
            (domain,),
        ).fetchall()
        events = {r[0]: r[1] for r in event_rows}
        stage_rows = conn.execute(
            """SELECT ps.stage, COUNT(*) FROM prospect_stages ps
               JOIN prospects p ON ps.prospect_id = p.id
               WHERE LOWER(p.company_domain) = ?
               GROUP BY ps.stage""",
            (domain,),
        ).fetchall()
        stages = {r[0]: r[1] for r in stage_rows}
    if stages.get("Replied") or stages.get("Meeting") or stages.get("Won"):
        events["replied"] = True
    if stages.get("Meeting") or stages.get("Won"):
        events["meeting"] = True
    if stages.get("Won"):
        events["won"] = True
    if stages.get("Lost"):
        events["lost"] = True
    return events


def _days_since_last_posting(domain: str) -> int | None:
    from src.database import db

    with db.get_connection() as conn:
        row = conn.execute(
            """SELECT MAX(scraped_at) FROM job_postings
               WHERE LOWER(company_domain) = ?""",
            (domain,),
        ).fetchone()
    if not row or not row[0]:
        return None
    try:
        last = datetime.fromisoformat(row[0])
        delta = datetime.now() - last
        return max(delta.days, 0)
    except (ValueError, TypeError):
        return None


def score_domain(
    domain: str, org_number: str | None = None, company_name: str | None = None
) -> dict:
    """Score one company domain end-to-end and persist to lead_scores."""
    from src.database import db

    domain = (domain or "").lower()
    company = _company_row(domain, org_number, company_name)
    intent = db.get_company_intent_signals(domain)
    days = _days_since_last_posting(domain)
    events = _engagement_events(domain)
    result = score_company(domain, company, intent, days, events, org_number)
    db.upsert_lead_score(
        domain,
        result["score"],
        result["level"],
        json.dumps({"components": result["components"], "details": result["details"]}),
    )
    return result


def score_all_domains() -> dict:
    """Score every domain with postings. Returns {scored, hot, warm}."""
    from src.database import db

    with db.get_connection() as conn:
        domains = [
            (r[0], r[1], r[2])
            for r in conn.execute(
                """SELECT company_domain, MAX(org_number), MAX(company_name)
                   FROM job_postings
                   WHERE company_domain IS NOT NULL
                   GROUP BY LOWER(company_domain)"""
            ).fetchall()
        ]
    stats = {"scored": 0, "hot": 0, "warm": 0}
    for domain, org_number, company_name in domains:
        if not domain:
            continue
        try:
            result = score_domain(domain, org_number, company_name)
            stats["scored"] += 1
            if result["level"] == "hot":
                stats["hot"] += 1
            elif result["level"] == "warm":
                stats["warm"] += 1
        except Exception as exc:
            logger.warning("Scoring failed for %s: %s", domain, exc)
    return stats


def calibration_report() -> list[dict]:
    """Win rate per score band from actual CRM outcomes.

    Joins lead_scores to prospect stages by domain. Bands with no decided
    outcomes report null win_rate (not zero — absence of evidence).
    """
    from src.database import db

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT
                   CASE WHEN ls.score >= 70 THEN 'hot'
                        WHEN ls.score >= 45 THEN 'warm'
                        WHEN ls.score >= 20 THEN 'medium'
                        ELSE 'cold' END AS band,
                   COUNT(DISTINCT p.id) AS prospects,
                   SUM(CASE WHEN ps.stage = 'Won' THEN 1 ELSE 0 END) AS won,
                   SUM(CASE WHEN ps.stage = 'Lost' THEN 1 ELSE 0 END) AS lost
               FROM lead_scores ls
               JOIN prospects p ON LOWER(p.company_domain) = LOWER(ls.domain)
               LEFT JOIN prospect_stages ps ON ps.prospect_id = p.id
                   AND ps.stage IN ('Won', 'Lost')
               GROUP BY band"""
        ).fetchall()
    report = []
    for band, prospects, won, lost in rows:
        won, lost = won or 0, lost or 0
        decided = won + lost
        report.append(
            {
                "band": band,
                "prospects": prospects,
                "won": won,
                "lost": lost,
                "win_rate": round(won / decided, 3) if decided else None,
            }
        )
    order = {"hot": 0, "warm": 1, "medium": 2, "cold": 3}
    return sorted(report, key=lambda r: order.get(r["band"], 9))
