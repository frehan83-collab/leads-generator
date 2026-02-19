"""Anthropic SDK wrapper for invoice extraction."""

import base64
import json
import logging
from pathlib import Path
from typing import Optional

import anthropic

from ..config import settings
from .extraction_prompts import build_extraction_prompt

logger = logging.getLogger(__name__)


class ClaudeExtractionClient:
    """Handles all Claude API calls for invoice data extraction."""

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def extract_from_text(
        self,
        ocr_text: str,
        vendor_context: Optional[str] = None,
    ) -> dict:
        """Extract invoice fields from plain text using the cost-effective text model."""
        prompt = build_extraction_prompt(ocr_text, vendor_context)

        async with self._client.messages.stream(
            model=settings.text_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = await stream.get_final_message()

        raw = message.content[0].text.strip()
        return self._parse_json(raw)

    async def extract_from_pdf(
        self,
        pdf_path: str,
        vendor_context: Optional[str] = None,
    ) -> dict:
        """Send a PDF directly to Claude — works for both digital and scanned PDFs."""
        with open(pdf_path, "rb") as f:
            pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

        prompt_text = build_extraction_prompt(
            "(PDF attached — extract all invoice fields from it)",
            vendor_context,
        )

        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_data,
                },
            },
            {"type": "text", "text": prompt_text},
        ]

        async with self._client.messages.stream(
            model=settings.vision_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = await stream.get_final_message()

        raw = message.content[0].text.strip()
        return self._parse_json(raw)

    async def extract_from_image(
        self,
        image_path: str,
        ocr_text: Optional[str] = None,
        vendor_context: Optional[str] = None,
    ) -> dict:
        """Extract invoice fields from an image using Claude vision."""
        image_data = self._encode_image(image_path)
        media_type = self._detect_media_type(image_path)

        prompt_text = build_extraction_prompt(
            ocr_text or "(see image — extract all invoice fields)",
            vendor_context,
        )

        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data,
                },
            },
            {"type": "text", "text": prompt_text},
        ]

        async with self._client.messages.stream(
            model=settings.vision_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            message = await stream.get_final_message()

        raw = message.content[0].text.strip()
        return self._parse_json(raw)

    async def generate_layout_hints(
        self,
        original_extraction: dict,
        corrections: dict,
    ) -> dict:
        """Ask Claude to summarize layout hints from human corrections."""
        from .extraction_prompts import build_correction_prompt
        prompt = build_correction_prompt(original_extraction, corrections)

        async with self._client.messages.stream(
            model=settings.text_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = await stream.get_final_message()

        raw = message.content[0].text.strip()
        return self._parse_json(raw)

    # ------------------------------------------------------------------ helpers

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _detect_media_type(self, image_path: str) -> str:
        ext = Path(image_path).suffix.lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }.get(ext, "image/jpeg")

    def _parse_json(self, raw: str) -> dict:
        """Robustly parse JSON — strip markdown fences if present."""
        text = raw
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Claude JSON response: %s\nRaw: %s", e, raw[:500])
            return {
                "confidence_score": 0.0,
                "extraction_notes": f"JSON parse error: {e}",
            }
