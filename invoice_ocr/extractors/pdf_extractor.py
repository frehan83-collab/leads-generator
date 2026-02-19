"""PDF extractor — pdfplumber for digital PDFs, pdf2image + Tesseract for scanned."""

import logging
import os
import tempfile
from typing import Optional

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

DIGITAL_MIN_CHARS = 50  # if pdfplumber extracts fewer chars, treat as scanned


class PDFExtractor(BaseExtractor):
    """Handles both digital and scanned PDFs."""

    def can_handle(self, file_path: str) -> bool:
        return self.file_extension(file_path) == ".pdf"

    def extract(self, file_path: str) -> ExtractionResult:
        text = self._extract_digital(file_path)

        if len(text.strip()) >= DIGITAL_MIN_CHARS:
            logger.debug("Digital PDF detected: %s (%d chars)", file_path, len(text))
            return ExtractionResult(text=text, images=[], format="pdf_digital")

        logger.debug("Scanned PDF detected: %s — running OCR", file_path)
        return self._extract_scanned(file_path)

    # ------------------------------------------------------------------ helpers

    def _extract_digital(self, file_path: str) -> str:
        """Use pdfplumber to extract text from a digital PDF."""
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed")
            return ""

        pages_text = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    # Also extract tables as text
                    for table in page.extract_tables():
                        for row in table:
                            pages_text.append(" | ".join(str(cell or "") for cell in row))
                    pages_text.append(page_text)
        except Exception as e:
            logger.error("pdfplumber error on %s: %s", file_path, e)

        return "\n".join(pages_text)

    def _extract_scanned(self, file_path: str) -> ExtractionResult:
        """Convert PDF pages to images, run Tesseract OCR on each."""
        images = []
        ocr_text_parts = []
        tmp_dir = tempfile.mkdtemp(prefix="invoice_ocr_")

        try:
            from pdf2image import convert_from_path
        except ImportError:
            logger.warning("pdf2image not installed — cannot OCR scanned PDF")
            return ExtractionResult(text="", images=[], format="pdf_scanned", error="pdf2image not installed")

        try:
            pil_images = convert_from_path(file_path, dpi=300)
        except Exception as e:
            return ExtractionResult(text="", images=[], format="pdf_scanned", error=str(e))

        for i, pil_img in enumerate(pil_images):
            img_path = os.path.join(tmp_dir, f"page_{i+1}.png")
            pil_img.save(img_path, "PNG")
            images.append(img_path)
            ocr_text_parts.append(self._run_tesseract(pil_img))

        return ExtractionResult(
            text="\n\n--- Page Break ---\n\n".join(ocr_text_parts),
            images=images,
            format="pdf_scanned",
            page_count=len(pil_images),
        )

    def _run_tesseract(self, pil_image) -> str:
        """Run Tesseract on a PIL image and return the text."""
        try:
            import pytesseract
            return pytesseract.image_to_string(pil_image, config="--psm 6")
        except ImportError:
            logger.warning("pytesseract not installed")
            return ""
        except Exception as e:
            logger.error("Tesseract error: %s", e)
            return ""
