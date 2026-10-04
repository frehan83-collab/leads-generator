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
    pipeline_trends = db.get_pipeline_run_trends(30)

    # F1: Outreach engagement stats
    outreach_stats = db.get_outreach_stats()
    engagement_chart = db.get_engagement_timeline(30)

    # F4: LinkedIn stats
    linkedin_stats = db.get_linkedin_stats()

    # C3: Hot prospects (companies with high intent signals)
    hot_prospects = db.get_hot_prospects(5)

    # C2: Pipeline counts
    pipeline_counts = db.get_pipeline_counts()

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_runs=recent_runs,
        activity=activity,
        postings_chart=postings_chart,
        prospects_chart=prospects_chart,
        pipeline_trends=pipeline_trends,
        outreach_stats=outreach_stats,
        engagement_chart=engagement_chart,
        linkedin_stats=linkedin_stats,
        hot_prospects=hot_prospects,
        pipeline_counts=pipeline_counts,
    )
