"""
Extraction Celery tasks — thin wrappers around the extraction pipeline.
All business logic lives in services/extraction.py and extraction/.
"""
import logging
import os
import sys
import urllib.parse
from pathlib import Path

import dspy
from celery_app import app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logger = logging.getLogger("prism.tasks.extraction")

@app.task(name="extract_requirements_task", bind=True)
def extract_requirements_task(
    self,
    project_id,
    local_files,
    output_dir,
    existing_model_state,
    multi_project_config,
    file_urls=None,
    document_statuses=None,
):
    """Extract requirements and store them in the Java backend."""
    from extraction.pipeline import extract_from_files, _get_lm
    from utils.java_client import update_document_status, store_requirements
    from utils.requirement_mapper import to_payload

    self.update_state(state="PROGRESS", meta={"message": "Starting extraction"})

    filename_to_id = _build_filename_id_map(document_statuses)

    def status_callback(file_path, status):
        _update_file_status(project_id, file_path, status, filename_to_id, file_urls)

    try:
        with dspy.context(lm=_get_lm()):
            result = extract_from_files(
                project_name=project_id,
                file_paths=local_files,
                output_dir=output_dir,
                model_state=existing_model_state,
                config=multi_project_config,
                status_callback=status_callback,
            )

        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "COMPLETED")

        requirements = result.get("requirements", [])
        if requirements:
            mapped = [to_payload(r, validation_confirmed=False) for r in requirements]
            store_requirements(project_id, mapped)

        return {"status": "success", "total": len(requirements)}

    except Exception as e:
        logger.error("Extraction failed: %s", e, exc_info=True)
        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "FAILED")
        raise

@app.task(name="extract_and_filter_duplicates_task", bind=True)
def extract_and_filter_duplicates_task(
    self,
    project_id,
    local_files,
    output_dir,
    project_name="Project",
    file_urls=None,
    document_statuses=None,
):
    """
    Full extraction flow:
      1. Extract requirements.
      2. Filter duplicates via cosine similarity.
      3. Store unique requirements in Java backend.
      4. Mark files COMPLETED.
      5. Auto-trigger test case generation.
    """
    from extraction.pipeline import extract_from_files, _get_lm
    from utils.java_client import update_document_status, store_requirements
    from utils.deduplication import filter_unique
    from utils.requirement_mapper import to_payload
    from tasks.testcases import generate_testcases_task

    self.update_state(state="PROGRESS", meta={"message": "Starting extraction"})

    filename_to_id = _build_filename_id_map(document_statuses)

    def status_callback(file_path, status):
        _update_file_status(project_id, file_path, status, filename_to_id, file_urls)

    try:
        with dspy.context(lm=_get_lm()):
            result = extract_from_files(
                project_name=project_id,
                file_paths=local_files,
                output_dir=output_dir,
                status_callback=status_callback,
            )

        extracted = result.get("requirements", [])
        if not extracted:
            return {"status": "success", "message": "No requirements found", "stored_count": 0}

        self.update_state(state="PROGRESS", meta={"message": "Filtering duplicates"})
        unique = filter_unique(project_id=project_id, new_requirements=extracted, threshold=0.85)

        if unique:
            mapped = [to_payload(r) for r in unique]
            store_requirements(project_id, mapped)
            logger.info(
                "Stored %d unique requirements (%d filtered) for project %s",
                len(unique), len(extracted) - len(unique), project_id,
            )

        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "COMPLETED")

        if unique:
            logger.info("Auto-triggering test case generation for project %s", project_id)
            generate_testcases_task.delay(
                project_id=project_id,
                project_name=project_name,
                requirements_data=unique,
                local_doc_paths=local_files,
            )

        return {
            "status": "success",
            "extracted": len(extracted),
            "stored_unique": len(unique),
            "removed_duplicates": len(extracted) - len(unique),
            "tc_generation_triggered": bool(unique),
        }

    except Exception as e:
        logger.error("Extraction failed: %s", e, exc_info=True)
        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "FAILED")
        raise

def _build_filename_id_map(document_statuses: list) -> dict:
    """Build a filename → document_status_id map from the status records."""
    if not document_statuses:
        return {}
    result = {}
    for record in document_statuses:
        url = record.get("documentUrl", "")
        doc_id = record.get("id")
        if url and doc_id:
            fname = urllib.parse.unquote(url).split("/")[-1]
            result[fname] = doc_id
    return result

def _update_file_status(project_id, file_path, status, filename_to_id, file_urls):
    """Update a single file's document status in the Java backend."""
    from utils.java_client import update_document_status
    fname = Path(file_path).name
    doc_id = filename_to_id.get(fname)
    s3_url = next(
        (u for u in (file_urls or []) if fname in urllib.parse.unquote(u)),
        None,
    )
    if doc_id and s3_url:
        update_document_status(project_id, doc_id, s3_url, status)
