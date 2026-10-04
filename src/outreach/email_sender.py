"""Direct email sending via Resend API."""

import html
import logging
from datetime import datetime, timezone

import resend

from src.config import settings
from src.database import db

logger = logging.getLogger(__name__)


def _text_to_html(body: str) -> str:
    """Convert plain-text email body to clean HTML."""
    escaped = html.escape(body)
    paragraphs = escaped.split("\n\n")
    html_parts = []
    for p in paragraphs:
        lines = p.strip().replace("\n", "<br>\n")
        if lines:
            html_parts.append(f"<p>{lines}</p>")

    body_html = "\n".join(html_parts)

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.6; color: #1a1a1a; max-width: 600px; margin: 0 auto; padding: 20px;">
{body_html}
</body>
</html>"""


def _send_with_retry(params: dict, max_attempts: int = 3):
    """Send via Resend, retrying only safe-to-retry failures.

    Retried: transport errors (no response received — a retry cannot
    double-send) and rate limits. API rejections (validation, auth,
    application errors including 5xx responses) raise immediately:
    a 5xx may already have sent, so those need operator review, not
    an automatic second POST.
    """
    import time as _time

    import requests as _requests
    from resend.exceptions import RateLimitError, ResendError

    retryable = (
        RateLimitError,
        _requests.exceptions.ConnectionError,
        _requests.exceptions.Timeout,
    )
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return resend.Emails.send(params)
        except retryable as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            logger.warning("Resend send attempt %d/%d failed (%s), retrying",
                           attempt, max_attempts, exc)
            _time.sleep(2.0 * attempt)
        except ResendError:
            raise
    raise last_exc  # pragma: no cover - unreachable


def send_email_direct(draft_id: int) -> dict:
    """Send a single approved draft directly via Resend.

    Returns {"success": bool, "error": str|None, "resend_id": str|None}
    """
    api_key = settings.resend_api_key
    from_email = settings.from_email

    draft = db.get_email_draft_by_id(draft_id)
    if not draft:
        return {"success": False, "error": "Draft not found"}

    if draft["status"] != "approved":
        return {"success": False, "error": f"Draft status is '{draft['status']}', expected 'approved'"}
    if draft.get("sent_at"):
        return {"success": False, "error": "Draft already sent (double-send guard)"}

    if db.is_suppressed(draft.get("prospect_email") or ""):
        return {"success": False, "error": "Recipient is suppressed (bounce/complaint)"}

    if not api_key:
        return {"success": False, "error": "RESEND_API_KEY not configured"}

    resend.api_key = api_key

    try:
        email_html = _text_to_html(draft["body"])

        params = {
            "from": f"{settings.from_name} <{from_email}>",
            "to": [draft["prospect_email"]],
            "subject": draft["subject"],
            "html": email_html,
        }

        result = _send_with_retry(params)
        resend_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)

        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        db.update_email_draft(draft_id, {
            "status": "sent",
            "sent_at": now,
            "resend_id": resend_id,
            "notes": f"sent_via_resend:{resend_id or 'ok'}",
        })
        db.log_outreach({
            "prospect_id": draft["prospect_id"],
            "campaign_id": "resend_direct",
            "status": "sent_via_resend",
            "sent_at": now,
            "notes": f"Draft #{draft_id} sent directly via Resend to {draft['prospect_email']}",
        })

        logger.info("Email sent via Resend to %s (draft #%d, id=%s)", draft["prospect_email"], draft_id, resend_id)
        return {"success": True, "error": None, "resend_id": resend_id}

    except Exception as exc:
        logger.error("Resend send failed for draft #%d: %s", draft_id, exc, exc_info=True)
        return {"success": False, "error": str(exc)}


def send_all_approved_email() -> dict:
    """Send all approved drafts directly via Resend.

    Respects scheduled_for times: if a draft has a scheduled_for timestamp
    in the future, it is skipped until that time arrives.

    Returns {total, sent, failed, skipped_scheduled, errors}.
    """
    api_key = settings.resend_api_key
    if not api_key:
        return {"total": 0, "sent": 0, "failed": 0, "skipped_scheduled": 0, "errors": ["RESEND_API_KEY not configured"]}

    drafts = db.get_approved_drafts_with_prospects()
    stats = {"total": len(drafts), "sent": 0, "failed": 0, "skipped_scheduled": 0, "errors": []}

    if not drafts:
        return stats

    now = datetime.now(timezone.utc)

    for draft in drafts:
        # Check scheduled_for: skip if it's in the future
        scheduled_for = draft.get("scheduled_for")
        if scheduled_for:
            try:
                sched_dt = datetime.fromisoformat(scheduled_for).replace(tzinfo=timezone.utc)
                if sched_dt > now:
                    logger.debug(
                        "Draft #%d scheduled for %s, skipping (now=%s)",
                        draft["id"], scheduled_for, now.isoformat(),
                    )
                    stats["skipped_scheduled"] += 1
                    continue
            except (ValueError, TypeError):
                pass  # Invalid date — send anyway

        result = send_email_direct(draft["id"])
        if result["success"]:
            stats["sent"] += 1
        else:
            stats["failed"] += 1
            stats["errors"].append(f"Draft #{draft['id']}: {result['error']}")

    logger.info("Bulk Resend send complete: %s", stats)
    return stats


def schedule_approved_drafts() -> dict:
    """Assign optimal send times to all approved drafts that don't have one.

    Returns {total, scheduled}.
    """
    from src.outreach.smart_scheduler import calculate_optimal_send_time

    drafts = db.get_approved_drafts_with_prospects()
    stats = {"total": len(drafts), "scheduled": 0}

    for draft in drafts:
        if draft.get("scheduled_for"):
            continue  # Already scheduled

        send_time = calculate_optimal_send_time()
        iso = send_time.replace(tzinfo=None).isoformat()
        db.update_email_draft(draft["id"], {"scheduled_for": iso})
        stats["scheduled"] += 1
        logger.debug("Draft #%d scheduled for %s", draft["id"], iso)

    if stats["scheduled"]:
        logger.info("Scheduled %d drafts for optimal send times", stats["scheduled"])
    return stats
