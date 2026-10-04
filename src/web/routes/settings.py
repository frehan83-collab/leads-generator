"""Settings page — keywords config, Snov balance, manual pipeline trigger."""

import logging
import os
import threading

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from src.database import db
from src.web.auth import audit
from src.web.jobstate import is_running, set_running, snapshot

settings_bp = Blueprint("settings", __name__)
logger = logging.getLogger(__name__)


def _ensure_keywords_seeded():
    """On first load, seed the keywords table from .env if it's empty."""
    env_raw = os.getenv(
        "FINN_KEYWORDS",
        "seafood,aquaculture,biologi,fiske og fangst,oppdrett,akvakultur,smolt,RAS,fiskehelse,røkter,IK-mat,driftsleder,lokalitetssjef,eksport,matfisk,produksjon,foredling",
    )
    env_keywords = [k.strip() for k in env_raw.split(",") if k.strip()]
    db.seed_keywords_from_env(env_keywords)


@settings_bp.route("/settings")
def settings():
    _ensure_keywords_seeded()
    keywords = db.get_keywords(active_only=True)
    run_time = os.getenv("RUN_TIME", "09:30")
    snov_list_id = os.getenv("SNOV_LIST_ID", "")
    recent_runs = db.get_recent_pipeline_runs(10)

    # Try to get Snov balance
    snov_balance = None
    try:
        from src.snov.client import SnovClient

        snov = SnovClient()
        bal = snov.get_balance()
        data = bal.get("data") or bal
        snov_balance = {
            "credits": data.get("balance", "N/A"),
            "recipients_used": data.get("recipients_used", "N/A"),
            "limit_resets_in": data.get("limit_resets_in", "N/A"),
            "expires_in": data.get("expires_in", "N/A"),
        }
    except Exception as exc:
        logger.warning("Could not fetch Snov balance: %s", exc)

    send_time = os.getenv("SEND_TIME", "08:30")
    resend_configured = bool(os.getenv("RESEND_API_KEY"))

    return render_template(
        "settings.html",
        keywords=keywords,
        run_time=run_time,
        send_time=send_time,
        snov_list_id=snov_list_id,
        snov_balance=snov_balance,
        recent_runs=recent_runs,
        pipeline_running=snapshot()["pipeline"],
        sending_running=snapshot()["sending"],
        resend_configured=resend_configured,
        emailing_running=snapshot()["emailing"],
    )


@settings_bp.route("/settings/keywords/add", methods=["POST"])
def add_keyword():
    keyword = request.form.get("keyword", "").strip()
    if not keyword:
        flash("Keyword cannot be empty.", "warning")
        return redirect(url_for("settings.settings"))

    # Support comma-separated bulk add
    added = []
    for kw in keyword.split(","):
        kw = kw.strip()
        if kw:
            result = db.add_keyword(kw)
            if result:
                added.append(kw)

    if added:
        audit("keywords.add", "keyword", "", ", ".join(added))
        flash(
            f"Added keyword{'s' if len(added) > 1 else ''}: {', '.join(added)}",
            "success",
        )
    else:
        flash("No new keywords to add.", "info")

    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/keywords/remove/<int:keyword_id>", methods=["POST"])
def remove_keyword(keyword_id):
    removed = db.remove_keyword(keyword_id)
    if removed:
        audit("keywords.remove", "keyword", keyword_id, "")
        flash("Keyword removed.", "success")
    else:
        flash("Keyword not found.", "warning")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/run-pipeline", methods=["POST"])
def run_pipeline():
    if is_running("pipeline"):
        flash("Pipeline is already running. Please wait.", "warning")
        return redirect(url_for("settings.settings"))

    set_running("pipeline", True)

    def _run():
        try:
            from src.pipeline.lead_pipeline import LeadPipeline

            _ensure_keywords_seeded()
            keywords = db.get_keyword_list()
            if not keywords:
                keywords = [
                    k.strip()
                    for k in os.getenv("FINN_KEYWORDS", "seafood,aquaculture").split(
                        ","
                    )
                    if k.strip()
                ]
            snov_list_id = os.getenv("SNOV_LIST_ID")
            pipeline = LeadPipeline(snov_list_id=snov_list_id)
            pipeline.run(keywords)
        except Exception as exc:
            logger.error("Manual pipeline run failed: %s", exc, exc_info=True)
        finally:
            set_running("pipeline", False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    flash(
        "Pipeline started in the background. Check the activity feed for progress.",
        "success",
    )
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/pipeline-status")
def pipeline_status():
    """HTMX endpoint — returns current pipeline running status."""
    return jsonify({"running": is_running("pipeline")})


@settings_bp.route("/settings/send-now", methods=["POST"])
def send_now():
    """Manually trigger sending all approved drafts to Snov.io."""
    if is_running("sending"):
        flash("Send job is already running. Please wait.", "warning")
        return redirect(url_for("settings.settings"))

    set_running("sending", True)

    def _run():
        try:
            from src.outreach.sender import send_approved_drafts

            stats = send_approved_drafts()
            logger.info("Manual send complete: %s", stats)
        except Exception as exc:
            logger.error("Manual send failed: %s", exc, exc_info=True)
        finally:
            set_running("sending", False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    flash("Sending approved drafts to Snov.io in the background.", "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/send-status")
def send_status():
    """HTMX endpoint — returns current send job running status."""
    return jsonify({"running": is_running("sending")})


@settings_bp.route("/settings/send-email-now", methods=["POST"])
def send_email_now():
    """Manually trigger sending all approved drafts directly via Resend."""
    if is_running("emailing"):
        flash("Email send job is already running. Please wait.", "warning")
        return redirect(url_for("settings.settings"))

    set_running("emailing", True)

    def _run():
        try:
            from src.outreach.email_sender import send_all_approved_email

            stats = send_all_approved_email()
            logger.info("Manual Resend email send complete: %s", stats)
        except Exception as exc:
            logger.error("Manual Resend email send failed: %s", exc, exc_info=True)
        finally:
            set_running("emailing", False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    flash("Sending approved drafts via email (Resend) in the background.", "success")
    return redirect(url_for("settings.settings"))
