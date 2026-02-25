"""
FastAPI service for PTW Requirements Extraction with S3 Integration
Start: python app.py
Docs:  http://localhost:8000/docs
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional, Union
from celery.result import AsyncResult
from celery_app import extract_requirements_task

from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
from document_status import update_document_statuses

# Load environment
load_dotenv()

# Ensure project directory is in path
sys.path.insert(0, str(Path(__file__).parent))

# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="PTW Requirements Extractor",
    description="Extract user-facing requirements from project documents stored in S3",
    version="2.0.0",
)

# Allow Angular frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with your Angular app URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class ExtractionRequest(BaseModel):
    """Request body for POST /extract"""
    project_id: Union[str, int]
    project_name: Optional[str] = None
    file_urls: List[str]  # S3 URLs or S3 keys

class UploadUrlRequest(BaseModel):
    """Request body for POST /generate-upload-url"""
    project_id: str
    filename: str

class ExtractionResponse(BaseModel):
    """Response body for POST /extract"""
    status: str
    project_id: str
    total_requirements: int
    requirements: list
    s3_output: dict

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Check if the service is running and all credentials configured."""
    groq_key = os.getenv("GROQ_API_KEY")
    aws_key = os.getenv("AWS_ACCESS_KEY_ID")
    bucket = os.getenv("S3_BUCKET_NAME", "katsuai-tcgen")

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "groq_api_key_set": bool(groq_key),
            "aws_credentials_set": bool(aws_key),
            "s3_bucket": bucket,
        },
    }


@app.post("/generate-upload-url")
async def generate_upload_url_endpoint(request: UploadUrlRequest):
    """
    Generate a pre-signed URL for the frontend to upload a file directly to S3.
    Choice B workflow: Use this to get a secure upload link without exposing AWS keys.
    """
    try:
        from s3_utils import generate_presigned_upload_url
        
        project_id = request.project_id
        filename = request.filename
        
        # Consistent pathing: uploads/{project_id}/{filename}
        s3_key = f"uploads/{project_id}/{filename}"
        
        presigned_data = generate_presigned_upload_url(s3_key)
        
        return {
            "status": "success",
            "project_id": project_id,
            "filename": filename,
            "s3_key": s3_key,
            "presigned_post": presigned_data
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate upload URL: {str(e)}"
        )


@app.get("/requirements/project/{project_id}")
async def get_requirements(project_id: str):
    """
    Get cached requirements from S3 (no re-extraction).
    Fetches the last extracted results from S3.
    """
    try:
        from s3_utils import download_json_from_s3, file_exists_in_s3

        s3_key = f"projects/{project_id}/output/requirements.json"

        if not file_exists_in_s3(s3_key):
            raise HTTPException(
                status_code=404,
                detail=f"No requirements found for project '{project_id}'. Run POST /extract first.",
            )

        data = download_json_from_s3(s3_key)

        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": len(data.get("requirements", [])),
            "requirements": data.get("requirements", []),
            "s3_url": f"s3://{os.getenv('S3_BUCKET_NAME', 'katsuai-tcgen')}/{s3_key}",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch requirements: {str(e)}"
        )


# ============================================================================
# MAIN
# ============================================================================

@app.post("/extract-async")
async def extract_requirements_async(request: ExtractionRequest):
    """
    Asynchronous version of the extraction endpoint.
    Queues the task in Celery and returns a task_id immediately.
    """
    project_id = request.project_id
    file_urls = request.file_urls
    
    if not project_id:
        raise HTTPException(status_code=400, detail="No project_id provided")

    # Check local model
    model_dir = Path(__file__).parent / "models" / str(project_id)
    model_path = model_dir / "classifier_model.json"
    existing_model_state = None
    if model_path.exists():
        try:
            with open(model_path, 'r') as f:
                existing_model_state = json.load(f)
        except Exception:
            pass

    # Create temp directory
    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_async_{project_id}")
    input_dir = os.path.join(tmp_dir, "input")
    output_dir = os.path.join(tmp_dir, "output")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Download files (Worker will need local paths)
    from s3_utils import download_from_s3
    local_files = []
    for url in file_urls:
        try:
            local_path = download_from_s3(url, input_dir)
            local_files.append(local_path)
        except Exception:
            pass

    if not local_files:
        raise HTTPException(status_code=400, detail="Failed to download any files from S3")

    # POST initial PENDING status to Java backend (best-effort)
    # Returns the created records with their database IDs
    document_statuses = update_document_statuses(str(project_id), file_urls, "PENDING")
    print(f"  [App] Java backend returned {len(document_statuses)} status records: {document_statuses}")

    # Dispatch to Celery — pass the document status records so the worker
    # can UPDATE by ID instead of creating duplicate rows
    task = extract_requirements_task.delay(
        project_id=str(project_id),
        local_files=local_files,
        output_dir=output_dir,
        existing_model_state=existing_model_state,
        multi_project_config=None,
        file_urls=file_urls,
        document_statuses=document_statuses,
    )
    return {
        "status": "accepted",
        "task_id": task.id,
        "message": "Requirement extraction queued successfully",
        "document_statuses": document_statuses,
    }


@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """
    Check the status of a Celery task.
    """
    task_result = AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": task_result.status,
    }
    
    if task_result.status == 'SUCCESS':
        response["result"] = task_result.result
    elif task_result.status == 'FAILURE':
        response["error"] = str(task_result.result)
    
    return response


if __name__ == "__main__":
    print("Starting PTW Requirements Extractor API...")
    print("Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
