"""
Snov.io API client.
Handles authentication (OAuth2), token refresh, and all API calls
used in the lead generation pipeline.
"""

import logging
import time
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://api.snov.io"
TOKEN_URL = f"{BASE_URL}/v1/oauth/access_token"
RATE_LIMIT_DELAY = 1.1  # seconds between calls to stay under 60 req/min


class SnovClient:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ):
        self.client_id = client_id or os.getenv("SNOV_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SNOV_CLIENT_SECRET", "")
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

        if not self.client_id:
            raise ValueError("SNOV_CLIENT_ID is not set")
        if not self.client_secret:
            raise ValueError("SNOV_CLIENT_SECRET is not set")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 3600)
        logger.debug("Snov.io token refreshed")
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _get(self, path: str, params: dict = None) -> dict:
        time.sleep(RATE_LIMIT_DELAY)
        resp = requests.get(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict = None) -> dict:
        time.sleep(RATE_LIMIT_DELAY)
        resp = requests.post(
            f"{BASE_URL}{path}",
            headers=self._headers(),
            json=data or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Async start/poll helpers
    # ------------------------------------------------------------------

    def _poll(self, result_path: str, task_hash: str, max_wait: int = 30) -> Optional[dict]:
        """Poll an async endpoint until result is ready or timeout."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            try:
                result = self._get(result_path, {"task_hash": task_hash})
                if result.get("status") == "complete" or result.get("data") is not None:
                    return result
                logger.debug("Task %s not ready yet, waiting...", task_hash)
                time.sleep(3)
            except Exception as exc:
                logger.warning("Poll error for %s: %s", task_hash, exc)
                break
        logger.warning("Polling timed out for task_hash=%s", task_hash)
        return None

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_balance(self) -> dict:
        """Return current credit balance and subscription info."""
        return self._get("/v1/get-balance")

    # ------------------------------------------------------------------
    # Domain / Company lookup
    # ------------------------------------------------------------------

    def find_domain_by_company_name(self, company_name: str) -> Optional[str]:
        """
        Given a company name, return its domain (e.g. 'Acme AS' → 'acme.no').
        Uses async start/poll pattern.
        """
        try:
            start = self._post(
                "/v2/company-domain-by-name/start",
                {"names": [company_name]},
            )
            task_hash = start.get("task_hash") or (start.get("data") or {}).get("task_hash")
            if not task_hash:
                logger.warning("No task_hash for company '%s'", company_name)
                return None

            result = self._poll("/v2/company-domain-by-name/result", task_hash)
            if not result:
                return None

            items = result.get("data") or []
            if isinstance(items, list) and items:
                domain = items[0].get("domain")
                logger.info("Domain for '%s': %s", company_name, domain)
                return domain
        except Exception as exc:
            logger.error("find_domain_by_company_name error: %s", exc)
        return None

    def get_domain_email_count(self, domain: str) -> int:
        """Free check — how many emails Snov.io has for this domain."""
        try:
            result = self._post("/v1/get-domain-emails-count", {"domain": domain})
            count = result.get("data", {}).get("total") or 0
            logger.debug("Email count for %s: %d", domain, count)
            return count
        except Exception as exc:
            logger.warning("get_domain_email_count error: %s", exc)
            return 0

    def search_domain(self, domain: str) -> Optional[dict]:
        """
        Get company info (name, industry, size, phone) for a domain.
        """
        try:
            start = self._post("/v2/domain-search/start", {"domain": domain})
            task_hash = (start.get("data") or {}).get("task_hash") or start.get("task_hash")
            if not task_hash:
                return None
            return self._poll(f"/v2/domain-search/result/{task_hash}", task_hash)
        except Exception as exc:
            logger.error("search_domain error for %s: %s", domain, exc)
        return None

    def get_prospects_by_domain(
        self,
        domain: str,
        positions: Optional[list[str]] = None,
        page: int = 1,
    ) -> list[dict]:
        """
        Return prospect profiles (name, title) for a domain.
        Optionally filter by job positions (max 10).
        """
        try:
            payload: dict = {"domain": domain, "page": page}
            if positions:
                payload["positions[]"] = positions[:10]

            start = self._post("/v2/domain-search/prospects/start", payload)
            task_hash = (start.get("data") or {}).get("task_hash") or start.get("task_hash")
            if not task_hash:
                return []

            result = self._poll(
                f"/v2/domain-search/prospects/result/{task_hash}", task_hash
            )
            if not result:
                return []

            prospects = result.get("data") or []
            logger.info("Found %d prospects for domain %s", len(prospects), domain)
            return prospects
        except Exception as exc:
            logger.error("get_prospects_by_domain error: %s", exc)
        return []

    def find_email_by_name_domain(
        self, first_name: str, last_name: str, domain: str
    ) -> Optional[dict]:
        """
        Find a verified email given first name, last name and domain.
        Returns dict with email + smtp_status, or None.
        """
        try:
            start = self._post(
                "/v2/emails-by-domain-by-name/start",
                {
                    "names[]": [
                        {
                            "first_name": first_name,
                            "last_name": last_name,
                            "domain": domain,
                        }
                    ]
                },
            )
            task_hash = (start.get("data") or {}).get("task_hash") or start.get("task_hash")
            if not task_hash:
                return None

            result = self._poll("/v2/emails-by-domain-by-name/result", task_hash)
            if not result:
                return None

            items = result.get("data") or []
            if isinstance(items, list) and items:
                item = items[0]
                email = item.get("email")
                status = item.get("smtp_status")
                if email:
                    logger.info(
                        "Email found: %s (status: %s)", email, status
                    )
                    return {"email": email, "smtp_status": status}
        except Exception as exc:
            logger.error("find_email_by_name_domain error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------

    def verify_email(self, email: str) -> Optional[str]:
        """
        Verify an email address. Returns 'valid', 'not_valid', or 'unknown'.
        Uses Snov.io v2 async endpoint.
        Response shape: {"data": [{"email": "...", "result": {"smtp_status": "..."}}]}
        """
        try:
            start = self._post(
                "/v2/email-verification/start", {"emails": [email]}
            )
            task_hash = (start.get("data") or {}).get("task_hash") or start.get("task_hash")
            if not task_hash:
                return None

            # Verification can take 5-15s — poll with longer wait
            result = self._poll("/v2/email-verification/result", task_hash, max_wait=60)
            if not result:
                return None

            items = result.get("data") or []
            if isinstance(items, list) and items:
                item = items[0]
                # v2 nests the status under "result" sub-object
                smtp_status = (
                    (item.get("result") or {}).get("smtp_status")
                    or item.get("smtp_status")
                )
                logger.info("Email %s verification: %s", email, smtp_status)
                return smtp_status
        except Exception as exc:
            logger.error("verify_email error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Profile enrichment
    # ------------------------------------------------------------------

    def get_profile_by_email(self, email: str) -> Optional[dict]:
        """Enrich a prospect profile from their email address."""
        try:
            result = self._post(
                "/v1/get-profile-by-email", {"email": email}
            )
            return result.get("data") or result
        except Exception as exc:
            logger.error("get_profile_by_email error: %s", exc)
        return None

    def get_linkedin_profile(self, linkedin_url: str) -> Optional[dict]:
        """Enrich a profile from a LinkedIn URL."""
        try:
            start = self._post(
                "/v2/li-profiles-by-urls/start", {"urls[]": [linkedin_url]}
            )
            task_hash = (start.get("data") or {}).get("task_hash") or start.get("task_hash")
            if not task_hash:
                return None
            result = self._poll("/v2/li-profiles-by-urls/result", task_hash)
            items = (result or {}).get("data") or []
            return items[0] if items else None
        except Exception as exc:
            logger.error("get_linkedin_profile error: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Prospect & Campaign management
    # ------------------------------------------------------------------

    def get_user_lists(self) -> list[dict]:
        """Return all prospect lists in the account."""
        try:
            result = self._get("/v1/get-user-lists")
            # API may return a list directly or wrapped in {"data": [...]}
            if isinstance(result, list):
                return result
            return result.get("data") or []
        except Exception as exc:
            logger.error("get_user_lists error: %s", exc)
        return []

    def create_list(self, name: str) -> Optional[str]:
        """Create a new prospect list and return its ID."""
        try:
            result = self._post("/v1/lists", {"name": name})
            list_id = (result.get("data") or {}).get("id") or result.get("id")
            logger.info("Created Snov list '%s' id=%s", name, list_id)
            return str(list_id) if list_id else None
        except Exception as exc:
            logger.error("create_list error: %s", exc)
        return None

    def add_prospect_to_list(self, list_id: str, prospect: dict) -> bool:
        """
        Add a prospect to a Snov.io list (and auto-enroll in any active campaign).
        prospect dict keys: email, firstName, lastName, position, companyName, companySite
        """
        try:
            # companySite must be a full URL (e.g. https://company.no)
            raw_site = prospect.get("company_domain", "")
            if raw_site and not raw_site.startswith("http"):
                company_site = f"https://{raw_site}"
            else:
                company_site = raw_site

            payload = {
                "listId": list_id,
                "email": prospect.get("email", ""),
                "firstName": prospect.get("first_name", ""),
                "lastName": prospect.get("last_name", ""),
                "fullName": prospect.get("full_name", ""),
                "position": prospect.get("position", ""),
                "companyName": prospect.get("company_name", ""),
                "companySite": company_site,
                "updateContact": False,
                "createDuplicates": False,
            }
            result = self._post("/v1/add-prospect-to-list", payload)
            added = result.get("added") or (result.get("data") or {}).get("added")
            logger.info(
                "Prospect %s added to list %s: %s",
                prospect.get("email"),
                list_id,
                added,
            )
            return bool(added)
        except Exception as exc:
            logger.error("add_prospect_to_list error: %s", exc)
        return False

    def get_campaign_analytics(self, campaign_id: str) -> Optional[dict]:
        """Return full analytics for a campaign."""
        try:
            return self._get(
                "/v2/statistics/campaign-analytics",
                {"campaign_id": campaign_id},
            )
        except Exception as exc:
            logger.error("get_campaign_analytics error: %s", exc)
        return None

    def get_user_campaigns(self) -> list[dict]:
        """Return all campaigns."""
        try:
            result = self._get("/v1/get-user-campaigns")
            return result.get("data") or []
        except Exception as exc:
            logger.error("get_user_campaigns error: %s", exc)
        return []
