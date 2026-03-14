"""
Test Case Service — Phase 2 orchestration.

Handles optional document context download, TestGenPipeline execution,
S3 result upload, and test case storage in the Java backend.
"""
import logging
import os
import shutil
import tempfile

import utils.s3 as s3
from utils.java_client import get_headers, store_test_cases

logger = logging.getLogger("prism.services.testcases")

async def queue_testcase_generation(
    project_id: str,
    project_name: str,
    requirements_s3_key: str = None,
    requirements: list = None,
    document_urls: list = None,
) -> dict:
    """Queue a Celery task for async test case generation."""
    from tasks.testcases import generate_testcases_task

    local_docs = _download_context_docs(
        document_urls or [],
        os.path.join(tempfile.gettempdir(), f"prism_testgen_{project_id}"),
    )

    task = generate_testcases_task.delay(
        project_id=project_id,
        project_name=project_name,
        requirements_s3_key=requirements_s3_key,
        requirements_data=requirements,
        local_doc_paths=local_docs if local_docs else None,
    )

    logger.info("Test case generation task queued: task_id=%s", task.id)
    return {
        "status": "accepted",
        "task_id": task.id,
        "message": "Test case generation queued successfully",
        "documents_loaded": len(local_docs),
    }

async def run_testcase_generation_sync(
    project_id: str,
    project_name: str,
    requirements_s3_key: str = None,
    requirements: list = None,
    document_urls: list = None,
) -> dict:
    """Run test case generation synchronously and return results immediately."""
    from testgen import TestGenPipeline

    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_testgen_{project_id}_{os.getpid()}")
    try:
        reqs = _load_requirements(requirements, requirements_s3_key)
        local_docs = _download_context_docs(document_urls or [], tmp_dir)

        output_dir = os.path.join(tmp_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        result = TestGenPipeline().run(
            requirements=reqs,
            project_name=project_name,
            output_dir=output_dir,
            document_paths=local_docs or None,
        )

        s3_urls = _upload_results(project_id, result)
        store_test_cases(project_id, _flatten_test_cases(result))

        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": result["total_requirements"],
            "total_test_cases": result["total_test_cases"],
            "test_plan": result["test_plan"],
            "s3_output": s3_urls,
            "documents_used": len(local_docs),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def get_cached_testplan(project_id: str) -> dict:
    """Fetch the last test plan from S3. Raises FileNotFoundError if absent."""
    s3_key = f"projects/{project_id}/output/test_plan.json"
    if not s3.exists(s3_key):
        raise FileNotFoundError(f"No test plan found for project '{project_id}'")
    return s3.download_json(s3_key)

def generate_and_store(
    project_id: str,
    project_name: str,
    requirements: list,
    local_doc_paths: list = None,
) -> dict:
    """Run the test gen pipeline, upload results to S3, and store in Java backend."""
    from testgen import TestGenPipeline

    output_dir = os.path.join(tempfile.gettempdir(), f"prism_testgen_{project_id}", "output")
    os.makedirs(output_dir, exist_ok=True)

    result = TestGenPipeline().run(
        requirements=requirements,
        project_name=project_name,
        output_dir=output_dir,
        document_paths=local_doc_paths or None,
    )

    s3_urls = _upload_results(project_id, result)
    store_test_cases(project_id, _flatten_test_cases(result))

    return {
        "status": "success",
        "total_requirements": result["total_requirements"],
        "total_test_cases": result["total_test_cases"],
        "s3_output": s3_urls,
    }

def _load_requirements(requirements: list, requirements_s3_key: str) -> list:
    """Load requirements from direct list or from an S3 JSON file."""
    if requirements:
        return requirements
    if requirements_s3_key:
        data = s3.download_json(requirements_s3_key)
        return data.get("requirements", []) if isinstance(data, dict) else data
    raise ValueError("No requirements provided")

def _download_context_docs(document_urls: list, tmp_dir: str) -> list:
    """Download source documents for context injection. Failures are non-fatal."""
    if not document_urls:
        return []
    os.makedirs(tmp_dir, exist_ok=True)
    local_docs = []
    for url in document_urls:
        try:
            local_docs.append(s3.download(url, tmp_dir))
        except Exception as e:
            logger.warning("Could not download document %s for context: %s", url, e)
    return local_docs

def _flatten_test_cases(result: dict) -> list:
    """Extract a flat list of test cases from the test_plan result dict."""
    all_test_cases = []
    for plan in result.get("test_plan", {}).get("test_plans", []):
        all_test_cases.extend(plan.get("test_cases", []))
    return all_test_cases

def _upload_results(project_id: str, result: dict) -> dict:
    """Upload JSON and Excel test plan to S3. Returns S3 URL dict."""
    json_key = f"projects/{project_id}/output/test_plan.json"
    excel_key = f"projects/{project_id}/output/test_plan.xlsx"
    s3.upload(result["json_path"], json_key)
    s3.upload(result["excel_path"], excel_key)
    bucket = s3.get_bucket()
    return {
        "json": f"s3://{bucket}/{json_key}",
        "excel": f"s3://{bucket}/{excel_key}",
    }
