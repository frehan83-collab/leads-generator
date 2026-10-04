"""
Typed Snov.io API errors.

The client raises these instead of returning silent None/[] so callers can
tell fatal problems (bad credentials, empty balance) apart from transient
failures. Fatal errors must abort a pipeline run; anything else degrades
gracefully per posting.
"""


class SnovError(Exception):
    """Base class for Snov.io API failures."""


class SnovAuthError(SnovError):
    """HTTP 401/403 — credentials rejected. Fatal: fix SNOV_CLIENT_ID/SECRET."""


class SnovOutOfCredits(SnovError):
    """HTTP 402 or credit-exhausted payload. Fatal: top up before re-running."""


_CREDIT_HINTS = ("credit", "balance", "insufficient", "quota", "limit exhausted")


def is_credit_error_text(text: str) -> bool:
    """Heuristic: does an API error message describe an empty balance?"""
    lowered = (text or "").lower()
    return any(hint in lowered for hint in _CREDIT_HINTS)
