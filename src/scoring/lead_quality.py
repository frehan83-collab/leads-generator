"""Lead quality signals: role addresses and identity confidence.

Used to keep low-value contacts (generic inboxes, unparseable names) out of
hot lists and first sends — without deleting anything.
"""

import logging

logger = logging.getLogger(__name__)

# Generic inbox local-parts. Conservative on purpose: hr/sales/kontakt/post
# can be real recruitment targets, so they are NOT listed here.
ROLE_LOCALS = frozenset(
    {
        "info",
        "postmottak",
        "soknad",
        "support",
        "help",
        "helpdesk",
        "webmaster",
        "hostmaster",
        "postmaster",
        "abuse",
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "newsletter",
        "unsubscribe",
        "subscribe",
        "booking",
        "bestilling",
        "faktura",
        "invoice",
        "regnskap",
        "kundeservice",
        "customer",
        "communications",
        "media",
        "presse",
        "admin",
        "it",
        "privacy",
        "gdpr",
        "personvern",
    }
)


def is_role_address(email: str | None) -> bool:
    """True for generic inboxes (info@, support@, noreply@, ...)."""
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    if local in ROLE_LOCALS:
        return True
    return any(
        local.startswith(f"{role}.") or local.startswith(f"{role}+")
        for role in ROLE_LOCALS
    )


def identity_confidence(prospect: dict) -> int:
    """2 = full name, 1 = partial/handle-ish, 0 = no usable name.

    Sniffs out email-handle parses ("frida" from frida@x.no) versus real
    first+last names, so lists can prefer confident identities.
    """
    first = (prospect.get("first_name") or "").strip()
    last = (prospect.get("last_name") or "").strip()
    full = (prospect.get("full_name") or "").strip()
    if first.isalpha() and last.isalpha() and len(first) >= 2 and len(last) >= 2:
        return 2
    candidate = full or first or last
    return 1 if len(candidate) >= 3 else 0
