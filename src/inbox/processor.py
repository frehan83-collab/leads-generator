"""Reply processor: match inbox messages to prospects, classify, act.

Per message:
1. Skip if Message-ID already processed (idempotent re-runs).
2. Match From-address to a prospect (case-insensitive).
3. Match to the most recent sent draft (thread subject preferred).
4. Classify: human / auto_reply / unsubscribe / angry.
5. Human → replied event + replied_at + CRM Replied + notify.
   Unsubscribe/angry → suppress the address (+ event).
   Auto-reply → logged event only (no stage move, no sequence stop).
"""

import json
import logging

logger = logging.getLogger(__name__)


def check_inbox(provider=None, since_days: int = 7, limit: int = 100) -> dict:
    """Fetch candidates and process them. Returns stats."""
    from src.inbox.classify import classify_reply

    stats = {
        "fetched": 0,
        "matched": 0,
        "human": 0,
        "auto_reply": 0,
        "unsubscribed": 0,
        "angry": 0,
        "errors": [],
    }
    if provider is None:
        provider = _default_provider()
        if provider is None:
            logger.info(
                "Inbox checking not configured (INBOX_IMAP_HOST unset) — skipping"
            )
            return stats
    try:
        messages = provider.fetch_candidates(since_days=since_days, limit=limit)
    except Exception as exc:
        logger.error("Inbox fetch failed: %s", exc)
        stats["errors"].append(str(exc))
        return stats
    stats["fetched"] = len(messages)
    for message in messages:
        try:
            outcome = _process_message(message, classify_reply)
            if outcome in stats:
                stats[outcome] += 1
                stats["matched"] += 1
        except Exception as exc:
            logger.warning(
                "Reply processing failed for %s: %s", message.message_id, exc
            )
            stats["errors"].append(f"{message.message_id}: {exc}")
    if stats["human"] or stats["unsubscribed"] or stats["angry"]:
        _notify(stats)
    logger.info(
        "Inbox check complete: %s", {k: v for k, v in stats.items() if k != "errors"}
    )
    return stats


def _default_provider():
    from src.config import settings
    from src.inbox.imap_provider import ImapInboxProvider

    if not settings.inbox_imap_host:
        return None
    return ImapInboxProvider(
        host=settings.inbox_imap_host,
        username=settings.inbox_imap_user or "",
        password=settings.inbox_imap_pass or "",
        port=settings.inbox_imap_port,
        folder=settings.inbox_imap_folder,
    )


def _process_message(message, classify_fn) -> str:
    """Process one message. Returns outcome label or 'skipped'/'unknown'."""
    from src.database import db

    if db.inbox_already_processed(message.message_id):
        return "skipped"
    prospect = db.get_prospect_by_email(message.from_email)
    if not prospect:
        db.mark_inbox_processed(message.message_id)  # not ours; don't re-scan
        return "unknown"
    draft = _match_draft(prospect["id"], message)
    result = classify_fn(message.subject, message.snippet, message.headers)
    label = result["label"]
    payload = json.dumps(
        {
            "from": message.from_email,
            "subject": message.subject,
            "snippet": message.snippet[:500],
            "classification": result,
            "date": message.date,
        },
        ensure_ascii=False,
    )
    if label == "auto_reply":
        if draft:
            db.insert_email_event(
                {
                    "draft_id": draft["id"],
                    "resend_id": draft.get("resend_id"),
                    "event_type": "auto_replied",
                    "payload": payload,
                }
            )
        db.mark_inbox_processed(message.message_id)
        logger.info("Auto-reply from %s logged (no action)", message.from_email)
        return "auto_reply"
    if label in ("unsubscribe", "angry"):
        db.add_suppression(message.from_email, label)
        if draft:
            db.insert_email_event(
                {
                    "draft_id": draft["id"],
                    "resend_id": draft.get("resend_id"),
                    "event_type": "replied",
                    "payload": payload,
                }
            )
            db.update_email_draft(draft["id"], {"replied_at": db._now()})
        db.mark_inbox_processed(message.message_id)
        logger.warning("%s from %s — address suppressed", label, message.from_email)
        return "unsubscribed" if label == "unsubscribe" else "angry"
    # human reply
    if draft:
        db.insert_email_event(
            {
                "draft_id": draft["id"],
                "resend_id": draft.get("resend_id"),
                "event_type": "replied",
                "payload": payload,
            }
        )
        db.update_email_draft(draft["id"], {"replied_at": db._now()})
    try:
        db.auto_move_prospect_stage(prospect["id"], "replied")
    except Exception as exc:
        logger.debug("CRM auto-move failed: %s", exc)
    db.mark_inbox_processed(message.message_id)
    logger.warning(
        "HUMAN REPLY from %s (%s) — follow-ups stop here",
        message.from_email,
        message.subject[:80],
    )
    return "human"


def _match_draft(prospect_id: int, message) -> dict | None:
    """Most recent sent draft for this prospect, preferring thread match."""
    from src.database import db
    from src.inbox.base import normalize_subject

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT ed.* FROM email_drafts ed
               WHERE ed.prospect_id = ? AND ed.status = 'sent'
               ORDER BY ed.sent_at DESC""",
            (prospect_id,),
        ).fetchall()
    if not rows:
        return None
    drafts = [dict(r) for r in rows]
    wanted = normalize_subject(message.subject)
    if wanted:
        for draft in drafts:
            if normalize_subject(draft.get("subject") or "") == wanted:
                return draft
    return drafts[0]


def _notify(stats: dict) -> None:
    try:
        from src.notifications.webhook import send_pipeline_alert

        send_pipeline_alert(
            {},
            status="warning",
            error_message=(
                f"Inbox: {stats['human']} human replies, "
                f"{stats['unsubscribed']} unsubscribes, {stats['angry']} angry. "
                "Check the CRM."
            ),
        )
    except Exception as exc:
        logger.debug("Reply notification failed: %s", exc)
