"""Pre-send deliverability gate: content scoring for drafts.

Scores subject + body 0-100 and lists concrete issues. Pure function of
the text — cheap enough to run on every draft render.

Verdicts: pass (>= 80), warn (50-79), fail (< 50).
Default policy warns only; set DELIVERABILITY_BLOCK_BELOW (0-100) to
refuse sends below a threshold.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Classic spam-trigger tokens (EN + NO). Whole-word / phrase matches.
SPAM_TOKENS = (
    r"100% free|free money|double your|earn \$|make money fast|no cost|"
    r"risk.?free|guarantee[ds]?|winner|congratulations you (?:won|have)|"
    r"act now|limited time|urgent|click (here|below)|dear friend|"
    r"gratis|vinn|gevinst|gratulerer|begrenset tid|handle nå| Klikk her|"
    r"tj€n penger|fantastisk tilbud|du er valgt"
)

MAX_SUBJECT_LEN = 60
MIN_BODY_LEN = 50
MAX_LINKS = 3


def _count_links(text: str) -> int:
    return len(re.findall(r"https?://", text or ""))


def check_draft(subject: str, body: str) -> dict:
    """Score a draft. Returns {score, verdict, issues[]}."""
    subject = subject or ""
    body = body or ""
    issues: list[str] = []
    score = 100

    hits = re.findall(SPAM_TOKENS, f"{subject}\n{body}", re.IGNORECASE)
    if hits:
        unique = sorted({h.lower() for h in hits})
        score -= min(40, 15 * len(unique))
        issues.append(f"Spam-trigger words: {', '.join(unique[:5])}")

    caps = sum(1 for c in subject if c.isupper())
    letters = sum(1 for c in subject if c.isalpha())
    if letters >= 10 and caps / letters > 0.7:
        score -= 15
        issues.append("Subject is mostly ALL CAPS")

    bangs = subject.count("!") + body.count("!")
    if bangs >= 3:
        score -= 10
        issues.append(f"{bangs} exclamation marks (spammy)")

    if len(subject) > MAX_SUBJECT_LEN:
        score -= 10
        issues.append(f"Subject {len(subject)} chars (aim under {MAX_SUBJECT_LEN})")
    elif len(subject.strip()) < 10:
        score -= 5
        issues.append("Subject very short (looks automated)")

    links = _count_links(body)
    if links > MAX_LINKS:
        score -= 10
        issues.append(f"{links} links in body (aim max {MAX_LINKS})")

    if len(body.strip()) < MIN_BODY_LEN:
        score -= 10
        issues.append("Body very short (thin content)")

    if not re.search(
        r"(avmeld|unsubscribe|meld meg av|ikke (interessert|kontakt))",
        body,
        re.IGNORECASE,
    ):
        issues.append("No opt-out line (recommended for cold outreach)")

    score = max(0, score)
    verdict = "pass" if score >= 80 else ("warn" if score >= 50 else "fail")
    return {"score": score, "verdict": verdict, "issues": issues}


def gate_allows(score: int) -> bool:
    """True unless the operator configured DELIVERABILITY_BLOCK_BELOW above it.

    Default 0 = warn-only, never blocks. Set e.g. 50 to refuse sends that
    score below 50 (likely spam-folder material).
    """
    import os as _os

    try:
        threshold = int(_os.getenv("DELIVERABILITY_BLOCK_BELOW", "0"))
    except (TypeError, ValueError):
        threshold = 0
    return score >= threshold
