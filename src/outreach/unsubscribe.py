"""One-click unsubscribe (RFC 8058) for cold outreach.

- Tokenized URL: /unsubscribe/<token> (GET shows confirm, POST unsubscribes;
  Gmail's one-click sends POST). Signed with itsdangerous + FLASK_SECRET.
- Headers for Resend sends: List-Unsubscribe (https + mailto) and
  List-Unsubscribe-Post for one-click.
- Footer appended at send time (draft bodies stay clean).
- Unsubscribing suppresses the address (existing suppression list).
"""

import logging

logger = logging.getLogger(__name__)

_TOKEN_SALT = "unsubscribe-v1"


def _serializer():
    from itsdangerous import URLSafeTimedSerializer

    from src.config import settings

    return URLSafeTimedSerializer(settings.resolved_flask_secret(), salt=_TOKEN_SALT)


def make_unsubscribe_token(email: str) -> str:
    """Signed token identifying an address (no DB lookup needed)."""
    return _serializer().dumps([(email or "").strip().lower()])


def verify_unsubscribe_token(token: str, max_age_days: int = 365) -> str | None:
    """Return the address for a valid token, else None."""
    try:
        (email,) = _serializer().loads(token, max_age=max_age_days * 86400)
        return email or None
    except Exception:
        return None


def unsubscribe_url(email: str) -> str | None:
    """Public one-click URL, or None when APP_BASE_URL is unset."""
    from src.config import settings

    base = (settings.app_base_url or "").rstrip("/")
    if not base:
        return None
    return f"{base}/unsubscribe/{make_unsubscribe_token(email)}"


def unsubscribe_headers(email: str) -> dict:
    """List-Unsubscribe headers for a Resend send to this address."""
    from src.config import settings

    entries = []
    url = unsubscribe_url(email)
    if url:
        entries.append(f"<{url}>")
    if settings.unsubscribe_mailto:
        entries.append(f"<mailto:{settings.unsubscribe_mailto}?subject=unsub>")
    headers = {}
    if entries:
        headers["List-Unsubscribe"] = ", ".join(entries)
        if url:
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers


def unsubscribe_footer_text(email: str) -> str:
    """Plain-text footer appended at send time (empty when unconfigured)."""
    url = unsubscribe_url(email)
    if not url:
        return ""
    return (
        "\n\n--\nØnsker du ikke flere e-poster? Meld deg av her (one click): "
        f"{url}\nDon't want more emails? Unsubscribe here: {url}"
    )


def process_unsubscribe_token(token: str) -> str | None:
    """Verify token, suppress the address, log it. Returns email or None."""
    from src.database import db

    email = verify_unsubscribe_token(token)
    if not email:
        return None
    db.add_suppression(email, "unsubscribed")
    db.log_consent(
        email, "legitimate_interest", source="unsubscribe-link", note="opt-out honored"
    )
    return email
