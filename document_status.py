"""
Utility for posting document processing status updates to the Java backend.
Best-effort: failures are logged but never raised.
Returns the created/updated records (with IDs) so callers can forward them.
"""

import os
import requests
from typing import List, Optional, Dict, Any

JAVA_BACKEND_BASE_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")


def update_document_statuses(project_id: str, file_urls: List[str], status: str) -> List[Dict[str, Any]]:
    """
    POST document status updates to the Java backend (batch).

    Args:
        project_id: The project identifier.
        file_urls: List of original S3 URLs (the documentUrl values).
        status: One of "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED".

    Returns:
        List of created/updated document-status records from Java backend,
        each containing at least { id, documentUrl, status }.
        Returns empty list on failure.
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": file_url, "status": status} for file_url in file_urls]

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            print(f"  [DocumentStatus] Updated {len(file_urls)} file(s) to {status} for project {project_id}")
            # Parse and return the response body (contains IDs)
            try:
                return response.json()
            except ValueError:
                print(f"  [DocumentStatus] WARNING: Response is not JSON, returning empty list")
                return []
        else:
            print(f"  [DocumentStatus] WARNING: Java backend returned {response.status_code}: {response.text}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"  [DocumentStatus] WARNING: Failed to update status to {status}: {e}")
        return []


def update_single_document_status(project_id: str, file_url: str, status: str) -> Optional[Dict[str, Any]]:
    """
    POST a single document's status update to the Java backend.

    Args:
        project_id: The project identifier.
        file_url: Original S3 URL (the documentUrl value).
        status: One of "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED".

    Returns:
        The created/updated document-status record from Java backend
        containing at least { id, documentUrl, status }.
        Returns None on failure.
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": file_url, "status": status}]

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            print(f"  [DocumentStatus] {file_url} → {status}")
            # Parse and return the first record (contains ID)
            try:
                data = response.json()
                # Response is a list — return just the first item
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                return data
            except ValueError:
                print(f"  [DocumentStatus] WARNING: Response is not JSON, returning None")
                return None
        else:
            print(f"  [DocumentStatus] WARNING: Java backend returned {response.status_code}: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"  [DocumentStatus] WARNING: Failed to update {file_url} to {status}: {e}")
        return None
