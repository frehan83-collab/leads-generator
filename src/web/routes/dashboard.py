"""Dashboard home page — stats cards, charts, activity feed."""

import logging

from flask import Blueprint, render_template

from src.config import settings
from src.database import db

dashboard_bp = Blueprint("dashboard", __name__)
logger = logging.getLogger(__name__)


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

    # C3: Hot prospects — v2 scores first, v1 intent as fallback.
    # Role inboxes (info@, support@, ...) never headline a hot list.
    from src.scoring.lead_quality import is_role_address

    hot_prospects = [
        p for p in db.get_hot_prospects_v2(15) if not is_role_address(p.get("email"))
    ][:5]
    if not hot_prospects:
        hot_prospects = [
            {
                **p,
                "score": p.get("intent_score") or 0,
                "level": (
                    "hot"
                    if (p.get("intent_score") or 0) >= 70
                    else "warm"
                    if (p.get("intent_score") or 0) >= 45
                    else "medium"
                    if (p.get("intent_score") or 0) >= 20
                    else "cold"
                ),
            }
            for p in db.get_hot_prospects(5)
        ]

    # C2: Pipeline counts
    pipeline_counts = db.get_pipeline_counts()

    # Snov.io campaigns + analytics (best-effort; Draft campaigns have no stats)
    snov_campaigns = []
    try:
        from src.snov.client import SnovClient

        snov = SnovClient()
        for camp in snov.get_user_campaigns():
            entry = dict(camp)
            entry["analytics"] = None
            try:
                entry["analytics"] = snov.get_campaign_analytics(str(camp.get("id")))
            except Exception:
                pass
            entry["is_our_list"] = str(camp.get("list_id") or "") == str(
                settings.snov_list_id or ""
            )
            snov_campaigns.append(entry)
    except Exception as exc:
        logger.warning("Snov campaigns unavailable: %s", exc)

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
        snov_campaigns=snov_campaigns,
    )


@dashboard_bp.route("/scores")
def scores():
    """Lead scoring v2 leaderboard + calibration bands."""
    import json

    from src.scoring.lead_scorer import calibration_report

    rows = db.get_lead_scores(100)
    for row in rows:
        try:
            row["components"] = json.loads(row.get("components_json") or "{}").get(
                "components", {}
            )
        except (ValueError, TypeError):
            row["components"] = {}
    return render_template("scores.html", scores=rows, calibration=calibration_report())


@dashboard_bp.route("/actions")
def actions():
    """The rep's morning page: who to call, what to review, what's new."""
    from src.actions.today import get_today_actions

    return render_template("actions.html", **get_today_actions())
