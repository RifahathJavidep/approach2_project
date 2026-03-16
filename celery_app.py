"""
PRISM Celery Bootstrap

Celery instance configuration only.
Task definitions live in tasks/extraction.py and tasks/testcases.py.

Start worker: celery -A celery_app worker --loglevel=info
"""
import os
import ssl

from celery import Celery
from utils.secrets import get_secret
from utils.logging import setup_logging

setup_logging("INFO")

broker_url = get_secret("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = get_secret("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery("prism", broker=broker_url, backend=result_backend)

# SSL support for AWS ElastiCache (rediss://)
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
)

# Auto-discover tasks from the tasks/ package
app.autodiscover_tasks(["tasks"])
