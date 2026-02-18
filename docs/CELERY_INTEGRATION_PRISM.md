# Celery Integration Guide for Prism

This guide outlines how to implement Celery in the current **Prism** project structure based on your integration document.

## Phase 1: Infrastructure & Task Setup

### 1. Install Dependencies
You will need Celery and the Redis client for Python.

```bash
pip install celery[redis] redis
```

### 2. Configure Environment
Update your `.env` file with the Redis URL:
```env
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

### 3. Create `celery_app.py`
This will be the heart of your background processing.

```python
import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

app = Celery('prism', 
             broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
             backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'))

@app.task(name="extract_requirements_task")
def extract_requirements_task(project_id, local_files, output_dir, existing_model_state, multi_project_config):
    from extract_requirements import extract_from_files, _get_lm
    import dspy
    
    # We must wrap in dspy.context for the worker thread
    with dspy.context(lm=_get_lm()):
        return extract_from_files(
            project_name=project_id,
            file_paths=local_files,
            output_dir=output_dir,
            model_state=existing_model_state,
            config=multi_project_config
        )
```

### 4. Update `app.py`
Add a new asynchronous endpoint:

```python
from celery_app import extract_requirements_task

@app.post("/extract-async")
async def extract_requirements_async(request: ExtractionRequest):
    # ... handle file downloads as before ...
    
    # Trigger the task and return the ID immediately
    task = extract_requirements_task.delay(
        project_id, local_files, output_dir, existing_model_state, multi_project_config
    )
    
    return {"status": "accepted", "task_id": task.id}
```

## Next Steps
1. **Start Redis server** (e.g., `brew services start redis`).
2. **Start the Celery worker**:
   ```bash
   celery -A celery_app worker --loglevel=info
   ```
3. **Monitor with Flower** (Optional):
   ```bash
   celery -A celery_app flower
   ```
