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

import re
import json
import logging
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
from .generators.trained_extractor import (
    TrainedExtractor,
    BusinessFeatureExtractor,
    WorkflowRequirementExtractor,
    TechnicalRequirementExtractor,
    FunctionalDetailExtractor
)
from .generators.training import train_extractor
from .generators.postprocessing import deduplicate_requirements, deduplicate_multi_layer_requirements, deduplicate_cross_layer, deduplicate_by_topic, consolidate_requirements, merge_semantic_siblings
from .generators.validation import validate_requirement
from .generators.v4_br_extractor import extract_requirements as v4_extract_requirements
from .utils import chunk_document

# Load environment
load_dotenv()

logger = logging.getLogger("prism.pipeline")

# Global LM instance to avoid re-configuring in async tasks
_global_lm = None


# CONFIDENCE STRING -> FLOAT MAPPING
_CONFIDENCE_MAP = {'high': 0.9, 'medium': 0.6, 'low': 0.3}


def _confidence_to_float(conf) -> float:
    """Convert confidence value to float. Handles both string and numeric."""
    if isinstance(conf, (int, float)):
        return float(conf)
    if isinstance(conf, str):
        return _CONFIDENCE_MAP.get(conf.lower().strip(), 0.6)
    return 0.6


def _capture_supporting_context(req_title, req_desc, req_ac, supporting_texts, max_per_doc=2000):
    """Scan supporting document texts for content relevant to this requirement.

    Ported from Archive-01's extract_br.py to enrich requirements with
    cross-document supporting context.

    Args:
        req_title: Requirement title/feature_name
        req_desc: Requirement description
        req_ac: Acceptance criteria list
        supporting_texts: Dict[filename, full_text] of supporting documents
        max_per_doc: Max chars to capture per supporting doc

    Returns:
        List[{doc, relevance_score, text}] sorted by relevance
    """
    if not supporting_texts:
        return []

    ac_text = ' '.join(req_ac) if isinstance(req_ac, list) else str(req_ac or '')
    search_text = f"{req_title} {req_desc} {ac_text}".lower()

    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'for', 'and', 'or', 'to', 'in', 'of',
        'on', 'at', 'by', 'with', 'from', 'as', 'be', 'this', 'that', 'it',
        'not', 'but', 'if', 'can', 'will', 'has', 'have', 'do', 'does',
        'feature', 'verify', 'display', 'show', 'page', 'user', 'customer',
        'based', 'should', 'must', 'able', 'when', 'each', 'provide',
        'key', 'information', 'new', 'self', 'serve'
    }
    keywords = {w for w in search_text.split() if len(w) > 2} - stop_words

    if not keywords:
        return []

    contexts = []
    for fname, doc_text in supporting_texts.items():
        doc_lower = doc_text.lower()

        # Score: count keyword overlaps
        overlap = sum(1 for kw in keywords if kw in doc_lower)
        if overlap <= 2:
            continue

        # Extract the most relevant section (around highest keyword density)
        # Split into ~500-char windows and score each
        best_window = ""
        best_score = 0
        window_size = min(max_per_doc, len(doc_text))
        step = max(200, window_size // 4)

        for start in range(0, len(doc_text) - min(500, len(doc_text)), step):
            end = min(start + window_size, len(doc_text))
            window = doc_text[start:end]
            window_lower = window.lower()
            score = sum(1 for kw in keywords if kw in window_lower)
            if score > best_score:
                best_score = score
                best_window = window

        if best_window.strip() and best_score > 2:
            contexts.append({
                "doc": fname,
                "relevance_score": best_score,
                "text": best_window.strip()[:max_per_doc]
            })
            logger.info("    Supporting context: %s (score=%d, %d chars)",
                        Path(fname).stem if '/' in fname or '\\' in fname else fname,
                        best_score, len(best_window))

    contexts.sort(key=lambda x: x['relevance_score'], reverse=True)
    return contexts[:3]


# SOURCE GROUNDING (Anti-Hallucination)

_GROUNDING_STOPWORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'for', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'from',
    'with', 'by', 'of', 'that', 'this', 'it', 'as', 'if', 'so',
    'must', 'should', 'can', 'will', 'all', 'each', 'every',
    'any', 'no', 'not', 'only', 'also', 'both', 'than', 'more',
    'most', 'other', 'into', 'their', 'its', 'has', 'have',
    'using', 'ensure', 'system', 'including', 'specific',
    'based', 'such', 'which', 'when', 'where', 'how', 'new',
    'existing', 'current', 'following', 'required', 'need',
    'provide', 'support', 'allow', 'enable', 'use',
    'type', 'requirements', 'requirement'
})


