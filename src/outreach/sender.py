"""
Outreach sender — pushes approved email drafts to Snov.io campaign list.

Each prospect is added to the Snov list (auto-enrolls in active campaign),
then the draft status is flipped to 'sent'.

Guards (shared queue semantics with the Resend path):
- suppressed addresses are skipped, never enrolled;
- drafts with a future scheduled_for are skipped until due.
"""

import logging
from datetime import UTC, datetime

from src.config import settings
from src.database import db
from src.snov.client import SnovClient

logger = logging.getLogger(__name__)


def _scheduled_for_future(draft: dict, now: datetime) -> bool:
    scheduled_for = draft.get("scheduled_for")
    if not scheduled_for:
        return False
    try:
        sched_dt = datetime.fromisoformat(scheduled_for).replace(tzinfo=UTC)
        return sched_dt > now
    except (ValueError, TypeError):
        return False


def send_approved_drafts() -> dict:
    """
    Fetch all approved drafts, push each prospect to Snov.io, update status.

    Returns stats dict: {total, sent, failed, errors}.
    """
    snov_list_id = settings.snov_list_id
    if not snov_list_id:
        logger.error("SNOV_LIST_ID not set — cannot send drafts")
        return {"total": 0, "sent": 0, "failed": 0, "errors": ["SNOV_LIST_ID not set"]}

    drafts = db.get_approved_drafts_with_prospects()
    stats = {
        "total": len(drafts),
        "sent": 0,
        "failed": 0,
        "skipped_suppressed": 0,
        "skipped_scheduled": 0,
        "skipped_expired": 0,
        "errors": [],
    }

    if not drafts:
        logger.info("No approved drafts to send")
        return stats

    logger.info(
        "Sending %d approved drafts to Snov.io list %s", len(drafts), snov_list_id
    )
    snov = SnovClient()
    now = datetime.now(UTC)

    for draft in drafts:
        email = draft["prospect_email"]
        if db.is_suppressed(email):
            stats["skipped_suppressed"] += 1
            logger.info("Skipping suppressed address %s", email)
            continue
        if _scheduled_for_future(draft, now):
            stats["skipped_scheduled"] += 1
            logger.debug(
                "Draft #%d scheduled for %s, skipping",
                draft["id"],
                draft.get("scheduled_for"),
            )
            continue
        if db.posting_is_expired(draft.get("job_posting_id")):
            stats["skipped_expired"] += 1
            logger.info("Skipping draft #%d: job posting expired", draft["id"])
            continue
        from src.outreach.deliverability import check_draft, gate_allows

        gate = check_draft(draft.get("subject", ""), draft.get("body", ""))
        if not gate_allows(gate["score"]):
            stats["failed"] += 1
            stats["errors"].append(
                f"Draft #{draft['id']} blocked by deliverability gate"
            )
            logger.warning(
                "Draft #%d blocked by deliverability gate: %s",
                draft["id"],
                gate["issues"],
            )
            continue
        for issue in gate["issues"]:
            logger.debug("Draft #%d deliverability: %s", draft["id"], issue)
        try:
            prospect = {
                "email": draft["prospect_email"],
                "first_name": draft.get("first_name", ""),
                "last_name": draft.get("last_name", ""),
                "full_name": draft.get("prospect_name", ""),
                "position": draft.get("prospect_title", ""),
                "company_name": draft.get("company_name", ""),
                "company_domain": draft.get("company_domain", ""),
            }

            added = snov.add_prospect_to_list(snov_list_id, prospect)

            if added:
                sent_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
                db.update_email_draft(
                    draft["id"],
                    {
                        "status": "sent",
                        "sent_at": sent_at,
                    },
                )
                db.log_outreach(
                    {
                        "prospect_id": draft["prospect_id"],
                        "campaign_id": snov_list_id,
                        "status": "sent_to_snov",
                        "sent_at": sent_at,
                        "notes": f"Approved draft #{draft['id']} pushed to Snov list {snov_list_id}",
                    }
                )
                stats["sent"] += 1
                logger.info(
                    "Sent draft #%d for %s", draft["id"], draft["prospect_email"]
                )
            else:
                stats["failed"] += 1
                error_msg = f"Snov.io rejected prospect {draft['prospect_email']}"
                stats["errors"].append(error_msg)
                logger.warning(error_msg)

        except Exception as exc:
            stats["failed"] += 1
            error_msg = f"Error sending draft #{draft['id']}: {exc}"
            stats["errors"].append(error_msg)
            logger.error(error_msg, exc_info=True)

    logger.info(
        "Send job complete: %d/%d sent, %d failed",
        stats["sent"],
        stats["total"],
        stats["failed"],
    )
    return stats
