"""
Scheduler — runs the lead pipeline every morning at 09:30.
Uses the 'schedule' library. Keep this process running (e.g. via Windows Task Scheduler
or systemd on VPS).
"""

import logging
import os
import time

import schedule
from dotenv import load_dotenv

from src.pipeline.lead_pipeline import LeadPipeline

load_dotenv()
logger = logging.getLogger(__name__)


def _get_keywords() -> list[str]:
    raw = os.getenv("FINN_KEYWORDS", "seafood,aquaculture,sjømat,biologi")
    return [k.strip() for k in raw.split(",") if k.strip()]


def run_pipeline() -> None:
    logger.info("Scheduled pipeline triggered at 09:30")
    keywords = _get_keywords()
    snov_list_id = os.getenv("SNOV_LIST_ID")
    pipeline = LeadPipeline(snov_list_id=snov_list_id)
    try:
        stats = pipeline.run(keywords)
        logger.info("Pipeline finished: %s", stats)
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=True)


def run_send_job() -> None:
    """Push all approved email drafts to Snov.io, then check for follow-ups."""
    logger.info("Scheduled send job triggered")
    try:
        from src.outreach.sender import send_approved_drafts
        stats = send_approved_drafts()
        logger.info("Send job finished: %s", stats)
    except Exception as exc:
        logger.error("Send job failed: %s", exc, exc_info=True)

    # F3: Check and send follow-ups for emails with no opens
    try:
        from src.outreach.follow_up_checker import check_and_create_followups
        fu_stats = check_and_create_followups()
        logger.info("Follow-up check finished: %s", fu_stats)
    except Exception as exc:
        logger.error("Follow-up check failed: %s", exc, exc_info=True)


def start_scheduler(run_time: str = "09:30") -> None:
    send_time = os.getenv("SEND_TIME", "08:30")
    logger.info(
        "Scheduler started. Pipeline at %s, send job at %s", run_time, send_time
    )
    schedule.every().day.at(run_time).do(run_pipeline)
    schedule.every().day.at(send_time).do(run_send_job)

    while True:
        schedule.run_pending()
        time.sleep(30)  # check every 30 seconds
