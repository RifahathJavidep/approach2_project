"""
Extraction Package — Modular Requirement Extraction Pipeline

This package provides a professional 3-stage pipeline:
    Stage 1: File classification (FileRouter)
    Stage 2: Content requirement_engine (PDF, DOCX, PPTX, Image, OCR)
    Stage 3: AI-powered requirement generation (DSPy)

Quick Start:
    from requirement_engine import ExtractionPipeline

    pipeline = ExtractionPipeline(config=config)
    result = pipeline.run(file_paths, project_name="my_project")
"""

__version__ = "1.0.0"

from .file_router import FileRouter, FileType
from .pipeline import ExtractionPipeline
from .manual import ManualExtractor
from .manual_dspy import ManualDSPyExtractor

__all__ = [
    "FileRouter",
    "FileType",
    "ExtractionPipeline",
    "ManualExtractor",
    "ManualDSPyExtractor",
]
