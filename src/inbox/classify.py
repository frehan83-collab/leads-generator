"""Reply classification (rule-based, NO + EN).

Labels: human / auto_reply / unsubscribe / angry.
Only human replies move CRM stages and stop sequences; unsubscribes
suppress the address; auto-replies are logged without side effects.
"""

import re

AUTO_REPLY_PATTERNS = (
    # out-of-office
    r"out of (the )?office",
    r"automatic(ally)? reply",
    r"auto.?reply",
    r"er (ute|borte|på ferie)|ute av kontoret|automatisk svar|autosvar|ferie",
    r"abwesend|außer haus",
    # delivery machinery
    r"undeliverable|delivery (status|failure)|mailer.?daemon|postmaster",
    r"mail delivery",
)

UNSUBSCRIBE_PATTERNS = (
    r"\bunsubscribe\b|meld meg (av|ut)|ikke kontakt meg",
    r"remove me|stop (emailing|mailing)|do not (email|contact) me",
    r"GDPR|slett (meg|mine data)",
)

ANGRY_PATTERNS = (
    r"\bspam\b|anmeld|report you|slutt å sende|aldri (mer )?kontakt",
    r"fuck|idiot",
)

POSITIVE_HINTS = (
    r"\bmøte\b|meet|interessert|interested|ring meg|call me|"
    r"send (meg )?mer|pris|tilbud|demo|når passer|høres (bra|interessant) ut",
)


def _hits(patterns: tuple[str, ...], *texts: str) -> bool:
    blob = "\n".join(t or "" for t in texts).lower()
    return any(re.search(p, blob, re.IGNORECASE) for p in patterns)


def classify_reply(subject: str, body: str, headers: dict | None = None) -> dict:
    """Return {label, confidence, reasons} for a candidate reply."""
    headers = headers or {}
    reasons: list[str] = []

    auto_header = str(headers.get("Auto-Submitted", "")).lower()
    if auto_header and auto_header != "no":
        reasons.append("auto-submitted-header")
    if str(headers.get("X-Auto-Response-Suppress", "")).lower() in ("oof", "all"):
        reasons.append("auto-response-suppress-header")
    if _hits(AUTO_REPLY_PATTERNS, subject, body):
        reasons.append("out-of-office-pattern")
    if reasons:
        return {"label": "auto_reply", "confidence": 0.95, "reasons": reasons}

    if _hits(UNSUBSCRIBE_PATTERNS, subject, body):
        return {
            "label": "unsubscribe",
            "confidence": 0.9,
            "reasons": ["opt-out-pattern"],
        }
    if _hits(ANGRY_PATTERNS, subject, body):
        return {"label": "angry", "confidence": 0.85, "reasons": ["hostility-pattern"]}
    if _hits(POSITIVE_HINTS, subject, body):
        return {"label": "human", "confidence": 0.8, "reasons": ["positive-hint"]}
    return {"label": "human", "confidence": 0.6, "reasons": ["default-human"]}
