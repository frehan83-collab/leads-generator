"""
Karrierestart.no scraper — searches job postings by keyword.
Uses Playwright for reliable rendering of dynamic content.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Generator

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

KARRIERESTART_BASE_URL = "https://karrierestart.no"
KARRIERESTART_SEARCH_URL = f"{KARRIERESTART_BASE_URL}/ledig-stilling"


def _build_search_url(keyword: str, page: int = 1) -> str:
    encoded = keyword.replace(" ", "+")
    url = f"{KARRIERESTART_SEARCH_URL}?q={encoded}"
    if page > 1:
        url += f"&page={page}"
    return url


def _extract_job_id(url: str) -> str:
    """Extract job ID from Karrierestart URL."""
    match = re.search(r"/(\d+)(?:\?|$|/)", url)
    if match:
        return match.group(1)
    match = re.search(r"/ledig-stilling/([^/\?]+)", url)
    return match.group(1) if match else url


def _parse_listing_page(page: Page, keyword: str) -> list[dict]:
    """Parse job cards on a Karrierestart search results page."""
    results = []
    try:
        page.wait_for_selector("a[href*='/ledig-stilling/'], .job-listing, article", timeout=12000)
    except PWTimeout:
        logger.warning("No job listings found on Karrierestart for '%s'", keyword)
        return results

    # Try job card containers
    cards = page.query_selector_all(".job-listing, article, .search-result-item, [class*='job-card']")
    if not cards:
        # Fallback: find links to job postings
        cards = page.query_selector_all("a[href*='/ledig-stilling/']")

    seen_ids = set()
    for card in cards:
        try:
            # Find job link
            link_el = card.query_selector("a[href*='/ledig-stilling/']") if card.tag_name != "a" else card
            if not link_el:
                continue
            href = link_el.get_attribute("href") or ""
            if not href or "/ledig-stilling/" not in href:
                continue
            if not href.startswith("http"):
                href = KARRIERESTART_BASE_URL + href

            job_id = _extract_job_id(href)
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Title
            title = ""
            title_el = card.query_selector("h2, h3, h4, [class*='title']")
            if title_el:
                title = title_el.inner_text().strip()
            if not title:
                title = link_el.inner_text().strip()
            if not title:
                continue

            # Company
            company = ""
            company_el = card.query_selector("[class*='company'], [class*='employer'], strong")
            if company_el:
                company = company_el.inner_text().strip()

            # Location
            location = ""
            location_el = card.query_selector("[class*='location'], [class*='place']")
            if location_el:
                location = location_el.inner_text().strip()

            # Published date
            published_at = None
            time_el = card.query_selector("time, [datetime]")
            if time_el:
                dt_attr = time_el.get_attribute("datetime")
                if dt_attr:
                    published_at = dt_attr[:10]

            results.append({
                "external_id": job_id,
                "source": "karrierestart",
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
            logger.debug("Error parsing Karrierestart card: %s", exc)
            continue

    logger.debug("Parsed %d cards on Karrierestart for '%s'", len(results), keyword)
    return results


def _has_next_page(page: Page, current_page: int) -> bool:
    try:
        next_btn = page.query_selector("a:has-text('Neste'), a[rel='next'], .pagination .next a")
        if next_btn:
            disabled = next_btn.get_attribute("disabled")
            aria_disabled = next_btn.get_attribute("aria-disabled")
            return disabled is None and aria_disabled != "true"
    except Exception:
        pass
    return False


def scrape_keyword(keyword: str, max_pages: int = 5, browser=None, known_ids: set = None) -> Generator[dict, None, None]:
    """Scrape karrierestart.no for a given keyword."""
    logger.info("Scraping karrierestart.no for keyword: '%s'", keyword)
    total = 0

    if browser is None:
        with sync_playwright() as pw:
            browser_local = pw.chromium.launch(headless=True)
            context = browser_local.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="nb-NO",
            )
            page = context.new_page()
            for posting in _scrape_pages(page, keyword, max_pages, known_ids):
                yield posting
                total += 1
            browser_local.close()
    else:
        from src.scraper.browser_manager import USER_AGENT
        context = browser.new_context(user_agent=USER_AGENT, locale="nb-NO")
        page = context.new_page()
        for posting in _scrape_pages(page, keyword, max_pages, known_ids):
            yield posting
            total += 1
        context.close()

    logger.info("Scraped %d postings from karrierestart.no for '%s'", total, keyword)


def _scrape_pages(page: Page, keyword: str, max_pages: int, known_ids: set = None) -> Generator[dict, None, None]:
    """Core pagination logic."""
    for page_num in range(1, max_pages + 1):
        url = _build_search_url(keyword, page_num)
        logger.debug("Fetching karrierestart page %d: %s", page_num, url)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)

            # Cookie banner
            try:
                page.click("button:has-text('Godta'), button:has-text('Aksepter')", timeout=2000)
                page.wait_for_timeout(500)
            except Exception:
                pass

            postings = _parse_listing_page(page, keyword)
            if not postings:
                logger.info("No results on page %d for '%s', stopping.", page_num, keyword)
                break

            if known_ids is not None:
                new_postings = [p for p in postings if p["external_id"] not in known_ids]
                if not new_postings:
                    logger.info("All %d postings on page %d already known for '%s', stopping early.", len(postings), page_num, keyword)
                    break
                postings = new_postings

            for posting in postings:
                yield posting

            if not _has_next_page(page, page_num):
                break

            page.wait_for_timeout(1000)

        except PWTimeout:
            logger.warning("Timeout on karrierestart page %d for '%s'", page_num, keyword)
            break
        except Exception as exc:
            logger.error("Error scraping karrierestart page %d: %s", page_num, exc)
            break


def scrape_all_keywords(keywords: list[str], max_pages: int = 5, browser=None, known_ids: set = None) -> Generator[dict, None, None]:
    seen_ids: set[str] = set()
    for keyword in keywords:
        for posting in scrape_keyword(keyword.strip(), max_pages=max_pages, browser=browser, known_ids=known_ids):
            jid = posting["external_id"]
            if jid not in seen_ids:
                seen_ids.add(jid)
                posting["scraped_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
                yield posting
            else:
                logger.debug("Duplicate karrierestart id=%s skipped", jid)
