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
    # Posting revalidation per run (keeps campaigns tied to live ads).
    revalidate_limit: int = int(os.getenv("REVALIDATE_LIMIT", "50"))
    revalidate_max_age_days: int = int(os.getenv("REVALIDATE_MAX_AGE_DAYS", "7"))
    revalidate_budget_sec: int = int(os.getenv("REVALIDATE_BUDGET_SEC", "300"))

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
    from_email: str = os.getenv("FROM_EMAIL", "fredrik@mail.sperton.com")
    from_name: str = os.getenv("FROM_NAME", "Fredrik Hansen")
    # Where replies land (monitored inbox). Defaults to the human address —
    # never the subdomain, which nobody reads.
    reply_to_email: str | None = os.getenv("REPLY_TO_EMAIL", "fredrik@sperton.com")
    send_time: str = os.getenv("SEND_TIME", "08:30")
    # Safe default: follow-ups are created as drafts awaiting human approval.
    # Set FOLLOWUP_AUTO_SEND=true to restore fully automatic sequences.
    followup_auto_send: bool = _as_bool(os.getenv("FOLLOWUP_AUTO_SEND"), False)
    followup_min_days: int = int(os.getenv("FOLLOWUP_MIN_DAYS", "3"))
    followup_max_step: int = int(os.getenv("FOLLOWUP_MAX_STEP", "3"))

    # -- AI -------------------------------------------------------------
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")

    # -- Inbox reply detection ------------------------------------------
    # Generic IMAP (Gmail/app-passwords/any IMAP). NOTE: Microsoft 365
    # retired basic-auth IMAP — that tenant needs the Graph provider.
    inbox_imap_host: str | None = os.getenv("INBOX_IMAP_HOST")
    inbox_imap_port: int = int(os.getenv("INBOX_IMAP_PORT", "993"))
    inbox_imap_user: str | None = os.getenv("INBOX_IMAP_USER")
    inbox_imap_pass: str | None = os.getenv("INBOX_IMAP_PASS")
    inbox_imap_folder: str = os.getenv("INBOX_IMAP_FOLDER", "INBOX")
    inbox_check_minutes: int = int(os.getenv("INBOX_CHECK_MINUTES", "30"))
    inbox_lookback_days: int = int(os.getenv("INBOX_LOOKBACK_DAYS", "7"))

    # -- Web ------------------------------------------------------------
    flask_secret: str | None = os.getenv("FLASK_SECRET")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_format: str = os.getenv("LOG_FORMAT", "pretty")
    # Public base URL of this dashboard (for one-click unsubscribe links).
    # Unset = no URL-based unsubscribe (mailto headers only, if configured).
    app_base_url: str | None = os.getenv("APP_BASE_URL")
    unsubscribe_mailto: str | None = os.getenv("UNSUBSCRIBE_MAILTO")
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

    @staticmethod
    def validate_time(value: str, name: str) -> str:
        """Validate an HH:MM daily time. Raises ValueError with guidance.

        NOTE: the `schedule` library triggers in server-local time, not UTC.
        Set the server timezone (or the value) accordingly.
        """
        import re as _re

        if not _re.fullmatch(r"\d{2}:\d{2}", value or ""):
            raise ValueError(
                f"{name}={value!r} is invalid — use 24h HH:MM (server-local time)."
            )
        hour, minute = int(value[:2]), int(value[3:])
        if hour > 23 or minute > 59:
            raise ValueError(
                f"{name}={value!r} is invalid — use 24h HH:MM (server-local time)."
            )
        return value

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


def resolve_keywords() -> list[str]:
    """Keywords for a pipeline run: Settings table first, .env fallback.

    The table is what the user edits in the UI (/settings). The .env list
    seeds the table on first load and covers fresh/empty databases.
    """
    try:
        from src.database import db

        words = db.get_keyword_list()
        if words:
            return words
    except Exception as exc:
        logger.warning("Keyword table unreadable, falling back to .env: %s", exc)
    return list(settings.finn_keywords)
