"""
Manual Service — business logic for manual BR extraction.
"""
import logging
import os
import shutil
import tempfile
from pathlib import Path

import utils.s3 as s3
from utils.deduplication import find_duplicates
from utils.java_client import store_draft_requirements
from utils.requirement_mapper import to_payload

logger = logging.getLogger("prism.manual.services.extraction")


async def run_manual_extraction(
    project_id: str, document_url: str, description: str, page_no: int
) -> dict:
    """Download a document and extract requirements with basic Groq LLM."""
    from extraction.manual import ManualExtractor

    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_manual_{os.getpid()}")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = s3.download(document_url, tmp_dir)
        result = ManualExtractor().extract_from_page(local_path, description, page_no)

        if result.get("status") == "success" and result.get("requirements"):
            # Ensure findings ARE saved to DB
            _store_manual_requirements(project_id, result["requirements"], document_url, page_no)
            
        return {
            "status": "success",
            "requirements": result.get("requirements", []),
            "total_extracted": len(result.get("requirements", [])),
            "source_page": page_no,
            "source_file": Path(document_url).name,
            "extraction_method": "basic_groq",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def run_manual_dspy_extraction(
    project_id: str, document_url: str, description: str, page_no: int, tenant_id: str | None = None
) -> dict:
    """
    Download a document, run DSPy extraction on a single page,
    check duplicates, then store results as drafts in the Java backend.
    """
    from extraction.manual_dspy import ManualDSPyExtractor

    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_manual_dspy_{os.getpid()}")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = s3.download(document_url, tmp_dir)

        result = ManualDSPyExtractor().extract_from_page(local_path, description, page_no)

        if result.get("status") != "success" or not result.get("requirements"):
            return result

        requirements, duplicates_count = find_duplicates(project_id, result["requirements"], tenant_id=tenant_id)

        _store_manual_requirements(project_id, requirements, document_url, page_no, tenant_id)

        return {
            "status": "success",
            "requirements": requirements,
            "total_extracted": len(requirements),
            "duplicates_count": duplicates_count,
            "source_page": page_no,
            "source_file": Path(document_url).name,
            "extraction_method": "dspy_trained",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _store_manual_requirements(
    project_id: str, requirements: list, document_url: str, page_no: int, tenant_id: str | None = None
) -> None:
    """Map and store manual requirements as drafts in the Java backend."""
    mapped = []
    for r in requirements:
        # Inject source info into the requirement dict before mapping
        r["source_file"] = document_url
        r["page_start"] = page_no
        r["page_end"] = page_no

        payload = to_payload(r, validation_confirmed=False)

        # Also update the metadata object directly
        if isinstance(payload.get("metadata"), dict):
            payload["metadata"]["source_file"] = document_url
            payload["metadata"]["page_start"] = page_no
            payload["metadata"]["page_end"] = page_no

        mapped.append(payload)

    store_draft_requirements(project_id, mapped, tenant_id)
