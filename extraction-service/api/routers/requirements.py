import logging


from fastapi import APIRouter, HTTPException, Depends

from api.schemas import ExtractionRequest
from services.extraction import queue_extraction, get_cached_requirements
from utils.security import get_team_user

logger = logging.getLogger("prism.api.requirements")
router = APIRouter()


@router.post("/teams/{team_id}/projects/{project_id}/extract-async")
async def extract_requirements_async(
    team_id: str,
    project_id: str,
    request: ExtractionRequest,
    user: dict = Depends(get_team_user),
):
    """
    Queue an async extraction job.
    Downloads files from S3, checks for document duplication, then dispatches a Celery task.
    Mirrors Java: POST /teams/{teamId}/projects/{projectId}/requirements
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
        logger.error("Failed to queue extraction: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue extraction: {e}")



@router.get("/teams/{team_id}/projects/{project_id}/requirements")
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
