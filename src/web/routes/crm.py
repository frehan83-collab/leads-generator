"""CRM Pipeline — Kanban board for prospect journey tracking."""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from src.database import db

crm_bp = Blueprint("crm", __name__)
logger = logging.getLogger(__name__)


@crm_bp.route("/crm")
def pipeline():
    """Kanban board view."""
    board = db.get_pipeline_board()
    counts = db.get_pipeline_counts()

    return render_template(
        "crm.html",
        board=board,
        counts=counts,
        stages=["New", "Contacted", "Opened", "Replied", "Meeting", "Won", "Lost"],
    )


@crm_bp.route("/crm/move", methods=["POST"])
def move_prospect():
    """Move a prospect to a new stage (HTMX or form)."""
    prospect_id = request.form.get("prospect_id", type=int)
    stage = request.form.get("stage", "").strip()

    if not prospect_id or not stage:
        flash("Missing prospect or stage.", "error")
        return redirect(url_for("crm.pipeline"))

    valid_stages = ["New", "Contacted", "Opened", "Replied", "Meeting", "Won", "Lost"]
    if stage not in valid_stages:
        flash(f"Invalid stage: {stage}", "error")
        return redirect(url_for("crm.pipeline"))

    notes = request.form.get("notes", "").strip() or "Manual move"
    db.set_prospect_stage(prospect_id, stage, notes)

    logger.info("Moved prospect %d to stage '%s'", prospect_id, stage)

    # HTMX partial or redirect
    if request.headers.get("HX-Request"):
        return "", 200
    flash(f"Prospect moved to {stage}.", "success")
    return redirect(url_for("crm.pipeline"))


@crm_bp.route("/crm/init-prospects", methods=["POST"])
def init_prospects():
    """Initialize all existing prospects into the pipeline as 'New'."""
    with db.get_connection() as conn:
        # Find prospects not yet in pipeline
        rows = conn.execute(
            """SELECT p.id FROM prospects p
               WHERE p.id NOT IN (SELECT DISTINCT prospect_id FROM prospect_stages)""",
        ).fetchall()

    count = 0
    for row in rows:
        db.set_prospect_stage(row[0], "New", "Pipeline initialization")
        count += 1

    flash(f"Added {count} prospects to the pipeline.", "success")
    return redirect(url_for("crm.pipeline"))
