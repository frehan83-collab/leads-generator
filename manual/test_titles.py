"""Quick live test - check titles are scraped from real company websites."""
import sys, logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, ".")

from src.scraper.website_scraper import scrape_emails_from_website

DOMAINS = ["biosort.no", "sinkaberg.no", "hofseth.no", "aquagen.no", "griegseafood.com"]

for domain in DOMAINS:
    contacts = scrape_emails_from_website(domain)
    print(f"\n{domain}:")
    for c in contacts:
        title_str = f" [{c['title']}]" if c["title"] else " [no title]"
        name_str = f" ({c['name']})" if c["name"] else ""
        print(f"  {c['email']}{name_str}{title_str}")
