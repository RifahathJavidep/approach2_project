"""
Manual Service Celery tasks — thin wrappers around manual extraction logic.
"""
import logging

from celery_app import app

logger = logging.getLogger("prism.manual.tasks.extraction")


@app.task(name="manual_extract_task", bind=True)
def manual_extract_task(self, project_id: str, document_url: str, description: str, page_no: int, tenant_id: str | None = None):
    """Run DSPy manual extraction as a background Celery task."""
    import asyncio
    from services.extraction import run_manual_dspy_extraction

    self.update_state(state="PROGRESS", meta={"message": "Starting manual extraction"})

    try:
        result = asyncio.get_event_loop().run_until_complete(
            run_manual_dspy_extraction(project_id, document_url, description, page_no, tenant_id)
        )
        return result
    except Exception as e:
        logger.error("Manual extraction task failed: %s", e, exc_info=True)
        raise
