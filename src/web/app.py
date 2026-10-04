"""
Flask application factory.
Run with: python main.py --web
"""

import logging
import os
import threading
import time

import schedule
from flask import Flask, Response, render_template, request

from src.config import settings
from src.database import db
from src.web.routes.api import api_bp
from src.web.routes.campaigns import campaigns_bp
from src.web.routes.crm import crm_bp
from src.web.routes.dashboard import dashboard_bp
from src.web.routes.health import health_bp
from src.web.routes.postings import postings_bp
from src.web.routes.prospects import prospects_bp
from src.web.routes.settings import settings_bp
from src.web.routes.webhooks import webhooks_bp

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = settings.resolved_flask_secret()

    # Initialise DB
    db.init_db()

    # Register Sperton blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(postings_bp)
    app.register_blueprint(prospects_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(crm_bp)
    app.register_blueprint(health_bp)

    # Exempt webhook from CSRF (if CSRF is ever added)
    # webhooks_bp routes accept raw POST from Resend

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("500.html"), 500

    # Optional HTTP basic auth (set DASHBOARD_USER + DASHBOARD_PASS).
    # Webhooks and the health probe stay open (Resend delivery, monitoring).
    if settings.dashboard_user and settings.dashboard_pass:

        @app.before_request
        def _require_auth():
            if (
                request.path.startswith("/webhooks/")
                or request.path.startswith("/static/")
                or request.path == "/healthz"
            ):
                return None
            auth = request.authorization
            if (
                not auth
                or auth.username != settings.dashboard_user
                or auth.password != settings.dashboard_pass
            ):
                return Response(
                    "Dashboard is password-protected.\n",
                    401,
                    {"WWW-Authenticate": 'Basic realm="Sperton"'},
                )
    else:
        logger.warning(
            "DASHBOARD_USER/DASHBOARD_PASS not set — dashboard has no login. "
            "Bind to 127.0.0.1 only."
        )

    return app


def _run_scheduler(run_time: str) -> None:
    """Background thread: runs the pipeline and send job on daily schedules."""
    import time as _time

    from src.config import Settings
    from src.pipeline.lead_pipeline import LeadPipeline

    run_time = Settings.validate_time(run_time, "RUN_TIME")
    send_time = Settings.validate_time(os.getenv("SEND_TIME", "08:30"), "SEND_TIME")
    keywords = settings.finn_keywords
    snov_list_id = settings.snov_list_id

    def _pipeline_job():
        logger.info("Scheduled pipeline triggered at %s", run_time)
        try:
            pipeline = LeadPipeline(snov_list_id=snov_list_id)
            pipeline.run(keywords)
        except Exception as exc:
            logger.error("Scheduled pipeline failed: %s", exc, exc_info=True)

    def _send_job():
        logger.info("Scheduled send job triggered")
        try:
            from src.outreach.sender import send_approved_drafts

            stats = send_approved_drafts()
            logger.info("Send job finished: %s", stats)
        except Exception as exc:
            logger.error("Scheduled send job failed: %s", exc, exc_info=True)

        # F3: Check and send follow-ups for emails with no opens
        try:
            from src.outreach.follow_up_checker import check_and_create_followups

            fu_stats = check_and_create_followups()
            logger.info("Follow-up check finished: %s", fu_stats)
        except Exception as exc:
            logger.error("Follow-up check failed: %s", exc, exc_info=True)

    send_time = Settings.validate_time(os.getenv("SEND_TIME", "08:30"), "SEND_TIME")

    schedule.every().day.at(run_time).do(_pipeline_job)
    schedule.every().day.at(send_time).do(_send_job)
    logger.info(
        "Background scheduler started — pipeline at %s, send job at %s "
        "(server-local time, TZ=%s)",
        run_time,
        send_time,
        _time.tzname,
    )

    while True:
        schedule.run_pending()
        time.sleep(30)


def start_web(
    host: str = "127.0.0.1", port: int = 5000, with_scheduler: bool = True
) -> None:
    """Start the dashboard with optional background scheduler.

    Uses waitress (production WSGI) when installed, else the Flask dev
    server (local use only).
    """
    run_time = os.getenv("RUN_TIME", "09:30")

    if with_scheduler:
        t = threading.Thread(target=_run_scheduler, args=(run_time,), daemon=True)
        t.start()

    app = create_app()
    try:
        from waitress import serve

        logger.info("Serving dashboard at http://%s:%d (waitress)", host, port)
        serve(app, host=host, port=port)
    except ImportError:
        logger.warning("waitress not installed — using Flask dev server (local only)")
        logger.info("Starting web dashboard at http://%s:%d", host, port)
        app.run(host=host, port=port, debug=False, use_reloader=False)
