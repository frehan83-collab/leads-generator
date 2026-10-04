"""Inbox provider interface + normalized message shape."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class InboxMessage:
    """One candidate reply, provider-agnostic."""

    message_id: str
    from_email: str
    from_name: str = ""
    subject: str = ""
    snippet: str = ""
    date: str = ""
    in_reply_to: str = ""
    references: str = ""
    headers: dict = field(default_factory=dict)


class InboxProvider(Protocol):
    """Fetch candidate replies since a cutoff. Implementations: IMAP, Graph."""

    def fetch_candidates(
        self, since_days: int = 7, limit: int = 100
    ) -> list[InboxMessage]: ...


def normalize_subject(subject: str) -> str:
    """Strip reply/forward prefixes (NO/EN) for thread matching."""
    import re as _re

    text = (subject or "").strip()
    for _ in range(3):  # Re: Re: Re: chains
        cleaned = _re.sub(
            r"^(re|sv|vs|aw|wg|vb|fwd|fw)\s*:\s*", "", text, flags=_re.IGNORECASE
        )
        if cleaned == text:
            break
        text = cleaned
    return text.lower().strip()
