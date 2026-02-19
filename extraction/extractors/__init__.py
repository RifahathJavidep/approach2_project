"""
Extractors Package — Stage 2 Content Extraction

Provides format-specific text and image extraction from documents.

Modules:
    pdf_extractor: PDF text + embedded image extraction (PyMuPDF)
    docx_extractor: DOCX text + embedded image extraction (python-docx)
    pptx_extractor: PPTX text + embedded image extraction (python-pptx)
    image_extractor: Standalone image text extraction
    ocr_extractor: PaddleOCR wrapper for local OCR
"""

from .pdf_extractor import PDFExtractor
from .docx_extractor import DOCXExtractor
from .pptx_extractor import PPTXExtractor
from .image_extractor import StandaloneImageExtractor
from .ocr_extractor import LocalOCRExtractor, OCRConfig

__all__ = [
    "PDFExtractor",
    "DOCXExtractor",
    "PPTXExtractor",
    "StandaloneImageExtractor",
    "LocalOCRExtractor",
    "OCRConfig",
]
