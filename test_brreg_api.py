"""
Test script for BRREG API client.
Verifies connection and data retrieval.
"""

import sys
from src.brreg.client import BRREGClient

def test_basic_search():
    """Test searching for aquaculture companies."""
    print("\n=== Testing BRREG API ===\n")

    client = BRREGClient()

    # Test 1: Search for aquaculture companies (first page)
    print("Test 1: Searching for aquaculture companies (NACE 03.2)...")
    result = client.search_companies_by_nace(["03.2"], page=0, size=5)

    companies = result.get("_embedded", {}).get("enheter", [])
    total = result.get("page", {}).get("totalElements", 0)

    print(f"[OK] Found {total} total aquaculture companies")
    print(f"[OK] Retrieved {len(companies)} companies in first batch\n")

    if companies:
        print("Sample company:")
        sample = companies[0]
        contact = client.extract_contact_info(sample)
        for key, value in contact.items():
            print(f"  {key:20} {value}")

        # Test 2: Get roles for this company
        org_num = contact["org_number"]
        print(f"\nTest 2: Fetching board members for {contact['name']}...")
        roles = client.get_company_roles(org_num)
        decision_makers = client.extract_decision_makers(roles)

        if decision_makers:
            print(f"[OK] Found {len(decision_makers)} decision makers:")
            for dm in decision_makers:
                print(f"  - {dm['name']:30} ({dm['role_description']})")
        else:
            print("  No decision makers found (may be private company)")

    # Test 3: Get all seafood companies (limited sample)
    print("\n\nTest 3: Fetching all seafood-related companies (sample of 20)...")
    seafood_companies = list(client.get_seafood_companies(max_results=20))
    print(f"[OK] Retrieved {len(seafood_companies)} companies")

    print("\nIndustry breakdown:")
    nace_counts = {}
    for company in seafood_companies:
        nace = company.get("naeringskode1", {}).get("beskrivelse", "Unknown")
        nace_counts[nace] = nace_counts.get(nace, 0) + 1

    for nace, count in sorted(nace_counts.items(), key=lambda x: -x[1]):
        print(f"  {nace:50} {count:3} companies")

    print("\n=== All tests passed! ===\n")
    return True

if __name__ == "__main__":
    try:
        test_basic_search()
    except Exception as exc:
        print(f"\n[ERROR] Test failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
