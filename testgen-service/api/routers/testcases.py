import logging

from fastapi import APIRouter, HTTPException, Depends

from api.schemas import TestCaseRequest
from services.testcases import (
    queue_testcase_generation,
    run_testcase_generation_sync,
    get_cached_testplan,
)
from utils.security import get_current_user, get_team_user

logger = logging.getLogger("prism.api.testcases")
router = APIRouter()


@router.post("/teams/{team_id}/projects/{project_id}/generate-testcases")
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


@router.post("/teams/{team_id}/projects/{project_id}/generate-testcases-sync")
async def generate_testcases_sync(
    team_id: str,
    project_id: str,
    request: TestCaseRequest,
    user: dict = Depends(get_team_user),
):
    """
    Synchronous test case generation — returns test cases immediately.
    """
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


@router.get("/teams/{team_id}/projects/{project_id}/test-cases")
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
