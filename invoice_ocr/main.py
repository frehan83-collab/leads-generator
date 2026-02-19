"""FastAPI entry point for the Invoice OCR service."""

import logging
import os

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models.base import init_db
from .api.routes import router, stats_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Invoice OCR API",
        description="AI-powered invoice scanning and data extraction (Claude Vision)",
        version="1.0.0",
    )

    # Init DB on startup
    @app.on_event("startup")
    def startup():
        init_db()
        os.makedirs(settings.storage_path, exist_ok=True)
        logger.info("Invoice OCR service started on port %d", settings.api_port)

    # Routes
    app.include_router(router)
    app.include_router(stats_router)

    # Dashboard UI
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard():
        template_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
        with open(template_path, "r") as f:
            return HTMLResponse(content=f.read())

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "invoice_ocr.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
