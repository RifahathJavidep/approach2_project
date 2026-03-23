import os
from typing import Dict, Any, Optional

from groq import Groq


class OCRVerifier:
    """Verifies and corrects PaddleOCR output using Groq Vision LLM."""

    DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

    def __init__(self, groq_api_key: str = None, model: str = None):
        self.client = None
        self.model = model or self.DEFAULT_MODEL

        api_key = groq_api_key or os.getenv("GROQ_API_KEY")

        if api_key:
            try:
                self.client = Groq(api_key=api_key)
                self.client.models.list()
            except Exception as e:
                self.client = None
                if not isinstance(e, ImportError):
                    print(f"  ⚠ Groq initialization failed (check API key): {e}")

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def verify_ocr(self, image_base64: str, ocr_text: str) -> Dict[str, Any]:
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
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
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
