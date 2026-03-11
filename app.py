"""
FastAPI service for PTW Requirements Extraction & Test Case Generation with S3 Integration
Start: python app.py
Docs:  http://localhost:8000/docs
"""

import json
import os
import sys
import time
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from celery.result import AsyncResult
from celery_app import extract_requirements_task, generate_testcases_task

from datetime import datetime
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
from document_status import update_document_statuses
import requests
from auth_config import get_java_auth_headers
import logging
from logging_config import setup_logging

# Load environment
load_dotenv()

# ── Logging ─────────────────────────────────────────────────────
setup_logging("DEBUG")
logger = logging.getLogger("prism.api")

# Ensure project directory is in path
sys.path.insert(0, str(Path(__file__).parent))

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="PRISM AI — Requirements & Test Cases",
    description="Extract requirements from documents and generate professional test cases",
    version="3.0.0",
)

# Allow Angular frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with your Angular app URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# REQUEST / RESPONSE LOGGING MIDDLEWARE
# ============================================================================

class APILoggingMiddleware(BaseHTTPMiddleware):
    """Log every incoming request and outgoing response."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        method = request.method
        path = request.url.path
        query = str(request.query_params) if request.query_params else ""
        client = request.client.host if request.client else "unknown"

        logger.info("⟶  %s %s%s  (client=%s)", method, path,
                    f"?{query}" if query else "", client)

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed = time.time() - start
            logger.error("⟵  %s %s — 500 UNHANDLED in %.3fs — %s",
                         method, path, elapsed, exc, exc_info=True)
            raise

        elapsed = time.time() - start
        logger.info("⟵  %s %s — %s in %.3fs", method, path,
                    response.status_code, elapsed)
        return response


app.add_middleware(APILoggingMiddleware)

# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class ExtractionRequest(BaseModel):
    """Request body for POST /extract"""
    project_id: Union[str, int]
    project_name: Optional[str] = None
    file_urls: List[str]  # S3 URLs or S3 keys

class UploadUrlRequest(BaseModel):
    """Request body for POST /generate-upload-url"""
    project_id: str
    filename: str

class ExtractionResponse(BaseModel):
    """Response body for POST /extract"""
    status: str
    project_id: str
    total_requirements: int
    requirements: list
    s3_output: dict

class ManualExtractionRequest(BaseModel):
    """Request body for POST /manual-extract and /manual-extract-dspy"""
    project_id: Union[str, int]  # Project ID for duplication checks
    document_url: str   # S3 URL or S3 key
    description: str    # User's brief description (semantic anchor)
    page_no: int        # 1-indexed page or slide number

class TestCaseRequest(BaseModel):
    """Request body for POST /generate-testcases"""
    project_id: Union[str, int]
    project_name: Optional[str] = None
    requirements_s3_key: Optional[str] = None  # S3 key to requirements JSON
    requirements: Optional[list] = None         # Direct requirements array
    document_urls: Optional[List[str]] = []     # Source documents for rich context

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Check if the service is running and all credentials configured."""
    groq_key = os.getenv("GROQ_API_KEY")
    aws_key = os.getenv("AWS_ACCESS_KEY_ID")
    bucket = os.getenv("S3_BUCKET_NAME", "katsuai-tcgen")

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "groq_api_key_set": bool(groq_key),
            "aws_credentials_set": bool(aws_key),
            "s3_bucket": bucket,
        },
    }


@app.post("/generate-upload-url")
async def generate_upload_url_endpoint(request: UploadUrlRequest):
    """
    Generate a pre-signed URL for the frontend to upload a file directly to S3.
    Choice B workflow: Use this to get a secure upload link without exposing AWS keys.
    """
    try:
        from s3_utils import generate_presigned_upload_url
        
        project_id = request.project_id
        filename = request.filename
        
        # Consistent pathing: uploads/{project_id}/{filename}
        s3_key = f"uploads/{project_id}/{filename}"
        
        presigned_data = generate_presigned_upload_url(s3_key)
        
        return {
            "status": "success",
            "project_id": project_id,
            "filename": filename,
            "s3_key": s3_key,
            "presigned_post": presigned_data
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate upload URL: {str(e)}"
        )


