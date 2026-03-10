"""Retry decorator with exponential backoff for HTTP and Playwright calls."""

import logging
import time
import functools
from typing import Type

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 16.0,
    retryable_exceptions: tuple[Type[Exception], ...] = (Exception,),
):
    """
    Retry decorator with exponential backoff.

    - On HTTP 429: reads Retry-After header for delay
    - On 4xx (except 429): does NOT retry (client error)
    - On 5xx or connection errors: retries with backoff
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc

                    # Check if it's an HTTP error we shouldn't retry
                    import requests
                    if isinstance(exc, requests.exceptions.HTTPError):
                        status_code = exc.response.status_code if exc.response is not None else 0

                        if status_code == 429:
                            # Rate limited — use Retry-After header
                            retry_after = exc.response.headers.get("Retry-After")
                            delay = float(retry_after) if retry_after else base_delay * (2 ** (attempt - 1))
                            delay = min(delay, max_delay)
                        elif 400 <= status_code < 500:
                            # Client error (not 429) — don't retry
                            raise
                        else:
                            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    else:
                        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)

                    if attempt < max_attempts:
                        logger.warning(
                            "Retry %d/%d for %s after error: %s (delay=%.1fs)",
                            attempt, max_attempts, func.__name__, exc, delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_attempts, func.__name__, exc,
                        )
            raise last_exc
        return wrapper
    return decorator


def goto_with_retry(page, url: str, max_attempts: int = 3, **kwargs):
    """Retry wrapper for Playwright page.goto() calls."""
    from playwright.sync_api import TimeoutError as PWTimeout

    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return page.goto(url, **kwargs)
        except PWTimeout as exc:
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "Retry %d/%d for page.goto(%s): timeout",
                    attempt, max_attempts, url,
                )
                time.sleep(1.0 * attempt)
            else:
                logger.error("All %d goto attempts failed for %s", max_attempts, url)
    raise last_exc
