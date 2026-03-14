"""
Standalone Image Extractor Module

Handles direct image files (PNG, JPG, etc.) that are not embedded
inside documents. Delegates to the OCR extractor for text extraction.

Example:
    from extraction.extractors import StandaloneImageExtractor

    extractor = StandaloneImageExtractor(ocr_extractor=ocr)
    text = extractor.extract_text("flowchart.png")
"""

import base64
from pathlib import Path
from typing import Dict, Any, Optional

class StandaloneImageExtractor:
    """
    Extract text from standalone image files using OCR.

    This extractor handles direct image files (not embedded inside
    documents). It delegates to LocalOCRExtractor for the actual
    OCR processing.

    Attributes:
        ocr_extractor: LocalOCRExtractor instance for OCR
    """

    def __init__(self, ocr_extractor=None):
        """
        Initialize the standalone image extractor.

        Args:
            ocr_extractor: LocalOCRExtractor instance. Required for
                           text extraction to work.
        """
        self.ocr_extractor = ocr_extractor

    def extract_text(self, file_path: str) -> str:
        """
        Extract text from a standalone image file using OCR.

        Args:
            file_path: Path to the image file

        Returns:
            Extracted text content
        """
        if not self.ocr_extractor:
            print(f"  ⚠ No OCR extractor available — cannot process image")
            return ""

        print(f"  Processing image: {Path(file_path).name}")
        result = self.ocr_extractor.extract_text_from_image(file_path)

        if result["success"] and result["text"].strip():
            print(f"  ✓ Image OCR: {len(result['text'])} chars (confidence: {result['confidence']:.2%})")
            return result["text"]
        else:
            print(f"  ⚠ No text detected in image")
            return ""

    def get_image_data(self, file_path: str) -> Dict[str, Any]:
        """
        Load an image file into a standardized dictionary format.

        This is used when the image needs to be sent to the image
        processing pipeline (classification, diagram analysis, etc.)

        Args:
            file_path: Path to the image file

        Returns:
            Dictionary with base64 data, format, and metadata
        """
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()

            img_format = Path(file_path).suffix.lstrip(".").lower()
            format_map = {"jpg": "jpeg", "jpe": "jpeg"}
            img_format = format_map.get(img_format, img_format)

            return {
                "format": img_format,
                "base64": base64.b64encode(image_bytes).decode("utf-8"),
                "bytes": image_bytes,
                "source": Path(file_path).name,
                "size_bytes": len(image_bytes),
            }

        except Exception as e:
            print(f"  ✗ Error loading image: {e}")
            return None
