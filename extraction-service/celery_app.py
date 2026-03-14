"""
Extraction Service — Celery bootstrap.
Start worker: celery -A celery_app worker --loglevel=info -Q extraction
"""
import os
import ssl

from celery import Celery
from dotenv import load_dotenv

from utils.logging import setup_logging

load_dotenv()
setup_logging("INFO")

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery("extraction", broker=broker_url, backend=result_backend)

if broker_url.startswith("rediss://"):
    app.conf.update(
        broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
        redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    )

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_default_queue="extraction",
)

app.autodiscover_tasks(["tasks"])
