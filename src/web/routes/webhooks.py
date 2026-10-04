"""Resend webhook receiver — tracks email delivery, opens, clicks, bounces."""

import json
import logging

from flask import Blueprint, request, jsonify

from src.database import db

webhooks_bp = Blueprint("webhooks", __name__)
logger = logging.getLogger(__name__)

# Map Resend event types to our simplified event names
EVENT_MAP = {
    "email.sent": "sent",
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.opened": "opened",
    "email.clicked": "clicked",
    "email.bounced": "bounced",
    "email.complained": "complained",
}


@webhooks_bp.route("/webhooks/resend", methods=["POST"])
def resend_webhook():
    """Receive and process Resend webhook events.

    Resend sends POST with JSON body containing:
    {
        "type": "email.opened",
        "data": {
            "email_id": "...",
            "from": "...",
            "to": ["..."],
            "subject": "...",
            ...
        }
    }
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            logger.warning("Webhook received empty or invalid JSON")
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        event_type_raw = payload.get("type", "")
        event_type = EVENT_MAP.get(event_type_raw)
        if not event_type:
            logger.debug("Ignoring unknown webhook event: %s", event_type_raw)
            return jsonify({"status": "ignored"}), 200

        data = payload.get("data", {})
        resend_id = data.get("email_id", "")

        if not resend_id:
            logger.warning("Webhook event missing email_id: %s", event_type_raw)
            return jsonify({"status": "error", "message": "Missing email_id"}), 400

        # Find the draft this event belongs to
        draft_id = db.get_draft_id_by_resend_id(resend_id)

        # Store the event
        db.insert_email_event({
            "draft_id": draft_id,
            "resend_id": resend_id,
            "event_type": event_type,
            "payload": json.dumps(payload),
        })

        # Update draft counters/timestamps if we found the draft
        if draft_id:
            if event_type == "opened":
                draft = db.get_email_draft_by_id(draft_id)
                current_opens = (draft or {}).get("open_count", 0) or 0
                update_data = {"open_count": current_opens + 1}
                if not (draft or {}).get("opened_at"):
                    from src.database.db import _now
                    update_data["opened_at"] = _now()
                db.update_email_draft(draft_id, update_data)

            elif event_type == "clicked":
                draft = db.get_email_draft_by_id(draft_id)
                current_clicks = (draft or {}).get("click_count", 0) or 0
                db.update_email_draft(draft_id, {"click_count": current_clicks + 1})

            elif event_type == "bounced":
                db.update_email_draft(draft_id, {
                    "notes": f"BOUNCED: {data.get('bounce_type', 'unknown')}",
                })

        # Auto-move prospect through CRM pipeline based on email events
        if draft_id and event_type in ("delivered", "opened", "clicked"):
            try:
                draft = draft or db.get_email_draft_by_id(draft_id)
                prospect_id = (draft or {}).get("prospect_id")
                if prospect_id:
                    db.auto_move_prospect_stage(prospect_id, event_type)
            except Exception as stage_exc:
                logger.debug("Auto-move stage failed: %s", stage_exc)

        logger.info(
            "Webhook processed: %s for resend_id=%s (draft_id=%s)",
            event_type, resend_id, draft_id,
        )
        return jsonify({"status": "ok"}), 200

    except Exception as exc:
        logger.error("Webhook processing error: %s", exc, exc_info=True)
        return jsonify({"status": "error"}), 500
