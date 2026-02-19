"""Image extractor — Tesseract OCR with PIL preprocessing."""

import logging

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)

SUPPORTED = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}


class ImageExtractor(BaseExtractor):
    """Extracts text from invoice images using Tesseract."""

    def can_handle(self, file_path: str) -> bool:
        return self.file_extension(file_path) in SUPPORTED

    def extract(self, file_path: str) -> ExtractionResult:
        try:
            from PIL import Image
            import pytesseract
        except ImportError as e:
            return ExtractionResult(text="", images=[file_path], format="image", error=str(e))

        try:
            img = Image.open(file_path)
            img = self._preprocess(img)
            text = pytesseract.image_to_string(img, config="--psm 6")
            return ExtractionResult(text=text, images=[file_path], format="image")
        except Exception as e:
            logger.error("Image OCR error on %s: %s", file_path, e)
            return ExtractionResult(text="", images=[file_path], format="image", error=str(e))

    def _preprocess(self, img):
        """Convert to grayscale and increase contrast for better OCR accuracy."""
        from PIL import ImageEnhance, ImageFilter
        img = img.convert("L")              # grayscale
        img = img.filter(ImageFilter.SHARPEN)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)
        return img
