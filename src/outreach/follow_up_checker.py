"""Automated follow-up sequence engine.

Checks for sent emails with no opens after N days and creates + sends follow-ups.
"""

import logging
from typing import Optional

from src.config import settings
from src.database import db
from src.emails.follow_up_templates import FOLLOW_UP_TEMPLATES

logger = logging.getLogger(__name__)


def create_follow_up_draft(
    parent_draft_id: int,
    step: int,
    auto_approve: bool | None = None,
) -> Optional[int]:
    """Create a follow-up draft for a parent draft.

    Args:
        parent_draft_id: The draft ID of the original (or previous step) email.
        step: The sequence step number (2 for first follow-up, 3 for second).
        auto_approve: Mark the draft 'approved' immediately. Defaults to the
            FOLLOWUP_AUTO_SEND setting (default False — drafts await review).

    Returns:
        New draft ID if created, None otherwise.
    """
    parent = db.get_email_draft_by_id(parent_draft_id)
    if not parent:
        logger.warning("Parent draft #%d not found", parent_draft_id)
        return None

    prospect = db.get_prospect_by_id(parent["prospect_id"])
    if not prospect:
        logger.warning("Prospect not found for parent draft #%d", parent_draft_id)
        return None

    template_fn = FOLLOW_UP_TEMPLATES.get(step)
    if not template_fn:
        logger.warning("No follow-up template for step %d", step)
        return None

    # Get the original subject (strip any existing "Re: " prefixes from parent)
    original_subject = parent["subject"]
    if original_subject.startswith("Re: "):
        original_subject = original_subject[4:]

    try:
        subject, body = template_fn(prospect, original_subject)
    except Exception as exc:
        logger.warning("Failed to generate follow-up for draft #%d step %d: %s",
                       parent_draft_id, step, exc)
        return None

    draft_data = {
        "prospect_id": parent["prospect_id"],
        "job_posting_id": parent.get("job_posting_id"),
        "template_name": f"follow_up_{step}",
        "subject": subject,
        "body": body,
        # Safe default: drafts await human approval unless auto-send is on.
        "status": "approved" if (settings.followup_auto_send if auto_approve is None else auto_approve) else "draft",
    }

    draft_id = db.insert_email_draft(draft_data)
    if draft_id:
        # Set sequence metadata
        db.update_email_draft(draft_id, {
            "sequence_step": step,
            "parent_draft_id": parent_draft_id,
        })
        logger.info(
            "Created follow-up draft #%d (step %d) for prospect %s",
            draft_id, step, prospect.get("email", "?"),
        )

    return draft_id


def check_and_create_followups(
    min_days: int = 3,
    max_step: int = 3,
    auto_send: bool | None = None,
) -> dict:
    """Check for sent emails needing follow-ups and create/send them.

    Args:
        min_days: Minimum days since last email before triggering follow-up.
        max_step: Maximum sequence step (e.g., 3 = original + 2 follow-ups).
        auto_send: If True, immediately send follow-ups via Resend.
            Defaults to the FOLLOWUP_AUTO_SEND setting (default False).

    Returns:
        Stats dict: {checked, followups_created, followups_sent, errors}
    """
    if auto_send is None:
        auto_send = settings.followup_auto_send
    stats = {"checked": 0, "followups_created": 0, "followups_sent": 0, "errors": []}

    try:
        drafts = db.get_sent_drafts_needing_followup(
            min_days=min_days, max_step=max_step
        )
    except Exception as exc:
        logger.error("Failed to fetch drafts needing follow-up: %s", exc)
        stats["errors"].append(str(exc))
        return stats

    stats["checked"] = len(drafts)
    logger.info("Found %d drafts needing follow-up", len(drafts))

    for draft in drafts:
        current_step = (draft.get("sequence_step") or 1)
        next_step = current_step + 1

        new_draft_id = create_follow_up_draft(draft["id"], next_step, auto_approve=auto_send)
        if not new_draft_id:
            stats["errors"].append(f"Failed to create follow-up for draft #{draft['id']}")
            continue

        stats["followups_created"] += 1

        if auto_send:
            try:
                from src.outreach.email_sender import send_email_direct
                result = send_email_direct(new_draft_id)
                if result["success"]:
                    stats["followups_sent"] += 1
                    logger.info("Auto-sent follow-up draft #%d", new_draft_id)
                else:
                    stats["errors"].append(
                        f"Follow-up #{new_draft_id} send failed: {result['error']}"
                    )
            except Exception as exc:
                stats["errors"].append(f"Follow-up #{new_draft_id} send error: {exc}")

    logger.info("Follow-up check complete: %s", stats)
    return stats
