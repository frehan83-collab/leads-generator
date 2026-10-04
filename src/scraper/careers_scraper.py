"""
Company career-page discovery source.

Many Norwegian SMEs post openings only on their own websites. This source
revisits the career pages of companies already seen in job postings —
no unbounded crawling: only known domains, only known career paths,
robots.txt honored, same-domain links only, capped jobs per domain.

Yields posting dicts with source="careers".
"""

import hashlib
import logging
import re
import time as _time
from collections.abc import Generator

import requests

from src.scraper.browser_manager import USER_AGENT
from src.scraper.website_scraper import (
    TAG_STRIP_PATTERN,
    _fetch_robots_disallows,
    _is_site_blocked,
    _path_allowed,
)

logger = logging.getLogger(__name__)

CAREER_PATHS = [
    "/karriere",
    "/ledige-stillinger",
    "/jobs",
    "/vacancies",
    "/stillinger",
    "/jobb",
    "/om-oss/karriere",
    "/about/careers",
]

JOB_URL_HINT = re.compile(
    r"/(stilling|stillinger|jobb|jobs|vacanc|career|karriere|position|opening|ledig)",
    re.IGNORECASE,
)
JOB_TEXT_HINT = re.compile(
    r"(s\xf8ker|stilling ledig|ledige stillinger|we.?re hiring|join (us|our team)|"
    r"apply now|s\xf8k (her|n\xe5)|bli en del av)",
    re.IGNORECASE,
)
ANCHOR_PATTERN = re.compile(
    r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
TITLE_PATTERN = re.compile(
    r"<h1[^>]*>(.*?)</h1>|<meta[^>]*property=[\"']og:title[\"'][^>]*content=[\"'](.*?)[\"']",
    re.DOTALL | re.IGNORECASE,
)

MAX_JOBS_PER_DOMAIN = 10


def _same_domain(url: str, domain: str) -> bool:
    from urllib.parse import urlparse

    try:
        netloc = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return False
    root = domain.lower().removeprefix("www.")
    return netloc == root or netloc.endswith("." + root)


def _absolutize(href: str, base_url: str) -> str | None:
    from urllib.parse import urljoin

    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    return urljoin(base_url + "/", href)


def _extract_title(html: str) -> str:
    match = TITLE_PATTERN.search(html)
    if not match:
        return ""
    title = match.group(1) or match.group(2) or ""
    title = TAG_STRIP_PATTERN.sub(" ", title)
    return re.sub(r"\s+", " ", title).strip()[:160]


def _candidate_job_links(
    html: str, page_url: str, domain: str
) -> list[tuple[str, str]]:
    """(url, link_text) pairs that look like job postings, same-domain only."""
    found: dict[str, str] = {}
    for match in ANCHOR_PATTERN.finditer(html):
        url = _absolutize(match.group(1), page_url)
        if not url or not _same_domain(url, domain) or url in found:
            continue
        text = TAG_STRIP_PATTERN.sub(" ", match.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        if JOB_URL_HINT.search(url) or (text and JOB_TEXT_HINT.search(text)):
            found[url] = text
        if len(found) >= MAX_JOBS_PER_DOMAIN:
            break
    return list(found.items())


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def scrape_career_pages(
    targets: list[dict],
    known_ids: set | None = None,
    max_domains: int | None = None,
    timeout_sec: int = 15,
    deadline: float | None = None,
) -> Generator[dict, None, None]:
    """Discover job postings on company career pages.

    Args:
        targets: [{"domain": ..., "company_name": ...}, ...]
        known_ids: external_ids to skip (incremental)
        max_domains: cap on domains visited this run
        timeout_sec: per-request timeout
        deadline: optional monotonic timestamp for the whole run
    """
    known_ids = known_ids or set()
    session = requests.Session()
    session.headers.update(
        {"User-Agent": USER_AGENT, "Accept-Language": "nb-NO,nb;q=0.9"}
    )

    visited = 0
    for target in targets:
        if max_domains is not None and visited >= max_domains:
            break
        if deadline is not None and _time.monotonic() > deadline:
            break
        domain = (target.get("domain") or "").strip().lower()
        company_name = (target.get("company_name") or "").strip()
        if not domain:
            continue
        visited += 1
        base_url = f"https://{domain}"

        disallows = _fetch_robots_disallows(domain)
        if _is_site_blocked(disallows):
            logger.debug("Skipping %s: disallowed by robots.txt", domain)
            continue
        paths = [p for p in CAREER_PATHS if _path_allowed(p, disallows)]

        seen_urls: set[str] = set()
        try:
            for path in paths:
                if deadline is not None and _time.monotonic() > deadline:
                    break
                try:
                    resp = session.get(base_url + path, timeout=timeout_sec)
                    if not resp.ok or not resp.text:
                        continue
                except Exception as exc:
                    logger.debug(
                        "Career page fetch failed %s%s: %s", base_url, path, exc
                    )
                    continue

                for job_url, link_text in _candidate_job_links(
                    resp.text, base_url + path, domain
                ):
                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)
                    external_id = _stable_id(job_url)
                    if external_id in known_ids:
                        continue
                    title = ""
                    try:
                        job_resp = session.get(job_url, timeout=timeout_sec)
                        if job_resp.ok and job_resp.text:
                            title = _extract_title(job_resp.text)
                    except Exception as exc:
                        logger.debug("Job page fetch failed %s: %s", job_url, exc)
                    title = title or link_text or "Stilling (see posting)"
                    yield {
                        "external_id": external_id,
                        "source": "careers",
                        "title": title,
                        "company_name": company_name,
                        "company_domain": domain,
                        "org_number": None,
                        "location": "",
                        "url": job_url,
                        "keyword_matched": "careers",
                        "published_at": None,
                    }
        except Exception as exc:
            logger.debug("Career scan failed for %s: %s", domain, exc)
            continue
