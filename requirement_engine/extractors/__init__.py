"""
Extractors Package — Stage 2 Content Extraction

Provides format-specific text and image requirement_engine from documents.

Modules:
    pdf_extractor: PDF text + embedded image requirement_engine (PyMuPDF)
    docx_extractor: DOCX text + embedded image requirement_engine (python-docx)
    pptx_extractor: PPTX text + embedded image requirement_engine (python-pptx)
    image_extractor: Standalone image text requirement_engine
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
