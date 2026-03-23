"""
Extraction Pipeline — v4.0 Enrichment-Pass

Uses the v4.0 BR extractor (Archive-01 document-tier aware extraction via DSPy).

Example:
    from extraction import ExtractionPipeline

    pipeline = ExtractionPipeline(config=config)
    result = pipeline.run(file_paths=["doc.pdf", "pres.pptx"], project_name="my_project")
"""

import json
import logging
import os
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any

from .generators.v4_br_extractor import extract_requirements as v4_extract_requirements

logger = logging.getLogger("prism.pipeline")

_CONFIDENCE_MAP = {'high': 0.9, 'medium': 0.6, 'low': 0.3}

def _confidence_to_float(conf) -> float:
    """Convert confidence value to float. Handles both string and numeric."""
    if isinstance(conf, (int, float)):
        return float(conf)
    if isinstance(conf, str):
        return _CONFIDENCE_MAP.get(conf.lower().strip(), 0.6)
    return 0.6


class ExtractionPipeline:
    """
    Master orchestrator for the v4.0 requirement extraction pipeline.

    Uses the document-tier aware v4.0 BR extractor (DSPy + Groq).

    Attributes:
        config: Multi-project configuration dictionary
    """

    def __init__(self, config: Optional[Dict] = None, model_state: Optional[Dict] = None):
        self.config = config or {}

    def _convert_v4_requirements(self, br_list, project_name):
        """Convert v4.0 BusinessRequirement objects to the standard dict format."""
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

    def run(self, file_paths: List[str], project_name: str, output_dir: Optional[str] = None,
            status_callback: Optional[Callable[[str, str], None]] = None,
            document_tiers: Optional[Dict[str, str]] = None) -> Dict:
        """
        Run the v4.0 extraction pipeline on a list of files.

        Args:
            file_paths: List of local file paths to process
            project_name: Project identifier (e.g. 'ptw_phase1')
            output_dir: Optional directory to save results locally
            status_callback: Optional callback(file_path, status)
            document_tiers: Optional dict mapping filename -> tier (primary/supporting)

        Returns:
            Dict with 'project', 'requirements', and 'model_state'
        """
        logger.info("=" * 80)
        logger.info("REQUIREMENTS EXTRACTION (v4.0) - %s", str(project_name).upper())
        logger.info("=" * 80)

        with tempfile.TemporaryDirectory() as tmp_dir:
            for fp in file_paths:
                shutil.copy2(fp, tmp_dir)
            br_list = v4_extract_requirements(input_dir=tmp_dir, document_tiers=document_tiers)

        unique = self._convert_v4_requirements(br_list, project_name)

        result_data = {
            'project': project_name,
            'requirements': unique,
            'model_state': {},
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_file = Path(output_dir) / f"{project_name}_requirements.json"
            with open(output_file, 'w') as f:
                json.dump(result_data, f, indent=2)
            logger.info("Saved locally to: %s", output_file)

        logger.info("Done! %d requirements extracted (v4.0 mode)", len(unique))
        return result_data


def extract_from_files(
    project_name: str,
    file_paths: List[str],
    output_dir: Optional[str] = None,
    model_state: Optional[Dict] = None,
    config: Optional[Dict] = None,
    status_callback: Optional[Callable[[str, str], None]] = None,
    document_tiers: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Extract requirements from a list of local file paths.
    Called by FastAPI after downloading files from S3.
    """
    pipeline = ExtractionPipeline(config=config, model_state=model_state)
    return pipeline.run(file_paths=file_paths, project_name=project_name, output_dir=output_dir,
                        status_callback=status_callback, document_tiers=document_tiers)
