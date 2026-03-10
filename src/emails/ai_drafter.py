"""AI-powered email draft personalization using Claude Haiku."""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def generate_ai_opener(
    prospect_name: str,
    prospect_title: str,
    company_name: str,
    job_posting_title: str,
    keyword: str,
) -> Optional[str]:
    """
    Generate a personalized 3-line email opening paragraph using Claude Haiku.
    Returns the opener text, or None if API key missing or call fails.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            "Write a personalized 3-line email opening paragraph in Norwegian "
            "for a recruitment outreach email.\n\n"
            f"Context:\n"
            f"- Recipient: {prospect_name}, {prospect_title} at {company_name}\n"
            f"- They posted a job listing: \"{job_posting_title}\"\n"
            f"- Industry keyword: {keyword}\n"
            f"- Sender: Sperton Rekruttering (specialist recruitment firm)\n\n"
            "Requirements:\n"
            "- 3 lines maximum, warm but professional tone\n"
            "- Reference the specific job posting naturally\n"
            "- End with a natural transition to offering recruitment help\n"
            "- Write in Norwegian (bokmaal)\n"
            "- Do NOT include greeting (Hei/Hello) or sign-off"
        )

        response = client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        opener = response.content[0].text.strip()
        logger.info(
            "AI opener generated for %s at %s (%d chars)",
            prospect_name, company_name, len(opener),
        )
        return opener

    except ImportError:
        logger.debug("anthropic package not installed, skipping AI draft")
        return None
    except Exception as exc:
        logger.warning("AI draft generation failed: %s", exc)
        return None
