import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

import fitz
from groq import Groq
from PIL import Image
from pptx import Presentation

from .file_router import FileRouter, FileType
from .extractors.pdf_extractor import PDFExtractor
from .extractors.docx_extractor import DOCXExtractor
from .extractors.pptx_extractor import PPTXExtractor
from .extractors.image_extractor import StandaloneImageExtractor
from .extractors.ocr_extractor import LocalOCRExtractor, OCRConfig
from common.secrets import get_secret

logger = logging.getLogger("prism.requirement_engine.manual")

MIN_CONTENT_CHARS = 30

EXTRACTION_PROMPT = """You are a senior business analyst. A user identified a requirement \
in a business document and gave you a brief description as a SEMANTIC ANCHOR.

Use the description to locate the relevant section in the provided page content, \
then extract a fully-structured requirement JSON.

─────────────────────────────────────────────────
USER DESCRIPTION (ANCHOR):
{description}

DOCUMENT : {doc_name}
PAGE     : {page_no}
─────────────────────────────────────────────────
PAGE CONTENT:
{page_text}
─────────────────────────────────────────────────

Return ONLY a valid JSON object with EXACTLY the keys below. No markdown, no extra text.
If the page content does NOT contain any requirement matching the description,
return ONLY: {{"status": "no_requirements"}}

{{
  "title":                "Short title 5–8 words",
  "description":          "Full 1–3 sentence description of what the system must do",
  "requirement_type":     "Functional or Non-Functional",
  "category":             "Feature area e.g. Dashboard, Warranty, Security, API, etc.",
  "priority":             "High or Medium or Low",
  "user_story":           "As a <role>, I want <action> so that <benefit>",
  "acceptance_criteria":  ["Testable criterion 1", "Testable criterion 2"],
  "test_steps": [
    {{"step_num": 1, "action": "...", "expected_result": "...", "test_data": "..."}}
  ],
  "business_rules":  ["Business rule 1"],
  "dependencies":    [],
  "assumptions":     []
}}

Rules:
- Ground every field in the provided page content.
- test_steps must follow professional QA standards.
"""

class ManualExtractor:
    """Handles single-page requirement extraction using the project's core extractors."""

    def __init__(self):
        self.ocr = LocalOCRExtractor(OCRConfig())
        self.extractors = {
            FileType.PDF: PDFExtractor(ocr_extractor=self.ocr),
            FileType.SCANNED_PDF: PDFExtractor(ocr_extractor=self.ocr),
            FileType.DOCX: DOCXExtractor(),
            FileType.PPTX: PPTXExtractor(),
            FileType.IMAGE: StandaloneImageExtractor(ocr_extractor=self.ocr),
        }

    def extract_from_page(self, file_path: str, description: str, page_no: int) -> Dict[str, Any]:
        """Extract text from a specific page and call Groq to generate a requirement."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_type = FileRouter.classify(file_path)

        extractor = self.extractors.get(file_type)
        if not extractor:
            return {
                "status": "error",
                "message": f"Unsupported file type: {file_type.value}"
            }

        try:
            if file_type in [FileType.PDF, FileType.SCANNED_PDF]:
                doc = fitz.open(file_path)
                if page_no < 1 or page_no > len(doc):
                    doc.close()
                    raise ValueError(f"Page {page_no} out of range (1-{len(doc)})")

                page = doc[page_no - 1]
                text = page.get_text().strip()
                if len(text) < 100:
                    pix = page.get_pixmap(dpi=200)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr_res = self.ocr.extract_text_from_pil_image(img)
                    text = ocr_res.get("text", "")
                doc.close()

            elif file_type == FileType.PPTX:
                prs = Presentation(file_path)
                if page_no < 1 or page_no > len(prs.slides):
                    raise ValueError(f"Slide {page_no} out of range (1-{len(prs.slides)})")
                slide = prs.slides[page_no - 1]
                text = "\n".join([shape.text for shape in slide.shapes if hasattr(shape, "text")])

            elif file_type == FileType.DOCX:
                text = extractor.extract_text(file_path)

            elif file_type == FileType.IMAGE:
                text = extractor.extract_text(file_path)

            else:
                text = ""

        except Exception as e:
            logger.error("Page text requirement_engine failed: %s", e, exc_info=True)
            return {"status": "error", "message": f"Extraction failed: {str(e)}"}

        if len(text.strip()) < MIN_CONTENT_CHARS:
            return {
                "status": "no_requirements",
                "message": "Page has insufficient text content."
            }

        return self._call_groq(description, path.name, page_no, text)

    def _call_groq(self, description: str, doc_name: str, page_no: int, text: str) -> Dict[str, Any]:
        api_key = get_secret("GROQ_API_KEY")
        if not api_key:
            return {"status": "error", "message": "GROQ_API_KEY not found in AWS Secrets Manager or environment"}

        client = Groq(api_key=api_key)
        prompt = EXTRACTION_PROMPT.format(
            description=description,
            doc_name=doc_name,
            page_no=page_no,
            page_text=text[:6000]
        )

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            raw = response.choices[0].message.content.strip()

            if "```" in raw:
                raw = re.sub(r"```json|```", "", raw).strip()

            data = json.loads(raw)
            if data.get("status") == "no_requirements":
                return {"status": "no_requirements", "message": "No matching requirement found on this page."}

            return {"status": "success", "requirement": data}

        except Exception as e:
            return {"status": "error", "message": f"AI requirement_engine failed: {str(e)}"}
