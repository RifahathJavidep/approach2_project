"""
PPTX Extractor Module

Extracts text content and embedded images from PowerPoint presentations.

Uses:
    - python-pptx for slide text extraction and shape-based image extraction

Example:
    from extraction.extractors import PPTXExtractor

    extractor = PPTXExtractor()
    text = extractor.extract_text("presentation.pptx")
    images = extractor.extract_images("presentation.pptx")
"""

import base64
from typing import List, Dict, Any


class PPTXExtractor:
    """
    Extract text and embedded images from PowerPoint presentations.

    Text extraction goes through each slide and pulls text from all
    shapes (text boxes, titles, content placeholders). Each slide is
    labeled with its number for context.

    Image extraction finds all picture-type shapes across all slides.

    Note:
        Speaker notes are not included in text extraction.
        SmartArt and charts may not be fully captured.
    """

    def extract_text(self, file_path: str) -> str:
        """
        Extract all text content from a PowerPoint presentation.

        Goes through each slide and extracts text from all shapes
        that contain text. Each slide is labeled with its number
        for context.

        Args:
            file_path: Path to the PPTX file

        Returns:
            Text from all slides, with slide numbers as headers
        """
        try:
            from pptx import Presentation
            prs = Presentation(file_path)
            text_parts = []

            for slide_num, slide in enumerate(prs.slides, 1):
                slide_text = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text)

                if slide_text:
                    text_parts.append(f"\n--- Slide {slide_num} ---\n" + "\n".join(slide_text))

            text = "\n".join(text_parts)

            if text:
                print(f"  ✓ PPTX text extracted ({len(text)} chars, {len(prs.slides)} slides)")
            else:
                print(f"  ⚠ PPTX has no text content")

            return text

        except Exception as e:
            print(f"  ✗ Error extracting text from PPTX: {e}")
            return ""

    def extract_images(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a PowerPoint presentation.

        Goes through each slide and extracts images from picture-type
        shapes. Tracks which slide each image came from for context.

        Args:
            file_path: Path to the PPTX file

        Returns:
            List of image dictionaries with keys:
                - slide: Slide number (1-indexed)
                - index: Sequential image number
                - format: Image format (png, jpeg, etc.)
                - base64: Base64-encoded image data
                - bytes: Raw image bytes
                - source: Descriptive identifier
                - size_bytes: Size of the image in bytes
        """
        images = []

        try:
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE
            prs = Presentation(file_path)
            img_counter = 0

            for slide_num, slide in enumerate(prs.slides, 1):
                for shape in slide.shapes:
                    try:
                        if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                            continue

                        image = shape.image
                        image_bytes = image.blob
                        image_ext = image.ext

                        # Skip very small images (icons, bullets)
                        if len(image_bytes) < 1000:
                            continue

                        # Normalize format names
                        format_map = {"jpg": "jpeg", "jpe": "jpeg"}
                        img_format = format_map.get(image_ext.lower(), image_ext.lower())

                        img_counter += 1

                        images.append({
                            "slide": slide_num,
                            "index": img_counter,
                            "format": img_format,
                            "base64": base64.b64encode(image_bytes).decode("utf-8"),
                            "bytes": image_bytes,
                            "source": f"pptx_slide{slide_num}_img{img_counter}.{img_format}",
                            "size_bytes": len(image_bytes),
                        })

                    except Exception:
                        # Shape might not have an image property — skip
                        continue

        except Exception as e:
            print(f"   ✗ Error extracting images from PPTX: {e}")

        if images:
            print(f"  ✓ Extracted {len(images)} embedded images from PPTX")

        return images
