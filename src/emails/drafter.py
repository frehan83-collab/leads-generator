"""
Auto-draft email campaigns for new prospects.

When a new prospect is added to the database, this module generates
personalised email drafts using the templates. Drafts are stored with
status='draft' and must be reviewed + approved before sending.
"""

import logging
import os

from src.database import db
from src.emails.ai_drafter import generate_ai_opener
from src.emails.templates import TEMPLATES

logger = logging.getLogger(__name__)

# Default template to use for auto-drafting
DEFAULT_TEMPLATE = "formal_outreach"


def auto_draft_for_new_prospect(
    prospect_id: int,
    job_posting_id: int,
    template_name: str = None,
) -> int | None:
    """
    Generate an email draft for a newly added prospect.

    Returns the draft ID if created, or None if skipped (e.g. draft already exists).
    """
    # Don't duplicate drafts
    if db.draft_exists_for_prospect(prospect_id):
        logger.debug("Draft already exists for prospect %d, skipping", prospect_id)
        return None

    prospect = db.get_prospect_by_id(prospect_id)
    if not prospect:
        logger.warning("Prospect %d not found, cannot draft", prospect_id)
        return None

    posting = db.get_job_posting_by_id(job_posting_id) if job_posting_id else {}
    posting = posting or {}

    # Pick template
    tpl_name = template_name or _pick_template(prospect)
    tpl = TEMPLATES.get(tpl_name)
    if not tpl:
        logger.warning("Template '%s' not found, using default", tpl_name)
        tpl_name = DEFAULT_TEMPLATE
        tpl = TEMPLATES[tpl_name]

    # Generate draft
    try:
        subject, body = tpl["fn"](prospect, posting)
    except Exception as exc:
        logger.warning("Failed to generate draft for prospect %d: %s", prospect_id, exc)
        return None

    # Try AI personalization — replace first body paragraph after greeting
    # F5: Enriched with company context from BRREG
    company_context = None
    ai_context_json = None
    if os.getenv("ANTHROPIC_API_KEY"):
        org_num = posting.get("org_number") or ""
        if org_num:
            try:
                company_data = db.get_company_by_org_number(org_num)
                if company_data:
                    company_context = {
                        "employee_count": company_data.get("employee_count"),
                        "nace_code": company_data.get("nace_code"),
                        "nace_description": company_data.get("nace_description"),
                        "city": company_data.get("city"),
                    }
            except Exception:
                pass

        ai_opener = generate_ai_opener(
            prospect_name=prospect.get("full_name", ""),
            prospect_title=prospect.get("position", ""),
            company_name=prospect.get("company_name", ""),
            job_posting_title=posting.get("title", ""),
            keyword=posting.get("keyword_matched", ""),
            company_context=company_context,
        )
        if ai_opener:
            paragraphs = body.split("\n\n")
            if len(paragraphs) >= 2:
                paragraphs[1] = ai_opener
                body = "\n\n".join(paragraphs)
            tpl_name = f"ai_{tpl_name}"
            if company_context:
                import json

                ai_context_json = json.dumps(company_context)

    draft_data = {
        "prospect_id": prospect_id,
        "job_posting_id": job_posting_id,
        "template_name": tpl_name,
        "subject": subject,
        "body": body,
        "status": "draft",
    }

    draft_id = db.insert_email_draft(draft_data)
    if draft_id:
        # F5: Store AI context metadata if enriched
        if ai_context_json:
            db.update_email_draft(draft_id, {"ai_context": ai_context_json})

        logger.info(
            "Created draft #%d for %s (%s template)",
            draft_id,
            prospect.get("email", "?"),
            tpl_name,
        )

        # F4: Auto-create LinkedIn connection request if prospect has LinkedIn URL
        if prospect.get("linkedin_url"):
            try:
                from src.emails.linkedin_templates import connection_request

                li_text = connection_request(prospect, posting)
                db.insert_linkedin_message(
                    {
                        "prospect_id": prospect_id,
                        "draft_id": draft_id,
                        "message_type": "connection_request",
                        "message_text": li_text,
                    }
                )
                logger.info("Created LinkedIn message for prospect %d", prospect_id)
            except Exception as exc:
                logger.warning("Failed to create LinkedIn message: %s", exc)

    return draft_id


def _pick_template(prospect: dict) -> str:
    """
    Choose the best template based on prospect data.

    - Executives/leaders → value_proposition (stats-driven)
    - HR / recruitment roles → short_intro (direct)
    - Default → formal_outreach (safe first contact)
    """
    position = (prospect.get("position") or "").lower()

    # Decision-makers get the value proposition
    executive_keywords = [
        "ceo",
        "cto",
        "cfo",
        "coo",
        "director",
        "direktoer",
        "daglig leder",
        "adm.dir",
        "administrerende",
        "managing",
        "partner",
        "founder",
        "grunder",
        "eier",
    ]
    for kw in executive_keywords:
        if kw in position:
            return "value_proposition"

    # HR / recruitment get the short intro
    hr_keywords = [
        "hr",
        "human resources",
        "personal",
        "rekruttering",
        "recruitment",
        "talent",
        "people",
    ]
    for kw in hr_keywords:
        if kw in position:
            return "short_intro"

    return DEFAULT_TEMPLATE


def regenerate_draft(
    draft_id: int,
    template_name: str = None,
) -> bool:
    """
    Regenerate an existing draft with a different template.
    Returns True if successful.
    """
    draft = db.get_email_draft_by_id(draft_id)
    if not draft:
        return False

    prospect = db.get_prospect_by_id(draft["prospect_id"])
    posting = (
        db.get_job_posting_by_id(draft["job_posting_id"])
        if draft.get("job_posting_id")
        else {}
    )
    posting = posting or {}

    tpl_name = template_name or DEFAULT_TEMPLATE
    tpl = TEMPLATES.get(tpl_name)
    if not tpl:
        return False

    try:
        subject, body = tpl["fn"](prospect, posting)
    except Exception:
        return False

    db.update_email_draft(
        draft_id,
        {
            "template_name": tpl_name,
            "subject": subject,
            "body": body,
            "status": "draft",
            "approved_at": None,
        },
    )
    logger.info("Regenerated draft #%d with template '%s'", draft_id, tpl_name)
    return True
