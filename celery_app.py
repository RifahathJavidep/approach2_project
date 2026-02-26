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

# Initialize Celery
app = Celery('prism',
             broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
             backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'))

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
        print(f"  [Celery] CRITICAL: Path error. sys.path: {sys.path}")
        raise ImportError(f"Cannot find modules in {BASE_DIR}. Error: {e}")

    import dspy
    self.update_state(state='PROGRESS', meta={'message': 'Starting extraction'})

    # ---------------------------------------------------------
    # Map normalized filename -> Record ID
    # ---------------------------------------------------------
    filename_to_id = {}
    if document_statuses:
        print(f"  [Celery] Received {len(document_statuses)} IDs from FastAPI")
        for record in document_statuses:
            url = record.get('documentUrl', '')
            doc_id = record.get('id')
            if url and doc_id:
                # Unquote URL to handle %20 etc, then get filename
                clean_url = urllib.parse.unquote(url)
                fname = clean_url.split('/')[-1]
                filename_to_id[fname] = doc_id
        print(f"  [Celery] Mapped IDs for files: {list(filename_to_id.keys())}")
    else:
        print("  [Celery] WARNING: No IDs received from FastAPI. Status updates will create DUPLICATE rows!")

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
            print(f"  [Celery] Updating ID {doc_id} ({fname}) to {status}")
            update_status_by_id(project_id, doc_id, s3_url, status)
        elif s3_url:
            print(f"  [Celery] Fallback: Creating new row for {fname} (ID match failed)")
            update_document_statuses(project_id, [s3_url], status)
        else:
            print(f"  [Celery] ERROR: Could not find matching URL for local file: {fname}")

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
                    print(f"\n  [Celery] Storing {len(requirements)} requirements in Java backend...")
                    
                    mapped_requirements = []
                    for req in requirements:
                        mapped_requirements.append({
                            "short_title": req.get("title") or req.get("short_title"),
                            "description": req.get("description"),
                            "is_requirement": True,
                            "user_story": req.get("user_story", ""),
                            "acceptance_criteria": req.get("acceptance_criteria", []),
                            "test_steps": req.get("test_steps", []),
                            "test_scenarios": req.get("test_scenarios", []),
                            "assumptions": req.get("assumptions", []),
                            "ambiguities": req.get("ambiguities", []),
                            "confidence": req.get("confidence", "High"),
                            "extraction_model": "llama-3.3-70b-versatile",
                            "extraction_timestamp": datetime.utcnow().isoformat(),
                            "validation_confirmed": False,
                            "metadata": {
                                "source_file": (file_urls[0].split("/")[-1]) if file_urls else "unknown",
                                "extraction_timestamp": datetime.utcnow().isoformat()
                            }
                        })

                    java_response = requests.post(
                        java_backend_url, 
                        json=mapped_requirements,
                        timeout=30.0
                    )
                    if java_response.status_code in [200, 201]:
                        print(f"  ✓ Successfully stored in Java backend (Postgres)")
                    else:
                        print(f"  ⚠ Java backend returned error: {java_response.status_code} - {java_response.text}")
                except Exception as e:
                    print(f"  ⚠ Failed to store in Java backend: {e}")

            return {"status": "success", "total": len(requirements)}

    except Exception as e:
        print(f"  [Celery] FAILED: {str(e)}")
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

    # ── Store in Java Backend ──────────────────────────────────────
    try:
        import requests
        java_url = f"http://localhost:8080/api/testcases/project/{project_id}"
        test_plans = result["test_plan"].get("test_plans", [])

        mapped_testcases = []
        tc_counter = 1
        for plan in test_plans:
            req_id = plan.get("requirement_id", "N/A")
            for tc in plan.get("test_cases", []):
                mapped_testcases.append({
                    "testCaseId": f"TC-{tc_counter:03d}",
                    "requirementId": req_id,
                    "title": tc.get("title", ""),
                    "description": tc.get("description", ""),
                    "testType": tc.get("test_type", "Functional"),
                    "testPhase": tc.get("test_phase", "E2E"),
                    "priority": tc.get("priority", "High"),
                    "prerequisites": tc.get("prerequisites", ""),
                    "testSteps": tc.get("test_steps", []),
                    "expectedResult": tc.get("expected_result", ""),
                    "status": "Not Executed",
                })
                tc_counter += 1

        if mapped_testcases:
            resp = requests.post(java_url, json=mapped_testcases, timeout=30.0)
            if resp.status_code in [200, 201]:
                print(f"  ✓ Stored {len(mapped_testcases)} test cases in Java backend")
            else:
                print(f"  ⚠ Java backend error: {resp.status_code}")
    except Exception as e:
        print(f"  ⚠ Failed to store in Java backend: {e}")

    return {
        "status": "success",
        "total_requirements": result["total_requirements"],
        "total_test_cases": result["total_test_cases"],
        "s3_output": {
            "json": f"s3://{bucket}/{s3_json_key}",
            "excel": f"s3://{bucket}/{s3_excel_key}",
        },
    }
