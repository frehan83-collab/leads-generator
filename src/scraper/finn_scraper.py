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


def scrape_company_domain(posting_url: str) -> str | None:
    """
    Visit a finn.no job posting page and extract the company's website domain
    from the 'Hjemmeside' link in the sidebar.
    Returns e.g. 'leroyseafood.com', or None if not found.
    """
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(posting_url, wait_until="domcontentloaded", timeout=20000)
            # Accept cookie banner if present
            try:
                page.click("button:has-text('Godta alle')", timeout=2000)
            except Exception:
                pass
            # Find the Hjemmeside link
            link_el = page.query_selector("a:has-text('Hjemmeside')")
            if link_el:
                href = link_el.get_attribute("href") or ""
                if href:
                    parsed = urlparse(href)
                    domain = parsed.netloc.lstrip("www.")
                    browser.close()
                    logger.debug("Found domain from finn.no posting: %s → %s", posting_url, domain)
                    return domain
            browser.close()
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
                "published_at": None,
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


def scrape_keyword(keyword: str, max_pages: int = 5) -> Generator[dict, None, None]:
    """
    Scrape finn.no for a given keyword across multiple pages.
    Yields one dict per job posting.
    """
    logger.info("Scraping finn.no for keyword: '%s'", keyword)
    total = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="nb-NO",
        )
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

        browser.close()

    logger.info("Scraped %d postings for keyword '%s'", total, keyword)


def scrape_all_keywords(keywords: list[str], max_pages: int = 5) -> Generator[dict, None, None]:
    """
    Scrape finn.no for all keywords. Deduplicates by finn_id across keywords.
    """
    seen_ids: set[str] = set()
    for keyword in keywords:
        for posting in scrape_keyword(keyword.strip(), max_pages=max_pages):
            finn_id = posting["finn_id"]
            if finn_id not in seen_ids:
                seen_ids.add(finn_id)
                posting["scraped_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
                yield posting
            else:
                logger.debug("Duplicate finn_id=%s skipped", finn_id)
