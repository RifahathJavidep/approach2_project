import os
import json
import sys
import urllib.parse
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

# 1. Aggressive path setup at module level
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv()

# Logging
import logging
from logging_config import setup_logging
setup_logging("INFO")
logger = logging.getLogger(__name__)

# Initialize Celery
app = Celery('prism',
             broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
             backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'))

from auth_config import get_java_auth_headers

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
)

@app.task(name="extract_requirements_task", bind=True)
def extract_requirements_task(self, project_id, local_files, output_dir, existing_model_state, multi_project_config, file_urls=None, document_statuses=None):
    """
    Background task to extract requirements.
    Updates Java status by ID to prevent duplicate rows.
    """
    # 2. Re-ensure path inside the task to avoid ModuleNotFoundError
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
        
    try:
        from extraction.pipeline import extract_from_files, _get_lm
        from document_status import update_status_by_id, update_document_statuses
    except ImportError as e:
        logger.critical("Path error. sys.path: %s", sys.path)
        raise ImportError(f"Cannot find modules in {BASE_DIR}. Error: {e}")

    import dspy
    self.update_state(state='PROGRESS', meta={'message': 'Starting extraction'})

    # ---------------------------------------------------------
    # Map normalized filename -> Record ID
    # ---------------------------------------------------------
    filename_to_id = {}
    if document_statuses:
        logger.info("Received %d IDs from FastAPI", len(document_statuses))
        for record in document_statuses:
            url = record.get('documentUrl', '')
            doc_id = record.get('id')
            if url and doc_id:
                # Unquote URL to handle %20 etc, then get filename
                clean_url = urllib.parse.unquote(url)
                fname = clean_url.split('/')[-1]
                filename_to_id[fname] = doc_id
        logger.info("Mapped IDs for files: %s", list(filename_to_id.keys()))
    else:
        logger.warning("No IDs received from FastAPI. Status updates will create DUPLICATE rows!")

    def status_callback(file_path, status):
        fname = Path(file_path).name # Already has spaces, not %20
        doc_id = filename_to_id.get(fname)
        
        # Match back to original S3 URL (we need the original for the update body)
        s3_url = None
        if file_urls:
            for url in file_urls:
                clean_u = urllib.parse.unquote(url)
                if fname == clean_u.split('/')[-1]:
                    s3_url = url
                    break

        if doc_id and s3_url:
            logger.info("Updating ID %s (%s) to %s", doc_id, fname, status)
            update_status_by_id(project_id, doc_id, s3_url, status)
        elif s3_url:
            logger.warning("Fallback: Creating new row for %s (ID match failed)", fname)
            update_document_statuses(project_id, [s3_url], status)
        else:
            logger.error("Could not find matching URL for local file: %s", fname)

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

            # Final check to mark all as COMPLETED
            if file_urls:
                for url in file_urls:
                    clean_u = urllib.parse.unquote(url)
                    fname = clean_u.split('/')[-1]
                    doc_id = filename_to_id.get(fname)
                    if doc_id:
                        update_status_by_id(project_id, doc_id, url, "COMPLETED")
                    else:
                        update_document_statuses(project_id, [url], "COMPLETED")

            # ----------------------------------------------------------
            # Automatically store in Java Backend (Postgres)
            # ----------------------------------------------------------
            requirements = result.get("requirements", [])
            if requirements:
                from datetime import datetime
                import requests
                
                try:
                    java_backend_url = f"http://localhost:8080/api/requirements/project/{project_id}"
                    logger.info("Storing %d requirements in Java backend for project %s...", requirements, project_id)
                    print("Storing %d requirements in Java backend for project %s...", requirements, project_id)
                    mapped_requirements = []
                    for req in requirements:
                        conf_val = req.get("confidence", 0.95)
                        conf_str = "high" if conf_val >= 0.8 else "medium" if conf_val >= 0.5 else "low"
                        now_str = datetime.utcnow().isoformat() + "Z"

                        mapped_requirements.append({
                            "is_requirement": True,
                            "short_title": req.get("title") or req.get("feature_name", ""),
                            "description": req.get("description"),
                            "user_story": req.get("user_story", ""),
                            "acceptance_criteria": req.get("acceptance_criteria", []),
                            "test_steps": req.get("test_steps", []),
                            "test_scenarios": req.get("test_scenarios", []),
                            "assumptions": req.get("assumptions", []),
                            "ambiguities": req.get("ambiguities", []),
                            "confidence": conf_str,
                            "extraction_model": "llama-3.3-70b-versatile",
                            "extraction_timestamp": now_str,
                            "validation_confirmed": False,
                            "metadata": {
                                "system": req.get("system", ""),
                                "category": req.get("category", ""),
                                "requirements_text": req.get("requirements_text", ""),
                                "confidence_score": conf_val,
                                "source_file": req.get("source_file", ""),
                                "page_start": req.get("page_start", 0),
                                "page_end": req.get("page_end", 0),
                                "start_line": req.get("line_start", 0),
                                "end_line": req.get("line_end", 0),
                                "verbatim_text": req.get("requirements_text", ""),
                                "supporting_context": req.get("supporting_context", []),
                                "extraction_model": "llama-3.3-70b-versatile",
                                "extraction_timestamp": now_str,
                                "validation_confirmed": False
                            }
                        })
                    logger.info("Mapped requirements: %s", mapped_requirements)
                    java_response = requests.post(
                        java_backend_url, 
                        json=mapped_requirements,
                        headers=get_java_auth_headers(),
                        timeout=30.0
                    )
                    if java_response.status_code in [200, 201]:
                        logger.info("✓ Successfully stored %d requirements in Java backend (Postgres). Response: %s",
                                    len(requirements), java_response.text[:500])
                    else:
                        logger.warning("⚠ Java backend returned error: %s - %s", java_response.status_code, java_response.text)
                except Exception as e:
                    logger.error("⚠ Failed to store in Java backend: %s", e, exc_info=True)

            return {"status": "success", "total": len(requirements)}

    except Exception as e:
        logger.error("Extraction FAILED: %s", e, exc_info=True)
        # Mark all as FAILED in Java
        if file_urls:
            for url in file_urls:
                clean_u = urllib.parse.unquote(url)
                fname = clean_u.split('/')[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_status_by_id(project_id, doc_id, url, "FAILED")
                else:
                    update_document_statuses(project_id, [url], "FAILED")
        raise


@app.task(name="generate_testcases_task", bind=True)
def generate_testcases_task(self, project_id, project_name, requirements_s3_key=None, requirements_data=None, local_doc_paths=None):
    """
    Background task to generate test cases from requirements.
    Supports document context injection for richer test steps.
    """
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    import tempfile

    try:
        from testgen import TestGenPipeline
        from s3_utils import download_json_from_s3, upload_to_s3
    except ImportError as e:
        raise ImportError(f"Cannot find modules in {BASE_DIR}. Error: {e}")

    self.update_state(state='PROGRESS', meta={'message': 'Starting test case generation'})

    # ── Load requirements ──────────────────────────────────────────
    if requirements_data:
        requirements = requirements_data
    elif requirements_s3_key:
        data = download_json_from_s3(requirements_s3_key)
        if isinstance(data, dict):
            requirements = data.get("requirements", [])
        else:
            requirements = data
    else:
        raise ValueError("No requirements provided")

    if not requirements:
        raise ValueError("Requirements list is empty")

    self.update_state(state='PROGRESS', meta={
        'message': f'Generating test cases for {len(requirements)} requirements'
    })

    # ── Run generation ─────────────────────────────────────────────
    output_dir = os.path.join(tempfile.gettempdir(), f"prism_testgen_{project_id}", "output")
    os.makedirs(output_dir, exist_ok=True)

    pipeline = TestGenPipeline()
    result = pipeline.run(
        requirements=requirements,
        project_name=project_name,
        output_dir=output_dir,
        document_paths=local_doc_paths if local_doc_paths else None,
    )

    # ── Upload to S3 ───────────────────────────────────────────────
    s3_json_key = f"projects/{project_id}/output/test_plan.json"
    s3_excel_key = f"projects/{project_id}/output/test_plan.xlsx"

    upload_to_s3(result["json_path"], s3_json_key)
    upload_to_s3(result["excel_path"], s3_excel_key)

    bucket = os.getenv("S3_BUCKET_NAME", "katsuai-tcgen")

    # ── Store in Java Backend (Katsu Specification) ────────────────
    try:
        import requests
        # Updated URL as per User's specification
        java_url = f"http://localhost:8080/projects/{project_id}/test-cases"
        
        test_plans = result["test_plan"].get("test_plans", [])

        # Flatten all test cases into a single list
        # They are already in TestCaseEditorDTO format from the planner
        all_test_cases = []
        for plan in test_plans:
            all_test_cases.extend(plan.get("test_cases", []))

        if all_test_cases:
            logger.info("Uploading %d test cases to Java backend: %s", len(all_test_cases), java_url)
            resp = requests.post(java_url, json=all_test_cases, headers=get_java_auth_headers(), timeout=30.0)
            if resp.status_code in [200, 201]:
                logger.info("✓ Successfully uploaded test cases. Response: %s", resp.text[:500])
            else:
                logger.warning("⚠ Java backend error (%s): %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("⚠ Failed to store test cases in Java backend: %s", e, exc_info=True)

    return {
        "status": "success",
        "total_requirements": result["total_requirements"],
        "total_test_cases": result["total_test_cases"],
        "s3_output": {
            "json": f"s3://{bucket}/{s3_json_key}",
            "excel": f"s3://{bucket}/{s3_excel_key}",
        },
    }


@app.task(name="extract_and_filter_duplicates_task", bind=True)
def extract_and_filter_duplicates_task(self, project_id, local_files, output_dir, project_name="Project", file_urls=None, document_statuses=None):
    """
    CLEAN EXTRACTION FLOW:
    1. Extract requirements from files.
    2. Fetch PREVIOUSLY created BRs from Java backend.
    3. Remove duplicates using Cosine Similarity.
    4. Store only UNIQUE BRs in database.
    """
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    try:
        from extraction.pipeline import extract_from_files, _get_lm
        from document_status import update_status_by_id, update_document_statuses
        from duplication_service import filter_unique_requirements
        from datetime import datetime
        import requests
        import dspy
    except ImportError as e:
        raise ImportError(f"Cannot find modules in {BASE_DIR}. Error: {e}")

    self.update_state(state='PROGRESS', meta={'message': 'Starting clean extraction'})

    # ---------------------------------------------------------
    # Status Management (Mapping IDs)
    # ---------------------------------------------------------
    filename_to_id = {}
    if document_statuses:
        for record in document_statuses:
            url = record.get('documentUrl', '')
            doc_id = record.get('id')
            if url and doc_id:
                clean_url = urllib.parse.unquote(url)
                fname = clean_url.split('/')[-1]
                filename_to_id[fname] = doc_id

    def status_callback(file_path, status):
        fname = Path(file_path).name
        doc_id = filename_to_id.get(fname)
        s3_url = next((u for u in file_urls if fname in urllib.parse.unquote(u)), None) if file_urls else None
        if doc_id and s3_url:
            update_status_by_id(project_id, doc_id, s3_url, status)

    try:
        # Step 1: Run Extraction
        with dspy.context(lm=_get_lm()):
            result = extract_from_files(
                project_name=project_id,
                file_paths=local_files,
                output_dir=output_dir,
                status_callback=status_callback,
            )

        extracted_reqs = result.get("requirements", [])
        if not extracted_reqs:
            return {"status": "success", "message": "No requirements found on page", "stored_count": 0}

        # Step 2: Fetch and Filter Duplicates (REMOVE duplicates)
        self.update_state(state='PROGRESS', meta={'message': 'Filtering duplicate requirements'})
        unique_reqs = filter_unique_requirements(
            project_id=project_id,
            new_requirements=extracted_reqs,
            threshold=0.85
        )

        # Step 3: Store ONLY UNIQUE BRs as drafts
        if unique_reqs:
            java_backend_url = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")
            java_url = f"{java_backend_url}/api/requirements/project/{project_id}"
            now = datetime.now().isoformat()
            
            mapped = []
            for r in unique_reqs:
                conf_val = r.get("confidence", 0.95)
                conf_str = "high" if conf_val >= 0.8 else "medium" if conf_val >= 0.5 else "low"
                now_str = datetime.now().isoformat() + "Z"

                mapped.append({
                    "is_requirement": True,
                    "short_title": r.get("title") or r.get("feature_name", ""),
                    "description": r.get("description", ""),
                    "user_story": r.get("user_story", ""),
                    "acceptance_criteria": r.get("acceptance_criteria", []),
                    "test_steps": r.get("test_steps", []),
                    "test_scenarios": r.get("test_scenarios", []),
                    "assumptions": r.get("assumptions", []),
                    "ambiguities": r.get("ambiguities", []),
                    "confidence": conf_str,
                    "extraction_model": "llama-3.3-70b-versatile",
                    "extraction_timestamp": now_str,
                    "validation_confirmed": True,
                    "metadata": {
                        "system": r.get("system", ""),
                        "category": r.get("category", ""),
                        "requirements_text": r.get("requirements_text", ""),
                        "confidence_score": conf_val,
                        "source_file": r.get("source_file", ""),
                        "page_start": r.get("page_start", 0),
                        "page_end": r.get("page_end", 0),
                        "start_line": r.get("line_start", 0),
                        "end_line": r.get("line_end", 0),
                        "verbatim_text": r.get("requirements_text", ""),
                        "supporting_context": r.get("supporting_context", []),
                        "extraction_model": "llama-3.3-70b-versatile",
                        "extraction_timestamp": now_str,
                        "validation_confirmed": True
                    }
                })

            resp = requests.post(java_url, json=mapped, headers=get_java_auth_headers(), timeout=30)
            logger.info("Filtered %d → %d unique. Stored in Java backend (project %s). Response: %s",
                        len(extracted_reqs), len(unique_reqs), project_id, resp.text[:500])

        # Step 4: Finalize Document Status
        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split('/')[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_status_by_id(project_id, doc_id, url, "COMPLETED")

        # ----------------------------------------------------------
        # STEP 5: AUTOMATIC TEST CASE GENERATION TRIGGER
        # ----------------------------------------------------------
        if unique_reqs:
            logger.info(">>> Auto-triggering Test Case Generation for project %s", project_id)
            # We pass the local_files for context and the unique_reqs directly to avoid re-downloading
            generate_testcases_task.delay(
                project_id=project_id,
                project_name=f"Project_{project_id}",
                requirements_data=unique_reqs,
                local_doc_paths=local_files
            )

        return {
            "status": "success",
            "extracted": len(extracted_reqs),
            "stored_unique": len(unique_reqs),
            "removed_duplicates": len(extracted_reqs) - len(unique_reqs),
            "tc_generation_triggered": bool(unique_reqs)
        }

    except Exception as e:
        logger.error("Clean Async Extraction Failed: %s", e, exc_info=True)
        if file_urls:
            for url in file_urls:
                fname = urllib.parse.unquote(url).split('/')[-1]
                doc_id = filename_to_id.get(fname)
                if doc_id:
                    update_status_by_id(project_id, doc_id, url, "FAILED")
        raise e
