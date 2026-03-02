"""
Utility for posting document processing status updates to the Java backend.
"""

import os
import requests
from typing import List, Optional, Dict, Any

JAVA_BACKEND_BASE_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")

def update_document_statuses(project_id: str, file_urls: List[str], status: str) -> List[Dict[str, Any]]:
    """
    POST initial PENDING status (batch). Returns list of records with IDs.
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/document-statuses/projects/{project_id}"
    payload = [{"documentUrl": url, "status": status} for url in file_urls]
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json() if response.status_code in [200, 201] else []
    except Exception as e:
        print(f"  [DocumentStatus] ERROR: {e}")
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
        print(f"  [DocumentStatus] Sending ID-based update: {payload}")
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code in [200, 201]:
            print(f"  [DocumentStatus] SUCCESS: ID {doc_status_id} updated to {status}")
            data = response.json()
            return data[0] if isinstance(data, list) and data else data
        else:
            print(f"  [DocumentStatus] FAILED: Java returned {response.status_code}")
            return None
    except Exception as e:
        print(f"  [DocumentStatus] EXCEPTION: {e}")
        return None
