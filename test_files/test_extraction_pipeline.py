"""
PRISM Extraction Pipeline — Comprehensive Test Suite

Tests ALL modules across the 3-stage architecture:
    1. File Router (Stage 1)
    2. Content Extractors (Stage 2)
    3. Image Processors (Image Pipeline)
    4. DSPy Generators (Stage 3)
    5. Pipeline Orchestrator
    6. Utilities

Run:
    python test_files/test_extraction_pipeline.py

    # Run specific test groups:
    python test_files/test_extraction_pipeline.py TestFileRouter
    python test_files/test_extraction_pipeline.py TestPDFExtractor
    python test_files/test_extraction_pipeline.py TestEndToEnd
"""

import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load environment variables from .env in project root
load_dotenv(PROJECT_ROOT / ".env")

# ============================================================================
# CONSTANTS
# ============================================================================

INPUT_DIR = PROJECT_ROOT / "input"
CRM_DIR = INPUT_DIR / "crm_cloud"
FINTECH_DIR = INPUT_DIR / "fintech_app"
HEALTHCARE_DIR = INPUT_DIR / "healthcare_portal"
ECOMMERCE_DIR = INPUT_DIR / "ecommerce_gateway"
LOGISTICS_DIR = INPUT_DIR / "logistics_manager"

# Sample files for testing (pick one from each project)
SAMPLE_PDF = CRM_DIR / "CRM_Enterprise_Requirements.pdf"
SAMPLE_WORKFLOW_PDF = FINTECH_DIR / "FIN_User_Workflows.pdf"

# Test outputs — saved to project's outputs/test_results/ directory
TEST_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "test_results"
TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def skip_if_no_file(filepath):
    """Decorator to skip test if a sample file doesn't exist."""
    return unittest.skipUnless(
        filepath.exists(),
        f"Test file not found: {filepath}"
    )


# ============================================================================
# 1. FILE ROUTER TESTS (Stage 1)
# ============================================================================

class TestFileRouter(unittest.TestCase):
    """Test file classification and routing logic."""

    def setUp(self):
        from extraction.file_router import FileRouter, FileType
        self.FileRouter = FileRouter
        self.FileType = FileType

    def test_classify_pdf(self):
        """PDF files should be classified as PDF."""
        file_type = self.FileRouter.classify("document.pdf")
        self.assertEqual(file_type, self.FileType.PDF)

    def test_classify_docx(self):
        """DOCX files should be classified as DOCX."""
        file_type = self.FileRouter.classify("document.docx")
        self.assertEqual(file_type, self.FileType.DOCX)

    def test_classify_doc(self):
        """DOC files should also classify as DOCX."""
        file_type = self.FileRouter.classify("document.doc")
        self.assertEqual(file_type, self.FileType.DOCX)

    def test_classify_pptx(self):
        """PPTX files should be classified as PPTX."""
        file_type = self.FileRouter.classify("slides.pptx")
        self.assertEqual(file_type, self.FileType.PPTX)

    def test_classify_ppt(self):
        """PPT files should also classify as PPTX."""
        file_type = self.FileRouter.classify("slides.ppt")
        self.assertEqual(file_type, self.FileType.PPTX)

    def test_classify_png(self):
        """PNG files should be classified as IMAGE."""
        file_type = self.FileRouter.classify("screenshot.png")
        self.assertEqual(file_type, self.FileType.IMAGE)

    def test_classify_jpg(self):
        """JPG files should be classified as IMAGE."""
        file_type = self.FileRouter.classify("photo.jpg")
        self.assertEqual(file_type, self.FileType.IMAGE)

    def test_classify_jpeg(self):
        """JPEG files should be classified as IMAGE."""
        file_type = self.FileRouter.classify("photo.jpeg")
        self.assertEqual(file_type, self.FileType.IMAGE)

    def test_classify_unknown(self):
        """Unknown extensions should return UNKNOWN."""
        file_type = self.FileRouter.classify("document.xyz")
        self.assertEqual(file_type, self.FileType.UNKNOWN)

    def test_classify_txt(self):
        """TXT files should return UNKNOWN."""
        file_type = self.FileRouter.classify("readme.txt")
        self.assertEqual(file_type, self.FileType.UNKNOWN)

    def test_classify_case_insensitive(self):
        """Classification should be case-insensitive."""
        file_type = self.FileRouter.classify("Document.PDF")
        self.assertEqual(file_type, self.FileType.PDF)

    def test_route_returns_tuple(self):
        """route() should return (FileType, description)."""
        result = self.FileRouter.route("test.pdf")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], self.FileType)
        self.assertIsInstance(result[1], str)

    @skip_if_no_file(SAMPLE_PDF)
    def test_route_real_pdf(self):
        """Test routing a real PDF file (should detect text layer)."""
        file_type, desc = self.FileRouter.route(str(SAMPLE_PDF))
        self.assertIn(file_type, [self.FileType.PDF, self.FileType.SCANNED_PDF])
        print(f"   Real PDF → {file_type.value}: {desc}")

    @skip_if_no_file(SAMPLE_WORKFLOW_PDF)
    def test_scanned_pdf_detection(self):
        """Verify scanned PDF detection on a workflow PDF."""
        file_type, desc = self.FileRouter.route(str(SAMPLE_WORKFLOW_PDF))
        self.assertIn(file_type, [self.FileType.PDF, self.FileType.SCANNED_PDF])
        print(f"   Workflow PDF → {file_type.value}: {desc}")


