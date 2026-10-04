"""Daily action list: the rep's morning page.

Three ranked sections, all derived from live data:
- call_now: engaged but unanswered prospects (opened/clicked, no reply),
  hottest companies first.
- review: unreviewed drafts at the highest-scored companies.
- hot_new: valid, unsuppressed prospects at warm+ companies with no
  outreach started yet.
"""

import logging

logger = logging.getLogger(__name__)

CALL_LIMIT = 5
REVIEW_LIMIT = 5
HOT_NEW_LIMIT = 5
HOT_THRESHOLD = 45


def get_today_actions() -> dict:
    """Return {call_now, review, hot_new} lists for /actions."""
    return {
        "call_now": _calls(),
        "review": _reviews(),
        "hot_new": _hot_new(),
    }


def _calls(limit: int = CALL_LIMIT) -> list[dict]:
    from src.database import db

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT p.id, p.full_name, p.position, p.email, p.company_name,
                      p.company_domain, COALESCE(ls.score, 0) AS score,
                      MAX(ee.created_at) AS last_engagement,
                      (SELECT ed.subject FROM email_drafts ed
                        JOIN email_events e2 ON e2.draft_id = ed.id
                        WHERE ed.prospect_id = p.id
                          AND e2.event_type IN ('opened', 'clicked')
                        ORDER BY e2.created_at DESC LIMIT 1) AS engaged_subject
               FROM prospects p
               JOIN email_drafts ed ON ed.prospect_id = p.id
               JOIN email_events ee ON ee.draft_id = ed.id
                 AND ee.event_type IN ('opened', 'clicked')
               LEFT JOIN lead_scores ls
                 ON LOWER(ls.domain) = LOWER(p.company_domain)
               WHERE NOT EXISTS (
                     SELECT 1 FROM email_events e2
                     JOIN email_drafts d2 ON d2.id = e2.draft_id
                     WHERE d2.prospect_id = p.id AND e2.event_type = 'replied'
                   )
                 AND NOT EXISTS (
                     SELECT 1 FROM prospect_stages ps
                     WHERE ps.prospect_id = p.id
                       AND ps.stage IN ('Replied', 'Meeting', 'Won', 'Lost')
                   )
                 AND NOT EXISTS (
                     SELECT 1 FROM suppressions s
                     WHERE LOWER(s.email) = LOWER(p.email)
                   )
               GROUP BY p.id
               ORDER BY score DESC, last_engagement DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _reviews(limit: int = REVIEW_LIMIT) -> list[dict]:
    from src.database import db

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT ed.id, ed.subject, p.full_name, p.company_name,
                      COALESCE(ls.score, 0) AS score
               FROM email_drafts ed
               JOIN prospects p ON ed.prospect_id = p.id
               LEFT JOIN lead_scores ls
                 ON LOWER(ls.domain) = LOWER(p.company_domain)
               WHERE ed.status = 'draft'
               ORDER BY score DESC, ed.created_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _hot_new(limit: int = HOT_NEW_LIMIT) -> list[dict]:
    from src.database import db

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT p.id, p.full_name, p.position, p.email, p.company_name,
                      ls.score
               FROM prospects p
               JOIN lead_scores ls
                 ON LOWER(ls.domain) = LOWER(p.company_domain)
               WHERE ls.score >= ?
                 AND p.email_status = 'valid'
                 AND NOT EXISTS (
                     SELECT 1 FROM email_drafts ed
                     WHERE ed.prospect_id = p.id
                       AND ed.status IN ('sent', 'approved')
                   )
                 AND NOT EXISTS (
                     SELECT 1 FROM suppressions s
                     WHERE LOWER(s.email) = LOWER(p.email)
                   )
               ORDER BY ls.score DESC, p.created_at ASC
               LIMIT ?""",
            (HOT_THRESHOLD, limit),
        ).fetchall()
    return [dict(r) for r in rows]
