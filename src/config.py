"""
Central application configuration — single source of truth for settings.

All tunables come from environment variables (loaded from .env once, here).
Import this module instead of calling os.getenv / load_dotenv elsewhere::

    from src.config import settings
"""

import logging
import os
import secrets
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

APP_VERSION = "2.0.0"


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    items = [v.strip() for v in value.split(",")]
    return [v for v in items if v]


@dataclass(frozen=True)
class Settings:
    # -- Scraping -------------------------------------------------------
    finn_keywords: list[str] = field(
        default_factory=lambda: _as_list(
            os.getenv("FINN_KEYWORDS"), ["seafood", "aquaculture", "sjømat"]
        )
    )
    run_time: str = os.getenv("RUN_TIME", "09:30")
    # Bounded parallel posting processing (2 default; each worker runs its
    # own headless browser — 3-4 max on typical hardware).
    pipeline_workers: int = min(4, max(1, int(os.getenv("PIPELINE_WORKERS", "2"))))
    # Max seconds spent on a single company domain (website + enrichment).
    domain_timeout_sec: int = int(os.getenv("DOMAIN_TIMEOUT_SEC", "300"))
    # Cap on company domains revisited per run by the careers source.
    careers_max_domains: int = int(os.getenv("CAREERS_MAX_DOMAINS", "30"))

    # -- Snov.io --------------------------------------------------------
    snov_client_id: str | None = os.getenv("SNOV_CLIENT_ID")
    snov_client_secret: str | None = os.getenv("SNOV_CLIENT_SECRET")
    snov_list_id: str | None = os.getenv("SNOV_LIST_ID")
    # Abort a run before burning time when balance is empty or below this.
    snov_min_credits: int = int(os.getenv("SNOV_MIN_CREDITS", "0"))
    # Warn (+ webhook if configured) when balance drops below this.
    snov_low_water_credits: int = int(os.getenv("SNOV_LOW_WATER_CREDITS", "200"))

    # -- Outreach -------------------------------------------------------
    resend_api_key: str | None = os.getenv("RESEND_API_KEY")
    from_email: str = os.getenv("FROM_EMAIL", "fredrik.hansen@sperton.com")
    from_name: str = os.getenv("FROM_NAME", "Fredrik Hansen")
    send_time: str = os.getenv("SEND_TIME", "08:30")
    # Safe default: follow-ups are created as drafts awaiting human approval.
    # Set FOLLOWUP_AUTO_SEND=true to restore fully automatic sequences.
    followup_auto_send: bool = _as_bool(os.getenv("FOLLOWUP_AUTO_SEND"), False)
    followup_min_days: int = int(os.getenv("FOLLOWUP_MIN_DAYS", "3"))
    followup_max_step: int = int(os.getenv("FOLLOWUP_MAX_STEP", "3"))

    # -- AI -------------------------------------------------------------
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")

    # -- Web ------------------------------------------------------------
    flask_secret: str | None = os.getenv("FLASK_SECRET")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_format: str = os.getenv("LOG_FORMAT", "pretty")
    # Dashboard basic auth. Unset = open dashboard (local use only) + warning.
    dashboard_user: str | None = os.getenv("DASHBOARD_USER")
    dashboard_pass: str | None = os.getenv("DASHBOARD_PASS")

    def resolved_flask_secret(self) -> str:
        """Return the configured secret, or an ephemeral one with a warning."""
        if self.flask_secret:
            return self.flask_secret
        logger.warning(
            "FLASK_SECRET is not set — using an ephemeral random secret. "
            "Sessions will not survive restarts. Set FLASK_SECRET in .env."
        )
        return secrets.token_hex(32)

    def validate(self, strict: bool = False) -> list[str]:
        """Return a list of configuration problems (empty = OK).

        With strict=True, missing third-party credentials are errors;
        otherwise they are warnings (features degrade gracefully).
        """
        problems: list[str] = []
        if not self.snov_client_id or not self.snov_client_secret:
            problems.append(
                "SNOV_CLIENT_ID / SNOV_CLIENT_SECRET not set — enrichment disabled"
            )
        if not self.resend_api_key:
            problems.append("RESEND_API_KEY not set — email sending disabled")
        if not self.anthropic_api_key:
            problems.append(
                "ANTHROPIC_API_KEY not set — AI personalization falls back to templates"
            )
        if not self.flask_secret:
            problems.append("FLASK_SECRET not set — ephemeral session secret in use")
        return problems


settings = Settings()


def log_config_status() -> None:
    for problem in settings.validate():
        logger.warning("Config: %s", problem)