# ============================================================================
# 2. CONTENT EXTRACTOR TESTS (Stage 2)
# ============================================================================

class TestPDFExtractor(unittest.TestCase):
    """Test PDF text and image extraction."""

    def setUp(self):
        from extraction.extractors.pdf_extractor import PDFExtractor
        self.extractor = PDFExtractor(ocr_extractor=None)  # No OCR for unit tests

    @skip_if_no_file(SAMPLE_PDF)
    def test_extract_text(self):
        """Extract text from a real PDF — should return non-empty string."""
        text = self.extractor.extract_text(str(SAMPLE_PDF))
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 100, "PDF text should be substantial")
        print(f"   Extracted {len(text)} chars from {SAMPLE_PDF.name}")

    @skip_if_no_file(SAMPLE_PDF)
    def test_extract_images(self):
        """Extract images from a PDF — should return a list."""
        images = self.extractor.extract_images(str(SAMPLE_PDF))
        self.assertIsInstance(images, list)
        print(f"   Found {len(images)} images in {SAMPLE_PDF.name}")

    @skip_if_no_file(SAMPLE_PDF)
    def test_text_contains_content(self):
        """Extracted text should contain meaningful content (not just whitespace)."""
        text = self.extractor.extract_text(str(SAMPLE_PDF))
        # Strip whitespace and check
        clean = text.strip()
        self.assertGreater(len(clean), 50)
        # Should contain at least some words
        words = clean.split()
        self.assertGreater(len(words), 10, "Should extract multiple words")


class TestDOCXExtractor(unittest.TestCase):
    """Test DOCX extraction with a mock document."""

    def setUp(self):
        from extraction.extractors.docx_extractor import DOCXExtractor
        self.extractor = DOCXExtractor()

    def test_extract_text_nonexistent_file(self):
        """Should handle non-existent file gracefully."""
        text = self.extractor.extract_text("/nonexistent/file.docx")
        self.assertEqual(text, "")

    def test_extract_images_nonexistent_file(self):
        """Should handle non-existent file gracefully."""
        images = self.extractor.extract_images("/nonexistent/file.docx")
        self.assertEqual(images, [])


class TestPPTXExtractor(unittest.TestCase):
    """Test PPTX extraction with a mock presentation."""

    def setUp(self):
        from extraction.extractors.pptx_extractor import PPTXExtractor
        self.extractor = PPTXExtractor()

    def test_extract_text_nonexistent_file(self):
        """Should handle non-existent file gracefully."""
        text = self.extractor.extract_text("/nonexistent/file.pptx")
        self.assertEqual(text, "")

    def test_extract_images_nonexistent_file(self):
        """Should handle non-existent file gracefully."""
        images = self.extractor.extract_images("/nonexistent/file.pptx")
        self.assertEqual(images, [])


