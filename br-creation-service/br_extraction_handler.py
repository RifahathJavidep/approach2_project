"""
Extraction Service — Phase 1 orchestration.

Handles parallel S3 downloads, document dedup checks, Celery task dispatch,
manual requirement_engine flows, and requirement storage to the Java backend.
"""
import logging
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import common.s3_client as s3
from config import settings
from common.deduplication import find_duplicates
from common.java_client import create_document_statuses, store_requirements
from common.requirement_mapper import to_payload
from document_handler import is_already_processed
from br_extraction_task import extract_and_filter_duplicates_task
from requirement_engine.manual import ManualExtractor
from requirement_engine.manual_dspy import ManualDSPyExtractor


logger = logging.getLogger("prism.services.requirement_engine")


async def queue_extraction(
    team_id: str,
    project_id: str,
    project_name: str,
    file_urls: list,
    tenant_id: str | None = None,
) -> dict:
    """
    Download files from S3 in parallel, set PENDING status,
    then dispatch a Celery task. Returns task_id and document status records.
    """

    if is_already_processed(project_id, file_urls):
        logger.warning("Documents already processed for project %s", project_id)
        return {
            "status": "conflict",
            "message": "This document has already been uploaded and processed for this project.",
            "document_urls": file_urls,
        }

    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_{project_id}")
    input_dir = os.path.join(tmp_dir, "input")
    output_dir = os.path.join(tmp_dir, "output")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    local_files = _download_parallel(file_urls, input_dir)

    if not local_files:
        raise ValueError("Failed to download any files from S3")

    document_statuses = create_document_statuses(project_id, file_urls, "PENDING", tenant_id)
    logger.info("Queuing requirement_engine: project=%s, files=%d", project_id, len(local_files))

    task = extract_and_filter_duplicates_task.delay(
        team_id=team_id,
        project_id=project_id,
        project_name=project_name,
        local_files=local_files,
        output_dir=output_dir,
        file_urls=file_urls,
        document_statuses=document_statuses,
        tenant_id=tenant_id,
    )

    logger.info("Extraction task queued: task_id=%s", task.id)
    return {
        "status": "accepted",
        "task_id": task.id,
        "message": "Extraction queued. Duplicates will be filtered before storage.",
        "document_statuses": document_statuses,
    }


def get_cached_requirements(project_id: str) -> dict:
    """Fetch the last requirement_engine result from S3. Raises FileNotFoundError if absent."""
    s3_key = f"projects/{project_id}/output/requirements.json"
    if not s3.exists(s3_key):
        raise FileNotFoundError(f"No requirements found for project '{project_id}'")
    return s3.download_json(s3_key)


async def run_manual_extraction(
    team_id: str,
    project_id: str,
    document_url: str,
    description: str,
    page_no: int,
    tenant_id: str | None = None,
) -> dict:
    """Download a document and extract a single requirement with basic Groq LLM."""

    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_manual_{os.getpid()}")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = s3.download(document_url, tmp_dir)
        result = ManualExtractor().extract_from_page(local_path, description, page_no)

        if result.get("status") == "success" and result.get("requirements"):
            _store_manual_requirements(team_id, project_id, result["requirements"], document_url, page_no, tenant_id)

        return result
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def run_manual_dspy_extraction(
    team_id: str,
    project_id: str,
    document_url: str,
    description: str,
    page_no: int,
    tenant_id: str | None = None,
) -> dict:
    """
    Download a document, run DSPy requirement_engine on a single page,
    check duplicates, then store results in the Java backend.
    """

    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_manual_dspy_{os.getpid()}")
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = s3.download(document_url, tmp_dir)

        result = ManualDSPyExtractor().extract_from_page(local_path, description, page_no)

        if result.get("status") != "success" or not result.get("requirements"):
            return result

        requirements, duplicates_count = find_duplicates(project_id, result["requirements"], tenant_id=tenant_id)

        _store_manual_requirements(team_id, project_id, requirements, document_url, page_no, tenant_id)

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
    team_id: str,
    project_id: str,
    requirements: list,
    document_url: str,
    page_no: int,
    tenant_id: str | None = None,
) -> None:
    mapped = []
    for r in requirements:
        payload = to_payload(r, validation_confirmed=False)
        payload["metadata"]["source_file"] = document_url
        payload["metadata"]["page_start"] = page_no
        payload["metadata"]["page_end"] = page_no
        mapped.append(payload)

    store_requirements(team_id, project_id, mapped, tenant_id)


def _download_parallel(file_urls: list, target_dir: str) -> list:
    """Download S3 files in parallel (up to 5 workers). Returns local paths."""
    local_files = []
    with ThreadPoolExecutor(max_workers=min(len(file_urls), settings.MAX_DOWNLOAD_WORKERS)) as pool:
        futures = {pool.submit(s3.download, url, target_dir): url for url in file_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                local_files.append(future.result())
                logger.info("Downloaded %s", url)
            except Exception as e:
                logger.error("Failed to download %s: %s", url, e, exc_info=True)
    return local_files
