"""
Java Backend Client — all HTTP calls to the Java (Katsu) backend.

Combines auth headers and document status tracking in one place,
since both are purely about communicating with the Java service.
"""
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("prism.java_client")

BASE_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")

def get_headers() -> dict:
    """Return standard headers for all Java backend requests."""
    return {"Content-Type": "application/json"}

def create_document_statuses(
    project_id: str, file_urls: List[str], status: str
) -> List[Dict[str, Any]]:
    """
    POST a batch of document status records.
    Returns the created records (each with an assigned ID).
    Used to set initial PENDING status before a task starts.
    """
    url = f"{BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": u, "status": status} for u in file_urls]

    logger.info("Creating '%s' status for %d documents (project %s)", status, len(file_urls), project_id)
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=10)
        if response.status_code in [200, 201]:
            result = response.json()
            logger.info("Document statuses created: %s", result)
            return result
        logger.warning("Failed to create document statuses: Java returned %s — %s",
                       response.status_code, response.text)
        return []
    except Exception as e:
        logger.error("Exception creating document statuses: %s", e, exc_info=True)
        return []

def update_document_status(
    project_id: str, doc_status_id: int, document_url: str, status: str
) -> Optional[Dict[str, Any]]:
    """
    Update a specific document status record by its ID.
    POST /api/document-statuses/projects/{project_id}
    Body: [{ "id": X, "documentUrl": "...", "status": "..." }]
    """
    url = f"{BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"id": int(doc_status_id), "documentUrl": document_url, "status": status}]

    try:
        logger.info("Updating document status: id=%s → %s", doc_status_id, status)
        response = requests.post(url, json=payload, headers=get_headers(), timeout=10)
        if response.status_code in [200, 201]:
            logger.info("Document status %s updated to '%s'", doc_status_id, status)
            data = response.json()
            return data[0] if isinstance(data, list) and data else data
        logger.warning("Failed to update status for id=%s: Java returned %s",
                       doc_status_id, response.status_code)
        return None
    except Exception as e:
        logger.error("Exception updating document status id=%s: %s", doc_status_id, e, exc_info=True)
        return None

def get_document_statuses(project_id: str) -> List[Dict[str, Any]]:
    """Fetch all document status records for a project."""
    url = f"{BASE_URL}/api/document-statuses/projects/{project_id}"
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error("Exception fetching document statuses: %s", e, exc_info=True)
        return []

def get_requirements(project_id: str) -> List[Dict]:
    """Fetch all requirements for a project."""
    url = f"{BASE_URL}/api/requirements/project/{project_id}"
    try:
        response = requests.get(url, headers=get_headers(), timeout=15)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return data
            return data.get("requirements", data.get("content", []))
        logger.warning("Backend returned %s for requirements (project %s)", response.status_code, project_id)
        return []
    except Exception as e:
        logger.error("Failed to fetch requirements for project %s: %s", project_id, e, exc_info=True)
        return []

def store_requirements(project_id: str, requirements: list) -> bool:
    """POST a list of mapped requirements to the Java backend."""
    url = f"{BASE_URL}/api/requirements/project/{project_id}"
    try:
        response = requests.post(url, json=requirements, headers=get_headers(), timeout=30)
        if response.status_code in [200, 201]:
            logger.info("Stored %d requirements for project %s", len(requirements), project_id)
            return True
        logger.warning("Failed to store requirements: Java returned %s — %s",
                       response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("Exception storing requirements: %s", e, exc_info=True)
        return False

def store_draft_requirements(project_id: str, requirements: list) -> bool:
    """POST requirements as drafts to the Java backend."""
    url = f"{BASE_URL}/api/requirements/drafts/project/{project_id}"
    try:
        response = requests.post(url, json=requirements, headers=get_headers(), timeout=30)
        if response.status_code in [200, 201]:
            logger.info("Stored %d draft requirements for project %s", len(requirements), project_id)
            return True
        logger.warning("Failed to store drafts: Java returned %s — %s",
                       response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("Exception storing draft requirements: %s", e, exc_info=True)
        return False

def store_test_cases(project_id: str, test_cases: list) -> bool:
    """POST test cases to the Java backend."""
    url = f"{BASE_URL}/projects/{project_id}/test-cases"
    try:
        response = requests.post(url, json=test_cases, headers=get_headers(), timeout=30)
        if response.status_code in [200, 201]:
            logger.info("Stored %d test cases for project %s", len(test_cases), project_id)
            return True
        logger.warning("Failed to store test cases: Java returned %s — %s",
                       response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("Exception storing test cases: %s", e, exc_info=True)
        return False
