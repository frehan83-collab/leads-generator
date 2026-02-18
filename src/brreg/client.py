"""
BRREG (Brønnøysundregistrene) API Client
Official Norwegian Business Registry - Free and Open API

Provides access to:
- All registered companies in Norway
- Company details (name, address, industry codes, employee count)
- Board members and management roles
- Filter by NACE industry codes

API Documentation: https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html
"""

import logging
import time
from typing import Optional, Generator
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data.brreg.no/enhetsregisteret/api"
RATE_LIMIT_DELAY = 0.5  # Be respectful to free API

# NACE codes for target industries
NACE_CODES = {
    "aquaculture": "03.2",  # Aquaculture
    "fish_processing": "10.2",  # Processing and preserving of fish, crustaceans and molluscs
    "fishing": "03.1",  # Fishing
    "wholesale_fish": "46.38",  # Wholesale of fish, crustaceans and molluscs
}


class BRREGClient:
    """Client for interacting with BRREG (Norwegian Business Registry) API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "LeadsGenerator/1.0 (Lead generation tool)",
        })

    def _get(self, path: str, params: dict = None) -> dict:
        """Make GET request with rate limiting."""
        time.sleep(RATE_LIMIT_DELAY)
        url = f"{BASE_URL}{path}"
        try:
            resp = self.session.get(url, params=params or {}, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("BRREG API error for %s: %s", url, exc)
            raise

    def search_companies_by_nace(
        self,
        nace_codes: list[str],
        page: int = 0,
        size: int = 100,
    ) -> dict:
        """
        Search for companies by NACE industry codes.

        Args:
            nace_codes: List of NACE codes (e.g. ["03.2", "10.2"])
            page: Page number (0-indexed)
            size: Results per page (max 100, default 20)

        Returns:
            Response dict with:
                - _embedded.enheter: List of company entities
                - page: Pagination info (totalElements, totalPages, etc.)

        Note: Max 10,000 results per query due to API limits.
        Use (page+1) × size <= 10,000
        """
        params = {
            "naeringskode": ",".join(nace_codes),
            "page": page,
            "size": min(size, 100),
        }
        result = self._get("/enheter", params)
        total = result.get("page", {}).get("totalElements", 0)
        logger.info(
            "BRREG search: NACE %s, page %d/%d, found %d total companies",
            nace_codes,
            page,
            result.get("page", {}).get("totalPages", 0),
            total,
        )
        return result

    def get_all_companies_by_nace(
        self,
        nace_codes: list[str],
        max_results: int = 10000,
    ) -> Generator[dict, None, None]:
        """
        Fetch all companies matching NACE codes (up to 10,000 due to API limit).
        Yields one company dict at a time.

        Args:
            nace_codes: List of NACE codes
            max_results: Maximum companies to fetch (default 10,000)

        Yields:
            Company dict with fields:
                - organisasjonsnummer
                - navn (company name)
                - organisasjonsform.kode (legal form)
                - naeringskode1 (primary NACE code)
                - forretningsadresse (business address)
                - antallAnsatte (employee count)
                - hjemmeside (website)
        """
        page = 0
        size = 100
        total_fetched = 0

        while total_fetched < max_results:
            try:
                result = self.search_companies_by_nace(nace_codes, page=page, size=size)
                companies = result.get("_embedded", {}).get("enheter", [])

                if not companies:
                    logger.info("No more companies found, stopping pagination")
                    break

                for company in companies:
                    if total_fetched >= max_results:
                        break
                    yield company
                    total_fetched += 1

                # Check if we've reached the last page
                page_info = result.get("page", {})
                if page >= page_info.get("totalPages", 0) - 1:
                    break

                # Check 10k API limit: (page+1) * size <= 10000
                if (page + 2) * size > 10000:
                    logger.warning(
                        "Approaching BRREG API 10k result limit at page %d. "
                        "Use more specific NACE codes or download full dataset.",
                        page,
                    )
                    break

                page += 1

            except Exception as exc:
                logger.error("Error fetching page %d: %s", page, exc)
                break

        logger.info("Fetched %d companies from BRREG", total_fetched)

    def get_company_details(self, org_number: str) -> Optional[dict]:
        """
        Get detailed information for a specific company.

        Args:
            org_number: Organization number (9 digits)

        Returns:
            Company details dict with full information
        """
        try:
            return self._get(f"/enheter/{org_number}")
        except Exception as exc:
            logger.error("Error fetching company %s: %s", org_number, exc)
            return None

    def get_company_roles(self, org_number: str) -> list[dict]:
        """
        Get board members and management roles for a company.

        Args:
            org_number: Organization number (9 digits)

        Returns:
            List of role dicts with:
                - rolle.kode: Role code (DAGL=CEO, LEDE=Board member, NEST=Deputy, etc.)
                - rolle.beskrivelse: Role description in Norwegian
                - person.navn: Person's full name (if public)
                - person.fodselsdato: Birth date (partial, for disambiguation)

        Note: Personal identification numbers require authenticated API access.
        """
        try:
            result = self._get(f"/enheter/{org_number}/roller")
            roles = result.get("rollegrupper", [])

            # Flatten role groups into simple list
            all_roles = []
            for group in roles:
                for role in group.get("roller", []):
                    all_roles.append(role)

            logger.info("Found %d roles for company %s", len(all_roles), org_number)
            return all_roles
        except Exception as exc:
            logger.error("Error fetching roles for %s: %s", org_number, exc)
            return []

    def get_aquaculture_companies(self, max_results: int = 10000) -> Generator[dict, None, None]:
        """
        Convenience method: Get all aquaculture companies.
        NACE 03.2 = Aquaculture
        """
        return self.get_all_companies_by_nace([NACE_CODES["aquaculture"]], max_results)

    def get_seafood_companies(self, max_results: int = 10000) -> Generator[dict, None, None]:
        """
        Convenience method: Get all seafood-related companies.
        Includes aquaculture, fish processing, fishing, and wholesale.
        """
        codes = [
            NACE_CODES["aquaculture"],
            NACE_CODES["fish_processing"],
            NACE_CODES["fishing"],
            NACE_CODES["wholesale_fish"],
        ]
        return self.get_all_companies_by_nace(codes, max_results)

    @staticmethod
    def extract_contact_info(company: dict) -> dict:
        """
        Extract useful contact information from a company record.

        Args:
            company: Company dict from BRREG API

        Returns:
            Dict with extracted fields:
                - org_number
                - name
                - website
                - email (if available)
                - phone (if available)
                - address
                - postal_code
                - city
                - employee_count
                - nace_code
                - nace_description
        """
        address = company.get("forretningsadresse", {}) or company.get("postadresse", {})
        nace1 = company.get("naeringskode1", {})

        return {
            "org_number": company.get("organisasjonsnummer", ""),
            "name": company.get("navn", ""),
            "website": company.get("hjemmeside", ""),
            "address": ", ".join(filter(None, [
                address.get("adresse", [None])[0] if address.get("adresse") else None,
                address.get("poststed", ""),
            ])),
            "postal_code": address.get("postnummer", ""),
            "city": address.get("poststed", ""),
            "employee_count": company.get("antallAnsatte", 0),
            "nace_code": nace1.get("kode", ""),
            "nace_description": nace1.get("beskrivelse", ""),
            "legal_form": company.get("organisasjonsform", {}).get("kode", ""),
        }

    @staticmethod
    def extract_decision_makers(roles: list[dict]) -> list[dict]:
        """
        Extract decision makers (CEO, board members) from roles list.

        Args:
            roles: List of role dicts from get_company_roles()

        Returns:
            List of decision maker dicts with:
                - name
                - role_code
                - role_description
                - birth_date (partial)
        """
        # Target role codes:
        # DAGL = Daglig leder (CEO)
        # LEDE = Styrets leder (Board chairman)
        # NEST = Nestleder (Vice chairman)
        # MEDL = Styremedlem (Board member)
        # VARA = Varamedlem (Deputy board member)
        target_roles = {"DAGL", "LEDE", "NEST", "MEDL", "VARA"}

        decision_makers = []
        for role in roles:
            role_code = role.get("rolle", {}).get("kode", "")
            if role_code not in target_roles:
                continue

            person = role.get("person", {})
            if not person or not person.get("navn"):
                continue

            name_parts = person.get("navn", {})
            full_name = " ".join(filter(None, [
                name_parts.get("fornavn", ""),
                name_parts.get("mellomnavn", ""),
                name_parts.get("etternavn", ""),
            ]))

            if full_name:
                decision_makers.append({
                    "name": full_name,
                    "role_code": role_code,
                    "role_description": role.get("rolle", {}).get("beskrivelse", ""),
                    "birth_date": person.get("fodselsdato", ""),
                })

        return decision_makers
