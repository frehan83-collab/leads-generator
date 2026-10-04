"""Posting lifecycle checks: is a scraped job ad still active?

Conservative by design — a posting is marked expired only on strong
signals (gone from the server, or an explicit expired/removed notice).
Anything ambiguous (network errors, unknown shapes) returns None
(unknown) and never flips a live posting to expired.
"""

import logging
import re

import requests

from src.scraper.browser_manager import USER_AGENT

logger = logging.getLogger(__name__)

# Explicit "this ad is dead" markers (Norwegian + English job boards).
EXPIRED_MARKERS = re.compile(
    r"annonsen er (utl.pt|fjernet)|stillingen er (fjernet|utl.pt|besatt)|"
    r"fant ikke (siden|annonsen)|siden (finnes ikke|er fjernet)|"
    r"this (job )?posting (has been |has |is )?(expired|removed)|"
    r"(job )?ad (has been |is )?(expired|removed)|"
    r"position (has been |is )?(filled|closed|expired)|"
    r"no longer (available|accepting applications)|"
    r"application deadline has passed.{0,40}closed",
    re.IGNORECASE,
)


def check_posting_active(url: str, timeout_sec: int = 15) -> bool | None:
    """Return True (active), False (expired), or None (unknown).

    Args:
        url: the original posting URL
        timeout_sec: per-request timeout
    """
    if not url:
        return None
    try:
        resp = requests.get(
            url,
            timeout=timeout_sec,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "nb-NO,nb;q=0.9"},
            allow_redirects=True,
        )
    except Exception as exc:
        logger.debug("Revalidate fetch failed for %s: %s", url, exc)
        return None
    if resp.status_code in (404, 410):
        return False
    if not resp.ok:
        return None  # 403/429/5xx: the ad may be fine, we are blocked
    text = resp.text or ""
    if EXPIRED_MARKERS.search(text):
        return False
    return True


def revalidate_one(posting_id: int, url: str, source: str | None = None) -> str:
    """Check a posting and persist the outcome. Returns the new status."""
    from src.database import db

    result = check_posting_active(url)
    now = db._now()
    if result is True:
        db.update_job_posting(posting_id, {"status": "active", "last_checked_at": now})
        return "active"
    if result is False:
        db.update_job_posting(posting_id, {"status": "expired", "last_checked_at": now})
        logger.info("Posting #%d expired: %s", posting_id, url)
        return "expired"
    db.update_job_posting(posting_id, {"last_checked_at": now})
    return "unknown"
