"""Central configuration via environment variables."""

import os
from pydantic_settings import BaseSettings
from typing import Optional

_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str

    # Database
    database_url: str = "sqlite:///./invoices.db"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Email (IMAP)
    email_imap_host: Optional[str] = None
    email_imap_user: Optional[str] = None
    email_imap_password: Optional[str] = None
    email_imap_port: int = 993
    email_poll_interval: int = 60  # seconds

    # File storage
    storage_path: str = "./uploads"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me-in-production"

    # AI models
    vision_model: str = "claude-sonnet-4-6"
    text_model: str = "claude-haiku-4-5"

    # Processing thresholds
    confidence_threshold: float = 0.85  # flag below this for review
    max_file_size_mb: int = 50

    class Config:
        env_file = _ENV_FILE
        env_file_encoding = "utf-8"


settings = Settings()
