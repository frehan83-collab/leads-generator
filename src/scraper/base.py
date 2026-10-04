"""
Shared plumbing for all Playwright scrapers.

- browser_context(): one context manager for standalone (own browser, always
  closed) and shared-browser mode (fresh context, always closed). Replaces the
  copy-pasted standalone/shared blocks that leaked browsers on exceptions.
- accept_cookies(): Norwegian cookie-banner variants in one place.
- check_selectors(): selector health report for a page (no raise).
- snapshot_on_fail(): best-effort HTML (+PNG) dump to logs/snapshots/ so a
  site redesign is diagnosable without re-running the scrape.
"""

import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

COOKIE_BUTTON_SELECTORS = (
    "button:has-text('Godta alle')",
    "button:has-text('Godta')",
    "button:has-text('Aksepter')",
    "button:has-text('Godkjenn')",
)

SNAPSHOT_DIR = Path(__file__).parent.parent.parent / "logs" / "snapshots"


@contextmanager
def browser_context(browser=None, headless: bool = True):
    """Yield a ready Playwright BrowserContext; always closes it afterwards.

    Args:
        browser: shared playwright Browser instance, or None to launch a
            throwaway headless browser for this block.
    """
    if browser is None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=headless)
            try:
                with _managed_context(br) as ctx:
                    yield ctx
            finally:
                try:
                    br.close()
                except Exception:
                    pass
    else:
        with _managed_context(browser) as ctx:
            yield ctx


@contextmanager
def _managed_context(browser):
    """Fresh stealth context on a Browser; closed on exit."""
    from src.scraper.browser_manager import USER_AGENT, apply_stealth_to_context

    ctx = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
    try:
        apply_stealth_to_context(ctx)
        yield ctx
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def accept_cookies(page, timeout: int = 2000) -> bool:
    """Click the first matching Norwegian cookie-accept button. Never raises."""
    for selector in COOKIE_BUTTON_SELECTORS:
        try:
            page.click(selector, timeout=timeout)
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def check_selectors(page, selectors: dict[str, str]) -> dict[str, int]:
    """Return match counts per named selector. Never raises (returns -1 on error)."""
    health: dict[str, int] = {}
    for name, selector in selectors.items():
        try:
            health[name] = len(page.query_selector_all(selector))
        except Exception:
            health[name] = -1
    return health


def snapshot_on_fail(page, label: str):
    """Save page HTML (+PNG best-effort) for post-mortem. Returns path or None."""
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:40]
        html_path = SNAPSHOT_DIR / f"{safe}_{stamp}.html"
        html_path.write_text(page.content(), encoding="utf-8", errors="replace")
        try:
            page.screenshot(path=str(html_path.with_suffix(".png")), full_page=False)
        except Exception:
            pass
        logger.warning("Saved failure snapshot: %s", html_path)
        return str(html_path)
    except Exception as exc:
        logger.debug("snapshot_on_fail failed: %s", exc)
        return None
