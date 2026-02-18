"""
NAV Arbeidsplassen scraper - searches job postings by keyword and extracts structured data.
Uses Playwright for reliable rendering of dynamic content.

arbeidsplassen.nav.no is Norway's official public job board, managed by NAV
(Norwegian Labour and Welfare Administration).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Generator
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

NAV_BASE_URL = "https://arbeidsplassen.nav.no"
NAV_SEARCH_URL = f"{NAV_BASE_URL}/stillinger"


def _build_search_url(keyword: str, page: int = 0) -> str:
    """
    Build NAV search URL.
    NAV uses pagination starting from 0.
    """
    encoded = keyword.replace(" ", "+")
    url = f"{NAV_SEARCH_URL}?q={encoded}"
    if page > 0:
        url += f"&from={page * 50}"  # NAV shows 50 results per page
    return url


def _extract_job_id(url: str) -> str:
    """
    Extract job ID from NAV URL.
    Format: /stillinger/stilling/UUID or /stilling/UUID
    """
    match = re.search(r"/stilling/([a-f0-9\-]+)", url)
    return match.group(1) if match else url


def _parse_listing_page(page: Page, keyword: str) -> list[dict]:
    """
    Parse all job cards on a NAV search result page.
    """
    results = []

    try:
        # Wait for job listings to load
        page.wait_for_selector("a[href*='/stillinger/stilling/']", timeout=12000)
    except PWTimeout:
        logger.warning("No job listings found for keyword '%s'", keyword)
        return results

    # Find all job posting links
    job_links = page.query_selector_all("a[href*='/stillinger/stilling/']")

    logger.debug("Found %d job links on page", len(job_links))

    seen_ids = set()

    for link in job_links:
        try:
            href = link.get_attribute("href") or ""
            if not href:
                continue

            # Make absolute URL
            if href.startswith("/"):
                href = NAV_BASE_URL + href

            job_id = _extract_job_id(href)

            # Skip duplicates (NAV sometimes shows same job multiple times)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Get the parent container (job card)
            # NAV uses various structures, try multiple approaches
            container = link

            # Try to find a better container (parent article, section, or div with data-testid)
            for _ in range(5):  # Walk up max 5 levels
                parent = container.evaluate_handle("el => el.parentElement").as_element()
                if parent:
                    tag = parent.evaluate("el => el.tagName").lower()
                    if tag in ["article", "section"]:
                        container = parent
                        break
                    test_id = parent.get_attribute("data-testid") or ""
                    if "job" in test_id.lower() or "stilling" in test_id.lower():
                        container = parent
                        break
                else:
                    break

            # Extract title
            title = ""
            # Try h2, h3, heading elements first
            title_el = container.query_selector("h2, h3, h4, [role='heading']")
            if title_el:
                title = title_el.inner_text().strip()
            else:
                # Fallback: use link text
                title = link.inner_text().strip()

            if not title:
                continue

            # Extract company name
            # Look for text near "Arbeidsgiver:" or employer-related keywords
            container_text = container.inner_text()
            company = ""

            # Common patterns in NAV
            company_match = re.search(r"Arbeidsgiver[:\s]+([^\n]+)", container_text, re.IGNORECASE)
            if company_match:
                company = company_match.group(1).strip()
            else:
                # Try to find company in text (usually second line or after title)
                lines = [l.strip() for l in container_text.split("\n") if l.strip()]
                if len(lines) > 1:
                    # Skip first line (title), take next non-location line
                    for line in lines[1:]:
                        # Skip if it looks like a location (contains county or "Sted:")
                        if any(county in line.upper() for county in [
                            "OSLO", "VIKEN", "ROGALAND", "VESTLAND", "TRØNDELAG",
                            "NORDLAND", "TROMS", "FINNMARK", "MØRE", "AGDER",
                        ]):
                            continue
                        if "Sted:" in line:
                            continue
                        company = line
                        break

            # Extract location
            location = ""
            location_match = re.search(r"Sted[:\s]+([^\n]+)", container_text, re.IGNORECASE)
            if location_match:
                location = location_match.group(1).strip()
            else:
                # Look for Norwegian county names
                for line in container_text.split("\n"):
                    if any(county in line.upper() for county in [
                        "OSLO", "VIKEN", "ROGALAND", "VESTLAND", "TRØNDELAG",
                        "NORDLAND", "TROMS", "FINNMARK", "MØRE", "AGDER",
                    ]):
                        location = line.strip()
                        break

            results.append({
                "nav_id": job_id,
                "external_id": job_id,
                "source": "nav",
                "title": title,
                "company_name": company,
                "company_domain": None,
                "org_number": None,
                "location": location,
                "url": href,
                "keyword_matched": keyword,
                "published_at": None,
                "scraped_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            })

        except Exception as exc:
            logger.debug("Error parsing NAV job card: %s", exc)
            continue

    logger.debug("Parsed %d unique jobs for '%s'", len(results), keyword)
    return results


def _has_next_page(page: Page, current_page: int) -> bool:
    """
    Check if there's a next page.
    NAV uses a "Next" button or page numbers.
    """
    try:
        # Look for "Neste" (Next) button or link
        next_btn = page.query_selector("a:has-text('Neste'), button:has-text('Neste')")
        if next_btn:
            # Check if it's disabled
            disabled = next_btn.get_attribute("disabled")
            aria_disabled = next_btn.get_attribute("aria-disabled")
            return disabled is None and aria_disabled != "true"

        # Fallback: check if we can find a link to the next page number
        next_page_num = current_page + 2  # NAV uses 1-indexed pages in UI
        next_link = page.query_selector(f"a:has-text('{next_page_num}')")
        return next_link is not None

    except Exception:
        pass

    return False


def scrape_keyword(keyword: str, max_pages: int = 5) -> Generator[dict, None, None]:
    """
    Scrape arbeidsplassen.nav.no for a given keyword across multiple pages.
    Yields one dict per job posting.

    Args:
        keyword: Search keyword (e.g. "seafood", "aquaculture", "sjømat")
        max_pages: Maximum number of pages to scrape

    Yields:
        Job posting dict with keys:
            - nav_id, external_id, source
            - title, company_name, location
            - url, keyword_matched
            - scraped_at
    """
    logger.info("Scraping NAV Arbeidsplassen for keyword: '%s'", keyword)
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

        for page_num in range(max_pages):
            url = _build_search_url(keyword, page_num)
            logger.debug("Fetching page %d: %s", page_num + 1, url)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)

                # Accept cookie banner if present
                try:
                    page.click("button:has-text('Godta'), button:has-text('Aksepter'), button:has-text('Godkjenn')", timeout=2000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

                postings = _parse_listing_page(page, keyword)

                if not postings:
                    logger.info("No results on page %d for '%s', stopping.", page_num + 1, keyword)
                    break

                for posting in postings:
                    yield posting
                    total += 1

                # Check for next page
                if not _has_next_page(page, page_num):
                    logger.debug("No next page after page %d for '%s'", page_num + 1, keyword)
                    break

                # Be polite - wait between pages
                page.wait_for_timeout(1000)

            except PWTimeout:
                logger.warning("Timeout on page %d for keyword '%s'", page_num + 1, keyword)
                break
            except Exception as exc:
                logger.error("Error scraping page %d: %s", page_num + 1, exc)
                break

        browser.close()

    logger.info("Scraped %d postings from NAV for keyword '%s'", total, keyword)


def scrape_all_keywords(keywords: list[str], max_pages: int = 5) -> Generator[dict, None, None]:
    """
    Scrape NAV for all keywords. Deduplicates by nav_id across keywords.

    Args:
        keywords: List of search keywords
        max_pages: Maximum pages per keyword

    Yields:
        Job posting dicts
    """
    seen_ids: set[str] = set()

    for keyword in keywords:
        for posting in scrape_keyword(keyword.strip(), max_pages=max_pages):
            job_id = posting["nav_id"]
            if job_id not in seen_ids:
                seen_ids.add(job_id)
                yield posting
            else:
                logger.debug("Duplicate nav_id=%s skipped", job_id)
