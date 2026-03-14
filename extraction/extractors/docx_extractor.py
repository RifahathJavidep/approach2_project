"""
DOCX Extractor Module

Extracts text content and embedded images from Microsoft Word documents.

Uses:
    - python-docx for paragraph text and relationship-based image extraction

Example:
    from extraction.extractors import DOCXExtractor

    extractor = DOCXExtractor()
    text = extractor.extract_text("document.docx")
    images = extractor.extract_images("document.docx")
"""

import base64
from typing import List, Dict, Any

class DOCXExtractor:
    """
    Extract text and embedded images from Word documents.

    Text extraction reads all paragraphs and joins them with newlines.
    Image extraction iterates through document relationships to find
    embedded image parts.

    Note:
        Tables, text boxes, headers/footers, and complex formatted
        regions may not be fully captured by paragraph extraction.
        Embedded images in EMF/WMF format are skipped (not supported
        by Vision APIs).
    """

    def extract_text(self, file_path: str) -> str:
        """
        Extract all text content from a Word document.

        Reads all paragraphs and joins them with newlines.
        Preserves the logical reading order of the document.

        Args:
            file_path: Path to the DOCX file

        Returns:
            Concatenated text from all paragraphs
        """
        try:
            from docx import Document
            doc = Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])

            if text:
                print(f"  ✓ DOCX text extracted ({len(text)} chars, {len(doc.paragraphs)} paragraphs)")
            else:
                print(f"  ⚠ DOCX has no paragraph text")

            return text

        except Exception as e:
            print(f"  ✗ Error extracting text from DOCX: {e}")
            return ""

    def extract_images(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a Word document.

        Iterates through the document's relationships to find image
        parts. Filters out very small images (< 1KB) and unsupported
        formats (EMF, WMF).

        Args:
            file_path: Path to the DOCX file

        Returns:
            List of image dictionaries with keys:
                - rel_id: Relationship ID in the document
                - index: Sequential image number
                - format: Image format (png, jpeg, etc.)
                - base64: Base64-encoded image data
                - bytes: Raw image bytes
                - source: Descriptive identifier
                - size_bytes: Size of the image in bytes
        """
        images = []
        try:
            from docx import Document
            doc = Document(file_path)
            img_counter = 0

            for rel in doc.part.rels.values():
                if "image" not in rel.reltype:
                    continue

                try:
                    image_part = rel.target_part
                    image_bytes = image_part.blob

                    # Skip very small images (icons, bullets)
                    if len(image_bytes) < 1000:
                        continue

                    # Get format from content type
                    content_type = image_part.content_type
                    image_ext = content_type.split("/")[-1]

                    # Normalize format names
                    format_map = {
                        "jpg": "jpeg",
                        "jpe": "jpeg",
                        "x-png": "png",
                    }
                    img_format = format_map.get(image_ext.lower(), image_ext.lower())

                    # Skip unsupported Windows Metafile formats
                    if img_format in {"x-emf", "x-wmf", "emf", "wmf"}:
                        continue

                    img_counter += 1

                    images.append({
                        "rel_id": rel.rId,
                        "index": img_counter,
                        "format": img_format,
                        "base64": base64.b64encode(image_bytes).decode("utf-8"),
                        "bytes": image_bytes,
                        "source": f"docx_img{img_counter}.{img_format}",
                        "size_bytes": len(image_bytes),
                    })

                except Exception as e:
                    print(f"   ⚠ Could not extract image {rel.rId}: {e}")
                    continue

        except Exception as e:
            print(f"   ✗ Error extracting images from DOCX: {e}")

        if images:
            print(f"  ✓ Extracted {len(images)} embedded images from DOCX")

        return images
