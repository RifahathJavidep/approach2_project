"""
MIIPE — Test Case Generation Service

Handles Phase 2: AI-powered test case generation from extracted
business requirements.

Start:  uvicorn app:app --host 0.0.0.0 --port 8002
Docs:   http://localhost:8002/docs
"""
import sys
import os
import logging
import time
from pathlib import Path
from datetime import datetime

# Add project root to sys.path so 'common' and 'testgen' are visible
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
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "testcase-service-ai")
os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", os.getenv("KEYCLOAK_TESTCASE_CLIENT_SECRET", ""))
setup_logging("DEBUG")
logger = logging.getLogger("prism.testcase_generation")

# ─── Schemas ─────────────────────────────────────────────────────────────────
from schemas import TestCaseRequest

# ─── Handlers ────────────────────────────────────────────────────────────────
from testcase_generation_handler import (
    queue_testcase_generation,
    run_testcase_generation_sync,
    get_cached_testplan,
)
from common.security import get_current_user, get_team_user

# ─── App Initialization ─────────────────────────────────────────────────────

app = FastAPI(
    title="PRISM — Test Case Generation Service",
    description="Generate test cases from extracted business requirements",
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
        "service": "testcase-generation-service",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "groq_api_key_set": bool(os.getenv("GROQ_API_KEY")),
            "aws_credentials_set": bool(os.getenv("AWS_ACCESS_KEY_ID")),
            "s3_bucket": os.getenv("S3_BUCKET_NAME", "katsu-ai-requirement-documents"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CASE GENERATION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/teams/{team_id}/projects/{project_id}/generate-testcases")
async def generate_testcases_async(
    team_id: str,
    project_id: str,
    request: TestCaseRequest,
    user: dict = Depends(get_team_user),
):
    """
    Queue async test case generation (Phase 2).
    Mirrors Java: POST /teams/{teamId}/projects/{projectId}/test-cases
    """
    if not request.requirements_s3_key and not request.requirements:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'requirements_s3_key' or 'requirements'",
        )

    project_name = request.project_name or f"project_{project_id}"

    try:
        result = await queue_testcase_generation(
            team_id=team_id,
            project_id=project_id,
            project_name=project_name,
            requirements_s3_key=request.requirements_s3_key,
            requirements=request.requirements,
            document_urls=request.document_urls or [],
            tenant_id=user.get("tenant_id"),
        )
        return result
    except Exception as e:
        logger.error("Failed to queue test case generation: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue test case generation: {e}")


@app.post("/teams/{team_id}/projects/{project_id}/generate-testcases-sync")
async def generate_testcases_sync(
    team_id: str,
    project_id: str,
    request: TestCaseRequest,
    user: dict = Depends(get_team_user),
):
    """Synchronous test case generation — returns test cases immediately."""
    if not request.requirements_s3_key and not request.requirements:
        raise HTTPException(
            status_code=400,
            detail="Provide either 'requirements_s3_key' or 'requirements'",
        )

    project_name = request.project_name or f"project_{project_id}"

    try:
        result = await run_testcase_generation_sync(
            team_id=team_id,
            project_id=project_id,
            project_name=project_name,
            requirements_s3_key=request.requirements_s3_key,
            requirements=request.requirements,
            document_urls=request.document_urls or [],
            tenant_id=user.get("tenant_id"),
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Test case generation failed: {e}")


@app.get("/teams/{team_id}/projects/{project_id}/test-cases")
async def get_testcases(
    team_id: str,
    project_id: str,
    user: dict = Depends(get_team_user),
):
    """Fetch cached test plan from S3 (no re-generation)."""
    try:
        data = get_cached_testplan(project_id)
        return {
            "status": "success",
            "team_id": team_id,
            "project_id": project_id,
            "total_requirements": data.get("total_requirements", 0),
            "total_test_cases": data.get("total_test_cases", 0),
            "test_plan": data,
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No test plan found for project '{project_id}'. Run POST generate-testcases first.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch test plan: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002, reload=False)
