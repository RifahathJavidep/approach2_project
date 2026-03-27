"""
Extraction Celery tasks — thin wrappers around the requirement extraction pipeline.
All business logic lives in services/extraction.py and requirement_engine/.
"""
import logging
import os
import sys
import urllib.parse
from pathlib import Path

import dspy
import requests
from celery_app import app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logger = logging.getLogger("prism.tasks.requirement_engine")

TESTGEN_SERVICE_URL = os.getenv("TESTGEN_SERVICE_URL", "http://localhost:8002")


@app.task(name="extract_requirements_task", bind=True)
def extract_requirements_task(
    self,
    team_id,
    project_id,
    local_files,
    output_dir,
    existing_model_state,
    multi_project_config,
    file_urls=None,
    document_statuses=None,
    tenant_id=None,
):
    """Extract requirements and store them in the Java backend."""
    from requirement_engine.pipeline import extract_from_files, _get_lm
    from common.java_client import update_document_status, store_requirements
    from common.requirement_mapper import to_payload

    self.update_state(state="PROGRESS", meta={"message": "Starting requirement_engine"})

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
                    update_document_status(project_id, doc_id, url, "COMPLETED", tenant_id)

        requirements = result.get("requirements", [])
        if requirements:
            mapped = [to_payload(r, validation_confirmed=False) for r in requirements]
            store_requirements(team_id, project_id, mapped, tenant_id)

        return {"status": "success", "total": len(requirements)}

    except Exception as e:
        logger.error("Extraction failed: %s", e, exc_info=True)
        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "FAILED", tenant_id)
        raise


@app.task(name="extract_and_filter_duplicates_task", bind=True)
def extract_and_filter_duplicates_task(
    self,
    team_id,
    project_id,
    local_files,
    output_dir,
    project_name="Project",
    file_urls=None,
    document_statuses=None,
    tenant_id=None,
    document_tiers=None,
):
    """
    Full requirement_engine flow:
      1. Extract requirements.
      2. Filter duplicates via cosine similarity.
      3. Store unique requirements in Java backend.
      4. Mark files COMPLETED.
      5. Trigger test case generation via HTTP call to testcase_engine-service.
    """
    from requirement_engine.pipeline import extract_from_files, _get_lm
    from common.java_client import update_document_status, store_requirements
    from common.deduplication import filter_unique
    from common.requirement_mapper import to_payload

    self.update_state(state="PROGRESS", meta={"message": "Starting requirement_engine"})

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
                document_tiers=document_tiers,
            )

        extracted = result.get("requirements", [])
        if not extracted:
            return {"status": "success", "message": "No requirements found", "stored_count": 0}

        self.update_state(state="PROGRESS", meta={"message": "Filtering duplicates"})
        unique = filter_unique(team_id=team_id, project_id=project_id, new_requirements=extracted, threshold=0.85, tenant_id=tenant_id)

        if unique:
            mapped = [to_payload(r) for r in unique]
            store_requirements(team_id, project_id, mapped, tenant_id)
            logger.info(
                "Stored %d unique requirements (%d filtered) for project %s",
                len(unique), len(extracted) - len(unique), project_id,
            )

        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "COMPLETED", tenant_id)

        # Automatic test generation disabled per user request
        # if unique:
        #     _trigger_testgen(team_id, project_id, project_name, unique, tenant_id)

        return {
            "status": "success",
            "extracted": len(extracted),
            "stored_unique": len(unique),
            "removed_duplicates": len(extracted) - len(unique),
            "tc_generation_triggered": False,
        }

    except Exception as e:
        logger.error("Extraction failed: %s", e, exc_info=True)
        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split("/")[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_document_status(project_id, doc_id, url, "FAILED", tenant_id)
        raise


def _trigger_testgen(
    team_id: str, project_id: str, project_name: str,
    requirements: list, tenant_id: str | None = None,
) -> None:
    """POST to testcase_engine-service to kick off test case generation. Failure is logged, not raised."""
    from common.java_client import get_headers
    try:
        headers = get_headers(tenant_id)
        url = f"{TESTGEN_SERVICE_URL}/teams/{team_id}/projects/{project_id}/generate-testcases"
        resp = requests.post(
            url,
            json={
                "project_id": project_id,
                "project_name": project_name,
                "requirements": requirements,
            },
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            task_id = resp.json().get("task_id", "unknown")
            logger.info("TestGen triggered for project %s (task_id=%s)", project_id, task_id)
        else:
            logger.warning("TestGen service returned %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.warning("Could not reach testcase_engine-service for project %s: %s", project_id, e)


@app.task(name="upload_document_to_s3_task", bind=True)
def upload_document_to_s3_task(self, tmp_path: str, s3_key: str, original_filename: str):
    """
    Async Celery task: upload a file from a local temp path to S3, then clean up.
    The HTTP endpoint returns immediately with a task_id; this runs in the background.
    """
    import common.s3_client as s3_client

    self.update_state(state="PROGRESS", meta={"message": f"Uploading {original_filename} to S3"})
    try:
        s3_url = s3_client.upload(tmp_path, s3_key)
        logger.info("Async upload complete: %s → %s", original_filename, s3_url)
        return {
            "status": "success",
            "filename": original_filename,
            "s3_key": s3_key,
            "s3_url": s3_url,
        }
    except Exception as e:
        logger.error("Async S3 upload failed for %s: %s", original_filename, e, exc_info=True)
        raise
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _build_filename_id_map(document_statuses: list) -> dict:
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
    from common.java_client import update_document_status
    fname = Path(file_path).name
    doc_id = filename_to_id.get(fname)
    s3_url = next(
        (u for u in (file_urls or []) if fname in urllib.parse.unquote(u)),
        None,
    )
    if doc_id and s3_url:
        update_document_status(project_id, doc_id, s3_url, status)
