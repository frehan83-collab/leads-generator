"""Verify Snov.io fixes work."""
import sys, time
sys.path.insert(0, ".")
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from src.snov.client import SnovClient
snov = SnovClient()

# Test 1: verify_email
print("=== verify_email ===")
result = snov.verify_email("frode.arntsen@salmar.no")
print(f"  Result: {result}")

# Test 2: add_prospect_to_list
print("\n=== add_prospect_to_list ===")
lists = snov.get_user_lists()
print(f"  Lists: {[(l.get('id'), l.get('name')) for l in lists]}")

if lists:
    list_id = str(lists[0]["id"])
    added = snov.add_prospect_to_list(list_id, {
        "email": "frode.arntsen@salmar.no",
        "first_name": "Frode",
        "last_name": "Arntsen",
        "full_name": "Frode Arntsen",
        "position": "Director",
        "company_name": "SalMar",
        "company_domain": "salmar.no",
    })
    print(f"  Added: {added}")
