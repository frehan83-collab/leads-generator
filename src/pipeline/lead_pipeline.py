"""
Main lead generation pipeline.
Orchestrates: scrape -> enrich -> verify -> store -> draft email -> add to Snov campaign.
Auto-exports CSV and tracks pipeline runs in the database.
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

from dotenv import load_dotenv

from src.brreg.client import BRREGClient
from src.database import db
from src.emails.drafter import auto_draft_for_new_prospect
from src.export.csv_exporter import auto_export_after_run
from src.notifications.webhook import send_pipeline_alert
from src.scraper.browser_manager import BrowserManager
from src.scraper.finn_scraper import scrape_all_keywords as scrape_finn
from src.scraper.finn_scraper import scrape_company_domain
from src.scraper.nav_scraper import scrape_all_keywords as scrape_nav
from src.scraper.website_scraper import scrape_emails_from_website
from src.snov.client import SnovClient
from src.snov.errors import SnovAuthError, SnovOutOfCredits

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


class _DomainTimeout(Exception):
    """Raised when a single domain exceeds its processing time budget."""


class LeadPipeline:
    def __init__(self, snov_list_id: str | None = None, sources: list[str] = None):
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
        self.sources = sources or ["finn", "nav"]  # Multi-source by default
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
            "postings_revalidated": 0,
            "postings_expired": 0,
            "errors": 0,
        }
        self._stats_lock = threading.Lock()
        self._run_id: int | None = None

    def run(self, keywords: list[str]) -> dict:
        """
        Full pipeline run for a list of keywords.
        Returns stats dict.
        """
        from src.config import settings as _settings
        from src.snov.errors import SnovAuthError, SnovOutOfCredits

        logger.info(
            "=== Lead pipeline starting -- %s ===", datetime.now(UTC).isoformat()
        )
        db.init_db()

        # Track this pipeline run
        self._run_id = db.insert_pipeline_run()

        # Hygiene: previous runs stuck in 'running' died with their process.
        stale = db.mark_stale_runs(except_id=self._run_id)
        if stale:
            logger.info("Marked %d stale pipeline run(s) from dead processes", stale)

        try:
            # Ensure we have a Snov list to add prospects to
            if not self.snov_list_id:
                self.snov_list_id = self._ensure_snov_list()

            # Credit guard: never burn hours on an empty Snov balance.
            self._check_snov_balance(_settings.snov_min_credits)

            # Step 1: Collect ALL postings from all sources (shared browser)
            with BrowserManager() as bm:
                postings = self._scrape_all_sources(keywords, browser=bm.browser)
                self._stats["postings_scraped"] = len(postings)
                logger.info(
                    "Scraped %d total postings from %d sources",
                    len(postings),
                    len(self.sources),
                )
                for source, count in self._stats["postings_by_source"].items():
                    logger.info("  - %s: %d postings", source, count)

            # Step 2: Process postings (sequential or bounded parallel)
            workers = _settings.pipeline_workers
            if workers <= 1:
                with BrowserManager() as bm:
                    for i, posting in enumerate(postings, 1):
                        self._process_posting_guarded(posting, bm.browser)
                        if i % 25 == 0:
                            self._heartbeat()
            else:
                logger.info(
                    "Processing %d postings with %d workers", len(postings), workers
                )
                self._process_postings_parallel(postings, workers)

            # Step 3: Calculate intent scores for companies with new postings
            self._calculate_intent_scores()

            # Step 3b: Lead scores v2 (fit + demand + engagement)
            try:
                from src.scoring.lead_scorer import score_all_domains

                previously_hot = {
                    r["domain"] for r in db.get_lead_scores(10000, min_score=70)
                }
                score_stats = score_all_domains()
                logger.info(
                    "Lead scoring v2: %d domains (%d hot, %d warm)",
                    score_stats["scored"],
                    score_stats["hot"],
                    score_stats["warm"],
                )
                newly_hot = [
                    r["domain"]
                    for r in db.get_lead_scores(10000, min_score=70)
                    if r["domain"] not in previously_hot
                ]
                if newly_hot:
                    logger.warning("New hot domains: %s", ", ".join(newly_hot[:10]))
                    try:
                        send_pipeline_alert(
                            {"hot_domains": len(newly_hot)},
                            status="hot_leads",
                            error_message=f"New hot leads: {', '.join(newly_hot[:10])}",
                        )
                    except Exception as exc:
                        logger.debug("Hot-lead alert failed: %s", exc)
            except Exception as exc:
                logger.warning("Lead scoring v2 failed: %s", exc)

            # Step 3c: Revalidate stale postings so campaigns track live ads
            try:
                re_stats = self._revalidate_postings()
                logger.info(
                    "Revalidated %d postings (%d expired)",
                    re_stats["revalidated"],
                    re_stats["expired"],
                )
            except Exception as exc:
                logger.warning("Posting revalidation failed: %s", exc)

            # Step 4: Auto-export CSV
            csv_path = auto_export_after_run()
            if csv_path:
                logger.info("Auto-exported CSV to %s", csv_path)

            # Mark run as completed
            self._finish_run("completed", csv_path=csv_path)

        except (SnovAuthError, SnovOutOfCredits) as exc:
            logger.error("Pipeline aborted: %s", exc)
            self._stats["errors"] += 1
            self._finish_run("failed", error_message=f"{type(exc).__name__}: {exc}")
            raise
        except Exception as exc:
            logger.error("Pipeline failed: %s", exc, exc_info=True)
            self._stats["errors"] += 1
            self._finish_run("failed", error_message=str(exc))
            raise
        finally:
            try:
                self.brreg.close()
            except Exception:
                pass

        self._log_stats()
        return self._stats

    def _process_posting_guarded(self, posting: dict, browser=None) -> None:
        """Process one posting; isolated errors count and continue."""
        from src.snov.errors import SnovAuthError, SnovOutOfCredits

        try:
            self._process_posting(posting, browser=browser)
        except (SnovAuthError, SnovOutOfCredits):
            raise  # fatal: abort the whole run, don't swallow per posting
        except _DomainTimeout as exc:
            logger.warning(
                "Skipped posting %s: domain %s timed out",
                posting.get("external_id", "?"),
                exc,
            )
            with self._stats_lock:
                self._stats["errors"] += 1
        except Exception as exc:
            logger.error(
                "Error processing posting %s: %s",
                posting.get("external_id", "?"),
                exc,
            )
            with self._stats_lock:
                self._stats["errors"] += 1

    def _process_postings_parallel(self, postings: list[dict], workers: int) -> None:
        """Bounded parallel processing; each worker owns its browser.

        Playwright sync objects are not thread-safe, so workers never share
        a browser — each thread creates and destroys its own BrowserManager.
        SQLite handles concurrent writers via WAL + busy_timeout; stats stay
        behind the existing _stats_lock.
        """
        import threading as _threading

        _local = _threading.local()
        _managers: list = []
        _managers_lock = _threading.Lock()

        def _worker_browser():
            bm = getattr(_local, "bm", None)
            if bm is None:
                bm = BrowserManager()
                bm.__enter__()
                _local.bm = bm
                with _managers_lock:
                    _managers.append(bm)
            return bm.browser

        def _work(posting: dict) -> None:
            self._process_posting_guarded(posting, browser=_worker_browser())

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_work, p): p for p in postings}
                for i, future in enumerate(as_completed(futures), 1):
                    future.result()  # raises fatal Snov errors to abort the run
                    if i % 25 == 0:
                        self._heartbeat()
        finally:
            for bm in _managers:
                try:
                    bm.__exit__(None, None, None)
                except Exception:
                    pass

    def _heartbeat(self) -> None:
        """Write current stats to the run row so live views stay truthful."""
        if not self._run_id:
            return
        try:
            with self._stats_lock:
                data = {
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
            db.update_pipeline_run(self._run_id, data)
        except Exception as exc:
            logger.debug("Heartbeat write failed: %s", exc)

    def _check_snov_balance(self, min_credits: int) -> None:
        """Abort early when the Snov.io balance can't fund a run."""
        from src.config import settings as _settings
        from src.snov.errors import SnovError, SnovOutOfCredits

        try:
            balance = self._snov_balance_probe()
        except SnovError as exc:
            logger.warning("Could not read Snov.io balance, continuing: %s", exc)
            return
        if balance is None:
            return
        logger.info("Snov.io balance: %s credits", balance)
        if balance <= 0:
            raise SnovOutOfCredits(
                "Snov.io balance is 0 — top up before running the pipeline."
            )
        if min_credits and balance < min_credits:
            raise SnovOutOfCredits(
                f"Snov.io balance ({balance}) below SNOV_MIN_CREDITS ({min_credits})."
            )
        low_water = _settings.snov_low_water_credits
        if low_water and balance < low_water:
            logger.warning(
                "Snov.io balance low: %s credits (warning level %s) — top up soon",
                balance,
                low_water,
            )
            try:
                send_pipeline_alert(
                    {"snov_balance": balance},
                    status="warning",
                    error_message=f"Snov.io balance low: {balance} credits remaining",
                )
            except Exception as exc:
                logger.debug("Low-water webhook failed: %s", exc)

    def _snov_balance_probe(self):
        """Best-effort credit read; returns int, None if unreadable."""
        result = self.snov.get_balance()
        if not isinstance(result, dict):
            return None
        data = result.get("data", result)
        if isinstance(data, dict):
            for key in ("balance", "credits", "credits_left", "remaining"):
                if isinstance(data.get(key), (int, float)):
                    return int(data[key])
        return None

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
            "finished_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "status": status,
            "postings_scraped": self._stats["postings_scraped"],
            "postings_new": self._stats["postings_new"],
            "domains_resolved": self._stats["domains_resolved"],
            "prospects_found": self._stats["prospects_found"],
            "emails_found": self._stats["emails_found"],
            "emails_verified": self._stats["emails_verified"],
            "prospects_added": self._stats["prospects_added_to_snov"],
            "drafts_created": self._stats["drafts_created"],
            "postings_revalidated": self._stats["postings_revalidated"],
            "postings_expired": self._stats["postings_expired"],
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

        # Send webhook alert
        try:
            send_pipeline_alert(self._stats, status, error_message=error_message)
        except Exception as exc:
            logger.debug("Webhook alert error: %s", exc)

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _ensure_snov_list(self) -> str | None:
        """Get or create a Snov.io prospect list for this tool."""
        list_name = "Multi-Source Leads"  # Updated name for multi-source
        lists = self.snov.get_user_lists()
        for lst in lists:
            if lst.get("name") == list_name:
                logger.info("Using existing Snov list '%s' id=%s", list_name, lst["id"])
                return str(lst["id"])
        list_id = self.snov.create_list(list_name)
        return list_id

    def _scrape_all_sources(self, keywords: list[str], browser=None) -> list[dict]:
        """
        Scrape job postings from all configured sources.
        Uses incremental scraping to skip already-known postings.
        Returns combined list of postings with source tracking.

        Args:
            keywords: List of search keywords
            browser: Optional shared Playwright browser instance for reuse
        """
        all_postings = []
        seen_ids = set()  # Cross-source deduplication by URL

        for source in self.sources:
            logger.info("Scraping source: %s", source)
            source_count = 0

            # Incremental: load known IDs for this source
            known_ids = db.get_existing_external_ids(source)
            logger.info("Source %s: %d existing IDs in DB", source, len(known_ids))

            try:
                if source == "finn":
                    for posting in scrape_finn(
                        keywords, known_ids=known_ids, browser=browser
                    ):
                        # Check for duplicates by URL
                        if posting["url"] not in seen_ids:
                            seen_ids.add(posting["url"])
                            all_postings.append(posting)
                            source_count += 1

                elif source == "nav":
                    for posting in scrape_nav(
                        keywords, known_ids=known_ids, browser=browser
                    ):
                        if posting["url"] not in seen_ids:
                            seen_ids.add(posting["url"])
                            all_postings.append(posting)
                            source_count += 1

                elif source == "karrierestart":
                    from src.scraper.karrierestart_scraper import (
                        scrape_all_keywords as scrape_karrierestart,
                    )

                    for posting in scrape_karrierestart(
                        keywords, known_ids=known_ids, browser=browser
                    ):
                        if posting["url"] not in seen_ids:
                            seen_ids.add(posting["url"])
                            all_postings.append(posting)
                            source_count += 1

                elif source == "jobbnorge":
                    from src.scraper.jobbnorge_scraper import (
                        scrape_all_keywords as scrape_jobbnorge,
                    )

                    for posting in scrape_jobbnorge(
                        keywords, known_ids=known_ids, browser=browser
                    ):
                        if posting["url"] not in seen_ids:
                            seen_ids.add(posting["url"])
                            all_postings.append(posting)
                            source_count += 1

                elif source == "careers":
                    # Bounded revisit of known companies' own career pages
                    # (no keywords, no unbounded crawl — DB domains only).
                    from src.config import settings as _career_settings
                    from src.scraper.careers_scraper import scrape_career_pages

                    targets = db.get_domains_for_career_scan(
                        limit=_career_settings.careers_max_domains
                    )
                    logger.info("Career scan: %d known domains", len(targets))
                    for posting in scrape_career_pages(targets, known_ids=known_ids):
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

    def _enrich_with_brreg(self, company_name: str, posting_id: int) -> str | None:
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
                logger.debug(
                    "Matched '%s' to BRREG org=%s (from local DB)",
                    company_name,
                    org_number,
                )
                with self._stats_lock:
                    self._stats["brreg_matches"] += 1
                return org_number

        # Fuzzy match against local companies table
        try:
            from rapidfuzz import fuzz, process

            with db.get_connection() as conn:
                all_companies = conn.execute(
                    "SELECT org_number, name FROM companies"
                ).fetchall()

            if all_companies:
                company_names = {
                    row["name"]: row["org_number"] for row in all_companies
                }
                match = process.extractOne(
                    company_name,
                    company_names.keys(),
                    scorer=fuzz.token_sort_ratio,
                    score_cutoff=85,
                )
                if match:
                    matched_name, score, _ = match
                    org_number = company_names[matched_name]
                    logger.info(
                        "Fuzzy matched '%s' -> '%s' (score=%d, org=%s)",
                        company_name,
                        matched_name,
                        score,
                        org_number,
                    )
                    with self._stats_lock:
                        self._stats["brreg_matches"] += 1
                    return org_number
        except ImportError:
            logger.debug("rapidfuzz not installed, skipping fuzzy match")
        except Exception as exc:
            logger.debug("Fuzzy match error for '%s': %s", company_name, exc)

        # Try BRREG API name search as fallback (client: retries + backoff)
        try:
            cleaned = self._clean_company_name(company_name)
            companies = self.brreg.search_by_name(cleaned, size=5)
            if companies:
                if len(companies) == 1:
                    org_number = companies[0].get("organisasjonsnummer")
                else:
                    # Pick best fuzzy match from API results
                    try:
                        from rapidfuzz import fuzz

                        best_score = 0
                        best_org = None
                        for c in companies[:5]:  # Check top 5
                            score = fuzz.token_sort_ratio(cleaned, c.get("navn", ""))
                            if score > best_score:
                                best_score = score
                                best_org = c.get("organisasjonsnummer")
                        if best_score >= 70:
                            org_number = best_org
                        else:
                            org_number = companies[0].get("organisasjonsnummer")
                    except ImportError:
                        org_number = companies[0].get("organisasjonsnummer")
                if org_number:
                    logger.debug(
                        "BRREG API matched '%s' to org=%s", company_name, org_number
                    )
                    with self._stats_lock:
                        self._stats["brreg_matches"] += 1
                    return org_number
        except Exception as exc:
            logger.debug("BRREG API enrichment failed for '%s': %s", company_name, exc)

        return None

    @staticmethod
    def _check_deadline(deadline: float, domain: str, soft: bool = False) -> bool:
        """Return True (soft) or raise (hard) when the domain budget is spent."""
        if time.monotonic() > deadline:
            logger.warning("Domain time budget exceeded for %s, moving on", domain)
            if soft:
                return True
            raise _DomainTimeout(domain)
        return False

    def _process_posting(self, posting: dict, browser=None) -> None:
        """Process a single job posting through the full pipeline."""
        from src.config import settings as _settings

        deadline = time.monotonic() + _settings.domain_timeout_sec
        company_name = posting.get("company_name", "").strip()
        source = posting.get("source", "unknown")
        external_id = posting.get("external_id", posting.get("finn_id", ""))

        if not company_name:
            logger.debug(
                "Skipping posting %s from %s -- no company name", external_id, source
            )
            return

        # 1. Store job posting (skip if already in DB). The UNIQUE
        # (source, external_id) key makes re-runs idempotent: a posting is
        # never processed twice even if a previous run died mid-posting.
        posting_id = db.insert_job_posting(posting)
        if posting_id is None:
            logger.debug("Posting %s (%s) already in DB, skipping", external_id, source)
            return
        with self._stats_lock:
            self._stats["postings_new"] += 1

        logger.info(
            "Processing [%s]: %s -- %s", source, company_name, posting.get("title")
        )

        # 2. BRREG Enrichment: Try to match company and get org_number
        org_number = posting.get("org_number")
        if not org_number and company_name:
            org_number = self._enrich_with_brreg(company_name, posting_id)
            if org_number:
                posting["org_number"] = org_number

        # 3. Resolve company domain
        domain = self._resolve_domain(company_name, posting, browser=browser)
        if not domain:
            logger.warning("Could not resolve domain for '%s'", company_name)
            with self._stats_lock:
                self._stats["errors"] += 1
            return
        self._check_deadline(deadline, domain)

        # Update posting with domain and org_number
        db.update_job_posting(
            posting_id,
            {
                "company_domain": domain,
                "org_number": org_number,
            },
        )
        with self._stats_lock:
            self._stats["domains_resolved"] += 1

        # 4. Primary: scrape emails directly from the company website
        # Returns list of {"email": str, "title": str, "name": str}
        # Check website cache first
        website_contacts = db.get_cached_contacts(domain)
        if website_contacts is None:
            website_contacts = scrape_emails_from_website(
                domain,
                browser=browser,
                deadline=deadline,
            )
            db.cache_contacts(domain, website_contacts or [])
        stored_any = False
        if website_contacts:
            with self._stats_lock:
                self._stats["prospects_found"] += len(website_contacts)
            for contact in website_contacts:
                if self._check_deadline(deadline, domain, soft=True):
                    break
                stored_id = self._process_raw_email(
                    contact["email"],
                    domain,
                    posting_id,
                    posting,
                    title=contact.get("title", ""),
                    scraped_name=contact.get("name", ""),
                )
                stored_any = stored_any or stored_id is not None

        # 5. Snov.io domain search — runs when the website yielded nothing
        # storable (not merely when the contact list was empty), so Snov
        # credits are spent only where website scraping came up short.
        if stored_any:
            return
        self._check_deadline(deadline, domain)
        email_count = self.snov.get_domain_email_count(domain)
        if email_count == 0:
            logger.info("No emails found via website scrape or Snov.io for %s", domain)
            return

        prospects = self.snov.get_prospects_by_domain(
            domain, positions=TARGET_POSITIONS
        )
        with self._stats_lock:
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

    def _resolve_domain(
        self, company_name: str, posting: dict, browser=None
    ) -> str | None:
        """Try multiple strategies to resolve the company domain."""
        # Strategy 1: Already in posting data
        if posting.get("company_domain"):
            return posting["company_domain"]

        # Strategy 2: Scrape the company's homepage link from the finn.no posting page
        posting_url = posting.get("url")
        if posting_url:
            domain = scrape_company_domain(posting_url, browser=browser)
            if domain:
                return domain

        # Strategy 3: local BRREG table (free — website from org or fuzzy name)
        domain = db.get_company_website(
            posting.get("org_number"), company_name=company_name
        )
        if domain:
            logger.debug("Domain for '%s' from local BRREG: %s", company_name, domain)
            return domain

        # Strategy 4: Snov.io with cleaned company name (fallback, costs credits)
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
    ) -> int | None:
        """
        Handle an email found directly from the company website.
        title and scraped_name come from the website scraper's context parsing.
        Returns the new prospect id, or None if skipped/duplicate.
        """
        if db.email_exists(email):
            logger.debug("Email %s already in DB, skipping", email)
            return

        with self._stats_lock:
            self._stats["emails_found"] += 1

        # Try to verify via Snov.io (uses credits but prevents bounces)
        smtp_status = "unknown"
        try:
            verified = self.snov.verify_email(email)
            smtp_status = verified or "unknown"
        except (SnovAuthError, SnovOutOfCredits):
            raise  # fatal: abort the run, don't degrade per email
        except Exception:
            smtp_status = "unknown"

        if smtp_status == "not_valid":
            logger.info("Email %s failed verification, skipping", email)
            return

        with self._stats_lock:
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
            "position": title,  # job title scraped from website
            "company_name": posting.get("company_name", ""),
            "company_domain": domain,
            "linkedin_url": None,
            "snov_prospect_id": None,
            "snov_list_id": self.snov_list_id,
        }
        prospect_id = db.insert_prospect(prospect_record)
        if not prospect_id:
            return None

        # Auto-draft email campaign for this prospect
        try:
            draft_id = auto_draft_for_new_prospect(prospect_id, posting_id)
            if draft_id:
                with self._stats_lock:
                    self._stats["drafts_created"] += 1
        except Exception as exc:
            logger.warning("Failed to auto-draft for %s: %s", email, exc)

        # Add to Snov.io campaign list
        if self.snov_list_id:
            added = self.snov.add_prospect_to_list(self.snov_list_id, prospect_record)
            if added:
                with self._stats_lock:
                    self._stats["prospects_added_to_snov"] += 1
                db.log_outreach(
                    {
                        "prospect_id": prospect_id,
                        "campaign_id": self.snov_list_id,
                        "status": "added_to_snov",
                        "notes": f"Website scraped from {domain}, {posting.get('source', 'finn')} posting {posting.get('external_id', posting.get('finn_id', ''))}",
                    }
                )
                logger.info("Added %s to Snov list %s", email, self.snov_list_id)

        return prospect_id

    def _process_prospect(
        self,
        prospect_data: dict,
        domain: str,
        posting_id: int,
        posting: dict,
    ) -> None:
        """Enrich, verify, store and enroll a single prospect."""
        first_name = prospect_data.get("first_name") or prospect_data.get(
            "firstName", ""
        )
        last_name = prospect_data.get("last_name") or prospect_data.get("lastName", "")
        position = prospect_data.get("position", "")

        if not first_name or not last_name:
            return

        # 5. Find email
        email_result = self.snov.find_email_by_name_domain(
            first_name, last_name, domain
        )
        if not email_result or not email_result.get("email"):
            logger.debug("No email found for %s %s @ %s", first_name, last_name, domain)
            return

        email = email_result["email"]
        smtp_status = email_result.get("smtp_status", "unknown")
        with self._stats_lock:
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

        with self._stats_lock:
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
            "linkedin_url": prospect_data.get("linkedinUrl")
            or prospect_data.get("linkedin_url"),
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
                with self._stats_lock:
                    self._stats["drafts_created"] += 1
        except Exception as exc:
            logger.warning("Failed to auto-draft for %s: %s", email, exc)

        # 9. Add to Snov.io campaign list
        if self.snov_list_id:
            added = self.snov.add_prospect_to_list(self.snov_list_id, prospect_record)
            if added:
                with self._stats_lock:
                    self._stats["prospects_added_to_snov"] += 1
                db.log_outreach(
                    {
                        "prospect_id": prospect_id,
                        "campaign_id": self.snov_list_id,
                        "status": "added_to_snov",
                        "notes": f"Auto-added from {posting.get('source', 'finn')} posting {posting.get('external_id', posting.get('finn_id', ''))}",
                    }
                )

    def _revalidate_postings(self) -> dict:
        """Re-check liveness of stale postings (bounded by count + time).

        Keeps campaign leads tied to actually-active ads: expired postings
        are flagged so senders skip drafts that reference dead roles.
        """
        from src.config import settings as _settings
        from src.scraper.revalidate import revalidate_one

        queue = db.get_postings_for_revalidation(
            limit=_settings.revalidate_limit,
            older_than_days=_settings.revalidate_max_age_days,
        )
        deadline = time.monotonic() + _settings.revalidate_budget_sec
        stats = {"revalidated": 0, "expired": 0}
        for item in queue:
            if time.monotonic() > deadline:
                logger.info(
                    "Revalidation budget spent, %d left for next run",
                    len(queue) - stats["revalidated"],
                )
                break
            if not item.get("url"):
                db.update_job_posting(
                    item["id"],
                    {"status": "unknown", "last_checked_at": db._now()},
                )
                stats["revalidated"] += 1
                continue
            try:
                outcome = revalidate_one(item["id"], item["url"], item.get("source"))
            except Exception as exc:
                logger.debug("Revalidate failed for posting #%d: %s", item["id"], exc)
                continue
            stats["revalidated"] += 1
            if outcome == "expired":
                stats["expired"] += 1
                with self._stats_lock:
                    self._stats["postings_expired"] += 1
        with self._stats_lock:
            self._stats["postings_revalidated"] += stats["revalidated"]
        return stats

    def _calculate_intent_scores(self) -> None:
        """Calculate hiring intent scores for all companies with job postings."""
        import json

        try:
            with db.get_connection() as conn:
                domains = conn.execute(
                    "SELECT DISTINCT company_domain FROM job_postings WHERE company_domain IS NOT NULL"
                ).fetchall()

            scored = 0
            for row in domains:
                domain = row[0]
                if not domain:
                    continue

                signals = db.get_company_intent_signals(domain)
                score = signals.get("score", 0)
                if score > 0:
                    db.update_company_intent_score(domain, score, json.dumps(signals))
                    scored += 1

            if scored:
                logger.info("Updated intent scores for %d companies", scored)
        except Exception as exc:
            logger.warning("Intent score calculation failed: %s", exc)

    def _log_stats(self) -> None:
        logger.info("=== Pipeline complete ===")
        for key, val in self._stats.items():
            logger.info("  %-35s %s", key + ":", val)
