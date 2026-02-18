"""
Flask application factory.
Run with: python main.py --web
"""

import logging
import os
import threading
import time

import schedule
from flask import Flask

from src.database import db
from src.web.routes.dashboard import dashboard_bp
from src.web.routes.postings import postings_bp
from src.web.routes.prospects import prospects_bp
from src.web.routes.campaigns import campaigns_bp
from src.web.routes.settings import settings_bp
from src.web.routes.api import api_bp
from src.web.routes.era_dashboard import era_bp
from src.web.routes.era_extractions import era_extractions_bp
from src.web.routes.era_templates import era_templates_bp

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = os.getenv("FLASK_SECRET", "sperton-leads-secret-2024")

    # Initialise DB
    db.init_db()

    # Register Sperton blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(postings_bp)
    app.register_blueprint(prospects_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)

    # Register ERA Group blueprints
    app.register_blueprint(era_bp)
    app.register_blueprint(era_extractions_bp)
    app.register_blueprint(era_templates_bp)

    return app


def _run_scheduler(run_time: str) -> None:
    """Background thread: runs the pipeline on a daily schedule."""
    from src.pipeline.lead_pipeline import LeadPipeline

    keywords = [
        k.strip()
        for k in os.getenv("FINN_KEYWORDS", "seafood,aquaculture").split(",")
        if k.strip()
    ]
    snov_list_id = os.getenv("SNOV_LIST_ID")

    def _job():
        logger.info("Scheduled pipeline triggered at %s", run_time)
        try:
            pipeline = LeadPipeline(snov_list_id=snov_list_id)
            pipeline.run(keywords)
        except Exception as exc:
            logger.error("Scheduled pipeline failed: %s", exc, exc_info=True)

    schedule.every().day.at(run_time).do(_job)
    logger.info("Background scheduler started — pipeline runs daily at %s", run_time)

    while True:
        schedule.run_pending()
        time.sleep(30)


def start_web(host: str = "127.0.0.1", port: int = 5000, with_scheduler: bool = True) -> None:
    """Start Flask dev server with optional background scheduler."""
    run_time = os.getenv("RUN_TIME", "09:30")

    if with_scheduler:
        t = threading.Thread(target=_run_scheduler, args=(run_time,), daemon=True)
        t.start()

    app = create_app()
    logger.info("Starting web dashboard at http://%s:%d", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)