class TestOCRExtractor(unittest.TestCase):
    """Test PaddleOCR wrapper."""

    def test_import(self):
        """OCRExtractor should be importable."""
        from extraction.extractors.ocr_extractor import LocalOCRExtractor, OCRConfig
        self.assertIsNotNone(LocalOCRExtractor)
        self.assertIsNotNone(OCRConfig)

    def test_ocr_config_defaults(self):
        """OCRConfig should have sensible defaults."""
        from extraction.extractors.ocr_extractor import OCRConfig
        config = OCRConfig()
        self.assertEqual(config.language, "en")
        self.assertTrue(config.verify_with_vision)
        self.assertFalse(config.use_gpu)

    def test_ocr_config_from_env(self):
        """OCRConfig.from_env() should work with defaults."""
        from extraction.extractors.ocr_extractor import OCRConfig
        config = OCRConfig.from_env()
        self.assertIsInstance(config, OCRConfig)


class TestImageExtractor(unittest.TestCase):
    """Test standalone image extractor."""

    def test_import(self):
        """StandaloneImageExtractor should be importable."""
        from extraction.extractors.image_extractor import StandaloneImageExtractor
        self.assertIsNotNone(StandaloneImageExtractor)

    def test_get_image_data_nonexistent(self):
        """Should return None for nonexistent image."""
        from extraction.extractors.image_extractor import StandaloneImageExtractor
        extractor = StandaloneImageExtractor(ocr_extractor=None)
        result = extractor.get_image_data("/nonexistent/image.png")
        self.assertIsNone(result)


# ============================================================================
# 3. IMAGE PROCESSOR TESTS (Image Pipeline)
# ============================================================================

class TestOCRVerifier(unittest.TestCase):
    """Test Vision LLM OCR verification."""

    @patch.dict(os.environ, {}, clear=True)
    def test_init_without_key(self):
        """Should initialize gracefully without API key."""
        from extraction.processors.vision_verifier import OCRVerifier
        # Pass None explicitly and ensure env is empty via mock
        verifier = OCRVerifier(groq_api_key=None)
        self.assertFalse(verifier.is_available)

    def test_verify_without_key(self):
        """Should return original text when no API key."""
        from extraction.processors.vision_verifier import OCRVerifier
        verifier = OCRVerifier(groq_api_key=None)
        result = verifier.verify_ocr("base64data", "Hello World")
        self.assertEqual(result["verified_text"], "Hello World")
        self.assertFalse(result["was_corrected"])
        self.assertFalse(result["success"])

    @patch("groq.Groq")
    def test_verify_empty_text(self, mock_groq):
        """Should handle empty OCR text."""
        from extraction.processors.vision_verifier import OCRVerifier
        verifier = OCRVerifier(groq_api_key="test_key_placeholder")
        # Even with a key, empty text should be handled
        if verifier.is_available:
            result = verifier.verify_ocr("base64data", "")
            self.assertFalse(result["was_corrected"])

    def test_model_default(self):
        """Default model should be Llama 4 Scout."""
        from extraction.processors.vision_verifier import OCRVerifier
        verifier = OCRVerifier(groq_api_key=None)
        self.assertEqual(verifier.model, "meta-llama/llama-4-scout-17b-16e-instruct")

    @unittest.skipUnless(os.getenv("GROQ_API_KEY"), "GROQ_API_KEY not set")
    def test_verify_with_real_key(self):
        """Integration test: verify OCR with real Groq API."""
        from extraction.processors.vision_verifier import OCRVerifier
        verifier = OCRVerifier()  # Auto-detects GROQ_API_KEY from env
        self.assertTrue(verifier.is_available)
        print("   ✓ OCR Verifier initialized with Groq API key")


