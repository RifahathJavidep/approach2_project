"""
MIIPE — BR Manual Creation Service

Handles manual, single-page business requirement extraction using
Groq LLM and DSPy-trained pipelines.

Start:  uvicorn app:app --host 0.0.0.0 --port 8003
Docs:   http://localhost:8003/docs
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
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from common.logging_config import setup_logging

load_dotenv()
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "manual-service")
os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", os.getenv("KEYCLOAK_MANUAL_CLIENT_SECRET", ""))
setup_logging("DEBUG")
logger = logging.getLogger("prism.br_manual_creation")

# ─── Schemas ─────────────────────────────────────────────────────────────────
from schemas import ManualExtractionRequest

# ─── Handlers ────────────────────────────────────────────────────────────────
from manual_extraction_handler import (
    run_manual_extraction,
    run_manual_dspy_extraction,
)
from common.security import get_team_user

# ─── App Initialization ─────────────────────────────────────────────────────

app = FastAPI(
    title="PRISM — BR Manual Creation Service",
    description="Add new business requirements manually from a specific document page",
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
        "service": "br-manual-creation-service",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "groq_api_key_set": bool(os.getenv("GROQ_API_KEY")),
            "aws_credentials_set": bool(os.getenv("AWS_ACCESS_KEY_ID")),
            "s3_bucket": os.getenv("S3_BUCKET_NAME", "not set"),
        },
    }


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
    """
    Extract a single requirement from a specific page using basic Groq LLM.
    Mirrors Java: POST /teams/{teamId}/projects/{projectId}/requirements
    """
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
    """
    Extract requirements from a specific page using the trained DSPy pipeline.
    Includes duplicate detection against existing project requirements.
    """
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
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003, reload=False)
