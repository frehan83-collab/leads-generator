"""
Main lead generation pipeline.
Orchestrates: scrape -> enrich -> verify -> store -> draft email -> add to Snov campaign.
Auto-exports CSV and tracks pipeline runs in the database.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv

from src.scraper.finn_scraper import scrape_all_keywords as scrape_finn, scrape_company_domain
from src.scraper.nav_scraper import scrape_all_keywords as scrape_nav
from src.scraper.website_scraper import scrape_emails_from_website
from src.snov.client import SnovClient
from src.brreg.client import BRREGClient
from src.database import db
from src.emails.drafter import auto_draft_for_new_prospect
from src.export.csv_exporter import auto_export_after_run

load_dotenv()
logger = logging.getLogger(__name__)

# Job titles to target at scraped companies (HR, recruitment, management)
TARGET_POSITIONS = [
    "CEO",
    "Managing Director",
    "HR Manager",
    "Human Resources",
    "Recruitment",
    "Talent Acquisition",
    "Daglig leder",
    "HR-sjef",
    "Personalsjef",
]


class LeadPipeline:
    def __init__(self, snov_list_id: Optional[str] = None, sources: list[str] = None):
        """
        Initialize lead generation pipeline.

        Args:
            snov_list_id: Snov.io campaign list ID
            sources: List of sources to scrape (default: ['finn', 'nav'])
                     Available: 'finn', 'nav'
        """
        self.snov = SnovClient()
        self.brreg = BRREGClient()
        self.snov_list_id = snov_list_id or os.getenv("SNOV_LIST_ID")
        self.sources = sources or ['finn', 'nav']  # Multi-source by default
        self._stats = {
            "postings_scraped": 0,
            "postings_new": 0,
            "postings_by_source": {},  # Track per-source stats
            "domains_resolved": 0,
            "brreg_matches": 0,  # Companies matched to BRREG
            "prospects_found": 0,
            "emails_found": 0,
            "emails_verified": 0,
            "prospects_added_to_snov": 0,
            "drafts_created": 0,
            "errors": 0,
        }
        self._run_id: Optional[int] = None

    def run(self, keywords: list[str]) -> dict:
        """
        Full pipeline run for a list of keywords.
        Returns stats dict.
        """
        logger.info("=== Lead pipeline starting -- %s ===", datetime.now(timezone.utc).isoformat())
        db.init_db()

        # Track this pipeline run
        self._run_id = db.insert_pipeline_run()

        try:
            # Ensure we have a Snov list to add prospects to
            if not self.snov_list_id:
                self.snov_list_id = self._ensure_snov_list()

            # Step 1: Collect ALL postings from all sources (Playwright contexts close cleanly)
            postings = self._scrape_all_sources(keywords)
            self._stats["postings_scraped"] = len(postings)
            logger.info("Scraped %d total postings from %d sources", len(postings), len(self.sources))
            for source, count in self._stats["postings_by_source"].items():
                logger.info("  - %s: %d postings", source, count)

            # Step 2: Process each posting (domain resolution, enrichment, outreach)
            for posting in postings:
                self._process_posting(posting)

            # Step 3: Auto-export CSV
            csv_path = auto_export_after_run()
            if csv_path:
                logger.info("Auto-exported CSV to %s", csv_path)

            # Mark run as completed
            self._finish_run("completed", csv_path=csv_path)

        except Exception as exc:
            logger.error("Pipeline failed: %s", exc, exc_info=True)
            self._stats["errors"] += 1
            self._finish_run("failed", error_message=str(exc))
            raise

        self._log_stats()
        return self._stats

    # ------------------------------------------------------------------
    # Run tracking
    # ------------------------------------------------------------------

    def _finish_run(
        self,
        status: str,
        csv_path: str = None,
        error_message: str = None,
    ) -> None:
        """Update the pipeline_runs record with final stats."""
        if not self._run_id:
            return
        data = {
            "finished_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "status": status,
            "postings_scraped": self._stats["postings_scraped"],
            "postings_new": self._stats["postings_new"],
            "domains_resolved": self._stats["domains_resolved"],
            "prospects_found": self._stats["prospects_found"],
            "emails_found": self._stats["emails_found"],
            "emails_verified": self._stats["emails_verified"],
            "prospects_added": self._stats["prospects_added_to_snov"],
            "drafts_created": self._stats["drafts_created"],
            "errors": self._stats["errors"],
        }
        if csv_path:
            data["csv_path"] = csv_path
        if error_message:
            data["error_message"] = error_message
        try:
            db.update_pipeline_run(self._run_id, data)
        except Exception as exc:
            logger.warning("Failed to update pipeline run: %s", exc)

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _ensure_snov_list(self) -> Optional[str]:
        """Get or create a Snov.io prospect list for this tool."""
        list_name = "Multi-Source Leads"  # Updated name for multi-source
        lists = self.snov.get_user_lists()
        for lst in lists:
            if lst.get("name") == list_name:
                logger.info("Using existing Snov list '%s' id=%s", list_name, lst["id"])
                return str(lst["id"])
        list_id = self.snov.create_list(list_name)
        return list_id

    def _scrape_all_sources(self, keywords: list[str]) -> list[dict]:
        """
        Scrape job postings from all configured sources.
        Returns combined list of postings with source tracking.
        """
        all_postings = []
        seen_ids = set()  # Cross-source deduplication by URL

        for source in self.sources:
            logger.info("Scraping source: %s", source)
            source_count = 0

            try:
                if source == 'finn':
                    for posting in scrape_finn(keywords):
                        # Check for duplicates by URL
                        if posting["url"] not in seen_ids:
                            seen_ids.add(posting["url"])
                            all_postings.append(posting)
                            source_count += 1

                elif source == 'nav':
                    for posting in scrape_nav(keywords):
                        if posting["url"] not in seen_ids:
                            seen_ids.add(posting["url"])
                            all_postings.append(posting)
                            source_count += 1

                else:
                    logger.warning("Unknown source: %s", source)

                self._stats["postings_by_source"][source] = source_count
                logger.info("Source %s: %d postings", source, source_count)

            except Exception as exc:
                logger.error("Error scraping source %s: %s", source, exc)
                self._stats["errors"] += 1
                self._stats["postings_by_source"][source] = 0

        return all_postings

    def _enrich_with_brreg(self, company_name: str, posting_id: int) -> Optional[str]:
        """
        Try to match company to BRREG database and get org_number.
        First checks local companies table, then tries BRREG API.

        Args:
            company_name: Company name from job posting
            posting_id: Job posting ID for logging

        Returns:
            Organization number if found, else None
        """
        # Check if we already have this company in our database
        # (from previous BRREG import)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT org_number FROM companies WHERE LOWER(name) = LOWER(?) LIMIT 1",
                (company_name,),
            ).fetchone()
            if row:
                org_number = row[0]
                logger.debug("Matched '%s' to BRREG org=%s (from local DB)", company_name, org_number)
                self._stats["brreg_matches"] += 1
                return org_number

        # Try BRREG API name search as fallback
        try:
            cleaned = self._clean_company_name(company_name)
            import requests as _req
            resp = _req.get(
                "https://data.brreg.no/enhetsregisteret/api/enheter",
                params={"navn": cleaned, "size": 1},
                headers={"Accept": "application/json"},
                timeout=15,
            )
            if resp.ok:
                companies = resp.json().get("_embedded", {}).get("enheter", [])
                if companies:
                    org_number = companies[0].get("organisasjonsnummer")
                    if org_number:
                        logger.debug("BRREG API matched '%s' to org=%s", company_name, org_number)
                        self._stats["brreg_matches"] += 1
                        return org_number
        except Exception as exc:
            logger.debug("BRREG API enrichment failed for '%s': %s", company_name, exc)

        return None

    def _process_posting(self, posting: dict) -> None:
        """Process a single job posting through the full pipeline."""
        company_name = posting.get("company_name", "").strip()
        source = posting.get("source", "unknown")
        external_id = posting.get("external_id", posting.get("finn_id", ""))

        if not company_name:
            logger.debug("Skipping posting %s from %s -- no company name", external_id, source)
            return

        # 1. Store job posting (skip if already in DB)
        posting_id = db.insert_job_posting(posting)
        if posting_id is None:
            logger.debug("Posting %s (%s) already in DB, skipping", external_id, source)
            return
        self._stats["postings_new"] += 1

        logger.info("Processing [%s]: %s -- %s", source, company_name, posting.get("title"))

        # 2. BRREG Enrichment: Try to match company and get org_number
        org_number = posting.get("org_number")
        if not org_number and company_name:
            org_number = self._enrich_with_brreg(company_name, posting_id)
            if org_number:
                posting["org_number"] = org_number

        # 3. Resolve company domain
        domain = self._resolve_domain(company_name, posting)
        if not domain:
            logger.warning("Could not resolve domain for '%s'", company_name)
            self._stats["errors"] += 1
            return

        # Update posting with domain and org_number
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE job_postings SET company_domain = ?, org_number = ? WHERE id = ?",
                (domain, org_number, posting_id),
            )
        self._stats["domains_resolved"] += 1

        # 3. Primary: scrape emails directly from the company website
        # Returns list of {"email": str, "title": str, "name": str}
        website_contacts = scrape_emails_from_website(domain)
        if website_contacts:
            self._stats["prospects_found"] += len(website_contacts)
            for contact in website_contacts:
                self._process_raw_email(
                    contact["email"],
                    domain,
                    posting_id,
                    posting,
                    title=contact.get("title", ""),
                    scraped_name=contact.get("name", ""),
                )
            return  # done for this posting

        # 4. Fallback: try Snov.io domain search (works for global companies)
        email_count = self.snov.get_domain_email_count(domain)
        if email_count == 0:
            logger.info("No emails found via website scrape or Snov.io for %s", domain)
            return

        prospects = self.snov.get_prospects_by_domain(
            domain, positions=TARGET_POSITIONS
        )
        self._stats["prospects_found"] += len(prospects)

        for prospect_data in prospects:
            self._process_prospect(prospect_data, domain, posting_id, posting)

    @staticmethod
    def _clean_company_name(raw: str) -> str:
        """
        Strip department prefixes and suffixes from Norwegian company names
        so Snov.io can match them.
        """
        import re as _re
        name = raw.strip()

        # If comma-separated, take the LAST segment (usually the actual company)
        if "," in name:
            name = name.split(",")[-1].strip()

        # Remove legal suffixes
        for suffix in [" HF", " AS", " ASA", " KF", " SF", " IKS", ", Norway"]:
            if name.upper().endswith(suffix.upper()):
                name = name[: -len(suffix)].strip()

        # Collapse extra whitespace
        name = _re.sub(r"\s+", " ", name).strip()
        return name

    def _resolve_domain(self, company_name: str, posting: dict) -> Optional[str]:
        """Try multiple strategies to resolve the company domain."""
        # Strategy 1: Already in posting data
        if posting.get("company_domain"):
            return posting["company_domain"]

        # Strategy 2: Scrape the company's homepage link from the finn.no posting page
        posting_url = posting.get("url")
        if posting_url:
            domain = scrape_company_domain(posting_url)
            if domain:
                return domain

        # Strategy 3: Snov.io with cleaned company name (fallback)
        cleaned = self._clean_company_name(company_name)
        domain = self.snov.find_domain_by_company_name(cleaned)
        if domain:
            return domain

        return None

    def _process_raw_email(
        self,
        email: str,
        domain: str,
        posting_id: int,
        posting: dict,
        title: str = "",
        scraped_name: str = "",
    ) -> None:
        """
        Handle an email found directly from the company website.
        title and scraped_name come from the website scraper's context parsing.
        """
        if db.email_exists(email):
            logger.debug("Email %s already in DB, skipping", email)
            return

        self._stats["emails_found"] += 1

        # Try to verify via Snov.io (uses credits but prevents bounces)
        smtp_status = "unknown"
        try:
            verified = self.snov.verify_email(email)
            smtp_status = verified or "unknown"
        except Exception:
            smtp_status = "unknown"

        if smtp_status == "not_valid":
            logger.info("Email %s failed verification, skipping", email)
            return

        self._stats["emails_verified"] += 1

        # Derive first/last name: prefer scraped_name, else parse from email
        first_name, last_name = "", ""
        if scraped_name and " " in scraped_name:
            parts = scraped_name.split(" ", 1)
            first_name, last_name = parts[0], parts[1]
        else:
            local = email.split("@")[0]
            if "." in local:
                parts = local.split(".")
                if len(parts) == 2 and all(p.isalpha() for p in parts):
                    first_name = parts[0].capitalize()
                    last_name = parts[1].capitalize()

        prospect_record = {
            "job_posting_id": posting_id,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": (
                scraped_name
                or f"{first_name} {last_name}".strip()
                or email.split("@")[0]
            ),
            "email": email,
            "email_status": smtp_status,
            "position": title,          # job title scraped from website
            "company_name": posting.get("company_name", ""),
            "company_domain": domain,
            "linkedin_url": None,
            "snov_prospect_id": None,
            "snov_list_id": self.snov_list_id,
        }
        prospect_id = db.insert_prospect(prospect_record)
        if not prospect_id:
            return

        # Auto-draft email campaign for this prospect
        try:
            draft_id = auto_draft_for_new_prospect(prospect_id, posting_id)
            if draft_id:
                self._stats["drafts_created"] += 1
        except Exception as exc:
            logger.warning("Failed to auto-draft for %s: %s", email, exc)

        # Add to Snov.io campaign list
        if self.snov_list_id:
            added = self.snov.add_prospect_to_list(self.snov_list_id, prospect_record)
            if added:
                self._stats["prospects_added_to_snov"] += 1
                db.log_outreach({
                    "prospect_id": prospect_id,
                    "campaign_id": self.snov_list_id,
                    "status": "added_to_snov",
                    "notes": f"Website scraped from {domain}, {posting.get('source', 'finn')} posting {posting.get('external_id', posting.get('finn_id', ''))}",
                })
                logger.info("Added %s to Snov list %s", email, self.snov_list_id)

    def _process_prospect(
        self,
        prospect_data: dict,
        domain: str,
        posting_id: int,
        posting: dict,
    ) -> None:
        """Enrich, verify, store and enroll a single prospect."""
        first_name = prospect_data.get("first_name") or prospect_data.get("firstName", "")
        last_name = prospect_data.get("last_name") or prospect_data.get("lastName", "")
        position = prospect_data.get("position", "")

        if not first_name or not last_name:
            return

        # 5. Find email
        email_result = self.snov.find_email_by_name_domain(first_name, last_name, domain)
        if not email_result or not email_result.get("email"):
            logger.debug("No email found for %s %s @ %s", first_name, last_name, domain)
            return

        email = email_result["email"]
        smtp_status = email_result.get("smtp_status", "unknown")
        self._stats["emails_found"] += 1

        # 6. Skip if already contacted
        if db.email_exists(email):
            logger.debug("Email %s already in DB, skipping", email)
            return

        # 7. Verify email quality -- skip if definitely invalid
        if smtp_status == "not_valid":
            logger.info("Email %s is invalid, skipping", email)
            return

        if smtp_status == "unknown":
            verified = self.snov.verify_email(email)
            smtp_status = verified or "unknown"
            if smtp_status == "not_valid":
                logger.info("Email %s failed verification, skipping", email)
                return

        self._stats["emails_verified"] += 1

        # 8. Store prospect in DB
        prospect_record = {
            "job_posting_id": posting_id,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "email": email,
            "email_status": smtp_status,
            "position": position,
            "company_name": posting.get("company_name", ""),
            "company_domain": domain,
            "linkedin_url": prospect_data.get("linkedinUrl") or prospect_data.get("linkedin_url"),
            "snov_prospect_id": None,
            "snov_list_id": self.snov_list_id,
        }
        prospect_id = db.insert_prospect(prospect_record)
        if not prospect_id:
            return

        # Auto-draft email campaign for this prospect
        try:
            draft_id = auto_draft_for_new_prospect(prospect_id, posting_id)
            if draft_id:
                self._stats["drafts_created"] += 1
        except Exception as exc:
            logger.warning("Failed to auto-draft for %s: %s", email, exc)

        # 9. Add to Snov.io campaign list
        if self.snov_list_id:
            added = self.snov.add_prospect_to_list(self.snov_list_id, prospect_record)
            if added:
                self._stats["prospects_added_to_snov"] += 1
                db.log_outreach({
                    "prospect_id": prospect_id,
                    "campaign_id": self.snov_list_id,
                    "status": "added_to_snov",
                    "notes": f"Auto-added from {posting.get('source', 'finn')} posting {posting.get('external_id', posting.get('finn_id', ''))}",
                })

    def _log_stats(self) -> None:
        logger.info("=== Pipeline complete ===")
        for key, val in self._stats.items():
            logger.info("  %-35s %s", key + ":", val)
