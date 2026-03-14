"""
Document Service — S3 document operations and duplication checks.
"""
import logging
import os
import tempfile

from fastapi import UploadFile

import utils.s3 as s3
from utils.java_client import get_document_statuses

logger = logging.getLogger("prism.services.documents")


def list_general_documents() -> list:
    """Return all files in the uploads/general S3 folder."""
    return s3.list_files("uploads/general/")


def generate_upload_url(project_id: str, filename: str) -> dict:
    """Generate a pre-signed S3 POST URL for direct browser uploads."""
    s3_key = f"uploads/{project_id}/{filename}"
    return {
        "project_id": project_id,
        "filename": filename,
        "s3_key": s3_key,
        "presigned_post": s3.presign_upload(s3_key),
    }


async def upload_document(project_id: str, file: UploadFile) -> dict:
    """Save an uploaded file to a temp path then push to S3."""
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            f.write(await file.read())

        s3_key = f"uploads/{project_id}/{file.filename}"
        s3_url = s3.upload(tmp_path, s3_key)

        return {
            "project_id": project_id,
            "filename": file.filename,
            "s3_url": s3_url,
            "s3_key": s3_key,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def is_already_processed(project_id: str, file_urls: list) -> bool:
    """
    Return True if any of the given file URLs are already tracked for this project.
    Prevents re-processing the same document.
    """
    try:
        existing = get_document_statuses(project_id)
        existing_urls = {d.get("documentUrl") for d in existing if d.get("documentUrl")}
        return any(u in existing_urls for u in file_urls)
    except Exception as e:
        logger.error("Duplication check failed: %s", e, exc_info=True)
        return False