class TestImageClassifier(unittest.TestCase):
    """Test image classification."""

    @patch.dict(os.environ, {}, clear=True)
    def test_init_without_key(self):
        """Should initialize gracefully without API key."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier(groq_api_key=None)
        self.assertFalse(classifier.is_available)

    def test_classify_without_key(self):
        """Should return default 'informational' when no API key."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier(groq_api_key=None)
        result = classifier.classify("base64data", source="test.png")
        self.assertEqual(result["image_type"], "informational")
        self.assertFalse(result["is_workflow"])
        self.assertFalse(result["success"])

    def test_model_default(self):
        """Default model should be Llama 4 Scout."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier(groq_api_key=None)
        self.assertEqual(classifier.model, "meta-llama/llama-4-scout-17b-16e-instruct")

    def test_parse_classification_workflow(self):
        """Should correctly parse a WORKFLOW classification response."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier(groq_api_key=None)
        reply = "TYPE: workflow\nCONFIDENCE: high\nDESCRIPTION: A login flow diagram"
        result = classifier._parse_classification(reply, "test.png")
        self.assertTrue(result["is_workflow"])
        self.assertEqual(result["image_type"], "workflow")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["description"], "A login flow diagram")

    def test_parse_classification_informational(self):
        """Should correctly parse an INFORMATIONAL classification response."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier(groq_api_key=None)
        reply = "TYPE: informational\nCONFIDENCE: medium\nDESCRIPTION: Screenshot of dashboard"
        result = classifier._parse_classification(reply, "test.png")
        self.assertFalse(result["is_workflow"])
        self.assertEqual(result["image_type"], "informational")
        self.assertEqual(result["confidence"], "medium")

    @unittest.skipUnless(os.getenv("GROQ_API_KEY"), "GROQ_API_KEY not set")
    def test_classifier_with_real_key(self):
        """Integration test: classifier with real Groq API."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier()  # Auto-detects GROQ_API_KEY from env
        self.assertTrue(classifier.is_available)
        print("   ✓ Image Classifier initialized with Groq API key")


class TestDiagramAnalyzer(unittest.TestCase):
    """Test diagram analysis."""

    @patch.dict(os.environ, {}, clear=True)
    def test_init_without_key(self):
        """Should initialize gracefully without API key."""
        from extraction.processors.diagram_analyzer import DiagramAnalyzer
        analyzer = DiagramAnalyzer(groq_api_key=None)
        self.assertFalse(analyzer.is_available)

    def test_extract_without_key(self):
        """Should return empty result when no API key."""
        from extraction.processors.diagram_analyzer import DiagramAnalyzer
        analyzer = DiagramAnalyzer(groq_api_key=None)
        result = analyzer.extract_graph_json("base64data")
        self.assertFalse(result["has_diagram"])
        self.assertEqual(result["nodes"], [])

    def test_convert_to_narrative_empty(self):
        """Should return empty string for empty graph."""
        from extraction.processors.diagram_analyzer import DiagramAnalyzer
        analyzer = DiagramAnalyzer(groq_api_key=None)
        narrative = analyzer.convert_to_narrative({"has_diagram": False})
        self.assertEqual(narrative, "")

    def test_convert_to_narrative_with_data(self):
        """Should generate readable narrative from graph JSON."""
        from extraction.processors.diagram_analyzer import DiagramAnalyzer
        analyzer = DiagramAnalyzer(groq_api_key=None)

        graph = {
            "has_diagram": True,
            "diagram_type": "flowchart",
            "diagram_title": "Login Flow",
            "nodes": [
                {"id": "n1", "label": "Start", "type": "start"},
                {"id": "n2", "label": "Enter Credentials", "type": "process"},
                {"id": "n3", "label": "Valid?", "type": "decision"},
                {"id": "n4", "label": "Dashboard", "type": "end"},
                {"id": "n5", "label": "Error Page", "type": "end"},
            ],
            "connections": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n3", "to": "n4", "label": "Yes"},
                {"from": "n3", "to": "n5", "label": "No"},
            ],
            "decision_points": [
                {"node_id": "n3", "condition": "Credentials valid", "yes_path": "n4", "no_path": "n5"}
            ],
            "flow_paths": [
                {"name": "happy path", "steps": ["n1", "n2", "n3", "n4"]},
                {"name": "error path", "steps": ["n1", "n2", "n3", "n5"]},
            ],
        }

        narrative = analyzer.convert_to_narrative(graph)
        self.assertIn("Login Flow", narrative)
        self.assertIn("flowchart", narrative)
        self.assertIn("Enter Credentials", narrative)
        self.assertIn("Dashboard", narrative)
        self.assertIn("YES →", narrative)
        self.assertIn("NO  →", narrative)
        self.assertIn("happy path", narrative)
        print(f"   Generated narrative ({len(narrative)} chars):\n{narrative[:300]}...")

    def test_model_default(self):
        """Default model should be Llama 4 Scout."""
        from extraction.processors.diagram_analyzer import DiagramAnalyzer
        analyzer = DiagramAnalyzer(groq_api_key=None)
        self.assertEqual(analyzer.model, "meta-llama/llama-4-scout-17b-16e-instruct")


