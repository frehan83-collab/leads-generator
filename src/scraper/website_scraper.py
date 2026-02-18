"""
Direct website email scraper.
When Snov.io has no coverage (common for Norwegian SMEs), we scrape the
company's own website for contact emails AND job titles.

Strategy:
1. Visit the main domain
2. Also try /kontakt, /contact, /om-oss, /about, /team, /ansatte
3. For each mailto: link — grab the surrounding element text to extract
   the person's name and title (e.g. "John Doe - CEO  john@co.no")
4. Also scan visible body text for email patterns + nearby title hints
5. Filter out generic/useless emails and rank by quality
6. Return list of {"email": ..., "title": ..., "name": ...} dicts
"""

import logging
import re
from typing import Optional

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# Pages to check for contact info (relative paths)
CONTACT_PATHS = [
    "",           # home page
    "/kontakt",
    "/kontakt-oss",
    "/contact",
    "/contact-us",
    "/om-oss",
    "/about",
    "/about-us",
    "/bedriften",
    "/ansatte",
    "/team",
    "/ledelse",
    "/people",
    "/staff",
]

# Email pattern — strict enough to avoid HTML artifacts
EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{2,255}\.[a-zA-Z]{2,10}"
)

# Emails to skip — non-personal / automated / support
SKIP_PREFIXES = {
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "support", "help", "helpdesk",
    "webmaster", "hostmaster", "postmaster", "abuse",
    "bounce", "mailer-daemon",
    "newsletter", "unsubscribe", "subscribe",
    "sales",
    "marketing",
    "admin",
    "it", "itsupport",
    "faktura", "invoice", "regnskap",
    "kundeservice", "customer",
    "booking", "bestilling", "order",
    "privacy", "gdpr", "personvern",
    "media", "press", "presse",
}

# Prefixes that are USEFUL (role addresses worth contacting)
GOOD_ROLE_PREFIXES = {
    "dagligleder", "ceo", "director", "leder",
    "rekruttering", "rekrutering", "recruitment", "recruiting",
    "hr", "personal", "personalsjef",
    "careers", "jobb", "jobs",
    "kontakt", "contact",
    "post", "info",
}

# Norwegian / English title keywords to look for near an email
TITLE_KEYWORDS = re.compile(
    r"(daglig\s*leder|adm\.?\s*dir|administrerende\s*direkt|ceo|cto|cfo|coo|"
    r"direkt|manager|leder|sjef|head\s+of|partner|founder|grunder|"
    r"senior|principal|lead|engineer|ingeni|r.dgiver|r.dgivende|"
    r"konsulent|consultant|koordinator|controller|analytiker|analytist|"
    r"salg|sales|account|business\s+dev|bd\s*manager|"
    r"hr|personal|rekrutter|talent|"
    r"prosjekt|project|"
    r"teknisk|technical|tech\s*lead|"
    r"avdelingsleder|faglig\s*leder|driftsleder|driftssjef|"
    r"veterinær|biolog|forsker|researcher|scientist)",
    re.IGNORECASE,
)


def _is_valid_email(email: str, domain: str) -> bool:
    """Return True if the email looks useful for outreach."""
    email_lower = email.lower()
    local, _, email_domain = email_lower.partition("@")

    root = domain.lstrip("www.").lower()
    if not (email_domain == root or email_domain.endswith("." + root)):
        return False

    for prefix in SKIP_PREFIXES:
        if local == prefix or local.startswith(prefix + ".") or local.startswith(prefix + "+"):
            return False

    return True


def _score_email(email: str) -> int:
    """Score an email — higher = more likely to be a real decision-maker."""
    local = email.lower().split("@")[0]

    if "." in local and not any(local == p for p in GOOD_ROLE_PREFIXES):
        return 10  # personal firstname.lastname

    for role in GOOD_ROLE_PREFIXES:
        if local == role or local.startswith(role):
            return 5

    return 1


def _extract_title_from_text(text: str) -> str:
    """
    Given a chunk of text near an email (e.g. a card or list item),
    try to extract a job title. Returns empty string if nothing found.

    Examples of text chunks:
      "John Doe\\nCEO\\njohn@company.no"
      "Sales Manager | jane@company.no"
      "Ola Nordmann - Daglig leder\\n ola@company.no"
    """
    if not text:
        return ""

    # Clean up whitespace
    cleaned = re.sub(r"[ \t]+", " ", text.strip())
    lines = [l.strip() for l in re.split(r"[\n\r|•/–-]", cleaned) if l.strip()]

    for line in lines:
        # Skip lines that are just email addresses or very short
        if EMAIL_PATTERN.search(line):
            continue
        if len(line) < 3 or len(line) > 80:
            continue
        # Check if this line contains a title keyword
        if TITLE_KEYWORDS.search(line):
            # Clean up the line a bit
            title = re.sub(r"\s+", " ", line).strip(" .,;:")
            return title[:80]

    # Fallback: return the shortest non-email line as a possible title
    candidates = [l for l in lines if not EMAIL_PATTERN.search(l) and 3 <= len(l) <= 60]
    if candidates:
        # Prefer lines with title keywords, else take the shortest
        for c in candidates:
            if TITLE_KEYWORDS.search(c):
                return c.strip(" .,;:")[:80]

    return ""


