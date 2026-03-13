"""
Vision Verifier Module — OCR Verification via Groq Vision LLM

Verifies and corrects PaddleOCR output by sending the original image
and OCR text to Groq's Llama 3.2 Vision model. The LLM compares the
OCR output against what it sees in the image and corrects any errors.

This is especially useful for:
    - Low-confidence OCR results
    - Complex layouts with tables or mixed text/images
    - Handwritten or stylized text
    - Technical diagrams with small labels

Example:
    from extraction.processors import OCRVerifier

    verifier = OCRVerifier(groq_api_key="gsk_...")
    result = verifier.verify_ocr(image_base64, ocr_text)
    corrected_text = result['verified_text']
"""

import os
from typing import Dict, Any, Optional


class OCRVerifier:
    """
    Verify and correct OCR output using Groq Vision LLM.

    Sends the original image alongside the OCR-extracted text to
    Groq's Llama 3.2 Vision model. The model compares the OCR output
    against what it can see and returns corrected text.

    Falls back gracefully to the original OCR text if:
    - No API key is provided
    - The Vision API call fails
    - The verified text is empty
    """

    DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

    def __init__(self, groq_api_key: str = None, model: str = None):
        """
        Initialize the OCR verifier.

        Args:
            groq_api_key: Groq API key for Vision model access.
                          Falls back to GROQ_API_KEY env var.
                          If None, verification is skipped.
            model: Vision model to use (default: llama-3.2-90b-vision-preview)
        """
        self.client = None
        self.model = model or self.DEFAULT_MODEL

        api_key = groq_api_key or os.getenv("GROQ_API_KEY")

        if api_key:
            try:
                from groq import Groq
                self.client = Groq(
                    api_key=api_key,
                )
                # Test connection by making a dummy call
                self.client.models.list()
            except Exception as e:
                # Catch authentication errors or connection issues gracefully
                self.client = None
                if not isinstance(e, ImportError):
                    print(f"  ⚠ Groq initialization failed (check API key): {e}")

    @property
    def is_available(self) -> bool:
        """Check if Vision verification is available."""
        return self.client is not None

    def verify_ocr(self, image_base64: str, ocr_text: str) -> Dict[str, Any]:
        """
        Verify and correct OCR text using Groq Vision LLM.

        Args:
            image_base64: Base64-encoded image data
            ocr_text: Text extracted by PaddleOCR

        Returns:
            Dictionary containing:
                - original_ocr: The original OCR text
                - verified_text: Corrected text (or original if not corrected)
                - was_corrected: Whether the text was modified
                - success: Whether verification completed
        """
        if not self.client:
            return {
                "original_ocr": ocr_text,
                "verified_text": ocr_text,
                "was_corrected": False,
                "success": False,
                "reason": "No Vision LLM configured",
            }

        if not ocr_text.strip():
            return {
                "original_ocr": ocr_text,
                "verified_text": ocr_text,
                "was_corrected": False,
                "success": True,
                "reason": "Empty OCR text — nothing to verify",
            }

        try:
            prompt = (
                "I have extracted the following text from this image using OCR. "
                "Please verify the text against what you see in the image. "
                "If there are any errors, correct them. If the text is accurate, "
                "return it as-is. Return ONLY the corrected text, nothing else.\n\n"
                f"OCR Text:\n{ocr_text}"
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"}
                        },
                    ],
                }],
                max_tokens=4000,
                temperature=0.1,
            )

            verified_text = response.choices[0].message.content.strip()
            was_corrected = verified_text.strip() != ocr_text.strip()

            return {
                "original_ocr": ocr_text,
                "verified_text": verified_text,
                "was_corrected": was_corrected,
                "success": True,
            }

        except Exception as e:
            print(f"  ⚠ Vision verification failed: {e}")
            return {
                "original_ocr": ocr_text,
                "verified_text": ocr_text,
                "was_corrected": False,
                "success": False,
                "reason": str(e),
            }
