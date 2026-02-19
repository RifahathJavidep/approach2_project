"""
Requirements Extraction — Backward Compatibility Wrapper

This file re-exports the public API from the new `extraction` package
so that existing consumers (app.py, celery_app.py) continue to work
without any import changes.

The original monolithic logic has been refactored into:
    extraction/
        file_router.py       — Stage 1: File classification
        extractors/          — Stage 2: Content extraction
        processors/          — Image processing pipeline
        generators/          — Stage 3: DSPy requirement generation
        pipeline.py          — Master orchestrator
        utils.py             — Shared utilities

Usage (unchanged for existing code):
    from extract_requirements import extract_from_files, _get_lm
"""

# Re-export the main functions used by app.py and celery_app.py
from extraction.pipeline import (
    extract_from_files,
    extract_requirements,
    _get_lm,
    ExtractionPipeline,
)

# Re-export DSPy components for training/evaluation scripts
from extraction.generators.signatures import (
    RequirementExtraction,
    RequirementClassifier,
    RequirementDeMerger,
    RequirementConsolidation,
)
from extraction.generators.trained_extractor import TrainedExtractor
from extraction.generators.training import (
    train_extractor,
    POSITIVE_EXAMPLES,
    NEGATIVE_EXAMPLES,
    SKIP_KEYWORDS,
)
from extraction.generators.postprocessing import (
    deduplicate_requirements,
    consolidate_requirements,
)
from extraction.utils import chunk_document

import sys

def main():
    try:
        extract_requirements()
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
