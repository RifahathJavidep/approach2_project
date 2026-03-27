"""
Document Service — S3 document operations and duplication checks.
"""
import logging
import os
import tempfile

from fastapi import UploadFile

import common.s3_client as s3
from common.java_client import get_document_statuses

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



def filter_new_files(
    project_id: str,
    file_urls: list,
    tenant_id: str | None = None,
) -> tuple[list, list]:
    """
    Separate incoming file URLs into new (unprocessed) and skipped (already processed).

    Checks two sources (as per Bhasker's instruction):
      1. Java backend document-status records (primary check)
      2. S3 existence check (secondary safety net)

    Returns:
        (new_urls, skipped_urls)
    """
    if not file_urls:
        return [], []

    # --- Check 1: Java backend document statuses ---
    existing_urls: set = set()
    try:
        existing = get_document_statuses(project_id, tenant_id)
        existing_urls = {d.get("documentUrl") for d in existing if d.get("documentUrl")}
    except Exception as e:
        logger.error("Failed to fetch document statuses for filtering: %s", e, exc_info=True)

    new_urls = []
    skipped_urls = []

    for url in file_urls:
        # Skip if Java backend already tracks this URL
        if url in existing_urls:
            skipped_urls.append(url)
            logger.info("Skipping already-processed file: %s", url)
            continue

        # --- Check 2: S3 existence (Bhasker's S3 check) ---
        try:
            _, s3_key = s3.parse_url(url)
            if s3.exists(s3_key):
                # File exists in S3 but not tracked in Java — could be a partial failure.
                # Still treat as new so it gets processed and tracked properly.
                logger.info("File exists in S3 but not tracked in Java — will process: %s", url)
        except Exception as e:
            logger.warning("S3 existence check failed for %s: %s", url, e)

        new_urls.append(url)

    logger.info(
        "Partial upload filter: %d total → %d new, %d skipped (project %s)",
        len(file_urls), len(new_urls), len(skipped_urls), project_id,
    )
    return new_urls, skipped_urls
