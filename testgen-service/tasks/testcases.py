"""
Test Case Celery Task — thin wrapper around the testcase service.
"""
import logging
import os
import sys

from celery_app import app

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logger = logging.getLogger("prism.tasks.testcases")


@app.task(name="generate_testcases_task", bind=True)
def generate_testcases_task(
    self,
    project_id,
    project_name,
    requirements_s3_key=None,
    requirements_data=None,
    local_doc_paths=None,
):
    """Generate test cases from requirements."""
    from services.testcases import _load_requirements, generate_and_store

    self.update_state(state="PROGRESS", meta={"message": "Starting test case generation"})

    requirements = _load_requirements(requirements_data, requirements_s3_key)

    self.update_state(
        state="PROGRESS",
        meta={"message": f"Generating test cases for {len(requirements)} requirements"},
    )

    result = generate_and_store(
        project_id=project_id,
        project_name=project_name,
        requirements=requirements,
        local_doc_paths=local_doc_paths,
    )

    logger.info(
        "Test case generation complete: %d test cases for project %s",
        result["total_test_cases"],
        project_id,
    )
    return result
