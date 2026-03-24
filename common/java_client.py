"""
Java Backend Client — all HTTP calls to the Java (Katsu) backend.

URL structure mirrors the new Java controllers:
  RequirementController  → /teams/{teamId}/projects/{projectId}/requirements
  TestCaseController     → /teams/{teamId}/projects/{projectId}/test-cases
  DocumentStatusController → /api/document-statuses/projects/{projectId}  (no team scope)

Security:
  - Uses Keycloak Client Credentials Grant for service-to-service auth
  - Includes X-TENANT-ID header on every request (required by Java TenantInterceptor)
"""
import logging
import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from config import settings

load_dotenv()

logger = logging.getLogger("prism.java_client")

BASE_URL = settings.JAVA_BACKEND_URL

TENANT_HEADER = "X-TENANT-ID"


def get_headers(tenant_id: Optional[str] = None) -> dict:
    """
    Build headers for Java backend requests.
    Includes Authorization Bearer token (Keycloak service account) and X-TENANT-ID.
    """
    headers = {"Content-Type": "application/json"}

    try:
        from common.security import get_service_token
        token = get_service_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            logger.warning("No service token available — request may be rejected by Java backend")
    except Exception as e:
        logger.warning("Could not obtain service token: %s", e)

    if tenant_id:
        headers[TENANT_HEADER] = tenant_id

    return headers


# ═════════════════════════════════════════════════════════════════════════════
# Document Status — /api/document-statuses/projects/{project_id}
# (no team scope in Java — endpoint remains unchanged)
# ═════════════════════════════════════════════════════════════════════════════

def create_document_statuses(
    project_id: str, file_urls: List[str], status: str,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """POST a batch of document status records. Returns the created records."""
    url = f"{BASE_URL}/integration/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": u, "status": status} for u in file_urls]

    logger.info("Creating '%s' status for %d documents (project %s)", status, len(file_urls), project_id)
    try:
        response = requests.post(url, json=payload, headers=get_headers(tenant_id), timeout=settings.SHORT_TIMEOUT)
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
    project_id: str, doc_status_id: int, document_url: str, status: str,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update a specific document status record by its ID."""
    url = f"{BASE_URL}/integration/api/document-statuses/projects/{project_id}"
    payload = [{"id": int(doc_status_id), "documentUrl": document_url, "status": status}]

    try:
        logger.info("Updating document status: id=%s → %s", doc_status_id, status)
        response = requests.post(url, json=payload, headers=get_headers(tenant_id), timeout=settings.SHORT_TIMEOUT)
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


def get_document_statuses(
    project_id: str,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch all document status records for a project."""
    url = f"{BASE_URL}/api/document-statuses/projects/{project_id}"
    try:
        response = requests.get(url, headers=get_headers(tenant_id), timeout=settings.SHORT_TIMEOUT)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        logger.error("Exception fetching document statuses: %s", e, exc_info=True)
        return []


# ═════════════════════════════════════════════════════════════════════════════
# Requirements — /teams/{team_id}/projects/{project_id}/requirements
# Mirrors RequirementController.java
# ═════════════════════════════════════════════════════════════════════════════

def get_requirements(
    team_id: str,
    project_id: str,
    tenant_id: Optional[str] = None,
) -> List[Dict]:
    """
    Fetch all requirements for a project.
    Java: GET /teams/{teamId}/projects/{projectId}/requirements
    Java: @PreAuthorize("hasPermission(#teamId, 'Requirements', 'View')")
    """
    url = f"{BASE_URL}/integration/teams/{team_id}/projects/{project_id}/requirements"
    try:
        response = requests.get(url, headers=get_headers(tenant_id), timeout=settings.DEFAULT_TIMEOUT)
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


def store_requirements(
    team_id: str,
    project_id: str,
    requirements: list,
    tenant_id: Optional[str] = None,
) -> bool:
    """
    POST a list of mapped requirements to the Java backend.
    Java: POST /teams/{teamId}/projects/{projectId}/requirements
    Java: @PreAuthorize("hasPermission(#teamId, 'Requirements', 'Create')")
    """
    url = f"{BASE_URL}/integration/teams/{team_id}/projects/{project_id}/requirements"
    try:
        response = requests.post(url, json=requirements, headers=get_headers(tenant_id), timeout=settings.DEFAULT_TIMEOUT)
        if response.status_code in [200, 201]:
            logger.info("Stored %d requirements for project %s", len(requirements), project_id)
            return True
        logger.warning("Failed to store requirements: Java returned %s — %s",
                       response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("Exception storing requirements: %s", e, exc_info=True)
        return False




# ═════════════════════════════════════════════════════════════════════════════
# Test Cases — /teams/{team_id}/projects/{project_id}/test-cases
# Mirrors TestCaseController.java
# ═════════════════════════════════════════════════════════════════════════════

def store_test_cases(
    team_id: str,
    project_id: str,
    test_cases: list,
    tenant_id: Optional[str] = None,
) -> bool:
    """
    POST test cases to the Java backend.
    Java: POST /teams/{teamId}/projects/{projectId}/test-cases
    Java: @PreAuthorize("hasPermission(#teamId, 'Test Cases', 'Create')")
    """
    url = f"{BASE_URL}/integration/teams/{team_id}/projects/{project_id}/test-cases"
    try:
        response = requests.post(url, json=test_cases, headers=get_headers(tenant_id), timeout=30)
        if response.status_code in [200, 201]:
            logger.info("Stored %d test cases for project %s", len(test_cases), project_id)
            return True
        logger.warning("Failed to store test cases: Java returned %s — %s",
                       response.status_code, response.text)
        return False
    except Exception as e:
        logger.error("Exception storing test cases: %s", e, exc_info=True)
        return False
