"""Abstract base extractor — all format-specific extractors inherit from this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ExtractionResult:
    text: str                      # Raw extracted text
    images: list[str]              # Paths to page images (for vision fallback)
    format: str                    # pdf_digital / pdf_scanned / image / xml / csv / edi
    page_count: int = 1
    error: Optional[str] = None


class BaseExtractor(ABC):
    """Base class for all document extractors."""

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """Return True if this extractor supports the given file."""

    @abstractmethod
    def extract(self, file_path: str) -> ExtractionResult:
        """Extract raw text (and optionally images) from the document."""

    @staticmethod
    def file_extension(file_path: str) -> str:
        return Path(file_path).suffix.lower()
