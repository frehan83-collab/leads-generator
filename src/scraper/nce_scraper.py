"""
NCE Seafood Innovation member directory scraper.
Extracts member companies from the seafood innovation cluster.

NCE Seafood Innovation is an industry cluster representing the Norwegian seafood value chain.
Member companies are high-quality targets for recruiting.
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

NCE_MEMBERS_URL = "https://seafoodinnovation.no/our-partners-and-members/"


def _clean_domain(url: str) -> Optional[str]:
    """Extract clean domain from URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        domain = parsed.netloc.lstrip("www.")
        return domain if domain else None
    except Exception:
        return None


def scrape_nce_members() -> list[dict]:
    """
    Scrape NCE Seafood Innovation member directory.

    Returns:
        List of company dicts with:
            - name: Company name
            - website: Company website
            - domain: Clean domain
            - description: Company description (if available)
            - category: Member category (partner/member)
    """
    logger.info("Scraping NCE Seafood Innovation member directory...")

    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            logger.debug("Loading %s", NCE_MEMBERS_URL)
            page.goto(NCE_MEMBERS_URL, wait_until="domcontentloaded", timeout=25000)

            # Accept cookies if needed
            try:
                page.click("button:has-text('Accept'), button:has-text('Godta')", timeout=2000)
            except Exception:
                pass

            # Wait for content
            page.wait_for_timeout(2000)

            # Strategy 1: Look for member cards/sections
            # Try various common selectors for member listings
            member_selectors = [
                ".member",
                ".company",
                ".partner",
                "[class*='member']",
                "[class*='company']",
                "[class*='partner']",
                "article",
                ".wp-block-group",  # WordPress blocks
            ]

            members_found = []

            for selector in member_selectors:
                elements = page.query_selector_all(selector)
                if elements and len(elements) > 5:  # Likely found the right container
                    logger.debug("Found %d elements with selector: %s", len(elements), selector)
                    members_found = elements
                    break

            # Strategy 2: If no member cards, look for links with company names
            if not members_found:
                logger.debug("No member containers found, trying link-based extraction...")
                # Look for external links (likely company websites)
                links = page.query_selector_all("a[href^='http']")
                for link in links:
                    href = link.get_attribute("href") or ""
                    text = link.inner_text().strip()

                    # Skip navigation/social links
                    if not text or len(text) < 3:
                        continue
                    if any(skip in href.lower() for skip in [
                        "facebook", "linkedin", "twitter", "instagram",
                        "seafoodinnovation.no", "youtube", "vimeo"
                    ]):
                        continue

                    domain = _clean_domain(href)
                    if domain:
                        results.append({
                            "name": text,
                            "website": href,
                            "domain": domain,
                            "description": "",
                            "category": "member",
                        })

            # Strategy 3: Parse member cards if found
            else:
                for element in members_found:
                    try:
                        # Extract company name (heading or strong text)
                        name = ""
                        name_el = element.query_selector("h2, h3, h4, strong, .name, [class*='title']")
                        if name_el:
                            name = name_el.inner_text().strip()

                        if not name:
                            # Try getting first line of text
                            text_lines = [l.strip() for l in element.inner_text().split("\n") if l.strip()]
                            if text_lines:
                                name = text_lines[0]

                        # Extract website link
                        website = ""
                        link_el = element.query_selector("a[href^='http']")
                        if link_el:
                            website = link_el.get_attribute("href") or ""

                        # Extract description (remaining text)
                        description = ""
                        desc_el = element.query_selector("p, .description, [class*='desc']")
                        if desc_el:
                            description = desc_el.inner_text().strip()

                        if name:
                            domain = _clean_domain(website)
                            results.append({
                                "name": name,
                                "website": website,
                                "domain": domain,
                                "description": description,
                                "category": "member",
                            })

                    except Exception as exc:
                        logger.debug("Error parsing member element: %s", exc)
                        continue

            browser.close()

        except PWTimeout:
            logger.error("Timeout loading NCE members page")
            browser.close()
            return []

        except Exception as exc:
            logger.error("Error scraping NCE members: %s", exc)
            browser.close()
            return []

    # Deduplicate by name
    seen_names = set()
    unique_results = []
    for company in results:
        name_key = company["name"].lower().strip()
        if name_key not in seen_names:
            seen_names.add(name_key)
            unique_results.append(company)

    logger.info("Found %d NCE Seafood Innovation member companies", len(unique_results))
    return unique_results
