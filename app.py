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
from typing import List, Optional, Union, Any, Dict
from celery.result import AsyncResult
from celery_app import extract_requirements_task

from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
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


@app.post("/extract")
async def extract_requirements_endpoint(request: ExtractionRequest):
    """
    Main extraction endpoint.

    Flow:
    1. Download files from S3 URLs
    2. Extract text (OCR for image-based PDFs)
    3. Train classifier + extract requirements
    4. Upload results + trained model to S3
    5. Return requirements JSON
    """
    project_id = request.project_id
    file_urls = request.file_urls

    if not file_urls:
        raise HTTPException(status_code=400, detail="No file URLs provided")

    if not project_id:
        raise HTTPException(status_code=400, detail="No project_id provided")

    # Load multi-project config for training context
    config_path = Path(__file__).parent / "config" / "config.json"
    multi_project_config = None
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                multi_project_config = json.load(f)
                # Ensure the current project is correctly set in config
                multi_project_config['current_project'] = project_id
        except Exception as e:
            print(f"  WARNING: Failed to load config.json: {e}")

    # Create temp directory for this extraction
    tmp_dir = os.path.join(tempfile.gettempdir(), f"prism_{project_id}")
    input_dir = os.path.join(tmp_dir, "input")
    output_dir = os.path.join(tmp_dir, "output")
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    try:
        from s3_utils import download_from_s3, upload_json_to_s3
        from extract_requirements import extract_from_files

        # ----------------------------------------------------------
        # Step 1: Download all files from S3
        # ----------------------------------------------------------
        print(f"\n{'='*60}")
        print(f"PROJECT: {project_id}")
        print(f"{'='*60}")
        print(f"\n1. Downloading {len(file_urls)} file(s) from S3...")

        local_files = []
        for url in file_urls:
            try:
                local_path = download_from_s3(url, input_dir)
                local_files.append(local_path)
            except Exception as e:
                print(f"  WARNING: Failed to download {url}: {e}")

        if not local_files:
            raise HTTPException(
                status_code=400,
                detail="Failed to download any files from S3",
            )

        print(f"  Downloaded {len(local_files)} file(s)")

        # ----------------------------------------------------------
        # Step 1.5: Check for existing model state LOCALLY
        # ----------------------------------------------------------
        model_dir = Path(__file__).parent / "models" / str(project_id)
        model_path = model_dir / "classifier_model.json"
        existing_model_state = None
        
        if model_path.exists():
            try:
                print(f"\n1.5. Found existing model LOCALLY: {model_path}")
                with open(model_path, 'r') as f:
                    existing_model_state = json.load(f)
                print("  ✓ Model state loaded from local disk")
            except Exception as e:
                print(f"  ⚠ Failed to load local model: {e}")

        # ----------------------------------------------------------
        # Step 2: Extract requirements from all files
        # ----------------------------------------------------------
        print(f"\n2. Extracting requirements...")

        import dspy
        from extract_requirements import _get_lm
        
        # Use dspy.context for thread/async safety
        with dspy.context(lm=_get_lm()):
            result = extract_from_files(
                project_name=project_id,
                file_paths=local_files,
                output_dir=output_dir,
                model_state=existing_model_state,
                config=multi_project_config
            )

        requirements = result["requirements"]
        print(f"  Extracted {len(requirements)} requirements")

        # ----------------------------------------------------------
        # Step 3: Upload results to S3 & Save model LOCALLY
        # ----------------------------------------------------------
        print(f"\n3. Uploading results to S3 and Saving Model Locally...")

        # Upload requirements JSON to S3
        req_s3_key = f"projects/{project_id}/output/requirements.json"
        req_s3_url = upload_json_to_s3(result, req_s3_key)

        # Save trained model state LOCALLY
        model_s3_url = None
        if "model_state" in result:
            os.makedirs(model_dir, exist_ok=True)
            with open(model_path, 'w') as f:
                json.dump(result["model_state"], f, indent=2)
            print(f"  ✓ Model state saved LOCALLY to: {model_path}")
            
            # (Optional) Still upload a backup to S3 if desired, 
            # but the user asked to work locally.
            model_s3_key = f"projects/{project_id}/models/classifier_model.json"
            model_s3_url = upload_json_to_s3(result["model_state"], model_s3_key)

        print(f"\n{'='*60}")
        print(f"DONE: {len(requirements)} requirements extracted")
        print(f"{'='*60}")

        # ----------------------------------------------------------
        # Step 4: Automatically store in Java Backend (Postgres)
        # ----------------------------------------------------------
        try:
            java_backend_url = f"http://localhost:8080/api/requirements/project/{project_id}"
            print(f"\n4. Storing {len(requirements)} requirements in Java backend...")
            
            # Map Python format to Java DTO format
            mapped_requirements = []
            for req in requirements:
                mapped_requirements.append({
                    "short_title": req.get("title") or req.get("short_title"),
                    "description": req.get("description"),
                    "is_requirement": True,
                    "user_story": req.get("user_story", ""),
                    "acceptance_criteria": req.get("acceptance_criteria", []),
                    "test_steps": req.get("test_steps", []),
                    "test_scenarios": req.get("test_scenarios", []),
                    "assumptions": req.get("assumptions", []),
                    "ambiguities": req.get("ambiguities", []),
                    "confidence": req.get("confidence", "High"),
                    "extraction_model": "llama-3.3-70b-versatile",
                    "extraction_timestamp": datetime.utcnow().isoformat(),
                    "validation_confirmed": False,
                    "metadata": {
                        "source_file": (file_urls[0].split("/")[-1]) if file_urls else "unknown",
                        "extraction_timestamp": datetime.utcnow().isoformat()
                    }
                })

            async with httpx.AsyncClient() as client:
                java_response = await client.post(
                    java_backend_url, 
                    json=mapped_requirements,
                    timeout=10.0
                )
                if java_response.status_code in [200, 201]:
                    print(f"  ✓ Successfully stored in Java backend (Postgres)")
                else:
                    print(f"  ⚠ Java backend returned error: {java_response.status_code} - {java_response.text}")
        except Exception as e:
            print(f"  ⚠ Failed to store in Java backend: {e}")

        return {
            "status": "success",
            "project_id": project_id,
            "total_requirements": len(requirements),
            "requirements": requirements,
            "s3_output": {
                "requirements_url": req_s3_url,
                "model_url": model_s3_url,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Extraction failed: {str(e)}"
        )
    finally:
        # Clean up temp files
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


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

    # Load multi-project config
    config_path = Path(__file__).parent / "config" / "config.json"
    multi_project_config = None
    if config_path.exists():
        try:
            with open(config_path, 'r') as f:
                multi_project_config = json.load(f)
                multi_project_config['current_project'] = project_id
        except Exception:
            pass

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

    # Dispatch to Celery
    task = extract_requirements_task.delay(
        project_id=str(project_id),
        local_files=local_files,
        output_dir=output_dir,
        existing_model_state=existing_model_state,
        multi_project_config=multi_project_config,
        file_urls=file_urls,
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
