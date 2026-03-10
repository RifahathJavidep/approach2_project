"""
Utility for posting document processing status updates to the Java backend.
"""

import os
import logging
import requests
from typing import List, Optional, Dict, Any

logger = logging.getLogger("prism.document_status")

JAVA_BACKEND_BASE_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")

from auth_config import get_java_auth_headers

def update_document_statuses(project_id: str, file_urls: List[str], status: str) -> List[Dict[str, Any]]:
    """
    POST initial PENDING status (batch). Returns list of records with IDs.
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": u, "status": status} for u in file_urls]
    
    logger.info("Sending batch status update (%s) for %d documents to %s", status, len(file_urls), url)
    logger.debug("Payload: %s", payload)
    
    try:
        response = requests.post(url, json=payload, headers=get_java_auth_headers(), timeout=10)
        if response.status_code in [200, 201]:
            result = response.json()
            logger.info("Batch status update SUCCESS: %s", result)
            return result
        else:
            logger.warning("Batch status update FAILED: Java returned %s — %s", response.status_code, response.text)
            return []
    except Exception as e:
        logger.error("Batch status update EXCEPTION: %s", e, exc_info=True)
        return []

def update_status_by_id(project_id: str, doc_status_id: int, document_url: str, status: str) -> Optional[Dict[str, Any]]:
    """
    IMPLEMENTATION OF POSTMAN SCREENSHOT:
    Sends a POST to /api/document-statuses/projects/{project_id}
    Body: [ { "id": X, "documentUrl": "...", "status": "..." } ]
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    
    # EXACT PAYLOAD FROM POSTMAN SCREENSHOT
    payload = [
        {
            "id": int(doc_status_id),
            "documentUrl": document_url,
            "status": status
        }
    ]

    try:
        logger.info("Sending ID-based update: id=%s url=%s status=%s", doc_status_id, document_url, status)
        response = requests.post(url, json=payload, headers=get_java_auth_headers(), timeout=10)
        if response.status_code in [200, 201]:
            logger.info("SUCCESS: ID %s updated to %s", doc_status_id, status)
            data = response.json()
            return data[0] if isinstance(data, list) and data else data
        else:
            logger.warning("FAILED: Java returned %s for ID %s", response.status_code, doc_status_id)
            return None
    except Exception as e:
        logger.error("EXCEPTION updating ID %s: %s", doc_status_id, e, exc_info=True)
        return None
