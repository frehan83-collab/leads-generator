"""Extractor registry — auto-selects the right extractor for each file format."""

from .base import BaseExtractor, ExtractionResult
from .pdf_extractor import PDFExtractor
from .image_extractor import ImageExtractor
from .xml_extractor import XMLExtractor
from .csv_extractor import CSVExtractor

_EXTRACTORS: list[BaseExtractor] = [
    PDFExtractor(),
    ImageExtractor(),
    XMLExtractor(),
    CSVExtractor(),
]


def get_extractor(file_path: str) -> BaseExtractor:
    """Return the first extractor that can handle this file."""
    for extractor in _EXTRACTORS:
        if extractor.can_handle(file_path):
            return extractor
    raise ValueError(f"No extractor available for: {file_path}")


def extract(file_path: str) -> ExtractionResult:
    """Convenience wrapper — detect format and extract in one call."""
    return get_extractor(file_path).extract(file_path)


__all__ = ["extract", "get_extractor", "ExtractionResult", "BaseExtractor"]
