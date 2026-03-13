"""
PDF Extractor Module

Extracts text content and embedded images from PDF documents.
Supports both standard text-layer PDFs and scanned PDFs with OCR fallback.

Uses:
    - pymupdf4llm for high-quality markdown text extraction
    - PyMuPDF (fitz) for embedded image extraction and OCR fallback

Example:
    from extraction.extractors import PDFExtractor

    extractor = PDFExtractor()
    text = extractor.extract_text("document.pdf")
    images = extractor.extract_images("document.pdf")
"""

import base64
import io
from pathlib import Path
from typing import List, Dict, Any, Optional

from PIL import Image


class PDFExtractor:
    """
    Extract text and embedded images from PDF documents.

    Provides two extraction strategies:
    1. Standard: Uses pymupdf4llm for text-layer PDFs (fast, accurate)
    2. OCR fallback: Renders pages as images and uses PaddleOCR for
       scanned/image-only PDFs

    Attributes:
        ocr_extractor: Optional LocalOCRExtractor for scanned PDF fallback
    """

    def __init__(self, ocr_extractor=None):
        """
        Initialize the PDF extractor.

        Args:
            ocr_extractor: Optional LocalOCRExtractor instance for OCR fallback.
                           If None, scanned PDFs will return empty text.
        """
        self.ocr_extractor = ocr_extractor

    def extract_text(self, file_path: str) -> str:
        """
        Extract text from a PDF file.

        First attempts high-quality extraction via pymupdf4llm (preserves
        formatting as markdown). If that returns minimal text (< 100 chars),
        falls back to OCR via PaddleOCR.

        Args:
            file_path: Path to the PDF file

        Returns:
            Extracted text content (may be markdown-formatted)
        """
        # Strategy 1: pymupdf4llm for text-layer PDFs
        try:
            import pymupdf4llm
            text = pymupdf4llm.to_markdown(file_path)
            if text and len(text.strip()) > 100:
                print(f"  ✓ PDF text extracted via pymupdf4llm ({len(text)} chars)")
                return text
        except Exception as e:
            print(f"  ⚠ pymupdf4llm failed: {e}")

        # Strategy 2: OCR fallback for scanned PDFs
        return self._extract_text_with_ocr(file_path)

    def extract_images(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a PDF file.

        Uses PyMuPDF to find and extract images from each page.
        Small images (< 1KB, likely icons or bullets) are filtered out.

        Args:
            file_path: Path to the PDF file

        Returns:
            List of image dictionaries with keys:
                - page: Page number (1-indexed)
                - index: Image index on that page
                - format: Image format (png, jpeg, etc.)
                - base64: Base64-encoded image data
                - bytes: Raw image bytes (for PaddleOCR)
                - source: Descriptive identifier
                - size_bytes: Size of the image in bytes
        """
        import fitz  # PyMuPDF

        images = []

        try:
            pdf_doc = fitz.open(file_path)

            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                image_list = page.get_images(full=True)

                for img_index, img in enumerate(image_list):
                    try:
                        xref = img[0]
                        base_image = pdf_doc.extract_image(xref)

                        if not base_image:
                            continue

                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        # Skip very small images (icons, bullets)
                        if len(image_bytes) < 1000:
                            continue

                        # Normalize format names
                        format_map = {"jpg": "jpeg", "jpe": "jpeg", "jp2": "jpeg"}
                        img_format = format_map.get(image_ext.lower(), image_ext.lower())

                        images.append({
                            "page": page_num + 1,
                            "index": img_index + 1,
                            "format": img_format,
                            "base64": base64.b64encode(image_bytes).decode("utf-8"),
                            "bytes": image_bytes,
                            "source": f"pdf_page{page_num + 1}_img{img_index + 1}.{img_format}",
                            "size_bytes": len(image_bytes),
                        })

                    except Exception as e:
                        print(f"   ⚠ Could not extract image {img_index + 1} from page {page_num + 1}: {e}")
                        continue

            pdf_doc.close()

        except Exception as e:
            print(f"   ✗ Error extracting images from PDF: {e}")

        if images:
            print(f"  ✓ Extracted {len(images)} embedded images from PDF")

        return images

    def _extract_text_with_ocr(self, file_path: str) -> str:
        """
        Extract text from a scanned PDF using PaddleOCR.

        Renders each page as a 200-DPI image and runs OCR.

        Args:
            file_path: Path to the scanned PDF

        Returns:
            Combined OCR text from all pages
        """
        if not self.ocr_extractor:
            print("  ⚠ No OCR extractor available — cannot process scanned PDF")
            return ""

        print("  ⚠ Standard extraction returned minimal text — falling back to OCR...")

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            all_text = []

            for page_num in range(len(doc)):
                page = doc[page_num]
                # Render at 200 DPI for good OCR quality
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))

                ocr_result = self.ocr_extractor.extract_text_from_pil_image(img)

                if ocr_result["success"] and ocr_result["text"].strip():
                    all_text.append(f"--- Page {page_num + 1} ---\n{ocr_result['text']}")
                    print(f"  ✓ Page {page_num + 1}: {len(ocr_result['text'])} chars via OCR")
                else:
                    print(f"  ⚠ Page {page_num + 1}: No text detected")

            doc.close()

            if all_text:
                combined = "\n\n".join(all_text)
                print(f"  ✓ OCR complete: {len(combined)} total chars from {len(all_text)} pages")
                return combined

        except Exception as e:
            print(f"  ✗ OCR failed: {e}")

        return ""
