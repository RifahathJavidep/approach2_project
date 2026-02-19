import os
import json
import sys
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv
from document_status import update_document_statuses, update_single_document_status

# Ensure project directory is in path for Celery worker
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
    
print(f"DEBUG: Celery Worker started. BASE_DIR: {BASE_DIR}")
print(f"DEBUG: sys.path includes: {sys.path[:3]}")

# Load environment variables
load_dotenv()

# Initialize Celery
app = Celery('prism',
             broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
             backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'))

# Celery Configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600, # 1 hour max
)

@app.task(name="extract_requirements_task", bind=True)
def extract_requirements_task(self, project_id, local_files, output_dir, existing_model_state, multi_project_config, file_urls=None):
    """
    Background task to extract requirements.
    This runs the heavy lifting in a Celery worker.
    """
    import sys, os
    from pathlib import Path
    
    # Absolute path check
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
        
    try:
        from extract_requirements import extract_from_files, _get_lm
    except ImportError as e:
        print(f"DEBUG: Task failed to import. sys.path: {sys.path}")
        print(f"DEBUG: current_dir: {current_dir}")
        print(f"DEBUG: dir contents: {os.listdir(current_dir)}")
        raise ImportError(f"Celery worker cannot find 'extract_requirements'. Path: {current_dir}. Error: {e}")

    import dspy
    
    self.update_state(state='PROGRESS', meta={'message': 'Starting extraction process'})

    # Build per-file status callback (maps local paths → S3 URLs)
    status_callback = None
    if file_urls:
        # Map local file paths to their original S3 URLs by matching filenames
        local_to_url = {}
        for local_path, s3_url in zip(local_files, file_urls):
            local_to_url[local_path] = s3_url

        def status_callback(file_path, status):
            """Called by the pipeline for each file: IN_PROGRESS, COMPLETED, or FAILED."""
            s3_url = local_to_url.get(file_path)
            if s3_url:
                update_single_document_status(project_id, s3_url, status)

    try:
        # We MUST wrap in dspy.context for the worker thread
        with dspy.context(lm=_get_lm()):
            result = extract_from_files(
                project_name=project_id,
                file_paths=local_files,
                output_dir=output_dir,
                model_state=existing_model_state,
                config=multi_project_config,
                status_callback=status_callback,
            )

            # Save the model locally as requested by the user previously
            if "model_state" in result:
                model_dir = Path(__file__).parent / "models" / str(project_id)
                model_path = model_dir / "classifier_model.json"
                os.makedirs(model_dir, exist_ok=True)
                with open(model_path, 'w') as f:
                    json.dump(result["model_state"], f, indent=2)
                print(f"  ✓ Celery Worker saved model LOCALLY to: {model_path}")

            return {
                "status": "success",
                "project_id": project_id,
                "total_requirements": len(result.get("requirements", [])),
                "req_s3_key": f"projects/{project_id}/output/requirements.json"
            }

    except Exception as e:
        # Mark any remaining files as FAILED
        if file_urls:
            update_document_statuses(project_id, file_urls, "FAILED")
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise e