def _get_mailto_contacts(page) -> list[dict]:
    """
    Extract all mailto: links from the page, with surrounding context text
    so we can find name/title near each email.
    Returns list of {"email": str, "context": str}
    """
    try:
        contacts = page.evaluate("""
            () => {
                const results = [];
                const links = document.querySelectorAll('a[href^="mailto:"]');
                links.forEach(link => {
                    const href = link.getAttribute('href') || '';
                    const email = href.replace('mailto:', '').split('?')[0].trim().toLowerCase();
                    if (!email) return;

                    // Walk up to find a meaningful container (card, li, div with text)
                    let el = link;
                    let context = '';
                    for (let i = 0; i < 5; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const text = el.innerText || el.textContent || '';
                        if (text.trim().length > 10 && text.trim().length < 500) {
                            context = text.trim();
                            break;
                        }
                    }
                    results.push({ email, context });
                });
                return results;
            }
        """)
        return contacts or []
    except Exception:
        return []


def scrape_emails_from_website(domain: str, timeout_sec: int = 20) -> list[dict]:
    """
    Visit the company website and return a ranked list of contacts.
    Each contact is a dict: {"email": str, "title": str, "name": str}
    Returns at most 5 contacts, best-scored first.
    """
    if not domain:
        return []

    base_url = f"https://{domain}"
    # email -> {"score": int, "title": str, "name": str}
    found: dict[str, dict] = {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="nb-NO",
            )
            page = context.new_page()

            for path in CONTACT_PATHS:
                url = base_url + path
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)

                    # Accept cookie banner if present
                    try:
                        page.click("button:has-text('Godta alle')", timeout=1500)
                    except Exception:
                        try:
                            page.click("button:has-text('Aksepter')", timeout=1000)
                        except Exception:
                            pass

                    # Strategy A: mailto: links with surrounding context
                    mailto_contacts = _get_mailto_contacts(page)
                    for contact in mailto_contacts:
                        email = contact.get("email", "").lower()
                        context_text = contact.get("context", "")
                        if not email or not EMAIL_PATTERN.match(email):
                            continue
                        if not _is_valid_email(email, domain):
                            continue

                        score = _score_email(email)
                        title = _extract_title_from_text(context_text)

                        # Parse name from email local part if firstname.lastname
                        name = ""
                        local = email.split("@")[0]
                        if "." in local:
                            parts = local.split(".")
                            if len(parts) == 2 and all(p.isalpha() for p in parts):
                                name = f"{parts[0].capitalize()} {parts[1].capitalize()}"

                        if email not in found or found[email]["score"] < score:
                            found[email] = {"score": score, "title": title, "name": name}
                            logger.debug(
                                "Found mailto: %s title='%s' (score %d)", email, title, score
                            )

                    # Strategy B: scan visible body text for bare email addresses
                    body_text = page.inner_text("body")
                    for match in EMAIL_PATTERN.finditer(body_text):
                        email = match.group(0).lower()
                        if not _is_valid_email(email, domain):
                            continue
                        if email in found:
                            continue  # already have it with context

                        score = _score_email(email)
                        # Try to grab surrounding text (±150 chars) for title hint
                        start = max(0, match.start() - 150)
                        end = min(len(body_text), match.end() + 150)
                        snippet = body_text[start:end]
                        title = _extract_title_from_text(snippet)

                        name = ""
                        local = email.split("@")[0]
                        if "." in local:
                            parts = local.split(".")
                            if len(parts) == 2 and all(p.isalpha() for p in parts):
                                name = f"{parts[0].capitalize()} {parts[1].capitalize()}"

                        found[email] = {"score": score, "title": title, "name": name}
                        logger.debug(
                            "Found text email: %s title='%s' (score %d)", email, title, score
                        )

                    # Stop early if we have enough high-quality personal emails
                    best = max((v["score"] for v in found.values()), default=0)
                    if best >= 10 and len(found) >= 2:
                        logger.debug(
                            "Found enough personal emails for %s, stopping early", domain
                        )
                        break

                except PWTimeout:
                    logger.debug("Timeout on %s", url)
                    continue
                except Exception as exc:
                    logger.debug("Error visiting %s: %s", url, exc)
                    continue

            browser.close()

    except Exception as exc:
        logger.warning("scrape_emails_from_website failed for %s: %s", domain, exc)
        return []

    # Sort by score descending, return top 5 as dicts
    ranked = sorted(found.keys(), key=lambda e: found[e]["score"], reverse=True)
    result = []
    for email in ranked[:5]:
        entry = found[email]
        result.append({
            "email": email,
            "title": entry["title"],
            "name": entry["name"],
        })

    if result:
        logger.info(
            "Website scrape for %s: found %d contact(s): %s",
            domain,
            len(result),
            [(r["email"], r["title"]) for r in result],
        )
    else:
        logger.debug("Website scrape for %s: no emails found", domain)

    return result
