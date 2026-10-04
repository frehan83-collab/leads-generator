"""Dashboard actor identity + audit helper for mutating routes."""

import logging

logger = logging.getLogger(__name__)


def current_actor() -> str:
    """Who is performing this action: basic-auth user, or scheduler/local."""
    try:
        from flask import has_request_context, request

        if has_request_context():
            auth = request.authorization
            if auth and auth.username:
                return auth.username
    except Exception:
        pass
    return "dashboard"


def audit(
    action: str, entity: str = "", entity_id: str | int = "", detail: str = ""
) -> None:
    """One-line audit write from routes. Never raises."""
    try:
        from src.database import db

        db.log_audit(current_actor(), action, entity, entity_id, detail)
    except Exception as exc:
        logger.debug("audit() failed: %s", exc)
