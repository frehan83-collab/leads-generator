"""Quick live test of website email scraper."""
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
sys.path.insert(0, ".")

from src.scraper.website_scraper import scrape_emails_from_website

# A sample of domains resolved from the last finn.no run
DOMAINS = [
    "scaleaq.no",
    "griegseafood.com",
    "aquatrans.no",
    "salmar.no",
    "stingray.no",
    "nofima.no",
    "norcod.no",
    "delifish.no",
]

total_with_emails = 0
for domain in DOMAINS:
    emails = scrape_emails_from_website(domain)
    status = f"FOUND {emails}" if emails else "- no emails"
    print(f"  {domain:<30} {status}")
    if emails:
        total_with_emails += 1

print(f"\nDomains with emails: {total_with_emails}/{len(DOMAINS)}")
