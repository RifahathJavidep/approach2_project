"""
manual_requirement_api.py
==========================
FastAPI service for manual requirement entry when DSPy auto-extraction fails.
Refactored to use centralized manual extraction logic.
"""

import os
import tempfile
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from s3_utils import download_from_s3, parse_s3_url
from extraction.manual import ManualExtractor

app = FastAPI(
    title="Manual Requirement Entry API v2",
    description="Fallback service for manual requirement entry. Uses centralized extraction logic.",
    version="2.0.0"
)

class ExtractionRequest(BaseModel):
    document_url: str = Field(..., description="S3 URL to the PDF")
    description: str = Field(..., min_length=10, description="Brief description of the requirement")
    page_no: int = Field(..., ge=1, description="Page number (1-indexed)")

@app.post("/extract-requirement")
def extract_requirement(request: ExtractionRequest):
    # 1. Download from S3
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            local_path = download_from_s3(request.document_url, tmp_dir)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"S3 Download failed: {str(e)}")

        # 2. Extract
        extractor = ManualExtractor()
        try:
            result = extractor.extract_from_page(local_path, request.description, request.page_no)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Extraction error: {str(e)}")

        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result.get("message"))
        
        if result["status"] == "no_requirements":
            raise HTTPException(status_code=404, detail=result.get("message"))

        # 3. Format Response (Maintaining compatibility with v1)
        req_data = result["requirement"]
        return {
            "requirement_id": f"MANUAL-{datetime.now().strftime('%Y%m%d-%H%M%s')}",
            "title": req_data.get("title", "Untitled Requirement"),
            "description": req_data.get("description", request.description),
            "requirement_type": req_data.get("requirement_type", "Functional"),
            "category": req_data.get("category", "General"),
            "priority": req_data.get("priority", "Medium"),
            "user_roles": req_data.get("user_roles", []),
            "user_story": req_data.get("user_story", ""),
            "acceptance_criteria": req_data.get("acceptance_criteria", []),
            "test_steps": req_data.get("test_steps", []),
            "business_rules": req_data.get("business_rules", []),
            "dependencies": req_data.get("dependencies", []),
            "assumptions": req_data.get("assumptions", []),
            "source_document": Path(local_path).name,
            "source_url": request.document_url,
            "source_page": request.page_no,
            "context_pages_used": [request.page_no],
            "extraction_method": "manual",
            "extracted_at": datetime.now().isoformat(),
            "user_provided_description": request.description,
            "validation_warnings": []
        }

@app.get("/health")
def health():
    return {"status": "ok", "mode": "modular_refactored"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
