"""XML / EDI extractor — converts structured invoice formats to flat text."""

import logging

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class XMLExtractor(BaseExtractor):
    """Handles XML and EDI X12 invoice files."""

    def can_handle(self, file_path: str) -> bool:
        return self.file_extension(file_path) in {".xml", ".edi", ".x12", ".835", ".810"}

    def extract(self, file_path: str) -> ExtractionResult:
        ext = self.file_extension(file_path)
        if ext == ".xml":
            return self._extract_xml(file_path)
        return self._extract_edi(file_path)

    def _extract_xml(self, file_path: str) -> ExtractionResult:
        try:
            from lxml import etree
        except ImportError:
            return ExtractionResult(text="", images=[], format="xml", error="lxml not installed")

        try:
            tree = etree.parse(file_path)
            root = tree.getroot()
            # Flatten all text nodes into a readable key: value format
            lines = []
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if elem.text and elem.text.strip():
                    lines.append(f"{tag}: {elem.text.strip()}")
            return ExtractionResult(text="\n".join(lines), images=[], format="xml")
        except Exception as e:
            logger.error("XML parse error on %s: %s", file_path, e)
            return ExtractionResult(text="", images=[], format="xml", error=str(e))

    def _extract_edi(self, file_path: str) -> ExtractionResult:
        """Basic EDI X12 810 (invoice) parser — segment-by-segment text dump."""
        try:
            with open(file_path, "r", errors="replace") as f:
                raw = f.read()

            # EDI segments are separated by ~ (typical X12)
            segments = [s.strip() for s in raw.replace("\n", "").split("~") if s.strip()]
            lines = []
            for seg in segments:
                elements = seg.split("*")
                segment_id = elements[0]
                lines.append(f"{segment_id}: {' | '.join(elements[1:])}")

            return ExtractionResult(text="\n".join(lines), images=[], format="edi")
        except Exception as e:
            logger.error("EDI parse error on %s: %s", file_path, e)
            return ExtractionResult(text="", images=[], format="edi", error=str(e))