@app.post("/upload-document")
async def upload_document_endpoint(
    project_id: str = Form("general"),
    file: UploadFile = File(...)
):
    """
    Directly upload a file to S3. Default path is uploads/general/{filename}.
    """
    tmp_path = None
    try:
        from s3_utils import upload_to_s3
        
        # Save to a temporary local file
        fd, tmp_path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, 'wb') as tmp:
                content = await file.read()
                tmp.write(content)
        finally:
            pass

        # Define S3 key
        s3_key = f"uploads/{project_id}/{file.filename}"
        
        # Upload to S3
        s3_url = upload_to_s3(tmp_path, s3_key)
        
        return {
            "status": "success",
            "project_id": project_id,
            "filename": file.filename,
            "s3_url": s3_url,
            "s3_key": s3_key
        }
    except Exception as e:
        logger.error("Upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.get("/documents/general")
async def list_general_documents():
    """
    List all documents in the 'uploads/general' S3 folder.
    """
    try:
        from s3_utils import list_files_in_s3
        files = list_files_in_s3("uploads/general/")
        return {
            "status": "success",
            "count": len(files),
            "documents": files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")


@app.get("/requirements/project/{project_id}")
async def get_requirements(project_id: str):
    """
    Get cached requirements from S3 (no re-extraction).
    Fetches the last extracted results from S3.
    """
    try:
        from s3_utils import download_json_from_s3, file_exists_in_s3

        s3_key = f"projects/{project_id}/output/requirements.json"

        if not file_exists_in_s3(s3_key):
            raise HTTPException(
                status_code=404,
                detail=f"No requirements found for project '{project_id}'. Run POST /extract first.",
            )

        data = download_json_from_s3(s3_key)

        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": len(data.get("requirements", [])),
            "requirements": data.get("requirements", []),
            "s3_url": f"s3://{os.getenv('S3_BUCKET_NAME', 'katsuai-tcgen')}/{s3_key}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch requirements: {str(e)}"
        )


def _is_document_already_processed(project_id: str, file_urls: List[str]) -> bool:
    """
    Check if any of these documents already exist in the project statuses.
    """
    try:
        java_backend_url = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")
        url = f"{java_backend_url}/api/document-statuses/projects/{project_id}"
        response = requests.get(url, headers=get_java_auth_headers(), timeout=10)
        
        if response.status_code == 200:
            existing_docs = response.json()
            # If backend returns a list of objects with 'documentUrl'
            existing_urls = {d.get("documentUrl") for d in existing_docs if d.get("documentUrl")}
            
            for f_url in file_urls:
                if f_url in existing_urls:
                    return True
        return False
    except Exception as e:
        logger.error("Check duplicate document failed: %s", e, exc_info=True)
        return False


# ============================================================================
# MAIN
# ============================================================================

@app.post("/extract-async")
async def extract_requirements_async(request: ExtractionRequest):
    """
    Asynchronous version of the extraction endpoint.
    1. Checks if document already exists in project.
    2. Queues the CLEAN extraction task (removes duplicate BRs).
    """
    project_id = str(request.project_id)
    project_name = request.project_name or f"project_{project_id}"
    file_urls = request.file_urls

    logger.info("━━━ /extract-async  project=%s  files=%s ━━━", project_id, file_urls)

    if not project_id:
        raise HTTPException(status_code=400, detail="No project_id provided")

    # =============================================================
    # NEW LOGIC: Document Duplication Check
    # =============================================================
    if _is_document_already_processed(project_id, file_urls):
        logger.warning("Document already processed for project %s — returning conflict", project_id)
        return {
            "status": "conflict",
            "message": "This document has already been uploaded and processed for this project.",
            "document_urls": file_urls
        }

    # Create temp directory
    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_async_{project_id}")
    input_dir = os.path.join(tmp_dir, "input")
    output_dir = os.path.join(tmp_dir, "output")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Download files in PARALLEL
    from s3_utils import download_from_s3
    local_files = []

    def _download_one(url):
        return download_from_s3(url, input_dir)

    with ThreadPoolExecutor(max_workers=min(len(file_urls), 5)) as executor:
        future_to_url = {executor.submit(_download_one, url): url for url in file_urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                local_path = future.result()
                local_files.append(local_path)
                logger.info("Downloaded %s → %s", url, local_path)
            except Exception as e:
                logger.error("Failed to download %s: %s", url, e, exc_info=True)

    if not local_files:
        logger.error("No files downloaded — aborting extraction")
        raise HTTPException(status_code=400, detail="Failed to download any files from S3")

    # POST initial PENDING status to Java backend
    logger.info("Setting PENDING status for %d documents", len(file_urls))
    document_statuses = update_document_statuses(project_id, file_urls, "PENDING")
    logger.info("Document statuses: %s", document_statuses)

    # Dispatch to the NEW Duplication-Aware Task
    from celery_app import extract_and_filter_duplicates_task
    task = extract_and_filter_duplicates_task.delay(
        project_id=project_id,
        project_name=project_name,
        local_files=local_files,
        output_dir=output_dir,
        file_urls=file_urls,
        document_statuses=document_statuses,
    )

    logger.info("Task queued  task_id=%s  for project=%s", task.id, project_id)

    return {
        "status": "accepted",
        "task_id": task.id,
        "message": "Clean extraction queued successfully. Duplicates will be filtered out before storage.",
        "document_statuses": document_statuses,
    }


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """
    Check the status of a Celery task.
    """
    task_result = AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": task_result.status,
    }
    
    if task_result.status == 'SUCCESS':
        response["result"] = task_result.result
    elif task_result.status == 'FAILURE':
        response["error"] = str(task_result.result)
    
    return response


@app.post("/manual-extract")
async def manual_extract_endpoint(request: ManualExtractionRequest):
    """
    Manual requirement extraction from a specific page or slide.

    Fallback when automatic extraction fails. The user provides:
      - document_url: S3 URL of the document
      - description:  Brief description of the requirement (semantic anchor)
      - page_no:      1-indexed page number (or slide number for PPTX)

    The API classifies the document type, extracts that page's content,
    and calls Groq LLM to generate one structured requirement JSON.
    Returns status "no_requirements" when the page has no readable content
    or the description does not match anything on the page.
    """
    tmp_dir = None
    try:
        from s3_utils import download_from_s3
        from extraction.manual import ManualExtractor

        if request.page_no < 1:
            raise HTTPException(status_code=400, detail="page_no must be 1 or greater")
        if not request.description.strip():
            raise HTTPException(status_code=400, detail="description cannot be empty")

        # Download file from S3 to a temp directory
        tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_manual_{os.getpid()}")
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = download_from_s3(request.document_url, tmp_dir)

        extractor = ManualExtractor()
        result = extractor.extract_from_page(
            file_path=local_path,
            description=request.description,
            page_no=request.page_no,
        )
        return result

    except HTTPException:
        raise
    except ValueError as e:
        # Out-of-range page numbers from extractors
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual extraction failed: {str(e)}")
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/manual-extract-dspy")
async def manual_extract_dspy_endpoint(request: ManualExtractionRequest):
    """
    DSPy-powered manual requirement extraction from a specific page.

    Uses the SAME trained DSPy extractors as the main pipeline:
    - BusinessFeatureExtractor
    - FunctionalDetailExtractor
    - WorkflowRequirementExtractor
    - TechnicalRequirementExtractor

    Includes duplication detection:
    1. Requirement-level: Checks new requirements against existing ones (TF-IDF)

    Input:
      - project_id:   Project ID for scoping duplication checks
      - document_url:  S3 URL of the document
      - description:   Brief description (semantic anchor)
      - page_no:       1-indexed page number

    Returns:
      - status: "success", "no_requirements"
      - requirements: list of structured requirement dicts
      - extraction_method: "dspy_trained"
    """
    tmp_dir = None
    try:
        from s3_utils import download_from_s3
        from extraction.manual_dspy import ManualDSPyExtractor
        from duplication_service import find_duplicate_requirements
        import dspy

        project_id = str(request.project_id)

        if request.page_no < 1:
            raise HTTPException(status_code=400, detail="page_no must be 1 or greater")
        if not request.description.strip():
            raise HTTPException(status_code=400, detail="description cannot be empty")

        # =============================================================
        # STEP 1: Download file and run DSPy extraction
        # =============================================================
        tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_manual_dspy_{os.getpid()}")
        os.makedirs(tmp_dir, exist_ok=True)
        local_path = download_from_s3(request.document_url, tmp_dir)

        extractor = ManualDSPyExtractor()
        result = extractor.extract_from_page(
            file_path=local_path,
            description=request.description,
            page_no=request.page_no,
        )

        # If no requirements extracted, return as-is
        if result.get("status") != "success" or not result.get("requirements"):
            return result

        new_requirements = result["requirements"]

        # =============================================================
        # STEP 2: Requirement-level duplication check
        #         Sets is_duplicate + duplicate_of on each requirement
        # =============================================================
        requirements, duplicates_count = find_duplicate_requirements(
            project_id=project_id,
            new_requirements=new_requirements,
        )

        # =============================================================
        # STEP 3: Store ALL requirements in main requirements table
        #         (both duplicates and unique — full BR data)
        # =============================================================
        _store_manual_requirements(
            project_id=project_id,
            requirements=requirements,
            document_url=request.document_url,
            page_no=request.page_no,
        )

        # =============================================================
        # STEP 4: Return unified response
        #         Always same shape — each requirement has is_duplicate
        #         + duplicate_of with full existing requirement details
        # =============================================================
        return {
            "status": "success",
            "requirements": requirements,
            "total_extracted": len(requirements),
            "duplicates_count": duplicates_count,
            "source_page": request.page_no,
            "source_file": Path(request.document_url).name,
            "extraction_method": "dspy_trained",
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DSPy manual extraction failed: {str(e)}")
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _store_manual_requirements(
    project_id: str,
    requirements: list,
    document_url: str,
    page_no: int = 1,
) -> None:
    """
    Store manually extracted requirements as drafts in the Java backend.
    POST /api/requirements/drafts/project/{project_id}

    Payload matches existing drafts API exactly — including placeholders for
    start_line, end_line, and verbatim_text in metadata.
    """
    try:
        import requests as req_lib

        java_backend_url = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")
        java_url = f"{java_backend_url}/api/requirements/project/{project_id}"

        mapped = []
        for r in requirements:
            conf_val = r.get("confidence", 0.95)
            conf_str = "high" if conf_val >= 0.8 else "medium" if conf_val >= 0.5 else "low"
            now_str = datetime.now().isoformat() + "Z"

            mapped.append({
                "is_requirement": True,
                "short_title": r.get("title") or r.get("feature_name", ""),
                "description": r.get("description", ""),
                "user_story": r.get("user_story", ""),
                "acceptance_criteria": [str(c) for c in r.get("acceptance_criteria", [])],
                "test_steps": [
                    f"Step {s.get('step_num', i+1)}: {s.get('action', '')} -> {s.get('expected_result', '')}" 
                    if isinstance(s, dict) else str(s)
                    for i, s in enumerate(r.get("test_steps", []))
                ],
                "test_scenarios": [str(s) for s in r.get("test_scenarios", [])],
                "assumptions": [str(a) for a in r.get("assumptions", [])],
                "ambiguities": [str(a) for a in r.get("ambiguities", [])],
                "confidence": conf_str,
                "extraction_model": "llama-3.3-70b-versatile",
                "extraction_timestamp": now_str,
                "validation_confirmed": True,
                "metadata": {
                    "system": r.get("system", ""),
                    "category": r.get("category", ""),
                    "requirements_text": r.get("requirements_text", ""),
                    "confidence_score": conf_val,
                    "source_file": document_url,
                    "page_start": page_no,
                    "page_end": page_no,
                    "start_line": 0,
                    "end_line": 0,
                    "verbatim_text": r.get("requirements_text", ""),
                    "supporting_context": r.get("supporting_context", []),
                    "extraction_model": "llama-3.3-70b-versatile",
                    "extraction_timestamp": now_str,
                    "validation_confirmed": True,
                },
            })

        response = req_lib.post(java_url, json=mapped, headers=get_java_auth_headers(), timeout=30)
        if response.status_code in [200, 201]:
            logger.info("✓ Stored %d manual requirements in Java backend (project %s) — response: %s",
                        len(mapped), project_id, response.text[:500])
        else:
            logger.warning("⚠ Java backend returned %s: %s", response.status_code, response.text)
    except Exception as e:
        logger.error("⚠ Failed to store requirements: %s", e, exc_info=True)


# ============================================================================
# TEST CASE GENERATION ENDPOINTS
# ============================================================================

@app.post("/generate-testcases")
async def generate_testcases_async(request: TestCaseRequest):
    """
    Async test case generation (Phase 2). Queues a Celery task.

    Provide EITHER:
    - requirements_s3_key: S3 path to requirements JSON from Phase 1
    - requirements: Direct JSON array of requirements

    Optional:
    - document_urls: S3 URLs of source documents for richer test cases
    """
    project_id = str(request.project_id)
    project_name = request.project_name or f"project_{project_id}"

    if not request.requirements_s3_key and not request.requirements:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'requirements_s3_key' or 'requirements'"
        )

    # If direct requirements provided, save to temp file
    requirements_data = None
    if request.requirements:
        requirements_data = request.requirements

    # Download source documents for context
    local_docs = []
    if request.document_urls:
        from s3_utils import download_from_s3
        tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_testgen_{project_id}")
        os.makedirs(tmp_dir, exist_ok=True)
        for url in request.document_urls:
            try:
                local_path = download_from_s3(url, tmp_dir)
                local_docs.append(local_path)
            except Exception:
                pass

    task = generate_testcases_task.delay(
        project_id=project_id,
        project_name=project_name,
        requirements_s3_key=request.requirements_s3_key,
        requirements_data=requirements_data,
        local_doc_paths=local_docs,
    )

    return {
        "status": "accepted",
        "task_id": task.id,
        "message": "Test case generation queued successfully",
        "documents_loaded": len(local_docs),
    }


@app.post("/generate-testcases-sync")
async def generate_testcases_sync(request: TestCaseRequest):
    """
    Synchronous test case generation (Phase 2). Returns test cases immediately.

    Provide EITHER:
    - requirements_s3_key: S3 path to requirements JSON from Phase 1
    - requirements: Direct JSON array of requirements

    Optional:
    - document_urls: S3 URLs of source documents for richer test cases
    """
    project_id = str(request.project_id)
    project_name = request.project_name or f"project_{project_id}"
    tmp_dir = None

    try:
        from s3_utils import download_from_s3, download_json_from_s3, upload_to_s3
        from testgen import TestGenPipeline

        # ── Load requirements ───────────────────────────────────────
        if request.requirements:
            requirements = request.requirements
        elif request.requirements_s3_key:
            data = download_json_from_s3(request.requirements_s3_key)
            if isinstance(data, dict):
                requirements = data.get("requirements", [])
            else:
                requirements = data
        else:
            raise HTTPException(status_code=400, detail="No requirements provided")

        if not requirements:
            raise HTTPException(status_code=400, detail="Requirements list is empty")

        # ── Download source documents for context ──────────────────
        local_docs = []
        tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_testgen_{project_id}_{os.getpid()}")
        if request.document_urls:
            os.makedirs(tmp_dir, exist_ok=True)
            for url in request.document_urls:
                try:
                    local_path = download_from_s3(url, tmp_dir)
                    local_docs.append(local_path)
                except Exception:
                    pass

        # ── Run test case generation ───────────────────────────────
        output_dir = os.path.join(tmp_dir or tempfile.mkdtemp(), "output")
        os.makedirs(output_dir, exist_ok=True)

        pipeline = TestGenPipeline()
        result = pipeline.run(
            requirements=requirements,
            project_name=project_name,
            output_dir=output_dir,
            document_paths=local_docs if local_docs else None,
        )

        # ── Upload results to S3 ───────────────────────────────────
        s3_json_key = f"projects/{project_id}/output/test_plan.json"
        s3_excel_key = f"projects/{project_id}/output/test_plan.xlsx"

        upload_to_s3(result["json_path"], s3_json_key)
        upload_to_s3(result["excel_path"], s3_excel_key)

        bucket = os.getenv("S3_BUCKET_NAME", "katsuai-tcgen")

        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": result["total_requirements"],
            "total_test_cases": result["total_test_cases"],
            "test_plan": result["test_plan"],
            "s3_output": {
                "json": f"s3://{bucket}/{s3_json_key}",
                "excel": f"s3://{bucket}/{s3_excel_key}",
            },
            "documents_used": len(local_docs),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Test case generation failed: {str(e)}")
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/testcases/project/{project_id}")
async def get_testcases(project_id: str):
    """Get cached test plan from S3 (no re-generation)."""
    try:
        from s3_utils import download_json_from_s3, file_exists_in_s3

        s3_key = f"projects/{project_id}/output/test_plan.json"

        if not file_exists_in_s3(s3_key):
            raise HTTPException(
                status_code=404,
                detail=f"No test plan found for project '{project_id}'. Run POST /generate-testcases first.",
            )

        data = download_json_from_s3(s3_key)

        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": data.get("total_requirements", 0),
            "total_test_cases": data.get("total_test_cases", 0),
            "test_plan": data,
            "s3_url": f"s3://{os.getenv('S3_BUCKET_NAME', 'katsuai-tcgen')}/{s3_key}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch test plan: {str(e)}")


if __name__ == "__main__":
    logger.info("Starting PRISM AI Service...")
    logger.info("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False,
                log_level="info")
