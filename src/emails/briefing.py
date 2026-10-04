"""Pre-meeting research briefs — deterministic assembly from stored data.

No external calls: everything comes from the DB (profile, BRREG row,
postings, outreach history, score). Talking points are rule-generated
from real signals so every claim in a brief is traceable.
"""

import logging

logger = logging.getLogger(__name__)


def build_brief(prospect_id: int) -> dict | None:
    """Assemble a meeting brief for a prospect. Returns None if unknown."""
    from src.database import db

    profile = db.get_prospect_full_profile(prospect_id)
    if not profile:
        return None

    domain = profile.get("company_domain") or ""
    score = db.get_lead_score(domain) if domain else None
    postings = _company_postings(domain)
    timeline = _outreach_timeline(prospect_id)
    talking_points = _talking_points(profile, score, postings, timeline)
    next_step = _suggested_next_step(profile, timeline)

    return {
        "prospect": profile,
        "company": profile.get("company_info"),
        "score": score,
        "postings": postings,
        "timeline": timeline,
        "talking_points": talking_points,
        "next_step": next_step,
    }


def _company_postings(domain: str, limit: int = 5) -> list[dict]:
    if not domain:
        return []
    from src.database import db

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT title, location, url, published_at, scraped_at, source
               FROM job_postings WHERE company_domain = ?
               ORDER BY scraped_at DESC LIMIT ?""",
            (domain, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _outreach_timeline(prospect_id: int) -> list[dict]:
    """Chronological outreach events: drafts sent + opens/clicks."""
    from src.database import db

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT ed.subject, ed.status, ed.sent_at, ed.open_count,
                      ed.click_count, ed.template_name
               FROM email_drafts ed WHERE ed.prospect_id = ?
               ORDER BY ed.created_at ASC""",
            (prospect_id,),
        ).fetchall()
    timeline = []
    for row in rows:
        row = dict(row)
        if row.get("sent_at"):
            timeline.append(
                {"kind": "sent", "text": row["subject"] or row["template_name"]}
            )
        if (row.get("open_count") or 0) > 0:
            timeline.append(
                {
                    "kind": "opened",
                    "text": f"Opened ×{row['open_count']}: {row['subject']}",
                }
            )
        if (row.get("click_count") or 0) > 0:
            timeline.append(
                {
                    "kind": "clicked",
                    "text": f"Clicked ×{row['click_count']}: {row['subject']}",
                }
            )
    return timeline


def _talking_points(
    profile: dict, score: dict | None, postings: list[dict], timeline: list[dict]
) -> list[str]:
    """Rule-generated, signal-backed talking points."""
    points: list[str] = []
    name = (profile.get("first_name") or profile.get("full_name") or "them").split()[0]

    if postings:
        latest = postings[0]
        points.append(
            f"Hiring now: “{latest.get('title', 'a role')}”"
            + (f" ({latest.get('location')})" if latest.get("location") else "")
            + " — expansion signal, ask what triggered the hire."
        )
        if len(postings) > 1:
            points.append(
                f"{len(postings)} open roles tracked — multi-hire motion, "
                "ask about team growth plans."
            )

    company_info = profile.get("company_info") or {}
    employees = company_info.get("employee_count") or 0
    if 10 <= employees <= 249:
        points.append(
            f"{employees} employees — typical Sperton client profile "
            "(mid-size companies hire recruiters most)."
        )
    nace_desc = company_info.get("nace_description") or ""
    if nace_desc:
        points.append(f"Industry: {nace_desc} — prepare one relevant case story.")

    engaged = [t for t in timeline if t["kind"] in ("opened", "clicked")]
    if engaged:
        points.append(
            f"Already engaged: {engaged[-1]['text']} — reference it in the first 30 seconds."
        )
    else:
        points.append(
            f"Cold so far — lead with the {postings[0]['title'] if postings else 'role'} "
            f"angle, not with Sperton."
        )

    if score and score.get("level") in ("hot", "warm"):
        points.append(
            f"Scored {score['score']} ({score['level']}) — prioritize a fast follow-up "
            "while the signal is fresh."
        )

    position = (profile.get("position") or "").lower()
    if any(
        k in position
        for k in ("daglig", "ceo", "director", "leder", "sjef", "manager", "head")
    ):
        points.append(
            f"{name} is a decision-maker ({profile.get('position')}) — "
            "you can talk commercials, not just process."
        )
    return points


def _suggested_next_step(profile: dict, timeline: list[dict]) -> str:
    stage = (
        ((profile.get("current_stage") or {}).get("stage"))
        if isinstance(profile.get("current_stage"), dict)
        else profile.get("current_stage")
    )
    sent = any(t["kind"] == "sent" for t in timeline)
    engaged = any(t["kind"] in ("opened", "clicked") for t in timeline)
    if stage in ("Meeting", "Won"):
        return "Relationship mode — no pitch. Ask for referrals into peer companies."
    if stage == "Replied":
        return "They answered: propose two concrete meeting times within 48 hours."
    if engaged:
        return "Warm: call referencing the exact email they opened, then follow up in writing."
    if sent:
        return "Sent but silent: one short follow-up call, then pause a week."
    return "First touch: short, role-specific opener tied to their hiring signal."
