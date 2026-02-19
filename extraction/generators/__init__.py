"""
Generators Package — Stage 3 AI Requirement Generation

DSPy-powered requirement extraction, classification, and consolidation.

Modules:
    signatures: DSPy Signature definitions
    trained_extractor: TrainedExtractor dspy.Module
    training: Training logic with BootstrapFewShot
    postprocessing: Deduplication and LLM consolidation
"""

from .signatures import (
    RequirementExtraction,
    RequirementDeMerger,
    RequirementClassifier,
    RequirementConsolidation,
)
from .trained_extractor import TrainedExtractor
from .training import train_extractor, SKIP_KEYWORDS, POSITIVE_EXAMPLES, NEGATIVE_EXAMPLES
from .postprocessing import deduplicate_requirements, consolidate_requirements

__all__ = [
    "RequirementExtraction",
    "RequirementDeMerger",
    "RequirementClassifier",
    "RequirementConsolidation",
    "TrainedExtractor",
    "train_extractor",
    "deduplicate_requirements",
    "consolidate_requirements",
    "SKIP_KEYWORDS",
    "POSITIVE_EXAMPLES",
    "NEGATIVE_EXAMPLES",
]