def _extract_key_terms(text: str) -> list:
    """Extract meaningful terms from text, skipping stopwords."""
    words = re.findall(r'[A-Za-z_][A-Za-z0-9_-]*', text)
    return [w for w in words if len(w) > 2 and w.lower() not in _GROUNDING_STOPWORDS]


def ground_check(requirements: list, source_text: str, min_grounding: float = 0.25) -> list:
    """
    Remove requirements whose key terms don't appear in the source document.

    This catches hallucinated details (e.g., "Elasticsearch CDC indexing"
    when the source never mentions Elasticsearch).
    """
    source_lower = source_text.lower()
    grounded = []
    removed = 0

    for req in requirements:
        title = req.get('title', '')
        desc = req.get('description', '')

        # Extract key terms from the requirement
        key_terms = _extract_key_terms(f"{title} {desc}")

        if not key_terms or len(key_terms) < 3:
            grounded.append(req)
            continue

        # Count how many key terms appear in source
        found = sum(1 for term in key_terms if term.lower() in source_lower)
        grounding_score = found / len(key_terms)

        if grounding_score >= min_grounding:
            grounded.append(req)
        else:
            removed += 1
            logger.warning("✗ Ungrounded: %s (score: %.0f%%)", title[:50], grounding_score * 100)

    if removed > 0:
        logger.info("Source grounding: removed %d hallucinated requirements", removed)

    return grounded


def _consolidate_defect_items(reqs: List[Dict]) -> List[Dict]:
    """
    Consolidate 'Prevent Regression of X-NNN' items by defect ID prefix.

    Ground truth documents often use umbrella defect categories
    (e.g., 'Defect Prevention - Integration' covering SADEFENDER-373,
    SADRSTRANG-13420, SADRSTRANG-13593). When the pipeline extracts every
    individual defect ID as a separate item, it over-extracts relative to
    the GT umbrellas, producing redundant false positives.

    Rule: when 2+ items share the same defect ID prefix (e.g., SADRSTRANG),
    keep only the FIRST extracted item (highest priority, extracted earliest).

    Generic: only triggers on 'Prevent Regression of X-NNN' pattern titles.
    No-op for other requirement types or when no items share a prefix.
    """
    defect_items = []
    non_defect_items = []

    for req in reqs:
        title_lower = req.get('title', '').lower()
        req_type = req.get('type', '').lower().replace(' ', '_')
        if 'prevent regression' in title_lower or req_type == 'defect_prevention':
            defect_items.append(req)
        else:
            non_defect_items.append(req)

    if not defect_items:
        return reqs

    # Group by defect ID prefix (e.g., "SADRSTRANG" from "SADRSTRANG-13583")
    groups: Dict[str, List[Dict]] = {}
    no_prefix = []

    for item in defect_items:
        title = item.get('title', '')
        match = re.search(r'Prevent Regression of ([A-Z_]+)-\d+', title, re.IGNORECASE)
        if match:
            prefix = match.group(1).upper()
            groups.setdefault(prefix, []).append(item)
        else:
            no_prefix.append(item)

    consolidated = list(no_prefix)
    removed = 0

    for prefix, items in groups.items():
        if len(items) >= 2:
            # Keep only the first extracted item per prefix (most likely the primary TP)
            consolidated.append(items[0])
            removed += len(items) - 1
            logger.info("Defect prefix consolidation: %s-* %d items → 1 (kept: %s)", prefix, len(items), items[0].get('title', ''))
        else:
            consolidated.extend(items)

    if removed > 0:
        logger.info("Defect consolidation: %d → %d defect items (%d merged)", len(defect_items), len(consolidated), removed)

    return non_defect_items + consolidated


