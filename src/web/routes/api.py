"""API endpoints for HTMX partials and JSON data."""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from src.database import db
from src.web.jobstate import snapshot

api_bp = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)

# A run still marked "running" after this long died without finishing.
STALE_RUN_AFTER_HOURS = 12


@api_bp.route("/stats")
def stats():
    return jsonify(db.get_dashboard_stats())


@api_bp.route("/activity")
def activity():
    items = db.get_recent_activity(20)
    return jsonify(items)


@api_bp.route("/chart-data")
def chart_data():
    postings = db.get_postings_by_day(30)
    prospects = db.get_prospects_by_day(30)
    return jsonify({"postings": postings, "prospects": prospects})


@api_bp.route("/run-progress")
def run_progress():
    """Live background-job state + latest pipeline run summary."""
    runs = db.get_recent_pipeline_runs(1)
    latest = dict(runs[0]) if runs else None
    if latest and latest.get("status") == "running":
        try:
            started = datetime.fromisoformat(latest.get("started_at") or "")
            if datetime.now() - started > timedelta(hours=STALE_RUN_AFTER_HOURS):
                latest["status"] = "stale"
        except (ValueError, TypeError):
            pass
    return jsonify(
        {
            "jobs": snapshot(),
            "latest_run": {
                "status": latest.get("status"),
                "started_at": latest.get("started_at"),
                "finished_at": latest.get("finished_at"),
                "postings_scraped": latest.get("postings_scraped", 0),
                "postings_new": latest.get("postings_new", 0),
                "prospects_added": latest.get("prospects_added", 0),
                "drafts_created": latest.get("drafts_created", 0),
                "errors": latest.get("errors", 0),
            }
            if latest
            else None,
        }
    )
