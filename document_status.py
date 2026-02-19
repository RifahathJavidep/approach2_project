"""
Utility for posting document processing status updates to the Java backend.
Best-effort: failures are logged but never raised.
"""

import os
import requests
from typing import List

JAVA_BACKEND_BASE_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")


def update_document_statuses(project_id: str, file_urls: List[str], status: str) -> None:
    """
    POST document status updates to the Java backend (batch).

    Args:
        project_id: The project identifier.
        file_urls: List of original S3 URLs (the documentUrl values).
        status: One of "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED".
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": file_url, "status": status} for file_url in file_urls]

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            print(f"  [DocumentStatus] Updated {len(file_urls)} file(s) to {status} for project {project_id}")
        else:
            print(f"  [DocumentStatus] WARNING: Java backend returned {response.status_code}: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"  [DocumentStatus] WARNING: Failed to update status to {status}: {e}")


def update_single_document_status(project_id: str, file_url: str, status: str) -> None:
    """
    POST a single document's status update to the Java backend.

    Args:
        project_id: The project identifier.
        file_url: Original S3 URL (the documentUrl value).
        status: One of "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED".
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": file_url, "status": status}]

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            print(f"  [DocumentStatus] {file_url} → {status}")
        else:
            print(f"  [DocumentStatus] WARNING: Java backend returned {response.status_code}: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"  [DocumentStatus] WARNING: Failed to update {file_url} to {status}: {e}")
