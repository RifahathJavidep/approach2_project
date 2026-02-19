# PaddleOCR Integration Guide

## New Workflow Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT FILES                                  │
│              (PDF / PPT / DOCX / Images)                            │
└─────────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
┌───────────────────────┐                 ┌───────────────────────────┐
│   DOCUMENT TEXT       │                 │   EMBEDDED IMAGES         │
│   EXTRACTION          │                 │   EXTRACTION              │
├───────────────────────┤                 ├───────────────────────────┤
│ PDF  → PyMuPDF        │                 │ PDF  → fitz.get_images()  │
│ PPT  → python-pptx    │                 │ PPT  → shape.image        │
│ DOCX → python-docx    │                 │ DOCX → doc.part.rels      │
└───────────────────────┘                 └───────────────────────────┘
        │                                               │
        ▼                                               ▼
┌───────────────────────┐                 ┌───────────────────────────┐
│   Document Text       │                 │   List of Embedded Images │
│   (native text layer) │                 │   (base64 encoded)        │
└───────────────────────┘                 └───────────────────────────┘
                                                        │
                                                        ▼
                                          ┌───────────────────────────┐
                                          │  STEP 1: LOCAL OCR        │
                                          │  (PaddleOCR)              │
                                          ├───────────────────────────┤
                                          │  For EACH embedded image: │
                                          │  → Run PaddleOCR locally  │
                                          │  → Extract text + conf.   │
                                          └───────────────────────────┘
                                                        │
                                                        ▼
                                          ┌───────────────────────────┐
                                          │  STEP 2: OCR VERIFICATION │
                                          │  (Vision LLM)             │
                                          ├───────────────────────────┤
                                          │  Send to Vision LLM:      │
                                          │  - Original image         │
                                          │  - PaddleOCR text         │
                                          │  → Verify/correct OCR     │
                                          └───────────────────────────┘
                                                        │
                                                        ▼
                                          ┌───────────────────────────┐
                                          │  STEP 3: CLASSIFY IMAGE   │
                                          │  (Vision LLM)             │
                                          ├───────────────────────────┤
                                          │  Is it a diagram/flowchart│
                                          │  or informational image?  │
                                          └───────────────────────────┘
                                                        │
                                    ┌───────────────────┴───────────────────┐
                                    ▼                                       ▼
                          ┌─────────────────────┐              ┌─────────────────────┐
                          │  WORKFLOW DIAGRAM   │              │  TEXT/INFO IMAGE    │
                          ├─────────────────────┤              ├─────────────────────┤
                          │  → Extract Graph    │              │  → Use verified     │
                          │    JSON structure   │              │    OCR text         │
                          │  → Convert to       │              │                     │
                          │    narrative        │              │                     │
                          └─────────────────────┘              └─────────────────────┘
                                    │                                       │
                                    └───────────────────┬───────────────────┘
                                                        ▼
┌───────────────────────┐                 ┌───────────────────────────┐
│   Document Text       │────────────────▶│  STEP 4: COMBINE ALL TEXT │
└───────────────────────┘                 ├───────────────────────────┤
                                          │  - Document text          │
                                          │  - Verified OCR text      │
                                          │  - Diagram narratives     │
                                          └───────────────────────────┘
                                                        │
                                                        ▼
                                          ┌───────────────────────────┐
                                          │  STEP 5: GENERATE BRD     │
                                          │  (LLM)                    │
                                          ├───────────────────────────┤
                                          │  Send combined text       │
                                          │  → Extract requirements   │
                                          │  → Generate test cases    │
                                          └───────────────────────────┘
```

### Key Point: Embedded Images Inside Documents

The workflow handles **TWO types of images**:

1. **Standalone Images** - Direct image files (PNG, JPG, etc.)
2. **Embedded Images** - Images inside PDF, DOCX, PPTX documents

Both types go through the same PaddleOCR → Vision Verification → Classification pipeline.

---

## PaddleOCR Installation

### Option 1: Full Installation (GPU Support)

```bash
# Install PaddlePaddle (CPU version)
pip install paddlepaddle

# OR for GPU support (CUDA 11.x)
pip install paddlepaddle-gpu