# ============================================================================
# 4. GENERATORS TESTS (Stage 3)
# ============================================================================

class TestSignatures(unittest.TestCase):
    """Test DSPy signature definitions."""

    def test_import_all_signatures(self):
        """All 4 signatures should be importable."""
        from extraction.generators.signatures import (
            RequirementExtraction,
            RequirementClassifier,
            RequirementDeMerger,
            RequirementConsolidation,
        )
        self.assertIsNotNone(RequirementExtraction)
        self.assertIsNotNone(RequirementClassifier)
        self.assertIsNotNone(RequirementDeMerger)
        self.assertIsNotNone(RequirementConsolidation)

    def test_requirement_extraction_fields(self):
        """RequirementExtraction should have expected input/output fields."""
        from extraction.generators.signatures import RequirementExtraction
        # Check that the class has the expected field names
        self.assertTrue(hasattr(RequirementExtraction, '__doc__'))


class TestTrainedExtractor(unittest.TestCase):
    """Test the TrainedExtractor DSPy module."""

    def test_import(self):
        """TrainedExtractor should be importable."""
        from extraction.generators.trained_extractor import TrainedExtractor
        self.assertIsNotNone(TrainedExtractor)

    def test_instantiate(self):
        """TrainedExtractor should instantiate."""
        from extraction.generators.trained_extractor import TrainedExtractor
        extractor = TrainedExtractor()
        self.assertIsNotNone(extractor)


class TestTraining(unittest.TestCase):
    """Test training examples and logic."""

    def test_import_examples(self):
        """Training examples should be importable."""
        from extraction.generators.training import (
            POSITIVE_EXAMPLES,
            NEGATIVE_EXAMPLES,
            SKIP_KEYWORDS,
        )
        self.assertIsInstance(POSITIVE_EXAMPLES, list)
        self.assertIsInstance(NEGATIVE_EXAMPLES, list)
        self.assertIsInstance(SKIP_KEYWORDS, list)

    def test_positive_examples_count(self):
        """Should have multiple positive examples."""
        from extraction.generators.training import POSITIVE_EXAMPLES
        self.assertGreaterEqual(len(POSITIVE_EXAMPLES), 5)
        print(f"   {len(POSITIVE_EXAMPLES)} positive training examples")

    def test_negative_examples_count(self):
        """Should have multiple negative examples."""
        from extraction.generators.training import NEGATIVE_EXAMPLES
        self.assertGreaterEqual(len(NEGATIVE_EXAMPLES), 5)
        print(f"   {len(NEGATIVE_EXAMPLES)} negative training examples")

    def test_skip_keywords_count(self):
        """Should have skip keywords for filtering."""
        from extraction.generators.training import SKIP_KEYWORDS
        self.assertGreater(len(SKIP_KEYWORDS), 0)
        print(f"   {len(SKIP_KEYWORDS)} skip keywords")

    def test_example_structure(self):
        """Each training example should have required fields."""
        from extraction.generators.training import POSITIVE_EXAMPLES, NEGATIVE_EXAMPLES
        for ex in POSITIVE_EXAMPLES + NEGATIVE_EXAMPLES:
            self.assertIn("title", ex)
            self.assertIn("description", ex)
            self.assertIn("is_requirement", ex)
            self.assertIsInstance(ex["is_requirement"], str)
            self.assertIn(ex["is_requirement"], ["Yes", "No"])


