"""API endpoints for HTMX partials and JSON data."""

from flask import Blueprint, jsonify

from src.database import db

api_bp = Blueprint("api", __name__, url_prefix="/api")


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
