import logging
import shutil
import tempfile
import os

from fastapi import APIRouter, HTTPException, Depends

from api.schemas import ManualExtractionRequest
from services.extraction import run_manual_extraction, run_manual_dspy_extraction
from utils.security import get_tenant_user

logger = logging.getLogger("prism.api.manual_extract")
router = APIRouter()


@router.post("/manual-extract")
async def manual_extract_endpoint(request: ManualExtractionRequest, user: dict = Depends(get_tenant_user)):
    """
    Extract a single requirement from a specific page using basic Groq LLM.
    Fallback when automatic extraction is too broad.
    """
    if request.page_no < 1:
        raise HTTPException(status_code=400, detail="page_no must be 1 or greater")
    if not request.description.strip():
        raise HTTPException(status_code=400, detail="description cannot be empty")

    try:
        return await run_manual_extraction(
            document_url=request.document_url,
            description=request.description,
            page_no=request.page_no,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manual extraction failed: {e}")


@router.post("/manual-extract-dspy")
async def manual_extract_dspy_endpoint(request: ManualExtractionRequest, user: dict = Depends(get_tenant_user)):
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
            project_id=str(request.project_id),
            document_url=request.document_url,
            description=request.description,
            page_no=request.page_no,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DSPy manual extraction failed: {e}")
