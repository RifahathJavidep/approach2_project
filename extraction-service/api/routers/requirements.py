import logging

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Depends

from api.schemas import ExtractionRequest
from services.extraction import queue_extraction, get_cached_requirements
from utils.security import get_current_user, get_tenant_user

logger = logging.getLogger("prism.api.requirements")
router = APIRouter()


@router.post("/extract-async")
async def extract_requirements_async(request: ExtractionRequest, user: dict = Depends(get_tenant_user)):
    """
    Queue an async extraction job.
    Downloads files from S3, checks for document duplication, then dispatches a Celery task.
    Returns a task_id to poll with GET /status/{task_id}.
    """
    project_id = str(request.project_id)
    project_name = request.project_name or f"project_{project_id}"

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")

    logger.info("POST /extract-async  project=%s  files=%s", project_id, request.file_urls)

    try:
        result = await queue_extraction(project_id, project_name, request.file_urls, user.get("tenant_id"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to queue extraction: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to queue extraction: {e}")


@router.get("/status/{task_id}")
async def get_task_status(task_id: str, user: dict = Depends(get_current_user)):
    """Poll the status of a Celery task."""
    task = AsyncResult(task_id)
    response = {"task_id": task_id, "status": task.status}

    if task.status == "SUCCESS":
        response["result"] = task.result
    elif task.status == "FAILURE":
        response["error"] = str(task.result)

    return response


@router.get("/requirements/project/{project_id}")
async def get_requirements(project_id: str, user: dict = Depends(get_tenant_user)):
    """Fetch cached requirements from S3 (no re-extraction)."""
    try:
        data = get_cached_requirements(project_id)
        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": len(data.get("requirements", [])),
            "requirements": data.get("requirements", []),
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No requirements found for project '{project_id}'. Run POST /extract-async first.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch requirements: {e}")
