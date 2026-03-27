"""
MIIPE — BR Creation Service (Business Requirement Extraction)

Handles Phase 1: document ingestion, requirement extraction via AI,
deduplication, and storage to the Java backend.

Start:  uvicorn app:app --host 0.0.0.0 --port 8001
Docs:   http://localhost:8001/docs
"""
import sys
import os
import logging
import time
from pathlib import Path
from datetime import datetime

# Add project root to sys.path so 'common' and 'extraction' are visible
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from common.logging_config import setup_logging

load_dotenv()
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "extracter-service")
os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", os.getenv("KEYCLOAK_EXTRACTION_CLIENT_SECRET", ""))
setup_logging("DEBUG")
logger = logging.getLogger("prism.br_creation")

# ─── Schemas ─────────────────────────────────────────────────────────────────
from schemas import ExtractionRequest, ManualExtractionRequest

# ─── Handlers ────────────────────────────────────────────────────────────────
from br_extraction_handler import (
    queue_extraction,
    get_cached_requirements,
    run_manual_extraction,
    run_manual_dspy_extraction,
)
from document_handler import (
    list_general_documents,
    upload_document_async,
)
from common.security import get_current_user, get_team_user, get_tenant_user

# ─── App Initialization ─────────────────────────────────────────────────────

app = FastAPI(
    title="PRISM — BR Creation Service",
    description="Extract business requirements from uploaded documents",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:3000",
        "http://127.0.0.1:4200",
        "*",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class APILoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("%s %s -- 500 -- %s", request.method, request.url.path, exc, exc_info=True)
            raise
        logger.info("%s %s -- %s  %.3fs", request.method, request.url.path, response.status_code, time.time() - start)
        return response


app.add_middleware(APILoggingMiddleware)


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Check that the service is running and credentials are configured."""
    return {
        "status": "healthy",
        "service": "br-creation-service",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "groq_api_key_set": bool(os.getenv("GROQ_API_KEY")),
            "aws_credentials_set": bool(os.getenv("AWS_ACCESS_KEY_ID")),
            "s3_bucket": os.getenv("S3_BUCKET_NAME", "katsu-ai-requirement-documents"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REQUIREMENT EXTRACTION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/teams/{team_id}/projects/{project_id}/extract-async")
async def extract_requirements_async(
    team_id: str,
    project_id: str,
    request: ExtractionRequest,
    user: dict = Depends(get_team_user),
):
    """
    Queue an async requirement_engine job.
    Downloads files from S3, checks for document duplication, then dispatches a Celery task.
    """
    project_name = request.project_name or f"project_{project_id}"
    logger.info("POST extract-async  team=%s  project=%s  files=%s", team_id, project_id, request.file_urls)

    try:
        result = await queue_extraction(
            team_id=team_id,
            project_id=project_id,
            project_name=project_name,
            file_urls=request.file_urls,
            tenant_id=user.get("tenant_id"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to queue requirement_engine: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue requirement_engine: {e}")


@app.get("/teams/{team_id}/projects/{project_id}/requirements")
async def get_requirements(
    team_id: str,
    project_id: str,
    user: dict = Depends(get_team_user),
):
    """Fetch cached requirements from S3 (no re-extraction)."""
    try:
        data = get_cached_requirements(project_id)
        return {
            "status": "success",
            "team_id": team_id,
            "project_id": project_id,
            "total_requirements": len(data.get("requirements", [])),
            "requirements": data.get("requirements", []),
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No requirements found for project '{project_id}'. Run POST extract-async first.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch requirements: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL EXTRACTION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/teams/{team_id}/projects/{project_id}/manual-extract")
async def manual_extract_endpoint(
    team_id: str,
    project_id: str,
    request: ManualExtractionRequest,
    user: dict = Depends(get_team_user),
):
    """Extract a single requirement from a specific page using basic Groq LLM."""
    if request.page_no < 1:
        raise HTTPException(status_code=400, detail="page_no must be 1 or greater")
    if not request.description.strip():
        raise HTTPException(status_code=400, detail="description cannot be empty")

    try:
        return await run_manual_extraction(
            team_id=team_id,
            project_id=project_id,
            document_url=request.document_url,
            description=request.description,
            page_no=request.page_no,
            tenant_id=user.get("tenant_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual requirement_engine failed: {e}")


@app.post("/teams/{team_id}/projects/{project_id}/manual-extract-dspy")
async def manual_extract_dspy_endpoint(
    team_id: str,
    project_id: str,
    request: ManualExtractionRequest,
    user: dict = Depends(get_team_user),
):
    """Extract requirements from a specific page using the trained DSPy pipeline."""
    if request.page_no < 1:
        raise HTTPException(status_code=400, detail="page_no must be 1 or greater")
    if not request.description.strip():
        raise HTTPException(status_code=400, detail="description cannot be empty")

    try:
        return await run_manual_dspy_extraction(
            team_id=team_id,
            project_id=project_id,
            document_url=request.document_url,
            description=request.description,
            page_no=request.page_no,
            tenant_id=user.get("tenant_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DSPy manual requirement_engine failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT MANAGEMENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/teams/{team_id}/documents/general")
async def list_documents(team_id: str, user: dict = Depends(get_team_user)):
    """List all documents in the uploads/general S3 folder."""
    try:
        files = list_general_documents()
        return {"status": "success", "count": len(files), "documents": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")


@app.post("/teams/{team_id}/projects/{project_id}/upload-document")
async def upload_document_endpoint(
    team_id: str,
    project_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_team_user),
):
    """
    Receive a file from the frontend and queue it for upload to S3.

    The browser sends the file here (multipart/form-data). The Python service
    saves it to a temp file and dispatches a Celery task to push it to S3.
    Returns immediately with a task_id — no waiting for the S3 upload to finish.
    AWS credentials are NEVER sent to the browser.
    """
    try:
        result = await upload_document_async(project_id, file)
        return {"status": "accepted", **result}
    except Exception as e:
        logger.error("Upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


@app.get("/teams/{team_id}/projects/{project_id}/upload-status/{task_id}")
async def upload_status_endpoint(
    team_id: str,
    project_id: str,
    task_id: str,
    user: dict = Depends(get_team_user),
):
    """
    Poll the status of an async document upload.
    Frontend calls this after receiving a task_id from /upload-document.
    """
    from celery_app import app as celery_app
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    if result.state == "SUCCESS":
        return {"status": "success", "task_id": task_id, **result.result}
    elif result.state == "FAILURE":
        return {"status": "failed", "task_id": task_id, "error": str(result.result)}
    else:
        return {"status": result.state.lower(), "task_id": task_id}


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