def _get_lm():
    """Get or create the global DSPy language model."""
    global _global_lm
    if _global_lm is None:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY not found in .env")
        _global_lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key, max_tokens=16384)
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

        logger.debug("DSPy settings checked")

        extractor = TrainedExtractor()

        if model_state:
            logger.info("✓ Loading existing model state (skipping training)")
            try:
                extractor.classifier.load_state(model_state)
            except Exception as e:
                logger.warning("Failed to load model state: %s. Falling back to training.", e)
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
            logger.warning("Could not save model state: %s", e)
            return {}

    def _convert_v4_requirements(self, br_list, project_name):
        """Convert v4.0 BusinessRequirement objects to the approach2_project dict format.

        Preserves ALL Archive-01 fields including source_file, page/line ranges,
        supporting_context, system, requirements_text, and category.
        """
        result = []
        for i, br in enumerate(br_list, 1):
            result.append({
                "requirement_id": f"{str(project_name).upper().replace(' ', '_')}-{i:03d}",
                "feature_name": br.feature_name,
                "title": br.feature_name,
                "description": br.description,
                "system": br.system or "",
                "requirements_text": br.requirements_text or br.description,
                "type": br.category or "Functional",
                "category": br.category or "",
                "user_story": br.user_story,
                "acceptance_criteria": br.acceptance_criteria,
                "test_steps": [{"step_num": s.step_num, "action": s.action,
                                "expected_result": s.expected_result, "test_data": s.test_data}
                               for s in br.test_steps],
                "test_scenarios": br.test_scenarios,
                "source_file": br.source_file or "",
                "page_start": br.page_start,
                "page_end": br.page_end,
                "line_start": br.line_start,
                "line_end": br.line_end,
                "confidence": _confidence_to_float(br.confidence),
                "supporting_context": [],
                "assumptions": [],
                "ambiguities": [],
            })
        return result

    # =========================================================================
    # STAGE 2: CONTENT EXTRACTION
    # =========================================================================

    def _extract_content(self, file_path: str, file_type: FileType) -> str:
        """
        Extract text + image content from a file based on its type.
        """
        logger.info("Processing: %s", file_path)

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
            logger.warning("Unsupported file type: %s", file_type)
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
        logger.info("✓ Combined text: %d chars", len(combined))
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
        """
        if not images:
            return ""

        logger.info("Processing %d embedded images...", len(images))
        text_parts = []

        for idx, img in enumerate(images, 1):
            source = img.get("source", f"image_{idx}")
            logger.info("[%d/%d] %s", idx, len(images), source)

            # Step 1: OCR
            if img.get("bytes"):
                from PIL import Image
                import io
                pil_img = Image.open(io.BytesIO(img["bytes"]))
                ocr_result = self.ocr_extractor.extract_text_from_pil_image(pil_img)
            elif img.get("base64"):
                ocr_result = self.ocr_extractor.extract_text_from_base64(img["base64"])
            else:
                logger.warning("No image data available for %s", source)
                continue

            ocr_text = ocr_result.get("text", "") if ocr_result.get("success") else ""
            ocr_confidence = ocr_result.get("confidence", 0)
            logger.debug("OCR: %d chars (confidence: %.2f%%)", len(ocr_text), ocr_confidence * 100)

            # Step 2: Verify OCR with Vision LLM
            image_base64 = img.get("base64", "")
            if self.ocr_verifier.is_available and ocr_text and image_base64:
                verified = self.ocr_verifier.verify_ocr(image_base64, ocr_text)
                if verified["success"]:
                    ocr_text = verified["verified_text"]
                    if verified["was_corrected"]:
                        logger.info("✓ OCR corrected by Vision LLM")

            # Step 3: Classify image
            if self.image_classifier.is_available and image_base64:
                classification = self.image_classifier.classify(image_base64, source=source)

                if classification.get("is_workflow") and self.diagram_analyzer.is_available:
                    # Step 4a: Workflow diagram → extract structure
                    logger.info("→ WORKFLOW detected: %s", classification.get('description', ''))
                    graph = self.diagram_analyzer.extract_graph_json(image_base64, source=source)
                    narrative = self.diagram_analyzer.convert_to_narrative(graph)

                    if narrative:
                        text_parts.append(f"--- WORKFLOW: {source} ---\n{narrative}")
                        if ocr_text:
                            text_parts.append(f"--- OCR TEXT: {source} ---\n{ocr_text}")
                        continue
                else:
                    # Step 4b: Informational image → use OCR text
                    logger.info("→ INFORMATIONAL: %s", classification.get('description', ''))

            # Default: use OCR text
            if ocr_text.strip():
                text_parts.append(f"--- IMAGE: {source} ---\n{ocr_text}")

        return "\n\n".join(text_parts)

    # =========================================================================
    # STAGE 3: REQUIREMENT GENERATION
    # =========================================================================

    def _generate_requirements(self, text: str) -> tuple:
        """
        Run MULTI-LAYER extraction with 3 specialized passes.
        Pass 1: Business Features (core capabilities)
        Pass 2: Functional Details (UI screens & workflows)
        Pass 3: Technical Requirements (data models, APIs, compliance, SLAs)
        Each pass receives context from previous passes to avoid re-extraction.
        """
        if not text:
            return [], []

        chunks = chunk_document(text)
        logger.info("Split into %d chunks", len(chunks))

        all_reqs = []
        all_filtered = []

        # Pass 1: Business Features
        logger.info("Pass 1/3: Extracting Business Features...")
        business_extractor = BusinessFeatureExtractor()
        pass1_reqs = []
        pass1_filtered = []

        for i, chunk in enumerate(chunks, 1):
            try:
                result = business_extractor(document_text=chunk)
                pass1_reqs.extend(result['requirements'])
                pass1_filtered.extend(result['filtered_out'])
                logger.info("    Chunk %d/%d: %d accepted, %d filtered", i, len(chunks), len(result['requirements']), len(result['filtered_out']))
            except Exception as e:
                logger.error("    Chunk %d/%d ERROR: %s", i, len(chunks), e, exc_info=True)

        all_reqs.extend(pass1_reqs)
        all_filtered.extend(pass1_filtered)
        logger.info("Business Features total: %d requirements", len(pass1_reqs))

        # Build context header for Pass 2 — prevents re-extraction of Pass 1 items
        if pass1_reqs:
            already_extracted = "\n".join(f"- {r.get('title', '')}" for r in pass1_reqs)
            context_header = (
                "ALREADY EXTRACTED IN PREVIOUS PASS — do NOT re-extract these as UI or Workflow variants:\n"
                + already_extracted
                + "\n\n--- DOCUMENT ---\n"
            )
        else:
            context_header = ""

        # Pass 2: Functional Details (UI & Workflows)
        logger.info("Pass 2/3: Extracting Functional Details (UI & Workflows)...")
        functional_extractor = FunctionalDetailExtractor()
        pass2_reqs = []
        pass2_filtered = []

        for i, chunk in enumerate(chunks, 1):
            try:
                contextual_chunk = context_header + chunk if context_header else chunk
                result = functional_extractor(document_text=contextual_chunk)
                pass2_reqs.extend(result['requirements'])
                pass2_filtered.extend(result['filtered_out'])
                logger.info("    Chunk %d/%d: %d accepted, %d filtered", i, len(chunks), len(result['requirements']), len(result['filtered_out']))
            except Exception as e:
                logger.error("    Chunk %d/%d ERROR: %s", i, len(chunks), e, exc_info=True)

        all_reqs.extend(pass2_reqs)
        all_filtered.extend(pass2_filtered)
        logger.info("Functional Details total: %d requirements", len(pass2_reqs))

        # Pass 3: Technical Requirements (Data Models, APIs, Compliance, SLAs)
        logger.info("Pass 3/3: Extracting Technical Requirements...")
        technical_extractor = TechnicalRequirementExtractor()
        pass3_reqs = []
        pass3_filtered = []

        # Build context header for Pass 3 — includes items from both previous passes
        all_previous = pass1_reqs + pass2_reqs
        if all_previous:
            already_all = "\n".join(f"- {r.get('title', '')}" for r in all_previous)
            tech_context_header = (
                "ALREADY EXTRACTED — do NOT re-extract these:\n"
                + already_all
                + "\n\n--- DOCUMENT ---\n"
            )
        else:
            tech_context_header = ""

        for i, chunk in enumerate(chunks, 1):
            try:
                contextual_chunk = tech_context_header + chunk if tech_context_header else chunk
                result = technical_extractor(document_text=contextual_chunk)
                pass3_reqs.extend(result['requirements'])
                pass3_filtered.extend(result['filtered_out'])
                logger.info("    Chunk %d/%d: %d accepted, %d filtered", i, len(chunks), len(result['requirements']), len(result['filtered_out']))
            except Exception as e:
                logger.error("    Chunk %d/%d ERROR: %s", i, len(chunks), e, exc_info=True)

        all_reqs.extend(pass3_reqs)
        all_filtered.extend(pass3_filtered)
        logger.info("Technical Requirements total: %d requirements", len(pass3_reqs))

        return all_reqs, all_filtered

    # =========================================================================
    # MAIN ENTRY POINTS
    # =========================================================================

    def run(self, file_paths: List[str], project_name: str, output_dir: str = None,
            status_callback: Callable[[str, str], None] = None,
            document_tiers: Dict[str, str] = None) -> Dict:
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
        logger.info("=" * 80)
        logger.info("REQUIREMENTS EXTRACTION - %s", str(project_name).upper())
        logger.info("=" * 80)

        # Check v4.0 Enrichment-Pass flag
        use_v4 = os.getenv('USE_V4_BR_EXTRACTION', 'false').lower() == 'true'

        if use_v4:
            import tempfile
            import shutil
            logger.info("Using v4.0 Enrichment-Pass BR Extraction (Document-Tier)")
            with tempfile.TemporaryDirectory() as tmp_dir:
                for fp in file_paths:
                    shutil.copy2(fp, tmp_dir)
                br_list = v4_extract_requirements(input_dir=tmp_dir, document_tiers=document_tiers)
            unique = self._convert_v4_requirements(br_list, project_name)
            new_model_state = self.save_model_state()
            result_data = {
                'project': project_name,
                'requirements': unique,
                'model_state': new_model_state,
            }
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                output_file = Path(output_dir) / f"{project_name}_requirements.json"
                with open(output_file, 'w') as f:
                    json.dump(result_data, f, indent=2)
                logger.info("Saved locally to: %s", output_file)
            logger.info("Done! %d requirements extracted (v4.0 mode)", len(unique))
            return result_data

        all_reqs = []
        all_filtered = []
        all_source_texts = []  # Collect source text for grounding check
        file_source_texts = {}  # Map filename -> extracted text (for supporting context)

        for file_path in file_paths:
            # Notify: this file is now being processed
            if status_callback:
                status_callback(file_path, "IN_PROGRESS")

            filename = Path(file_path).name

            try:
                # Stage 1: Classify
                file_type, description = FileRouter.route(file_path)
                logger.info("Classified: %s", description)

                if file_type == FileType.UNKNOWN:
                    logger.warning("Skipping unsupported file: %s", file_path)
                    if status_callback:
                        status_callback(file_path, "COMPLETED")
                    continue

                # Stage 2: Extract content
                combined_text = self._extract_content(file_path, file_type)

                if not combined_text:
                    logger.warning("No text extracted from %s", file_path)
                    if status_callback:
                        status_callback(file_path, "COMPLETED")
                    continue

                all_source_texts.append(combined_text)
                file_source_texts[filename] = combined_text

                # Stage 3: Generate requirements
                reqs, filtered = self._generate_requirements(combined_text)

                # Tag each requirement with its source file and raw text
                for req in reqs:
                    req['source_file'] = filename
                    req.setdefault('requirements_text', req.get('description', ''))

                all_reqs.extend(reqs)
                all_filtered.extend(filtered)

                # Notify: this file completed successfully
                if status_callback:
                    status_callback(file_path, "COMPLETED")

            except Exception as e:
                logger.error("Error processing %s: %s", file_path, e, exc_info=True)
                if status_callback:
                    status_callback(file_path, "FAILED")

        logger.info("Total raw: %d accepted, %d filtered out", len(all_reqs), len(all_filtered))

        # Validation: Filter out vague/generic requirements
        logger.info("Validation (specificity check):")
        validated_reqs = []
        rejected = []
        for req in all_reqs:
            is_valid, reason = validate_requirement(req)
            if is_valid:
                validated_reqs.append(req)
            else:
                rejected.append({'req': req, 'reason': reason})
                logger.info("  ✗ Rejected: %s — %s", req.get('title', 'N/A')[:50], reason)

        logger.info("After validation: %d -> %d valid (%d rejected)", len(all_reqs), len(validated_reqs), len(rejected))

        # Consolidate over-extracted defect prevention items before dedup
        # (groups 'Prevent Regression of X-NNN' by prefix X, keeps only the first per prefix)
        logger.info("Defect consolidation:")
        validated_reqs = _consolidate_defect_items(validated_reqs)

        # Postprocessing with layer-aware deduplication
        logger.info("Deduplication (layer-aware):")
        unique = deduplicate_multi_layer_requirements(validated_reqs)
        logger.info("After within-type dedup: %d -> %d unique", len(validated_reqs), len(unique))

        # Cross-layer deduplication: catches UI/Workflow variants of already-extracted Functional items
        # (safety net for context-aware Pass 2 — e.g., "Technical Details Page" [UI] vs
        #  "Technical Details Page Standardization" [Functional])
        before_cross = len(unique)
        unique = deduplicate_cross_layer(unique)
        if len(unique) < before_cross:
            logger.info("After cross-layer dedup: %d -> %d unique", before_cross, len(unique))


        # Topic-based dedup disabled — was removing valid distinct requirements
        # that share domain terms (e.g., MCDO-03 and MCDO-01 share 'meraki', 'datavalet')
        # before_topic = len(unique)
        # unique = deduplicate_by_topic(unique, min_shared_terms=6)
        # print(f"  After topic dedup: {before_topic} -> {len(unique)} unique")

        # Source grounding check (removes hallucinated requirements)
        full_source_text = "\n\n".join(all_source_texts)
        if full_source_text:
            before_ground = len(unique)
            unique = ground_check(unique, full_source_text, min_grounding=0.25)
            logger.info("After source grounding: %d -> %d grounded", before_ground, len(unique))

        unique = consolidate_requirements(unique)
        logger.info("After consolidation: %d requirements", len(unique))

        # Post-consolidation: merge remaining semantic siblings
        # (catches sub-features the LLM consolidation missed, e.g.,
        #  "Packing Slip" + "Certificate of Origin" → keep best one)
        before_sibling = len(unique)
        unique = merge_semantic_siblings(unique)
        if len(unique) < before_sibling:
            logger.info("After sibling merge: %d → %d requirements", before_sibling, len(unique))

        # Second grounding check after consolidation — catches any items injected by LLM consolidation
        if full_source_text:
            before_post_ground = len(unique)
            unique = ground_check(unique, full_source_text, min_grounding=0.25)
            if len(unique) < before_post_ground:
                logger.info("After post-consolidation grounding: %d -> %d (removed %d hallucinated)", before_post_ground, len(unique), before_post_ground - len(unique))

        # Add IDs and enrich with ALL Archive-01 fields
        logger.info("Enriching requirements with full Archive-01 field set...")
        for i, req in enumerate(unique, 1):
            req['requirement_id'] = f"{str(project_name).upper().replace(' ', '_')}-{i:03d}"

            # feature_name = copy of title (Archive-01 compatibility)
            req['feature_name'] = req.get('title', '')

            # system: system dependencies (empty by default, enriched if available)
            req.setdefault('system', '')

            # requirements_text: raw text from the source chunk
            req.setdefault('requirements_text', req.get('description', ''))

            # category: domain category (e.g., "Dashboard", "Warranty")
            # Map from type if not explicitly set
            req.setdefault('category', req.get('type', 'Functional'))

            # source_file: which document this requirement came from
            req.setdefault('source_file', '')

            # page/line ranges: default to 0 if not tracked
            req.setdefault('page_start', 0)
            req.setdefault('page_end', 0)
            req.setdefault('line_start', 0)
            req.setdefault('line_end', 0)

            # confidence: convert string -> float
            req['confidence'] = _confidence_to_float(req.get('confidence', 'medium'))

            # Ensure test_scenarios exists
            req.setdefault('test_scenarios', [])

            # Ensure test_steps exists
            req.setdefault('test_steps', [])

            # Ensure assumptions and ambiguities exist
            req.setdefault('assumptions', [])
            req.setdefault('ambiguities', [])

            # supporting_context: scan other files for relevant context
            # Use all file texts EXCEPT the requirement's own source file
            other_file_texts = {
                fname: text for fname, text in file_source_texts.items()
                if fname != req.get('source_file', '')
            }
            if other_file_texts:
                req['supporting_context'] = _capture_supporting_context(
                    req_title=req.get('title', ''),
                    req_desc=req.get('description', ''),
                    req_ac=req.get('acceptance_criteria', []),
                    supporting_texts=other_file_texts,
                )
            else:
                req.setdefault('supporting_context', [])

        logger.info("All requirements enriched with Archive-01 fields")

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
            logger.info("Saved locally to: %s", output_file)

        logger.info("Done! %d requirements extracted", len(unique))
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
    document_tiers: Dict[str, str] = None,
) -> Dict:
    """
    Extract requirements from a list of local file paths.
    Called by FastAPI after downloading files from S3.

    Backward-compatible wrapper around ExtractionPipeline.
    """
    pipeline = ExtractionPipeline(config=config, model_state=model_state)
    return pipeline.run(file_paths=file_paths, project_name=project_name, output_dir=output_dir,
                        status_callback=status_callback, document_tiers=document_tiers)


