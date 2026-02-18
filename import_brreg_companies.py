"""
Import companies from BRREG into local database.
Run this to populate your master company database with all Norwegian seafood/aquaculture companies.

Usage:
    python import_brreg_companies.py --all           # Import all seafood companies
    python import_brreg_companies.py --aquaculture   # Only aquaculture (NACE 03.2)
    python import_brreg_companies.py --limit 100     # Limit to 100 companies (for testing)
"""

import argparse
import logging
from src.brreg.client import BRREGClient
from src.database import db
from src.logger import setup_logging

logger = logging.getLogger(__name__)


def import_companies(nace_codes: list[str], max_results: int = 10000, fetch_roles: bool = True):
    """
    Import companies from BRREG into database.

    Args:
        nace_codes: List of NACE codes to fetch
        max_results: Maximum companies to import
        fetch_roles: Whether to also fetch board members/roles
    """
    client = BRREGClient()
    db.init_db()

    logger.info("Starting BRREG import for NACE codes: %s", nace_codes)
    logger.info("Max results: %d, Fetch roles: %s", max_results, fetch_roles)

    stats = {
        "companies_fetched": 0,
        "companies_new": 0,
        "companies_existing": 0,
        "roles_fetched": 0,
        "roles_new": 0,
        "errors": 0,
    }

    # Fetch and store companies
    for company in client.get_all_companies_by_nace(nace_codes, max_results):
        stats["companies_fetched"] += 1

        # Extract contact info
        contact = client.extract_contact_info(company)
        org_number = contact["org_number"]

        if not org_number:
            logger.warning("Skipping company with no org number: %s", contact.get("name"))
            continue

        # Check if exists
        if db.company_exists(org_number):
            stats["companies_existing"] += 1
            logger.debug("Company %s already in DB, skipping", org_number)
            continue

        # Insert company
        company_id = db.insert_company(contact)
        if company_id:
            stats["companies_new"] += 1
            logger.info(
                "[%d/%d] Imported: %s (org: %s, NACE: %s)",
                stats["companies_new"],
                stats["companies_fetched"],
                contact["name"],
                org_number,
                contact["nace_code"],
            )

            # Fetch and store roles (board members, CEO, etc.)
            if fetch_roles:
                try:
                    roles = client.get_company_roles(org_number)
                    decision_makers = client.extract_decision_makers(roles)

                    for dm in decision_makers:
                        role_data = {
                            "company_id": company_id,
                            "org_number": org_number,
                            "person_name": dm["name"],
                            "role_code": dm["role_code"],
                            "role_description": dm["role_description"],
                            "birth_date": dm["birth_date"],
                        }
                        role_id = db.insert_company_role(role_data)
                        if role_id:
                            stats["roles_new"] += 1

                    if decision_makers:
                        logger.info(
                            "  + %d decision makers: %s",
                            len(decision_makers),
                            ", ".join(f"{dm['name']} ({dm['role_code']})" for dm in decision_makers[:3]),
                        )
                        stats["roles_fetched"] += len(decision_makers)

                except Exception as exc:
                    logger.error("Error fetching roles for %s: %s", org_number, exc)
                    stats["errors"] += 1

        # Progress update every 50 companies
        if stats["companies_fetched"] % 50 == 0:
            logger.info(
                "Progress: %d fetched, %d new, %d existing, %d roles",
                stats["companies_fetched"],
                stats["companies_new"],
                stats["companies_existing"],
                stats["roles_new"],
            )

    # Final summary
    logger.info("=== Import complete ===")
    logger.info("Companies fetched:    %d", stats["companies_fetched"])
    logger.info("Companies new:        %d", stats["companies_new"])
    logger.info("Companies existing:   %d", stats["companies_existing"])
    logger.info("Roles fetched:        %d", stats["roles_fetched"])
    logger.info("Roles new:            %d", stats["roles_new"])
    logger.info("Errors:               %d", stats["errors"])

    return stats


def main():
    parser = argparse.ArgumentParser(description="Import BRREG companies into database")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Import all seafood-related companies (aquaculture, fishing, processing, wholesale)",
    )
    parser.add_argument(
        "--aquaculture",
        action="store_true",
        help="Import only aquaculture companies (NACE 03.2)",
    )
    parser.add_argument(
        "--fishing",
        action="store_true",
        help="Import only fishing companies (NACE 03.1)",
    )
    parser.add_argument(
        "--processing",
        action="store_true",
        help="Import only fish processing companies (NACE 10.2)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximum number of companies to import (default: 10000)",
    )
    parser.add_argument(
        "--no-roles",
        action="store_true",
        help="Skip fetching board members/roles (faster)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    # Determine which NACE codes to import
    nace_codes = []
    if args.all:
        nace_codes = ["03.2", "03.1", "10.2", "46.38"]
        logger.info("Importing ALL seafood-related companies")
    elif args.aquaculture:
        nace_codes = ["03.2"]
        logger.info("Importing AQUACULTURE companies")
    elif args.fishing:
        nace_codes = ["03.1"]
        logger.info("Importing FISHING companies")
    elif args.processing:
        nace_codes = ["10.2"]
        logger.info("Importing FISH PROCESSING companies")
    else:
        # Default: aquaculture only
        nace_codes = ["03.2"]
        logger.info("Importing AQUACULTURE companies (default). Use --all for all seafood companies.")

    import_companies(
        nace_codes=nace_codes,
        max_results=args.limit,
        fetch_roles=not args.no_roles,
    )


if __name__ == "__main__":
    main()
