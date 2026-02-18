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


def start_scheduler(run_time: str = "09:30") -> None:
    logger.info("Scheduler started. Pipeline will run daily at %s", run_time)
    schedule.every().day.at(run_time).do(run_pipeline)

    while True:
        schedule.run_pending()
        time.sleep(30)  # check every 30 seconds
