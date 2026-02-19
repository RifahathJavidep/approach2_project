"""
Extraction Pipeline — Master Orchestrator

Ties together all 3 stages of the extraction pipeline:
    Stage 1: File Classification (FileRouter)
    Stage 2: Content Extraction (PDF/DOCX/PPTX/Image + OCR + Image Processing)
    Stage 3: Requirement Generation (DSPy TrainedExtractor + Postprocessing)

This is the main entry point for both:
    - FastAPI/Celery flow (extract_from_files)
    - CLI flow (extract_requirements)

Example:
    from extraction import ExtractionPipeline

    pipeline = ExtractionPipeline(config=config)
    result = pipeline.run(file_paths=["doc.pdf", "pres.pptx"], project_name="my_project")
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Callable

import dspy
from dotenv import load_dotenv

from .file_router import FileRouter, FileType
from .extractors.pdf_extractor import PDFExtractor
from .extractors.docx_extractor import DOCXExtractor
from .extractors.pptx_extractor import PPTXExtractor
from .extractors.image_extractor import StandaloneImageExtractor
from .extractors.ocr_extractor import LocalOCRExtractor, OCRConfig
from .processors.vision_verifier import OCRVerifier
from .processors.image_classifier import ImageClassifier
from .processors.diagram_analyzer import DiagramAnalyzer
from .generators.trained_extractor import TrainedExtractor
from .generators.training import train_extractor
from .generators.postprocessing import deduplicate_requirements, consolidate_requirements
from .utils import chunk_document

# Load environment
load_dotenv()

# Global LM instance to avoid re-configuring in async tasks
_global_lm = None


def _get_lm():
    """Get or create the global DSPy language model."""
    global _global_lm
    if _global_lm is None:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY not found in .env")
        _global_lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key, max_tokens=4096)
    return _global_lm


class ExtractionPipeline:
    """
    Master orchestrator for the requirement extraction pipeline.

    Coordinates all 3 stages:
        1. FileRouter classifies each input file
        2. Format-specific extractors pull text + embedded images
        3. Image processing pipeline (OCR → Verify → Classify → Analyze)
        4. DSPy TrainedExtractor generates structured requirements
        5. Postprocessing deduplicates and consolidates

    Attributes:
        config: Multi-project configuration dictionary
        ocr_extractor: PaddleOCR instance (lazy-loaded)
        ocr_verifier: Vision LLM OCR verifier
        image_classifier: Vision LLM image classifier
        diagram_analyzer: Vision LLM diagram analyzer
        extractor: Trained DSPy requirement extractor
    """

    def __init__(self, config: Dict = None, model_state: Dict = None):
        """
        Initialize the extraction pipeline.

        Args:
            config: Multi-project config dict (from config.json)
            model_state: Pre-trained model state to skip training
        """
        self.config = config or {}

        # Stage 2: Initialize extractors
        self._ocr_extractor = None  # Lazy-loaded (PaddleOCR is heavy)
        self._ocr_config = OCRConfig.from_env()

        # Image processing pipeline (uses Groq Llama 3.2 Vision — same API key as DSPy)
        groq_key = os.getenv("GROQ_API_KEY")
        self.ocr_verifier = OCRVerifier(groq_api_key=groq_key)
        self.image_classifier = ImageClassifier(groq_api_key=groq_key)
        self.diagram_analyzer = DiagramAnalyzer(groq_api_key=groq_key)

        # Format-specific extractors (initialized with OCR when needed)
        self._pdf_extractor = None
        self._docx_extractor = DOCXExtractor()
        self._pptx_extractor = PPTXExtractor()
        self._image_extractor = None

        # Stage 3: Setup DSPy and get trained extractor
        self.extractor = self._setup_dspy(model_state=model_state)

    @property
    def ocr_extractor(self) -> LocalOCRExtractor:
        """Lazy-load PaddleOCR (downloads models on first use)."""
        if self._ocr_extractor is None:
            self._ocr_extractor = LocalOCRExtractor(config=self._ocr_config)
        return self._ocr_extractor

    @property
    def pdf_extractor(self) -> PDFExtractor:
        """PDF extractor with OCR fallback."""
        if self._pdf_extractor is None:
            self._pdf_extractor = PDFExtractor(ocr_extractor=self.ocr_extractor)
        return self._pdf_extractor

    @property
    def image_extractor_instance(self) -> StandaloneImageExtractor:
        """Standalone image extractor."""
        if self._image_extractor is None:
            self._image_extractor = StandaloneImageExtractor(ocr_extractor=self.ocr_extractor)
        return self._image_extractor

    def _setup_dspy(self, model_state: Dict = None) -> TrainedExtractor:
        """Configure DSPy and return a trained extractor."""
        lm = _get_lm()

        try:
            dspy.settings.configure(lm=lm)
        except Exception:
            pass  # Already configured

        print("DSPy settings checked")

        extractor = TrainedExtractor()

        if model_state:
            print("  ✓ Loading existing model state (skipping training)")
            try:
                extractor.classifier.load_state(model_state)
            except Exception as e:
                print(f"  ⚠ Failed to load model state: {e}. Falling back to training.")
                extractor = train_extractor(extractor, config=self.config)
        else:
            extractor = train_extractor(extractor, config=self.config)

        return extractor

    def save_model_state(self) -> Dict:
        """Save the trained model state for persistence."""
        try:
            state = self.extractor.classifier.dump_state()
            return state
        except Exception as e:
            print(f"  ⚠ Could not save model state: {e}")
            return {}

    # =========================================================================
    # STAGE 2: CONTENT EXTRACTION
    # =========================================================================

    def _extract_content(self, file_path: str, file_type: FileType) -> str:
        """
        Extract text + image content from a file based on its type.

        For documents (PDF/DOCX/PPTX):
            1. Extract text content
            2. Extract embedded images
            3. Process each image through the image pipeline
            4. Combine all text

        For standalone images:
            Run through OCR directly

        Args:
            file_path: Path to the input file
            file_type: Classification result from FileRouter

        Returns:
            Combined text (document text + image OCR + diagram narratives)
        """
        print(f"\n  Processing: {file_path}")

        # Determine which extractor to use
        if file_type in (FileType.PDF, FileType.SCANNED_PDF):
            text = self.pdf_extractor.extract_text(file_path)
            images = self.pdf_extractor.extract_images(file_path)
        elif file_type == FileType.DOCX:
            text = self._docx_extractor.extract_text(file_path)
            images = self._docx_extractor.extract_images(file_path)
        elif file_type == FileType.PPTX:
            text = self._pptx_extractor.extract_text(file_path)
            images = self._pptx_extractor.extract_images(file_path)
        elif file_type == FileType.IMAGE:
            # Standalone image — directly process
            return self._process_standalone_image(file_path)
        else:
            print(f"  ⚠ Unsupported file type: {file_type}")
            return ""

        # Process embedded images through the pipeline
        image_text = self._process_embedded_images(images)

        # Combine document text + image text
        combined_parts = []

        if text and text.strip():
            combined_parts.append("=== DOCUMENT TEXT CONTENT ===\n")
            combined_parts.append(text)

        if image_text and image_text.strip():
            combined_parts.append("\n\n=== TEXT FROM EMBEDDED IMAGES ===\n")
            combined_parts.append(image_text)

        combined = "\n".join(combined_parts)
        print(f"  ✓ Combined text: {len(combined)} chars")
        return combined

    def _process_standalone_image(self, file_path: str) -> str:
        """Process a standalone image through the full pipeline."""
        # Get image data for processing
        img_data = self.image_extractor_instance.get_image_data(file_path)
        if not img_data:
            return ""

        # OCR
        ocr_result = self.ocr_extractor.extract_text_from_image(file_path)
        ocr_text = ocr_result.get("text", "") if ocr_result.get("success") else ""

        # Verify OCR
        if self.ocr_verifier.is_available and img_data.get("base64"):
            verified = self.ocr_verifier.verify_ocr(img_data["base64"], ocr_text)
            ocr_text = verified["verified_text"]

        # Classify
        if self.image_classifier.is_available and img_data.get("base64"):
            classification = self.image_classifier.classify(img_data["base64"], source=Path(file_path).name)

            if classification.get("is_workflow") and self.diagram_analyzer.is_available:
                # It's a workflow diagram — extract structure
                graph = self.diagram_analyzer.extract_graph_json(img_data["base64"], source=Path(file_path).name)
                narrative = self.diagram_analyzer.convert_to_narrative(graph)
                if narrative:
                    return f"{ocr_text}\n\n{narrative}" if ocr_text else narrative

        return ocr_text

    def _process_embedded_images(self, images: List[Dict]) -> str:
        """
        Process all embedded images through the pipeline.

        For each image:
            1. PaddleOCR → extract text
            2. Vision Verifier → correct OCR errors
            3. Image Classifier → workflow or informational?
            4. If workflow → Diagram Analyzer → text narrative
            5. If informational → use OCR text directly

        Args:
            images: List of image dicts from extractors

        Returns:
            Combined text from all processed images
        """
        if not images:
            return ""

        print(f"  Processing {len(images)} embedded images...")
        text_parts = []

        for idx, img in enumerate(images, 1):
            source = img.get("source", f"image_{idx}")
            print(f"\n   [{idx}/{len(images)}] {source}")

            # Step 1: OCR
            if img.get("bytes"):
                from PIL import Image
                import io
                pil_img = Image.open(io.BytesIO(img["bytes"]))
                ocr_result = self.ocr_extractor.extract_text_from_pil_image(pil_img)
            elif img.get("base64"):
                ocr_result = self.ocr_extractor.extract_text_from_base64(img["base64"])
            else:
                print(f"      ⚠ No image data available")
                continue

            ocr_text = ocr_result.get("text", "") if ocr_result.get("success") else ""
            ocr_confidence = ocr_result.get("confidence", 0)
            print(f"      OCR: {len(ocr_text)} chars (confidence: {ocr_confidence:.2%})")

            # Step 2: Verify OCR with Vision LLM
            image_base64 = img.get("base64", "")
            if self.ocr_verifier.is_available and ocr_text and image_base64:
                verified = self.ocr_verifier.verify_ocr(image_base64, ocr_text)
                if verified["success"]:
                    ocr_text = verified["verified_text"]
                    if verified["was_corrected"]:
                        print(f"      ✓ OCR corrected by Vision LLM")

            # Step 3: Classify image
            if self.image_classifier.is_available and image_base64:
                classification = self.image_classifier.classify(image_base64, source=source)

                if classification.get("is_workflow") and self.diagram_analyzer.is_available:
                    # Step 4a: Workflow diagram → extract structure
                    print(f"      → WORKFLOW detected: {classification.get('description', '')}")
                    graph = self.diagram_analyzer.extract_graph_json(image_base64, source=source)
                    narrative = self.diagram_analyzer.convert_to_narrative(graph)

                    if narrative:
                        text_parts.append(f"--- WORKFLOW: {source} ---\n{narrative}")
                        if ocr_text:
                            text_parts.append(f"--- OCR TEXT: {source} ---\n{ocr_text}")
                        continue
                else:
                    # Step 4b: Informational image → use OCR text
                    print(f"      → INFORMATIONAL: {classification.get('description', '')}")

            # Default: use OCR text
            if ocr_text.strip():
                text_parts.append(f"--- IMAGE: {source} ---\n{ocr_text}")

        return "\n\n".join(text_parts)

    # =========================================================================
    # STAGE 3: REQUIREMENT GENERATION
    # =========================================================================

    def _generate_requirements(self, text: str) -> tuple:
        """
        Run text through DSPy TrainedExtractor.

        Chunks the text, processes each chunk, and collects results.

        Args:
            text: Combined document text

        Returns:
            Tuple of (accepted_requirements, filtered_out)
        """
        if not text:
            return [], []

        chunks = chunk_document(text)
        print(f"  Split into {len(chunks)} chunks")

        all_reqs = []
        all_filtered = []

        for i, chunk in enumerate(chunks, 1):
            print(f"    Chunk {i}/{len(chunks)}...", end='')
            try:
                result = self.extractor(document_text=chunk)
                all_reqs.extend(result['requirements'])
                all_filtered.extend(result['filtered_out'])
                print(f" {len(result['requirements'])} accepted, {len(result['filtered_out'])} filtered")
            except Exception as e:
                print(f" ERROR: {e}")

        return all_reqs, all_filtered

    # =========================================================================
    # MAIN ENTRY POINTS
    # =========================================================================

    def run(self, file_paths: List[str], project_name: str, output_dir: str = None,
            status_callback: Callable[[str, str], None] = None) -> Dict:
        """
        Run the complete extraction pipeline on a list of files.

        This is the main entry point called by both FastAPI/Celery
        and the CLI flow.

        Args:
            file_paths: List of local file paths to process
            project_name: Project identifier (e.g. 'ptw_phase1')
            output_dir: Optional directory to save results locally
            status_callback: Optional callback(file_path, status) called per file.
                             status is "IN_PROGRESS", "COMPLETED", or "FAILED".

        Returns:
            Dict with 'project', 'requirements', and 'model_state'
        """
        print("=" * 80)
        print(f"REQUIREMENTS EXTRACTION - {str(project_name).upper()}")
        print("=" * 80)

        all_reqs = []
        all_filtered = []

        for file_path in file_paths:
            # Notify: this file is now being processed
            if status_callback:
                status_callback(file_path, "IN_PROGRESS")

            try:
                # Stage 1: Classify
                file_type, description = FileRouter.route(file_path)
                print(f"\n  {description}")

                if file_type == FileType.UNKNOWN:
                    print(f"  ⚠ Skipping unsupported file: {file_path}")
                    if status_callback:
                        status_callback(file_path, "COMPLETED")
                    continue

                # Stage 2: Extract content
                combined_text = self._extract_content(file_path, file_type)

                if not combined_text:
                    print(f"  ⚠ No text extracted from {file_path}")
                    if status_callback:
                        status_callback(file_path, "COMPLETED")
                    continue

                # Stage 3: Generate requirements
                reqs, filtered = self._generate_requirements(combined_text)
                all_reqs.extend(reqs)
                all_filtered.extend(filtered)

                # Notify: this file completed successfully
                if status_callback:
                    status_callback(file_path, "COMPLETED")

            except Exception as e:
                print(f"  ✗ Error processing {file_path}: {e}")
                if status_callback:
                    status_callback(file_path, "FAILED")

        print(f"\n  Total raw: {len(all_reqs)} accepted, {len(all_filtered)} filtered out")

        # Postprocessing
        unique = deduplicate_requirements(all_reqs)
        print(f"  After dedup: {len(all_reqs)} -> {len(unique)} unique")

        unique = consolidate_requirements(unique)
        print(f"  After consolidation: {len(unique)} requirements")

        # Add IDs
        for i, req in enumerate(unique, 1):
            req['requirement_id'] = f"{str(project_name).upper().replace(' ', '_')}-{i:03d}"

        # Save model state
        new_model_state = self.save_model_state()

        # Build result
        result_data = {
            'project': project_name,
            'requirements': unique,
            'model_state': new_model_state,
        }

        # Optionally save locally
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_file = Path(output_dir) / f"{project_name}_requirements.json"
            with open(output_file, 'w') as f:
                json.dump(result_data, f, indent=2)
            print(f"  Saved locally to: {output_file}")

        print(f"\nDone! {len(unique)} requirements extracted")
        return result_data


# =========================================================================
# CONVENIENCE FUNCTIONS (backward compatibility)
# =========================================================================

def extract_from_files(
    project_name: str,
    file_paths: List[str],
    output_dir: str = None,
    model_state: Dict = None,
    config: Dict = None,
    status_callback: Callable[[str, str], None] = None,
) -> Dict:
    """
    Extract requirements from a list of local file paths.
    Called by FastAPI after downloading files from S3.

    Backward-compatible wrapper around ExtractionPipeline.
    """
    pipeline = ExtractionPipeline(config=config, model_state=model_state)
    return pipeline.run(file_paths=file_paths, project_name=project_name, output_dir=output_dir,
                        status_callback=status_callback)


def extract_requirements(config: Dict = None) -> Dict:
    """
    Core extraction logic using multi-project config (CLI flow).
    Reads current_project from config, processes all documents in
    that project's input_dir.

    Backward-compatible wrapper around ExtractionPipeline.
    """
    # Load config
    if config is None:
        config_file = Path("config/config.json")
        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {config_file}")
        with open(config_file) as f:
            config = json.load(f)

    # Read current project
    current_project = config.get('current_project')
    if not current_project:
        raise ValueError("'current_project' not set in config.json")

    projects = config.get('projects', {})
    if current_project not in projects:
        raise ValueError(f"Project '{current_project}' not found in config.projects. Available: {list(projects.keys())}")

    project_config = projects[current_project]
    input_dir = Path(project_config['input_dir'])
    output_dir = Path(config.get('output_dir', 'output'))

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    output_dir.mkdir(exist_ok=True)

    # Find all supported files
    supported_exts = ['*.pdf', '*.pptx', '*.docx', '*.png', '*.jpg', '*.jpeg']
    all_files = []
    for ext in supported_exts:
        all_files.extend(sorted(input_dir.glob(ext)))

    # Skip files that are NOT requirement sources
    skip_patterns = ['test_strategy', 'test strategy', 'traceability', 'about.txt']
    filtered_files = []
    for f in all_files:
        fname = f.name.lower()
        if any(pat in fname for pat in skip_patterns):
            print(f"  Skipping (not a requirements source): {f.name}")
        else:
            filtered_files.append(f)
    all_files = filtered_files

    if not all_files:
        raise FileNotFoundError(f"No supported files found in {input_dir}")

    print(f"\nProject: {current_project}")
    print(f"Input dir: {input_dir}")
    print(f"Files to process: {len(all_files)}")
    for f in all_files:
        print(f"  - {f.name}")

    # Run pipeline
    pipeline = ExtractionPipeline(config=config)
    return pipeline.run(
        file_paths=[str(f) for f in all_files],
        project_name=current_project,
        output_dir=str(output_dir),
    )
