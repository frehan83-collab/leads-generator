"""
Shared browser lifecycle manager.
Creates ONE Playwright browser instance for the entire pipeline run.
Supports optional proxy and stealth mode.
"""

import os
import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Standard user agent for all scraping
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BrowserManager:
    """
    Shared browser context manager.
    Usage:
        with BrowserManager() as bm:
            ctx = bm.new_context()
            page = ctx.new_page()
            ...
            ctx.close()
    """

    def __init__(self, proxy: str = None, headless: bool = True):
        self._proxy = proxy or os.getenv("PROXY_URL")
        self._headless = headless
        self._pw_cm = None
        self._playwright = None
        self._browser = None

    def __enter__(self):
        self._pw_cm = sync_playwright()
        self._playwright = self._pw_cm.__enter__()
        launch_args = {"headless": self._headless}
        if self._proxy:
            launch_args["proxy"] = {"server": self._proxy}
            logger.info("Launching browser with proxy: %s", self._proxy)
        self._browser = self._playwright.chromium.launch(**launch_args)
        logger.debug("Shared browser launched (headless=%s)", self._headless)
        return self

    def __exit__(self, *args):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw_cm:
            try:
                self._pw_cm.__exit__(*args)
            except Exception:
                pass
        logger.debug("Shared browser closed")

    def new_context(self, **kwargs):
        """Create a new browser context with standard settings + stealth."""
        defaults = {
            "user_agent": USER_AGENT,
            "locale": "nb-NO",
        }
        defaults.update(kwargs)
        ctx = self._browser.new_context(**defaults)
        # Apply stealth if available
        try:
            from playwright_stealth import stealth_sync
            stealth_sync(ctx)
        except ImportError:
            pass
        return ctx

    @property
    def browser(self):
        return self._browser
