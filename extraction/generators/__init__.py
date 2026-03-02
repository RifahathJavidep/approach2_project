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
    BusinessFeatureExtraction,
    UIRequirementExtraction,
    WorkflowRequirementExtraction,
    TechnicalRequirementExtraction,
    RequirementDeMerger,
    RequirementClassifier,
    RequirementConsolidation,
)
from .trained_extractor import (
    TrainedExtractor,
    BusinessFeatureExtractor,
    UIRequirementExtractor,
    WorkflowRequirementExtractor,
    TechnicalRequirementExtractor,
)
from .training import train_extractor, SKIP_KEYWORDS, POSITIVE_EXAMPLES, NEGATIVE_EXAMPLES
from .postprocessing import deduplicate_requirements, consolidate_requirements, deduplicate_multi_layer_requirements

# Backward compatibility alias
RequirementExtraction = BusinessFeatureExtraction

__all__ = [
    # Signatures
    "BusinessFeatureExtraction",
    "UIRequirementExtraction",
    "WorkflowRequirementExtraction",
    "TechnicalRequirementExtraction",
    "RequirementExtraction",  # Backward compatibility
    "RequirementDeMerger",
    "RequirementClassifier",
    "RequirementConsolidation",
    # Extractors
    "TrainedExtractor",
    "BusinessFeatureExtractor",
    "UIRequirementExtractor",
    "WorkflowRequirementExtractor",
    "TechnicalRequirementExtractor",
    # Training and postprocessing
    "train_extractor",
    "deduplicate_requirements",
    "deduplicate_multi_layer_requirements",
    "consolidate_requirements",
    "SKIP_KEYWORDS",
    "POSITIVE_EXAMPLES",
    "NEGATIVE_EXAMPLES",
]