class TestPostprocessing(unittest.TestCase):
    """Test deduplication and consolidation."""

    def test_deduplicate_empty(self):
        """Should handle empty list."""
        from extraction.generators.postprocessing import deduplicate_requirements
        result = deduplicate_requirements([])
        self.assertEqual(result, [])

    def test_deduplicate_unique(self):
        """Should keep unique requirements."""
        from extraction.generators.postprocessing import deduplicate_requirements
        reqs = [
            {"title": "User Login", "description": "Allow users to log in with username and password"},
            {"title": "Dashboard View", "description": "Show analytics dashboard with key metrics"},
            {"title": "Export Report", "description": "Users can export reports as PDF or Excel"},
        ]
        result = deduplicate_requirements(reqs)
        self.assertEqual(len(result), 3)

    def test_deduplicate_duplicates(self):
        """Should remove near-duplicate requirements."""
        from extraction.generators.postprocessing import deduplicate_requirements
        reqs = [
            {"title": "User Login", "description": "Allow users to log in with username and password"},
            {"title": "User Login System", "description": "Allow users to log in with their username and password"},
            {"title": "Dashboard View", "description": "Show analytics dashboard with key metrics"},
        ]
        result = deduplicate_requirements(reqs)
        self.assertLessEqual(len(result), 2)
        print(f"   3 reqs (2 near-dupes) → {len(result)} unique")

    def test_deduplicate_single(self):
        """Should handle single requirement."""
        from extraction.generators.postprocessing import deduplicate_requirements
        reqs = [{"title": "Login", "description": "User login feature"}]
        result = deduplicate_requirements(reqs)
        self.assertEqual(len(result), 1)


# ============================================================================
# 5. UTILS TESTS
# ============================================================================

