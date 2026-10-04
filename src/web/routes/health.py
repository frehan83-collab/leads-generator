"""Liveness/health endpoint for monitoring (no auth required)."""

from datetime import UTC, datetime

from flask import Blueprint, jsonify

from src.config import APP_VERSION
from src.database import db

health_bp = Blueprint("health", __name__)


@health_bp.route("/healthz")
def healthz():
    """Minimal health probe: process alive + database reachable."""
    body = {
        "status": "ok",
        "version": APP_VERSION,
        "time": datetime.now(UTC).isoformat(),
    }
    try:
        with db.get_connection() as conn:
            counts = {}
            for table in ("job_postings", "prospects", "email_drafts", "companies"):
                try:
                    counts[table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                except Exception:
                    counts[table] = None
        body["db"] = {"ok": True, "counts": counts}
    except Exception as exc:
        body["status"] = "degraded"
        body["db"] = {"ok": False, "error": str(exc)}
    return jsonify(body), 200 if body["status"] == "ok" else 503
