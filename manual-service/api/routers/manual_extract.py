import logging

from fastapi import APIRouter, HTTPException, Depends

from api.schemas import ManualExtractionRequest
from services.extraction import run_manual_extraction, run_manual_dspy_extraction
from utils.security import get_team_user

logger = logging.getLogger("prism.manual.api.manual_extract")
router = APIRouter()


@router.post("/teams/{team_id}/projects/{project_id}/manual-extract")
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
        raise HTTPException(status_code=500, detail=f"Manual extraction failed: {e}")


@router.post("/teams/{team_id}/projects/{project_id}/manual-extract-dspy")
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
        raise HTTPException(status_code=500, detail=f"DSPy manual extraction failed: {e}")
