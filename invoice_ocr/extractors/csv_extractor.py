"""CSV / Excel extractor."""

import logging

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class CSVExtractor(BaseExtractor):
    """Handles CSV and Excel invoice files."""

    def can_handle(self, file_path: str) -> bool:
        return self.file_extension(file_path) in {".csv", ".xlsx", ".xls"}

    def extract(self, file_path: str) -> ExtractionResult:
        try:
            import pandas as pd
        except ImportError:
            return ExtractionResult(text="", images=[], format="csv", error="pandas not installed")

        try:
            ext = self.file_extension(file_path)
            if ext == ".csv":
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)

            # Convert entire dataframe to a readable text representation
            text = df.to_string(index=False)
            return ExtractionResult(text=text, images=[], format="csv")
        except Exception as e:
            logger.error("CSV/Excel parse error on %s: %s", file_path, e)
            return ExtractionResult(text="", images=[], format="csv", error=str(e))