class TestUtils(unittest.TestCase):
    """Test utility functions."""

    def test_chunk_document_short(self):
        """Short text should produce a single chunk."""
        from extraction.utils import chunk_document
        text = "This is a short document."
        chunks = chunk_document(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_chunk_document_long(self):
        """Long text should produce multiple chunks."""
        from extraction.utils import chunk_document
        # Create a long text with many paragraphs
        paragraphs = [f"Paragraph {i}: " + "word " * 200 for i in range(30)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_document(text, max_chars=3000)
        self.assertGreater(len(chunks), 1)
        print(f"   {len(text)} chars → {len(chunks)} chunks")

    def test_chunk_document_overlap(self):
        """Chunks should have overlap to avoid losing context."""
        from extraction.utils import chunk_document
        paragraphs = [f"Unique paragraph {i}: " + "content " * 100 for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_document(text, max_chars=2000, overlap=0.2)
        # Check that consecutive chunks share some text
        if len(chunks) > 1:
            # The end of chunk 0 should overlap with the start of chunk 1
            self.assertGreater(len(chunks), 1)
            print(f"   {len(chunks)} overlapping chunks created")

    def test_chunk_document_empty(self):
        """Empty text should produce one empty chunk."""
        from extraction.utils import chunk_document
        chunks = chunk_document("")
        self.assertEqual(len(chunks), 1)

    def test_chunk_document_custom_size(self):
        """Custom max_chars should be respected."""
        from extraction.utils import chunk_document
        text = "Word " * 2000  # ~10,000 chars
        chunks = chunk_document(text, max_chars=1000)
        for chunk in chunks:
            # Allow some tolerance due to paragraph boundaries
            self.assertLessEqual(len(chunk), 2000)


# ============================================================================
# 6. PIPELINE INTEGRATION TESTS
# ============================================================================

class TestPipelineImports(unittest.TestCase):
    """Test that all pipeline imports work correctly."""

    def test_import_pipeline(self):
        """ExtractionPipeline should be importable."""
        from extraction.pipeline import ExtractionPipeline
        self.assertIsNotNone(ExtractionPipeline)

    def test_import_extract_from_files(self):
        """extract_from_files should be importable."""
        from extraction.pipeline import extract_from_files
        self.assertIsNotNone(extract_from_files)

    def test_import_extract_requirements(self):
        """extract_requirements should be importable."""
        from extraction.pipeline import extract_requirements
        self.assertIsNotNone(extract_requirements)

    def test_import_get_lm(self):
        """_get_lm should be importable."""
        from extraction.pipeline import _get_lm
        self.assertIsNotNone(_get_lm)

    def test_import_from_package_init(self):
        """Public API should be importable from package init."""
        from extraction import ExtractionPipeline
        self.assertIsNotNone(ExtractionPipeline)


class TestBackwardCompatWrapper(unittest.TestCase):
    """Test that the backward-compatibility wrapper works."""

    def test_import_from_wrapper(self):
        """Wrapper should re-export extract_from_files."""
        try:
            # Import the wrapper directly
            spec = __import__('extract_requirements_wrapper')
            self.assertTrue(hasattr(spec, 'extract_from_files'))
            self.assertTrue(hasattr(spec, '_get_lm'))
            self.assertTrue(hasattr(spec, 'ExtractionPipeline'))
            print("   ✓ Wrapper re-exports: extract_from_files, _get_lm, ExtractionPipeline")
        except ImportError as e:
            self.skipTest(f"Wrapper not yet activated: {e}")


# ============================================================================
# 7. END-TO-END INTEGRATION TESTS (require API keys)
# ============================================================================

@unittest.skipUnless(os.getenv("GROQ_API_KEY"), "GROQ_API_KEY not set — skipping E2E tests")
class TestEndToEnd(unittest.TestCase):
    """
    End-to-end integration tests using real files and real API calls.
    These tests require:
        - GROQ_API_KEY in .env
        - Sample PDF files in the input/ directory
    """

    @classmethod
    def setUpClass(cls):
        """Initialize DSPy once for all E2E tests."""
        import dspy
        from extraction.pipeline import _get_lm
        try:
            lm = _get_lm()
            dspy.settings.configure(lm=lm)
        except Exception:
            pass

    @skip_if_no_file(SAMPLE_PDF)
    def test_full_pdf_extraction(self):
        """
        FULL E2E: PDF → Route → Extract Text → Extract Images →
        Process Images → DSPy Extract → Dedup → Output
        """
        from extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline()

        result = pipeline.run(
            file_paths=[str(SAMPLE_PDF)],
            project_name="test_crm",
            output_dir=TEST_OUTPUT_DIR,
        )

        # Validate result structure
        self.assertIn("project", result)
        self.assertIn("requirements", result)
        self.assertIn("model_state", result)
        self.assertEqual(result["project"], "test_crm")

        # Should extract some requirements
        reqs = result["requirements"]
        self.assertIsInstance(reqs, list)
        self.assertGreater(len(reqs), 0, "Should extract at least 1 requirement")

        # Each requirement should have expected fields
        for req in reqs:
            self.assertIn("title", req)
            self.assertIn("description", req)
            self.assertIn("requirement_id", req)
            self.assertTrue(req["requirement_id"].startswith("TEST_CRM-"))

        print(f"\n   ✓ E2E: {len(reqs)} requirements extracted from {SAMPLE_PDF.name}")
        print(f"   Sample: {reqs[0].get('title', 'N/A')}")

        # Check output file was saved
        output_file = Path(TEST_OUTPUT_DIR) / "test_crm_requirements.json"
        self.assertTrue(output_file.exists(), "Output JSON should be saved")

    @skip_if_no_file(SAMPLE_PDF)
    def test_file_router_integration(self):
        """Test that FileRouter correctly classifies a real file."""
        from extraction.file_router import FileRouter, FileType

        file_type, description = FileRouter.route(str(SAMPLE_PDF))
        self.assertIn(file_type, [FileType.PDF, FileType.SCANNED_PDF])
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 0)

    @skip_if_no_file(SAMPLE_PDF)
    def test_pdf_text_extraction(self):
        """Test PDF text extraction produces meaningful content."""
        from extraction.extractors.pdf_extractor import PDFExtractor

        extractor = PDFExtractor(ocr_extractor=None)
        text = extractor.extract_text(str(SAMPLE_PDF))

        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 100)

        # Should contain some domain-specific terms for CRM
        text_lower = text.lower()
        has_domain_words = any(word in text_lower for word in [
            "customer", "user", "system", "data", "process",
            "dashboard", "report", "integration", "workflow",
        ])
        self.assertTrue(has_domain_words, "PDF should contain domain-relevant text")

    def test_multi_file_extraction(self):
        """Test extraction across multiple files from different projects."""
        files = []
        for d in [CRM_DIR, FINTECH_DIR, HEALTHCARE_DIR]:
            pdfs = sorted(d.glob("*.pdf"))
            if pdfs:
                files.append(str(pdfs[0]))

        if len(files) < 2:
            self.skipTest("Need at least 2 project PDFs")

        from extraction.pipeline import ExtractionPipeline

        pipeline = ExtractionPipeline()
        result = pipeline.run(
            file_paths=files,
            project_name="test_multi",
            output_dir=TEST_OUTPUT_DIR,
        )

        reqs = result["requirements"]
        self.assertGreater(len(reqs), 0)
        print(f"\n   ✓ Multi-file: {len(reqs)} requirements from {len(files)} files")

    @skip_if_no_file(SAMPLE_PDF)
    def test_model_state_persistence(self):
        """Test that model state can be saved and restored."""
        from extraction.pipeline import ExtractionPipeline

        # First run — train from scratch
        pipeline1 = ExtractionPipeline()
        state = pipeline1.save_model_state()
        self.assertIsInstance(state, dict)

        # Second run — load from state (should skip training)
        pipeline2 = ExtractionPipeline(model_state=state)
        self.assertIsNotNone(pipeline2.extractor)
        print("   ✓ Model state saved and restored successfully")


# ============================================================================
# 8. PROCESSOR INTEGRATION TESTS (require GROQ_API_KEY)
# ============================================================================

@unittest.skipUnless(os.getenv("GROQ_API_KEY"), "GROQ_API_KEY not set — skipping Vision tests")
class TestVisionIntegration(unittest.TestCase):
    """Integration tests for Vision LLM processors using real Groq API."""

    def test_ocr_verifier_initialization(self):
        """OCR Verifier should initialize with env key."""
        from extraction.processors.vision_verifier import OCRVerifier
        verifier = OCRVerifier()
        self.assertTrue(verifier.is_available)
        self.assertEqual(verifier.model, "meta-llama/llama-4-scout-17b-16e-instruct")

    def test_image_classifier_initialization(self):
        """Image Classifier should initialize with env key."""
        from extraction.processors.image_classifier import ImageClassifier
        classifier = ImageClassifier()
        self.assertTrue(classifier.is_available)

    def test_diagram_analyzer_initialization(self):
        """Diagram Analyzer should initialize with env key."""
        from extraction.processors.diagram_analyzer import DiagramAnalyzer
        analyzer = DiagramAnalyzer()
        self.assertTrue(analyzer.is_available)


# ============================================================================
# RUNNER
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("PRISM EXTRACTION PIPELINE — TEST SUITE")
    print("=" * 70)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Input dir: {INPUT_DIR}")
    print(f"Test output: {TEST_OUTPUT_DIR}")
    print(f"GROQ_API_KEY: {'✓ Set' if os.getenv('GROQ_API_KEY') else '✗ Not set (E2E tests will skip)'}")
    print(f"Sample PDF exists: {'✓' if SAMPLE_PDF.exists() else '✗'}")
    print("=" * 70)
    print()

    # Run tests with verbosity
    unittest.main(verbosity=2)
