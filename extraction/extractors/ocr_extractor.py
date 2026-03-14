"""
OCR Extractor Module — PaddleOCR Wrapper

Provides local OCR text extraction from images using PaddleOCR.
Replaces the previous pytesseract-based OCR fallback with a more
accurate and self-contained solution.

Key Features:
    - Local processing (no API calls needed for OCR)
    - Supports file paths, PIL Images, and base64-encoded images
    - Configurable language, GPU, and confidence thresholds
    - Batch processing support

Dependencies:
    - paddlepaddle>=2.5.0
    - paddleocr>=2.7.0
    - Pillow>=10.0.0
    - numpy>=1.24.0

Example:
    from extraction.extractors import LocalOCRExtractor

    ocr = LocalOCRExtractor(lang='en', use_gpu=False)
    result = ocr.extract_text_from_image("screenshot.png")
    print(result['text'])
"""

import base64
import io
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

import numpy as np
from PIL import Image

@dataclass
class OCRConfig:
    """Configuration for OCR processing."""
    use_gpu: bool = False
    language: str = "en"
    confidence_threshold: float = 0.85
    verify_with_vision: bool = True

    @classmethod
    def from_env(cls) -> "OCRConfig":
        """Load OCR configuration from environment variables."""
        return cls(
            use_gpu=os.getenv("USE_GPU", "false").lower() == "true",
            language=os.getenv("OCR_LANGUAGE", "en"),
            confidence_threshold=float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.85")),
            verify_with_vision=os.getenv("VERIFY_OCR", "true").lower() == "true",
        )

class LocalOCRExtractor:
    """
    Local OCR extraction using PaddleOCR.

    Extracts text from images without API calls. Supports multiple
    input formats (file path, PIL Image, base64 string) and can
    process images in batches.

    PaddleOCR downloads required models (~150MB) on first use.
    Subsequent runs use cached models for fast startup.

    Attributes:
        ocr: PaddleOCR instance
        config: OCR configuration settings
    """

    def __init__(self, lang: str = "en", use_gpu: bool = False, config: Optional[OCRConfig] = None):
        """
        Initialize PaddleOCR.

        Args:
            lang: Language code ('en', 'ch', 'japan', 'korean', etc.)
            use_gpu: Whether to use GPU acceleration
            config: Optional OCRConfig override (takes precedence)
        """
        self.config = config or OCRConfig(language=lang, use_gpu=use_gpu)

        from paddleocr import PaddleOCR

        # PaddleOCR initialization has become very sensitive to argument names in recent versions.
        # We use a defensive approach to only pass arguments supported by the current version.
        kwargs = {
            "lang": self.config.language,
        }

        # Handle version-specific argument names
        try:
            # Try newer argument name first
            self.ocr = PaddleOCR(use_textline_orientation=True, **kwargs)
        except (TypeError, ValueError):
            try:
                # Fallback to older argument name
                self.ocr = PaddleOCR(use_angle_cls=True, **kwargs)
            except (TypeError, ValueError):
                # Absolute fallback: minimal init
                self.ocr = PaddleOCR(**kwargs)
        print(f"  PaddleOCR initialized (lang={self.config.language}, gpu={self.config.use_gpu})")

    def extract_text_from_image(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from a single image file using PaddleOCR.

        Args:
            image_path: Path to the image file

        Returns:
            Dictionary containing:
                - text: Full extracted text
                - lines: List of text lines with confidence scores
                - boxes: Bounding box coordinates for each text region
                - confidence: Average confidence score
                - success: Whether extraction succeeded
        """
        try:
            result = self.ocr.ocr(image_path, cls=True)
            return self._parse_ocr_result(result)
        except Exception as e:
            return self._error_result(str(e))

    def extract_text_from_pil_image(self, pil_image: Image.Image) -> Dict[str, Any]:
        """
        Extract text from a PIL Image object.

        Args:
            pil_image: PIL Image object

        Returns:
            OCR result dictionary
        """
        try:
            img_array = np.array(pil_image)
            result = self.ocr.ocr(img_array, cls=True)
            return self._parse_ocr_result(result)
        except Exception as e:
            return self._error_result(str(e))

    def extract_text_from_base64(self, base64_string: str) -> Dict[str, Any]:
        """
        Extract text from a base64-encoded image.

        Args:
            base64_string: Base64 encoded image string

        Returns:
            OCR result dictionary
        """
        try:
            image_data = base64.b64decode(base64_string)
            pil_image = Image.open(io.BytesIO(image_data))
            return self.extract_text_from_pil_image(pil_image)
        except Exception as e:
            return self._error_result(str(e))

    def batch_extract(self, image_paths: List[str]) -> List[Dict[str, Any]]:
        """
        Extract text from multiple image files.

        Args:
            image_paths: List of image file paths

        Returns:
            List of OCR result dictionaries
        """
        results = []
        for path in image_paths:
            result = self.extract_text_from_image(path)
            result["source"] = path
            results.append(result)
        return results

    def _parse_ocr_result(self, result) -> Dict[str, Any]:
        """Parse raw PaddleOCR output into structured result."""
        if not result or not result[0]:
            return {
                "text": "",
                "lines": [],
                "boxes": [],
                "confidence": 0.0,
                "success": True,
            }

        lines = []
        boxes = []
        full_text_parts = []
        total_confidence = 0.0

        for line in result[0]:
            box = line[0]       # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text = line[1][0]   # Extracted text
            confidence = line[1][1]  # Confidence score

            lines.append({"text": text, "confidence": confidence})
            boxes.append(box)
            full_text_parts.append(text)
            total_confidence += confidence

        avg_confidence = total_confidence / len(lines) if lines else 0.0

        return {
            "text": "\n".join(full_text_parts),
            "lines": lines,
            "boxes": boxes,
            "confidence": avg_confidence,
            "success": True,
        }

    @staticmethod
    def _error_result(error_msg: str) -> Dict[str, Any]:
        """Create a standardized error result."""
        return {
            "text": "",
            "lines": [],
            "boxes": [],
            "confidence": 0.0,
            "success": False,
            "error": error_msg,
        }
