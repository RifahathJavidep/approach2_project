"""
Requirements Extraction FastAPI Service
Run: uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Requirements Extraction Service",
    description="AI-powered requirement extraction from PDF documents",
    version="1.0.0"
)

# ============================================================================
# MODELS
# ============================================================================

class ExtractRequest(BaseModel):
    project_id: int = 1
    project_name: str = "ptw"
    backend_url: str = "http://localhost:8080"

class ExtractResponse(BaseModel):
    project: str
    total_requirements: int
    requirements: list
    backend_result: Optional[dict] = None

class HealthResponse(BaseModel):
    status: str
    groq_key_set: bool
    config_loaded: bool

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health", response_model=HealthResponse)
def health_check():
    """Check service status and environment configuration."""
    groq_key = os.getenv("GROQ_API_KEY", "")
    config_file = Path("config/config.json")
    
    return HealthResponse(
        status="healthy",
        groq_key_set=bool(groq_key),
        config_loaded=config_file.exists()
    )

@app.post("/extract", response_model=ExtractResponse)
def extract_requirements_endpoint(request: ExtractRequest):
    """
    Extract, enrich, and POST requirements from a PDF document.
    
    Pipeline: OCR → Extract → Classify → Dedup → Enrich → POST to Backend
    
    Only requires project_name, project_id, and backend_url.
    PDF path and other config are read from config/config.json.
    """
    from extract_requirements import extract_requirements
    
    # Load base config from file
    config_file = Path("config/config.json")
    if not config_file.exists():
        raise HTTPException(status_code=500, detail="config/config.json not found")
    
    with open(config_file) as f:
        config = json.load(f)
    
    # Override with request values
    config["project_name"] = request.project_name
    config["project_id"] = request.project_id
    config["backend_url"] = ""  # Don't POST from extract_requirements, we do it here
    
    input_path = Path(config.get("input_pdf", ""))
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {config.get('input_pdf')}")
    
    try:
        # Run extraction (without backend POST)
        result = extract_requirements(config)
        
        # Load enriched output
        enriched_file = Path(config["output_dir"]) / f"{request.project_name}_requirements_enriched.json"
        enriched = []
        if enriched_file.exists():
            with open(enriched_file) as f:
                enriched = json.load(f).get('requirements', [])
        
        # POST to backend from here
        backend_result = None
        if request.backend_url and enriched:
            backend_result = post_to_backend(enriched, request.backend_url, request.project_id)
        
        return ExtractResponse(
            project=result['project'],
            total_requirements=len(enriched),
            requirements=enriched,
            backend_result=backend_result
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/evaluation/{project_name}")
def get_evaluation(project_name: str):
    """Get evaluation results (precision, recall, F1) for a project."""
    eval_file = Path("output") / f"{project_name}_evaluation.json"
    
    if not eval_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No evaluation for project '{project_name}'. Run evaluate.py first."
        )
    
    with open(eval_file) as f:
        return json.load(f)

# ============================================================================
# BACKEND API CALL
# ============================================================================

def post_to_backend(requirements: list, backend_url: str, project_id: int) -> dict:
    """POST enriched requirements to the backend API."""
    url = f"{backend_url}/api/requirements/project/{project_id}"
    print(f"\n📤 Posting {len(requirements)} requirements to {url}...")
    
    try:
        response = requests.post(
            url,
            json=requirements,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            print(f"  ✓ Backend accepted: {response.status_code}")
            return {'success': True, 'status_code': response.status_code, 'response': response.json() if response.text else {}}
        else:
            print(f"  ✗ Backend rejected: {response.status_code} - {response.text[:200]}")
            return {'success': False, 'status_code': response.status_code, 'error': response.text[:500]}
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ Backend not reachable at {backend_url}")
        return {'success': False, 'error': f'Connection refused: {backend_url}'}
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {'success': False, 'error': str(e)}
