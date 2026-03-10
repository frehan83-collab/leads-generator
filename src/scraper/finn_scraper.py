"""
Finn.no scraper — searches job postings by keyword and extracts structured data.
Uses Playwright for reliable rendering of dynamic content.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Generator

from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

FINN_SEARCH_URL = "https://www.finn.no/job/search"
FINN_BASE_URL = "https://www.finn.no"


def scrape_company_domain(posting_url: str, browser=None) -> str | None:
    """
    Visit a finn.no job posting page and extract the company's website domain
    from the 'Hjemmeside' link in the sidebar.
    Returns e.g. 'leroyseafood.com', or None if not found.

    Args:
        posting_url: URL of the finn.no job posting
        browser: Optional shared Playwright browser instance for reuse
    """
    try:
        if browser is None:
            # Standalone mode — create own browser
            with sync_playwright() as pw:
                br = pw.chromium.launch(headless=True)
                page = br.new_page()
                page.goto(posting_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.click("button:has-text('Godta alle')", timeout=2000)
                except Exception:
                    pass
                link_el = page.query_selector("a:has-text('Hjemmeside')")
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    if href:
                        parsed = urlparse(href)
                        domain = parsed.netloc.lstrip("www.")
                        br.close()
                        logger.debug("Found domain from finn.no posting: %s -> %s", posting_url, domain)
                        return domain
                br.close()
        else:
            # Shared browser mode — create a context, use it, close it
            from src.scraper.browser_manager import USER_AGENT
            ctx = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
            page = ctx.new_page()
            try:
                page.goto(posting_url, wait_until="domcontentloaded", timeout=20000)
                try:
                    page.click("button:has-text('Godta alle')", timeout=2000)
                except Exception:
                    pass
                link_el = page.query_selector("a:has-text('Hjemmeside')")
                if link_el:
                    href = link_el.get_attribute("href") or ""
                    if href:
                        parsed = urlparse(href)
                        domain = parsed.netloc.lstrip("www.")
                        logger.debug("Found domain from finn.no posting: %s -> %s", posting_url, domain)
                        return domain
            finally:
                ctx.close()
    except Exception as exc:
        logger.debug("scrape_company_domain error for %s: %s", posting_url, exc)
    return None


def _build_search_url(keyword: str, page: int = 1) -> str:
    encoded = keyword.replace(" ", "+")
    url = f"{FINN_SEARCH_URL}?q={encoded}"
    if page > 1:
        url += f"&page={page}"
    return url


def _extract_finn_id(url: str) -> str:
    # New format: /job/ad/123456789
    match = re.search(r"/job/ad/(\d+)", url)
    if match:
        return match.group(1)
    # Legacy format: finnkode=123456789
    match = re.search(r"finnkode=(\d+)", url)
    if match:
        return match.group(1)
    match = re.search(r"/(\d+)$", url.rstrip("/"))
    return match.group(1) if match else url


def _parse_relative_date(text: str) -> str | None:
    """Parse Norwegian relative date strings to ISO date."""
    from datetime import timedelta
    text = text.strip().lower()
    today = datetime.now(timezone.utc).replace(tzinfo=None)

    if text in ("i dag", "today"):
        return today.strftime("%Y-%m-%d")
    if text in ("i går", "yesterday"):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # "X dager siden"
    match = re.match(r"(\d+)\s*dager?\s*siden", text)
    if match:
        days = int(match.group(1))
        return (today - timedelta(days=days)).strftime("%Y-%m-%d")

    # "X timer siden" (hours ago -> today)
    match = re.match(r"(\d+)\s*timer?\s*siden", text)
    if match:
        return today.strftime("%Y-%m-%d")

    # "DD.MM.YYYY" Norwegian date format
    match = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    return None


def _parse_listing_page(page: Page, keyword: str) -> list[dict]:
    """Parse all job cards on a search result page."""
    results = []
    try:
        page.wait_for_selector("article", timeout=12000)
    except PWTimeout:
        logger.warning("No job cards found for keyword '%s'", keyword)
        return results

    articles = page.query_selector_all("article")
    for article in articles:
        try:
            # Job link — new finn.no uses /job/ad/ID
            link_el = article.query_selector("a[href*='/job/ad/']")
            if not link_el:
                continue
            href = link_el.get_attribute("href") or ""
            if href and not href.startswith("http"):
                href = FINN_BASE_URL + href

            finn_id = _extract_finn_id(href)
            if not finn_id:
                continue

            # Title — the link text or heading inside the card
            title = link_el.inner_text().strip()
            if not title:
                title_el = article.query_selector(".h4, h2, h3, [id^='card-heading-']")
                title = title_el.inner_text().strip() if title_el else ""

            # Company — .text-caption.s-text-subtle or <strong>
            company_el = article.query_selector(".text-caption.s-text-subtle, .s-text-subtle strong, strong")
            company = company_el.inner_text().strip() if company_el else ""

            # Location — inside the pill list
            location_el = article.query_selector("li.min-w-0 span, .job-card__pills li:first-child span")
            location = location_el.inner_text().strip() if location_el else ""

            # Published date
            published_at = None
            time_el = article.query_selector("time, [datetime]")
            if time_el:
                dt_attr = time_el.get_attribute("datetime")
                if dt_attr:
                    published_at = dt_attr[:10] if len(dt_attr) >= 10 else dt_attr
                else:
                    time_text = time_el.inner_text().strip()
                    published_at = _parse_relative_date(time_text)

            if not title:
                continue

            results.append({
                "finn_id": finn_id,
                "external_id": finn_id,
                "source": "finn",
                "title": title,
                "company_name": company,
                "company_domain": None,
                "org_number": None,
                "location": location,
                "url": href,
                "keyword_matched": keyword,
                "published_at": published_at,
            })
        except Exception as exc:
            logger.debug("Error parsing article: %s", exc)
            continue

    logger.debug("Parsed %d cards on this page for '%s'", len(results), keyword)
    return results


def _has_next_page(page: Page, current_page: int) -> bool:
    """Check if there is a next page link."""
    try:
        next_label = f"Side {current_page + 1}"
        next_btn = page.query_selector(f"a[aria-label='{next_label}']")
        return next_btn is not None
    except Exception:
        pass
    return False


def scrape_keyword(keyword: str, max_pages: int = 5, browser=None, known_ids: set = None) -> Generator[dict, None, None]:
    """
    Scrape finn.no for a given keyword across multiple pages.
    Yields one dict per job posting.

    Args:
        keyword: Search keyword
        max_pages: Maximum number of pages to scrape
        browser: Optional shared Playwright browser instance for reuse
        known_ids: Optional set of external_ids already in DB (for incremental scraping)
    """
    logger.info("Scraping finn.no for keyword: '%s'", keyword)
    total = 0

    def _scrape_with_context(context):
        nonlocal total
        page = context.new_page()

        for page_num in range(1, max_pages + 1):
            url = _build_search_url(keyword, page_num)
            logger.debug("Fetching page %d: %s", page_num, url)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)

                # Accept cookie banner if present
                try:
                    page.click("button:has-text('Godta alle')", timeout=3000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

                postings = _parse_listing_page(page, keyword)
                if not postings:
                    logger.info("No results on page %d for '%s', stopping.", page_num, keyword)
                    break

                # Incremental: skip already-known postings
                if known_ids is not None:
                    new_postings = [p for p in postings if p["external_id"] not in known_ids]
                    if len(new_postings) == 0:
                        logger.info("All %d postings on page %d already known for '%s', stopping early.", len(postings), page_num, keyword)
                        break
                    postings = new_postings

                for posting in postings:
                    yield posting
                    total += 1

                if not _has_next_page(page, page_num):
                    logger.debug("No next page after page %d for '%s'", page_num, keyword)
                    break

            except PWTimeout:
                logger.warning("Timeout on page %d for keyword '%s'", page_num, keyword)
                break
            except Exception as exc:
                logger.error("Error scraping page %d: %s", page_num, exc)
                break

    if browser is None:
        # Standalone mode — create own browser
        with sync_playwright() as pw:
            br = pw.chromium.launch(headless=True)
            context = br.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="nb-NO",
            )
            yield from _scrape_with_context(context)
            br.close()
    else:
        # Shared browser mode
        from src.scraper.browser_manager import USER_AGENT
        context = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
        try:
            yield from _scrape_with_context(context)
        finally:
            context.close()

    logger.info("Scraped %d postings for keyword '%s'", total, keyword)


def scrape_all_keywords(keywords: list[str], max_pages: int = 5, browser=None, known_ids: set = None) -> Generator[dict, None, None]:
    """
    Scrape finn.no for all keywords. Deduplicates by finn_id across keywords.

    Args:
        keywords: List of search keywords
        max_pages: Maximum pages per keyword
        browser: Optional shared Playwright browser instance for reuse
        known_ids: Optional set of external_ids already in DB (for incremental scraping)
    """
    seen_ids: set[str] = set()
    for keyword in keywords:
        for posting in scrape_keyword(keyword.strip(), max_pages=max_pages, browser=browser, known_ids=known_ids):
            finn_id = posting["finn_id"]
            if finn_id not in seen_ids:
                seen_ids.add(finn_id)
                posting["scraped_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
                yield posting
            else:
                logger.debug("Duplicate finn_id=%s skipped", finn_id)
