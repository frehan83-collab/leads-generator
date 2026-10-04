"""AI-powered email draft personalization using Claude Haiku.

F5 enhanced: Now includes company context (BRREG data), Sperton industry
value props, and optional A/B variant generation.
"""

import os
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)


def generate_ai_opener(
    prospect_name: str,
    prospect_title: str,
    company_name: str,
    job_posting_title: str,
    keyword: str,
    company_context: dict = None,
    variant_count: int = 1,
) -> Optional[Union[str, list[str]]]:
    """
    Generate a personalized 3-line email opening paragraph using Claude Haiku.

    Args:
        prospect_name: Full name of the prospect.
        prospect_title: Job title of the prospect.
        company_name: Company name.
        job_posting_title: Title of the job posting that triggered this.
        keyword: Industry keyword matched.
        company_context: Optional dict with BRREG data (employee_count, nace_code, city, etc.)
        variant_count: Number of variants to generate (1 = single opener, >1 = A/B variants).

    Returns:
        - If variant_count == 1: The opener text string, or None if failed.
        - If variant_count > 1: A list of opener text strings, or None if failed.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        # Build enriched context section
        context_lines = [
            f"- Recipient: {prospect_name}, {prospect_title} at {company_name}",
            f'- They posted a job listing: "{job_posting_title}"',
            f"- Industry keyword: {keyword}",
            f"- Sender: Sperton Rekruttering (specialist recruitment firm, 20+ years, ISO 9001:2015)",
        ]

        # F5: Add company context from BRREG if available
        if company_context:
            if company_context.get("employee_count"):
                context_lines.append(
                    f"- Company size: ~{company_context['employee_count']} employees"
                )
            if company_context.get("nace_description"):
                context_lines.append(
                    f"- Company industry (NACE): {company_context['nace_description']}"
                )
            if company_context.get("city"):
                context_lines.append(
                    f"- Company location: {company_context['city']}"
                )

        # F5: Add Sperton's industry-specific value proposition
        try:
            from src.emails.sperton_context import get_industry_context
            nace = (company_context or {}).get("nace_code", "")
            industry_pitch = get_industry_context(nace_code=nace, keyword=keyword)
            context_lines.append(
                f"- Sperton's relevant expertise: {industry_pitch}"
            )
        except Exception:
            pass  # Don't fail if sperton_context is unavailable

        context_block = "\n".join(context_lines)

        variant_instruction = ""
        if variant_count > 1:
            variant_instruction = (
                f"\n\nIMPORTANT: Generate exactly {variant_count} different variants, "
                "separated by '---'. Each variant should use a different angle/approach. "
                "For example: one could reference company size, another the industry, "
                "another the specific job posting."
            )

        prompt = (
            "Write a personalized 3-line email opening paragraph in Norwegian "
            "for a recruitment outreach email.\n\n"
            f"Context:\n{context_block}\n\n"
            "Requirements:\n"
            "- 3 lines maximum, warm but professional tone\n"
            "- Reference something specific about the company or job posting\n"
            "- End with a natural transition to offering recruitment help\n"
            "- Write in Norwegian (bokmaal)\n"
            "- Do NOT include greeting (Hei/Hello) or sign-off\n"
            "- Use concrete details from the context above to personalize"
            f"{variant_instruction}"
        )

        max_tokens = 200 if variant_count == 1 else 200 * variant_count

        response = client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text.strip()

        if variant_count > 1:
            variants = [v.strip() for v in raw_text.split("---") if v.strip()]
            logger.info(
                "AI generated %d variants for %s at %s",
                len(variants), prospect_name, company_name,
            )
            return variants if variants else None
        else:
            logger.info(
                "AI opener generated for %s at %s (%d chars)",
                prospect_name, company_name, len(raw_text),
            )
            return raw_text

    except ImportError:
        logger.debug("anthropic package not installed, skipping AI draft")
        return None
    except Exception as exc:
        logger.warning("AI draft generation failed: %s", exc)
        return None
