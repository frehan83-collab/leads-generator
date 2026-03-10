"""Generic webhook notifications for pipeline events.
Supports any JSON-accepting webhook (Discord, Teams, custom endpoints, etc.)."""

import os
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def send_pipeline_alert(
    stats: dict,
    status: str,
    error_message: str = None,
) -> bool:
    """
    Send pipeline results to a generic webhook URL.
    Payload format is simple JSON — works with Discord, Teams, or custom endpoints.
    Returns True if sent successfully.
    """
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        return False

    # Build alert title
    if status == "failed":
        title = "Pipeline Run FAILED"
    elif stats.get("postings_new", 0) == 0 and status == "completed":
        title = "Pipeline Run: No New Postings Found"
    elif status == "completed":
        title = "Pipeline Run Completed"
    else:
        title = f"Pipeline Run: {status}"

    # Summary text
    summary_lines = [
        f"**{title}**",
        f"Postings scraped: {stats.get('postings_scraped', 0)}",
        f"New postings: {stats.get('postings_new', 0)}",
        f"Prospects found: {stats.get('prospects_found', 0)}",
        f"Emails verified: {stats.get('emails_verified', 0)}",
        f"Drafts created: {stats.get('drafts_created', 0)}",
        f"Errors: {stats.get('errors', 0)}",
    ]
    if error_message:
        summary_lines.append(f"Error: {error_message[:200]}")

    summary = "\n".join(summary_lines)

    # Generic JSON payload (works with most webhook services)
    payload = {
        "text": summary,             # Generic / Mattermost
        "content": summary,          # Discord
        "title": title,
        "body": summary,
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Webhook alert sent to %s", webhook_url)
        return True
    except Exception as exc:
        logger.warning("Webhook alert failed: %s", exc)
        return False
