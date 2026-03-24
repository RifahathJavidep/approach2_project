"""
Test Case Generation Package (Phase 2)

Generates professional E2E test cases from extracted requirements.

Quick Start:
    from testcase_engine import TestGenPipeline

    pipeline = TestGenPipeline()
    result = pipeline.run(requirements, project_name="my_project")
"""

__version__ = "1.0.0"

from .planner import TestCasePlanner
from .pipeline import TestGenPipeline

__all__ = [
    "TestCasePlanner",
    "TestGenPipeline",
]
