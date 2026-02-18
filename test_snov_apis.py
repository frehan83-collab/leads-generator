"""Debug Snov.io API calls - check exact errors."""
import sys, os, json
sys.path.insert(0, ".")
import logging
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

import requests
from src.snov.client import SnovClient

snov = SnovClient()
token = snov._get_token()
headers = {"Authorization": f"Bearer {token}"}

# Test 1: verify_email — try different payload formats
print("\n=== Test verify_email ===")
for payload in [
    {"emails[]": ["test@griegseafood.com"]},
    {"emails": ["test@griegseafood.com"]},
    {"email": "test@griegseafood.com"},
]:
    import time; time.sleep(1.2)
    r = requests.post("https://api.snov.io/v2/email-verification/start", headers=headers, json=payload, timeout=15)
    print(f"  payload={list(payload.keys())} -> {r.status_code}: {r.text[:200]}")

# Test 2: add_prospect_to_list — check what list IDs exist
print("\n=== Existing lists ===")
time.sleep(1.2)
r = requests.get("https://api.snov.io/v1/get-user-lists", headers=headers, timeout=15)
print(f"  {r.status_code}: {r.text[:500]}")

# Test 3: add_prospect_to_list with minimal required fields
print("\n=== Test add_prospect_to_list ===")
# Get first list id
lists = r.json() if r.ok else []
if isinstance(lists, list) and lists:
    list_id = lists[0].get("id") or lists[0].get("listId")
    print(f"  Using list_id: {list_id}")
    time.sleep(1.2)
    payload = {
        "listId": list_id,
        "email": "frode.arntsen@salmar.no",
        "firstName": "Frode",
        "lastName": "Arntsen",
        "companyName": "SalMar",
        "companySite": "salmar.no",
    }
    r2 = requests.post("https://api.snov.io/v1/add-prospect-to-list", headers=headers, json=payload, timeout=15)
    print(f"  {r2.status_code}: {r2.text[:300]}")
else:
    print("  No lists found, trying to create one first")
    time.sleep(1.2)
    r_create = requests.post("https://api.snov.io/v1/lists", headers=headers, json={"name": "Finn.no Leads"}, timeout=15)
    print(f"  Create list: {r_create.status_code}: {r_create.text[:300]}")
