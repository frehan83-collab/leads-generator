"""
Test script to explore NAV Arbeidsplassen structure.
Run this to understand the page structure for scraping.
"""

from playwright.sync_api import sync_playwright
import time

def explore_nav():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # Visible browser for debugging
        page = browser.new_page()

        # Go to NAV with a search
        print("Navigating to NAV Arbeidsplassen...")
        page.goto("https://arbeidsplassen.nav.no/stillinger?q=seafood", wait_until="networkidle")

        # Wait for content to load
        print("Waiting for job listings to load...")
        time.sleep(3)

        # Try to find job cards
        print("\nTrying different selectors...")

        selectors = [
            "article",
            "[data-testid*='job']",
            "[data-testid*='stilling']",
            "a[href*='/stillinger/stilling/']",
            ".job-card",
            ".stilling",
        ]

        for selector in selectors:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    print(f"[OK] Found {len(elements)} elements with selector: {selector}")
                else:
                    print(f"[--] No elements for: {selector}")
            except Exception as exc:
                print(f"[!!] Error with selector {selector}: {exc}")

        # Try to find job title elements
        print("\nLooking for job title links...")
        job_links = page.query_selector_all("a[href*='/stillinger/stilling/']")
        if job_links:
            print(f"Found {len(job_links)} job links")
            print("\nFirst 3 job listings:")
            for i, link in enumerate(job_links[:3]):
                href = link.get_attribute("href")
                text = link.inner_text()
                print(f"\n  Job {i+1}:")
                print(f"    URL: {href}")
                print(f"    Text: {text[:100]}")

        # Get page HTML structure for analysis
        print("\nGetting page HTML structure...")
        html = page.content()
        with open("nav_page_structure.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved page HTML to nav_page_structure.html")

        input("\nPress Enter to close browser...")
        browser.close()

if __name__ == "__main__":
    explore_nav()
