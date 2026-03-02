"""
File Router — Stage 1 of the Extraction Pipeline

Classifies input files into processing categories based on file extension
and content analysis. Routes each file to the appropriate extractor.

Supported file types:
    - PDF (standard text-layer PDFs)
    - SCANNED_PDF (image-only PDFs without a text layer)
    - DOCX (Microsoft Word documents)
    - PPTX (Microsoft PowerPoint presentations)
    - IMAGE (standalone images: PNG, JPG, JPEG, SVG, GIF, WEBP, BMP)

Example:
    from extraction.file_router import FileRouter, FileType

    file_type = FileRouter.classify("requirements.pdf")
    # FileType.PDF

    file_type, message = FileRouter.route("flowchart.png")
    # (FileType.IMAGE, "Image Processor: flowchart.png (OCR + Vision)")
"""

from enum import Enum
from pathlib import Path
from typing import Tuple


class FileType(Enum):
    """Supported document types for the extraction pipeline."""
    PDF = "pdf"
    SCANNED_PDF = "scanned_pdf"
    DOCX = "docx"
    PPTX = "pptx"
    IMAGE = "image"
    UNKNOWN = "unknown"


class FileRouter:
    """
    Routes files to appropriate processing pipelines based on
    file extension and content analysis.
    """

    # Document types — processed for text + embedded image extraction
    PDF_EXTENSIONS = {".pdf"}
    DOCX_EXTENSIONS = {".docx", ".doc"}
    PPTX_EXTENSIONS = {".pptx", ".ppt"}

    # Image types — processed with OCR + Vision AI
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

    @classmethod
    def classify(cls, file_path: str) -> FileType:
        """
        Determine the processing type for a given file.

        For PDF files, performs content analysis to detect scanned PDFs
        (image-only, no text layer) vs standard text-based PDFs.

        Args:
            file_path: Path to the input file

        Returns:
            FileType enum value
        """
        ext = Path(file_path).suffix.lower()

        if ext in cls.PDF_EXTENSIONS:
            # Check if the PDF is scanned (no text layer)
            if cls._is_scanned_pdf(file_path):
                return FileType.SCANNED_PDF
            return FileType.PDF
        elif ext in cls.DOCX_EXTENSIONS:
            return FileType.DOCX
        elif ext in cls.PPTX_EXTENSIONS:
            return FileType.PPTX
        elif ext in cls.IMAGE_EXTENSIONS:
            return FileType.IMAGE
        else:
            return FileType.UNKNOWN

    @classmethod
    def route(cls, file_path: str) -> Tuple[FileType, str]:
        """
        Route a file and return a human-readable processing description.

        Args:
            file_path: Path to the input file

        Returns:
            Tuple of (FileType, description_message)
        """
        file_type = cls.classify(file_path)
        file_name = Path(file_path).name

        descriptions = {
            FileType.PDF: f"PDF Extractor: {file_name} (text + embedded images)",
            FileType.SCANNED_PDF: f"Scanned PDF Processor: {file_name} (OCR all pages)",
            FileType.DOCX: f"DOCX Extractor: {file_name} (paragraphs + embedded images)",
            FileType.PPTX: f"PPTX Extractor: {file_name} (slides + embedded images)",
            FileType.IMAGE: f"Image Processor: {file_name} (OCR + Vision analysis)",
            FileType.UNKNOWN: f"Unknown: {file_name} ({Path(file_path).suffix})",
        }

        return file_type, descriptions.get(file_type, f"Unknown: {file_name}")

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """Check if the file type is supported by the pipeline."""
        return cls.classify(file_path) != FileType.UNKNOWN

    @classmethod
    def get_supported_extensions(cls) -> dict:
        """Return all supported file extensions grouped by type."""
        return {
            "pdf": sorted(cls.PDF_EXTENSIONS),
            "docx": sorted(cls.DOCX_EXTENSIONS),
            "pptx": sorted(cls.PPTX_EXTENSIONS),
            "image": sorted(cls.IMAGE_EXTENSIONS),
        }

    @classmethod
    def _is_scanned_pdf(cls, file_path: str) -> bool:
        """
        Detect whether a PDF is scanned (image-only, no text layer).

        Opens the PDF and attempts text extraction. If the total extracted
        text is very short (< 100 characters), it's likely a scanned document
        that needs OCR processing.

        Args:
            file_path: Path to the PDF file

        Returns:
            True if the PDF appears to be scanned/image-only
        """
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            total_text = ""

            # Check first 3 pages (enough to determine if scanned)
            for page_num in range(min(3, len(doc))):
                page = doc[page_num]
                total_text += page.get_text()

            doc.close()

            # If very little text found, it's likely scanned
            return len(total_text.strip()) < 100

        except Exception:
            # If we can't open it, default to standard PDF processing
            return False
