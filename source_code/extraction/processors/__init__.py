"""
Processors Package — Image Processing Pipeline

Handles the processing of embedded and standalone images:
    1. vision_verifier: Corrects OCR errors using Vision LLM
    2. image_classifier: Classifies images as workflow diagrams vs informational
    3. diagram_analyzer: Extracts structured info from workflow diagrams
"""

from .vision_verifier import OCRVerifier
from .image_classifier import ImageClassifier
from .diagram_analyzer import DiagramAnalyzer

__all__ = [
    "OCRVerifier",
    "ImageClassifier",
    "DiagramAnalyzer",
]
