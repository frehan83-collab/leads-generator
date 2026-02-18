"""Dashboard home page — stats cards, charts, activity feed."""

from flask import Blueprint, render_template

from src.database import db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    stats = db.get_dashboard_stats()
    recent_runs = db.get_recent_pipeline_runs(5)
    activity = db.get_recent_activity(15)
    postings_chart = db.get_postings_by_day(30)
    prospects_chart = db.get_prospects_by_day(30)

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_runs=recent_runs,
        activity=activity,
        postings_chart=postings_chart,
        prospects_chart=prospects_chart,
    )
