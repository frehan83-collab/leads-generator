"""
Test NAV Arbeidsplassen scraper.
"""

import sys
from src.scraper.nav_scraper import scrape_keyword
from src.logger import setup_logging

setup_logging("INFO")

def test_nav_scraper():
    print("\n=== Testing NAV Arbeidsplassen Scraper ===\n")

    keyword = "sjømat"  # Norwegian for seafood
    print(f"Searching for: {keyword}")
    print("Fetching first page (max 10 results)...\n")

    results = []
    for i, posting in enumerate(scrape_keyword(keyword, max_pages=1)):
        results.append(posting)
        if i >= 9:  # Stop after 10 results
            break

    if results:
        print(f"[OK] Found {len(results)} job postings\n")
        print("Sample postings:")
        for i, posting in enumerate(results[:3], 1):
            print(f"\n{i}. {posting['title']}")
            print(f"   Company: {posting['company_name']}")
            print(f"   Location: {posting['location']}")
            print(f"   URL: {posting['url']}")
            print(f"   ID: {posting['nav_id']}")
    else:
        print("[WARN] No results found. This might be expected if 'seafood' has no matches on NAV.")
        print("Try a more general Norwegian term like 'leder' or 'sjømat'")
        return False

    print("\n=== Test completed successfully ===\n")
    return True

if __name__ == "__main__":
    try:
        success = test_nav_scraper()
        sys.exit(0 if success else 1)
    except Exception as exc:
        print(f"\n[ERROR] Test failed: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
