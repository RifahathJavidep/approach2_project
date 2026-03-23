import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends

from api.schemas import UploadUrlRequest
from services.documents import (
    generate_upload_url,
    list_general_documents,
    upload_document,
)
from utils.security import get_current_user, get_team_user, get_tenant_user

logger = logging.getLogger("prism.api.documents")
router = APIRouter()


@router.get("/teams/{team_id}/documents/general")
async def list_documents(team_id: str, user: dict = Depends(get_team_user)):
    """List all documents in the uploads/general S3 folder."""
    try:
        files = list_general_documents()
        return {"status": "success", "count": len(files), "documents": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")


@router.post("/teams/{team_id}/projects/{project_id}/generate-upload-url")
async def generate_upload_url_endpoint(
    team_id: str,
    project_id: str,
    request: UploadUrlRequest,
    user: dict = Depends(get_team_user)
):
    """Generate a pre-signed S3 URL so the frontend can upload directly without exposing AWS keys."""
    try:
        result = generate_upload_url(project_id, request.filename)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {e}")


@router.post("/teams/{team_id}/projects/{project_id}/upload-document")
async def upload_document_endpoint(
    team_id: str,
    project_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_team_user)
):
    """Upload a file directly to S3."""
    try:
        result = await upload_document(project_id, file)
        return {"status": "success", **result}
    except Exception as e:
        logger.error("Upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
