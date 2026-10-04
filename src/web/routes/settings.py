"""Settings page — keywords config, Snov balance, manual pipeline trigger."""

import os
import threading
import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from src.database import db

settings_bp = Blueprint("settings", __name__)
logger = logging.getLogger(__name__)

# Simple flags to prevent concurrent runs
_pipeline_running = False
_sending_running = False
_emailing_running = False


def _ensure_keywords_seeded():
    """On first load, seed the keywords table from .env if it's empty."""
    env_raw = os.getenv("FINN_KEYWORDS", "seafood,aquaculture,biologi,fiske og fangst,oppdrett,akvakultur,smolt,RAS,fiskehelse,røkter,IK-mat,driftsleder,lokalitetssjef,eksport,matfisk,produksjon,foredling")
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
        pipeline_running=_pipeline_running,
        sending_running=_sending_running,
        resend_configured=resend_configured,
        emailing_running=_emailing_running,
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
        flash(f"Added keyword{'s' if len(added) > 1 else ''}: {', '.join(added)}", "success")
    else:
        flash("No new keywords to add.", "info")

    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/keywords/remove/<int:keyword_id>", methods=["POST"])
def remove_keyword(keyword_id):
    removed = db.remove_keyword(keyword_id)
    if removed:
        flash("Keyword removed.", "success")
    else:
        flash("Keyword not found.", "warning")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/run-pipeline", methods=["POST"])
def run_pipeline():
    global _pipeline_running
    if _pipeline_running:
        flash("Pipeline is already running. Please wait.", "warning")
        return redirect(url_for("settings.settings"))

    _pipeline_running = True

    def _run():
        global _pipeline_running
        try:
            from src.pipeline.lead_pipeline import LeadPipeline
            _ensure_keywords_seeded()
            keywords = db.get_keyword_list()
            if not keywords:
                keywords = [
                    k.strip()
                    for k in os.getenv("FINN_KEYWORDS", "seafood,aquaculture").split(",")
                    if k.strip()
                ]
            snov_list_id = os.getenv("SNOV_LIST_ID")
            pipeline = LeadPipeline(snov_list_id=snov_list_id)
            pipeline.run(keywords)
        except Exception as exc:
            logger.error("Manual pipeline run failed: %s", exc, exc_info=True)
        finally:
            _pipeline_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    flash("Pipeline started in the background. Check the activity feed for progress.", "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/pipeline-status")
def pipeline_status():
    """HTMX endpoint — returns current pipeline running status."""
    return jsonify({"running": _pipeline_running})


@settings_bp.route("/settings/send-now", methods=["POST"])
def send_now():
    """Manually trigger sending all approved drafts to Snov.io."""
    global _sending_running
    if _sending_running:
        flash("Send job is already running. Please wait.", "warning")
        return redirect(url_for("settings.settings"))

    _sending_running = True

    def _run():
        global _sending_running
        try:
            from src.outreach.sender import send_approved_drafts
            stats = send_approved_drafts()
            logger.info("Manual send complete: %s", stats)
        except Exception as exc:
            logger.error("Manual send failed: %s", exc, exc_info=True)
        finally:
            _sending_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    flash("Sending approved drafts to Snov.io in the background.", "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/send-status")
def send_status():
    """HTMX endpoint — returns current send job running status."""
    return jsonify({"running": _sending_running})


@settings_bp.route("/settings/send-email-now", methods=["POST"])
def send_email_now():
    """Manually trigger sending all approved drafts directly via Resend."""
    global _emailing_running
    if _emailing_running:
        flash("Email send job is already running. Please wait.", "warning")
        return redirect(url_for("settings.settings"))

    _emailing_running = True

    def _run():
        global _emailing_running
        try:
            from src.outreach.email_sender import send_all_approved_email
            stats = send_all_approved_email()
            logger.info("Manual Resend email send complete: %s", stats)
        except Exception as exc:
            logger.error("Manual Resend email send failed: %s", exc, exc_info=True)
        finally:
            _emailing_running = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    flash("Sending approved drafts via email (Resend) in the background.", "success")
    return redirect(url_for("settings.settings"))