# Install PaddleOCR
pip install paddleocr
```

### Option 2: Lightweight Installation (CPU only)

```bash
pip install paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install paddleocr
```

### Required Dependencies

```bash
pip install opencv-python pillow numpy
```

### Add to requirements.txt

```
paddlepaddle>=2.5.0
paddleocr>=2.7.0
opencv-python>=4.8.0
pillow>=10.0.0
numpy>=1.24.0
```

---

## PaddleOCR Code Implementation

### Basic OCR Class

```python
from paddleocr import PaddleOCR
from PIL import Image
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple
import base64
import io


class LocalOCRExtractor:
    """
    Local OCR extraction using PaddleOCR.
    Extracts text from images without API calls.
    """

    def __init__(self, lang: str = 'en', use_gpu: bool = False):
        """
        Initialize PaddleOCR.

        Args:
            lang: Language code ('en', 'ch', 'japan', 'korean', etc.)
            use_gpu: Whether to use GPU acceleration
        """
        # Initialize PaddleOCR with settings
        # use_angle_cls=True enables text direction detection
        # show_log=False reduces console output
        self.ocr = PaddleOCR(
            use_angle_cls=True,
            lang=lang,
            use_gpu=use_gpu,
            show_log=False
        )
        print(f"PaddleOCR initialized (lang={lang}, gpu={use_gpu})")

    def extract_text_from_image(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from a single image using PaddleOCR.

        Args:
            image_path: Path to the image file

        Returns:
            Dictionary containing:
                - text: Full extracted text
                - lines: List of text lines with confidence scores
                - boxes: Bounding box coordinates for each text region
        """
        try:
            # Run OCR
            result = self.ocr.ocr(image_path, cls=True)

            if not result or not result[0]:
                return {
                    "text": "",
                    "lines": [],
                    "boxes": [],
                    "confidence": 0.0,
                    "success": True
                }

            lines = []
            boxes = []
            full_text_parts = []
            total_confidence = 0.0

            for line in result[0]:
                box = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = line[1][0]  # Extracted text
                confidence = line[1][1]  # Confidence score

                lines.append({
                    "text": text,
                    "confidence": confidence
                })
                boxes.append(box)
                full_text_parts.append(text)
                total_confidence += confidence

            avg_confidence = total_confidence / len(lines) if lines else 0.0

            return {
                "text": "\n".join(full_text_parts),
                "lines": lines,
                "boxes": boxes,
                "confidence": avg_confidence,
                "success": True
            }

        except Exception as e:
            return {
                "text": "",
                "lines": [],
                "boxes": [],
                "confidence": 0.0,
                "success": False,
                "error": str(e)
            }

    def extract_text_from_pil_image(self, pil_image: Image.Image) -> Dict[str, Any]:
        """
        Extract text from a PIL Image object.

        Args:
            pil_image: PIL Image object

        Returns:
            OCR result dictionary
        """
        # Convert PIL Image to numpy array
        img_array = np.array(pil_image)

        try:
            result = self.ocr.ocr(img_array, cls=True)

            if not result or not result[0]:
                return {
                    "text": "",
                    "lines": [],
                    "confidence": 0.0,
                    "success": True
                }

            lines = []
            full_text_parts = []
            total_confidence = 0.0

            for line in result[0]:
                text = line[1][0]
                confidence = line[1][1]

                lines.append({
                    "text": text,
                    "confidence": confidence
                })
                full_text_parts.append(text)
                total_confidence += confidence

            return {
                "text": "\n".join(full_text_parts),
                "lines": lines,
                "confidence": total_confidence / len(lines) if lines else 0.0,
                "success": True
            }

        except Exception as e:
            return {
                "text": "",
                "lines": [],
                "confidence": 0.0,
                "success": False,
                "error": str(e)
            }

    def extract_text_from_base64(self, base64_string: str) -> Dict[str, Any]:
        """
        Extract text from a base64 encoded image.

        Args:
            base64_string: Base64 encoded image string

        Returns:
            OCR result dictionary
        """
        # Decode base64 to PIL Image
        image_data = base64.b64decode(base64_string)
        pil_image = Image.open(io.BytesIO(image_data))

        return self.extract_text_from_pil_image(pil_image)

    def batch_extract(self, image_paths: List[str]) -> List[Dict[str, Any]]:
        """
        Extract text from multiple images.

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
```

---

## OCR Verification with Vision Model

```python
class OCRVerifier:
    """
    Verifies and corrects OCR output using Vision LLM.
    """

    def __init__(self, openai_client):
        """
        Initialize with OpenAI client for Vision API.

        Args:
            openai_client: OpenAI client instance
        """
        self.client = openai_client
        self.model = "gpt-4o"  # Vision-capable model

    def verify_ocr(self, image_base64: str, ocr_text: str) -> Dict[str, Any]:
        """
        Verify OCR text by sending both image and OCR result to Vision LLM.

        Args:
            image_base64: Base64 encoded image
            ocr_text: Text extracted by PaddleOCR

        Returns:
            Dictionary with verified/corrected text
        """
        prompt = f"""I have extracted the following text from this image using OCR:

--- OCR EXTRACTED TEXT ---
{ocr_text}
--- END OCR TEXT ---

Please analyze the image and:
1. Verify if the OCR text is correct
2. Correct any OCR errors (misread characters, missing text, wrong order)
3. Add any text that was missed by OCR
4. Fix formatting issues

Return the corrected text. If the OCR was perfect, return the same text.
Only return the corrected text, no explanations."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=4000,
                temperature=0.1
            )

            verified_text = response.choices[0].message.content.strip()

            return {
                "original_ocr": ocr_text,
                "verified_text": verified_text,
                "was_corrected": ocr_text.strip() != verified_text.strip(),
                "success": True
            }

        except Exception as e:
            return {
                "original_ocr": ocr_text,
                "verified_text": ocr_text,  # Fall back to original
                "was_corrected": False,
                "success": False,
                "error": str(e)
            }
```

---

## Updated Workflow Integration

```python
class EnhancedDocumentProcessor:
    """
    Document processor with local OCR and Vision verification.
    """

    def __init__(self, openai_api_key: str = None, use_gpu: bool = False):
        """
        Initialize processor with PaddleOCR and optional Vision verification.
        """
        # Local OCR
        self.ocr_extractor = LocalOCRExtractor(lang='en', use_gpu=use_gpu)

        # Vision verification (optional)
        if openai_api_key:
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=openai_api_key)
            self.ocr_verifier = OCRVerifier(self.openai_client)
        else:
            self.openai_client = None
            self.ocr_verifier = None

        print(f"EnhancedDocumentProcessor initialized")
        print(f"  - Local OCR: PaddleOCR")
        print(f"  - Vision Verification: {'Enabled' if openai_api_key else 'Disabled'}")

    def process_image(self, image_path: str, verify_with_vision: bool = True) -> Dict[str, Any]:
        """
        Process a single image: OCR + optional verification.

        Args:
            image_path: Path to image file
            verify_with_vision: Whether to verify OCR with Vision LLM

        Returns:
            Processed result with extracted text
        """
        print(f"\nProcessing image: {image_path}")

        # Step 1: Local OCR with PaddleOCR
        print("  Step 1: Running PaddleOCR...")
        ocr_result = self.ocr_extractor.extract_text_from_image(image_path)

        if not ocr_result["success"]:
            return {
                "source": image_path,
                "text": "",
                "method": "ocr_failed",
                "error": ocr_result.get("error")
            }

        ocr_text = ocr_result["text"]
        ocr_confidence = ocr_result["confidence"]
        print(f"  OCR extracted {len(ocr_text)} chars (confidence: {ocr_confidence:.2%})")

        # Step 2: Verify with Vision LLM (if enabled and confidence is low)
        if verify_with_vision and self.ocr_verifier:
            # Verify if confidence is below threshold or always verify
            should_verify = ocr_confidence < 0.9 or True  # Always verify for now

            if should_verify:
                print("  Step 2: Verifying with Vision LLM...")

                # Read and encode image
                with open(image_path, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode()

                verification = self.ocr_verifier.verify_ocr(image_base64, ocr_text)

                if verification["success"]:
                    final_text = verification["verified_text"]
                    was_corrected = verification["was_corrected"]
                    print(f"  Verification complete. Corrected: {was_corrected}")
                else:
                    final_text = ocr_text
                    print(f"  Verification failed, using OCR text")
            else:
                final_text = ocr_text
                print(f"  High confidence ({ocr_confidence:.2%}), skipping verification")
        else:
            final_text = ocr_text

        return {
            "source": image_path,
            "text": final_text,
            "ocr_text": ocr_text,
            "ocr_confidence": ocr_confidence,
            "verified": verify_with_vision and self.ocr_verifier is not None,
            "method": "paddleocr_verified" if verify_with_vision else "paddleocr"
        }

    def process_scanned_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Process a scanned PDF (no text layer) using OCR.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Combined extracted text from all pages
        """
        import fitz  # PyMuPDF

        print(f"\nProcessing scanned PDF: {pdf_path}")

        pdf_doc = fitz.open(pdf_path)
        total_pages = len(pdf_doc)
        print(f"  Pages: {total_pages}")

        all_text = []

        for page_num in range(total_pages):
            print(f"  Processing page {page_num + 1}/{total_pages}...")

            page = pdf_doc[page_num]

            # Render page to image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better OCR
            img_data = pix.tobytes("png")

            # Convert to PIL Image
            pil_image = Image.open(io.BytesIO(img_data))

            # OCR the page
            ocr_result = self.ocr_extractor.extract_text_from_pil_image(pil_image)

            if ocr_result["success"] and ocr_result["text"]:
                all_text.append(f"--- Page {page_num + 1} ---\n{ocr_result['text']}")

        pdf_doc.close()

        return {
            "source": pdf_path,
            "text": "\n\n".join(all_text),
            "page_count": total_pages,
            "method": "paddleocr_pdf"
        }
```

---

## Configuration Options

### Environment Variables

```bash
# .env file
OPENAI_API_KEY=your_openai_key_here
USE_GPU=false
OCR_LANGUAGE=en
VERIFY_OCR=true
OCR_CONFIDENCE_THRESHOLD=0.85
```

### Config Class

```python
class OCRConfig:
    """Configuration for OCR processing."""

    def __init__(self):
        self.use_gpu = os.getenv("USE_GPU", "false").lower() == "true"
        self.language = os.getenv("OCR_LANGUAGE", "en")
        self.verify_with_vision = os.getenv("VERIFY_OCR", "true").lower() == "true"
        self.confidence_threshold = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.85"))
```

---

## Supported Languages (PaddleOCR)

| Code         | Language         |
| ------------ | ---------------- |
| `en`       | English          |
| `ch`       | Chinese          |
| `japan`    | Japanese         |
| `korean`   | Korean           |
| `french`   | French           |
| `german`   | German           |
| `arabic`   | Arabic           |
| `cyrillic` | Russian/Cyrillic |

---

## Performance Considerations

1. **First Run**: PaddleOCR downloads models (~150MB) on first use
2. **GPU Acceleration**: 5-10x faster with CUDA-enabled GPU
3. **Memory**: ~1-2GB RAM for CPU, more for GPU
4. **Batch Processing**: Process multiple images together for efficiency

---

## Error Handling

```python
def safe_ocr_extract(image_path: str, ocr_extractor: LocalOCRExtractor) -> str:
    """
    Safely extract text with fallback.
    """
    try:
        result = ocr_extractor.extract_text_from_image(image_path)
        if result["success"]:
            return result["text"]
        else:
            print(f"OCR failed: {result.get('error')}")
            return ""
    except Exception as e:
        print(f"OCR exception: {e}")
        return ""
```

---

## Processing Embedded Images from Documents

This is the **critical section** for handling images that are embedded inside PDF, DOCX, and PPTX files.

### Complete Embedded Image Processing Class

```python
class EmbeddedImageProcessor:
    """
    Extracts and processes embedded images from documents using PaddleOCR.
    Handles PDF, DOCX, and PPTX files.
    """

    def __init__(self, openai_api_key: str = None, use_gpu: bool = False):
        """
        Initialize with PaddleOCR and optional Vision verification.
        """
        self.ocr_extractor = LocalOCRExtractor(lang='en', use_gpu=use_gpu)

        if openai_api_key:
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=openai_api_key)
            self.ocr_verifier = OCRVerifier(self.openai_client)
        else:
            self.openai_client = None
            self.ocr_verifier = None

    # =========================================================================
    # EMBEDDED IMAGE EXTRACTION (from PDF, DOCX, PPTX)
    # =========================================================================

    def extract_images_from_pdf(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a PDF file.
        """
        import fitz  # PyMuPDF
        import base64

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

                        if base_image:
                            image_bytes = base_image["image"]
                            image_ext = base_image["ext"]

                            # Skip very small images (icons/bullets)
                            if len(image_bytes) < 1000:
                                continue

                            images.append({
                                "page": page_num + 1,
                                "index": img_index + 1,
                                "format": image_ext,
                                "base64": base64.b64encode(image_bytes).decode('utf-8'),
                                "bytes": image_bytes,  # Keep raw bytes for PaddleOCR
                                "source": f"pdf_page{page_num + 1}_img{img_index + 1}.{image_ext}",
                                "size_bytes": len(image_bytes)
                            })
                    except Exception as e:
                        print(f"   Warning: Could not extract image: {e}")
                        continue

            pdf_doc.close()
        except Exception as e:
            print(f"   Error extracting images from PDF: {e}")

        return images

    def extract_images_from_docx(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a DOCX file.
        """
        from docx import Document
        import base64

        images = []

        try:
            doc = Document(file_path)
            img_counter = 0

            for rel in doc.part.rels.values():
                if "image" in rel.reltype:
                    try:
                        image_part = rel.target_part
                        image_bytes = image_part.blob

                        # Skip very small images
                        if len(image_bytes) < 1000:
                            continue

                        content_type = image_part.content_type
                        image_ext = content_type.split('/')[-1]

                        # Skip unsupported formats (EMF, WMF)
                        if image_ext.lower() in ['x-emf', 'x-wmf', 'emf', 'wmf']:
                            continue

                        img_counter += 1

                        images.append({
                            "index": img_counter,
                            "format": image_ext,
                            "base64": base64.b64encode(image_bytes).decode('utf-8'),
                            "bytes": image_bytes,
                            "source": f"docx_img{img_counter}.{image_ext}",
                            "size_bytes": len(image_bytes)
                        })
                    except Exception as e:
                        print(f"   Warning: Could not extract image: {e}")
                        continue
        except Exception as e:
            print(f"   Error extracting images from DOCX: {e}")

        return images

    def extract_images_from_pptx(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Extract all embedded images from a PPTX file.
        """
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        import base64

        images = []

        try:
            prs = Presentation(file_path)
            img_counter = 0

            for slide_num, slide in enumerate(prs.slides, 1):
                for shape in slide.shapes:
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        try:
                            image = shape.image
                            image_bytes = image.blob
                            image_ext = image.ext

                            # Skip very small images
                            if len(image_bytes) < 1000:
                                continue

                            img_counter += 1

                            images.append({
                                "slide": slide_num,
                                "index": img_counter,
                                "format": image_ext,
                                "base64": base64.b64encode(image_bytes).decode('utf-8'),
                                "bytes": image_bytes,
                                "source": f"pptx_slide{slide_num}_img{img_counter}.{image_ext}",
                                "size_bytes": len(image_bytes)
                            })
                        except Exception as e:
                            continue
        except Exception as e:
            print(f"   Error extracting images from PPTX: {e}")

        return images

    # =========================================================================
    # OCR PROCESSING FOR EMBEDDED IMAGES
    # =========================================================================

    def process_embedded_image(self, image_data: Dict[str, Any], verify: bool = True) -> Dict[str, Any]:
        """
        Process a single embedded image with PaddleOCR + optional Vision verification.

        Args:
            image_data: Dictionary with 'bytes' or 'base64' key containing image data
            verify: Whether to verify OCR with Vision LLM

        Returns:
            Processed result with OCR text
        """
        source = image_data.get('source', 'unknown')
        print(f"\n   Processing embedded image: {source}")

        # Step 1: Run PaddleOCR on the image
        print(f"      Step 1: Running PaddleOCR...")

        if 'bytes' in image_data:
            # Convert bytes to PIL Image
            pil_image = Image.open(io.BytesIO(image_data['bytes']))
            ocr_result = self.ocr_extractor.extract_text_from_pil_image(pil_image)
        elif 'base64' in image_data:
            ocr_result = self.ocr_extractor.extract_text_from_base64(image_data['base64'])
        else:
            return {
                "source": source,
                "text": "",
                "error": "No image data provided"
            }

        if not ocr_result["success"]:
            return {
                "source": source,
                "text": "",
                "error": ocr_result.get("error", "OCR failed")
            }

        ocr_text = ocr_result["text"]
        ocr_confidence = ocr_result["confidence"]
        print(f"      OCR extracted {len(ocr_text)} chars (confidence: {ocr_confidence:.2%})")

        # Step 2: Verify with Vision LLM (if enabled)
        if verify and self.ocr_verifier and ocr_text:
            print(f"      Step 2: Verifying with Vision LLM...")

            image_base64 = image_data.get('base64')
            if not image_base64 and 'bytes' in image_data:
                image_base64 = base64.b64encode(image_data['bytes']).decode('utf-8')

            verification = self.ocr_verifier.verify_ocr(image_base64, ocr_text)

            if verification["success"]:
                final_text = verification["verified_text"]
                was_corrected = verification["was_corrected"]
                print(f"      Verification complete. Corrected: {was_corrected}")
            else:
                final_text = ocr_text
                print(f"      Verification failed, using OCR text")
        else:
            final_text = ocr_text

        return {
            "source": source,
            "text": final_text,
            "ocr_text": ocr_text,
            "ocr_confidence": ocr_confidence,
            "verified": verify and self.ocr_verifier is not None,
            "has_text": bool(final_text.strip())
        }

    # =========================================================================
    # COMPLETE DOCUMENT PROCESSING
    # =========================================================================

    def process_document_with_embedded_images(
        self,
        file_path: str,
        verify_ocr: bool = True
    ) -> Dict[str, Any]:
        """
        Complete document processing including embedded image OCR.

        This is the MAIN method that handles:
        1. Extract text from document
        2. Extract embedded images
        3. OCR each embedded image with PaddleOCR
        4. Verify OCR with Vision LLM
        5. Combine all text

        Args:
            file_path: Path to PDF, DOCX, or PPTX file
            verify_ocr: Whether to verify OCR with Vision LLM

        Returns:
            Combined content dictionary
        """
        from pathlib import Path

        file_ext = Path(file_path).suffix.lower()
        file_name = Path(file_path).name

        print(f"\n{'='*60}")
        print(f"PROCESSING DOCUMENT: {file_name}")
        print(f"{'='*60}\n")

        # STEP 1: Extract text content from document
        print(f"Step 1: Extracting text from {file_ext}...")

        if file_ext == '.pdf':
            document_text = self._extract_text_from_pdf(file_path)
            embedded_images = self.extract_images_from_pdf(file_path)
        elif file_ext == '.docx':
            document_text = self._extract_text_from_docx(file_path)
            embedded_images = self.extract_images_from_docx(file_path)
        elif file_ext == '.pptx':
            document_text = self._extract_text_from_pptx(file_path)
            embedded_images = self.extract_images_from_pptx(file_path)
        else:
            raise ValueError(f"Unsupported format: {file_ext}")

        print(f"   Document text: {len(document_text)} characters")
        print(f"   Embedded images: {len(embedded_images)} found")

        # STEP 2: Process each embedded image with PaddleOCR
        image_texts = []

        if embedded_images:
            print(f"\nStep 2: Processing {len(embedded_images)} embedded images with PaddleOCR...")

            for idx, img in enumerate(embedded_images, 1):
                print(f"\n   [{idx}/{len(embedded_images)}] {img['source']}")

                result = self.process_embedded_image(img, verify=verify_ocr)

                if result.get('has_text'):
                    image_texts.append({
                        "source": result['source'],
                        "text": result['text'],
                        "confidence": result.get('ocr_confidence', 0)
                    })
                    print(f"      ✓ Extracted text from image")
                else:
                    print(f"      - No text found (may be a diagram)")

        # STEP 3: Combine all text
        print(f"\nStep 3: Combining all extracted text...")

        combined_parts = []

        # Add document text
        combined_parts.append("=== DOCUMENT TEXT CONTENT ===\n")
        combined_parts.append(document_text)
        combined_parts.append("\n\n")

        # Add embedded image text
        if image_texts:
            combined_parts.append("=== TEXT FROM EMBEDDED IMAGES ===\n\n")
            for img_text in image_texts:
                combined_parts.append(f"--- IMAGE: {img_text['source']} ---\n")
                combined_parts.append(img_text['text'])
                combined_parts.append("\n\n")

        combined_text = "".join(combined_parts)

        print(f"   Combined text: {len(combined_text)} characters")

        return {
            "file_path": file_path,
            "document_text": document_text,
            "embedded_images_count": len(embedded_images),
            "images_with_text": len(image_texts),
            "image_texts": image_texts,
            "combined_text": combined_text
        }

    # Helper methods for text extraction
    def _extract_text_from_pdf(self, file_path: str) -> str:
        import fitz
        text_parts = []
        pdf_doc = fitz.open(file_path)
        for page in pdf_doc:
            text_parts.append(page.get_text())
        pdf_doc.close()
        return "\n".join(text_parts)

    def _extract_text_from_docx(self, file_path: str) -> str:
        from docx import Document
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])

    def _extract_text_from_pptx(self, file_path: str) -> str:
        from pptx import Presentation
        text_parts = []
        prs = Presentation(file_path)
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text_parts.append(shape.text)
        return "\n".join(text_parts)
```

### Usage Example

```python
# Initialize processor
processor = EmbeddedImageProcessor(
    openai_api_key="your-key-here",  # For OCR verification
    use_gpu=False                     # Set True if CUDA available
)

# Process a PDF with embedded images
result = processor.process_document_with_embedded_images(
    file_path="requirements.pdf",
    verify_ocr=True  # Verify OCR with Vision LLM
)

# Access results
print(f"Document text: {len(result['document_text'])} chars")
print(f"Found {result['embedded_images_count']} embedded images")
print(f"Extracted text from {result['images_with_text']} images")
print(f"Combined text ready for BRD generation: {len(result['combined_text'])} chars")

# Use combined_text for requirement extraction
combined_text = result['combined_text']
```

### Processing Flow for Embedded Images

```
PDF/DOCX/PPTX Document
         │
         ├──────────────────────────────────────┐
         │                                      │
         ▼                                      ▼
   Extract Text                          Extract Embedded Images
   (PyMuPDF/python-docx/pptx)           (get_images/rels/shapes)
         │                                      │
         │                                      ▼
         │                              For EACH embedded image:
         │                                      │
         │                              ┌───────┴───────┐
         │                              ▼               │
         │                        PaddleOCR            │
         │                        (local)              │
         │                              │               │
         │                              ▼               │
         │                        Vision LLM           │
         │                        (verify OCR)         │
         │                              │               │
         │                              ▼               │
         │                        Verified Text ◄──────┘
         │                              │
         ▼                              ▼
   Document Text  ──────────────► COMBINE ALL TEXT
                                        │
                                        ▼
                                  Send to LLM
                                  (Generate BRD)
```

---

## Integration with Existing Code

To integrate with your existing `Test_case_generator.py`:

1. Add `LocalOCRExtractor` and `EmbeddedImageProcessor` to a new `ocr_extractor.py` file
2. Modify `RequirementExtractor` to use PaddleOCR for embedded images
3. Update `process_document_with_images()` to use the new OCR pipeline
4. Flow: Extract Images → PaddleOCR → Verify → Classify (diagram/text) → Combine → BRD

### Key Changes to Test_case_generator.py

```python
# In RequirementExtractor.__init__()
from ocr_extractor import LocalOCRExtractor, OCRVerifier

def __init__(self, groq_api_key: str, openai_api_key: str = None):
    self.client = Groq(api_key=groq_api_key)
    self.model = "llama-3.1-8b-instant"

    # Add PaddleOCR
    self.ocr_extractor = LocalOCRExtractor(lang='en', use_gpu=False)

    # Vision for verification and diagram extraction
    if openai_api_key:
        self.diagram_extractor = DiagramExtractor(openai_api_key)
        self.ocr_verifier = OCRVerifier(OpenAI(api_key=openai_api_key))
    else:
        self.diagram_extractor = None
        self.ocr_verifier = None
```

See the main code changes needed in `Test_case_generator.py` in the next section.
