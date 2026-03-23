"""
Manual Service — Celery bootstrap.
Start worker: celery -A celery_app worker --loglevel=info -Q manual
"""
import os
import sys
import ssl
from pathlib import Path
from celery import Celery
from dotenv import load_dotenv

# Add project root to sys.path so 'utils' and 'extraction' are visible
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from utils.secrets import get_secret
from utils.logging import setup_logging

load_dotenv()
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "manual-service")
os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", os.getenv("KEYCLOAK_MANUAL_CLIENT_SECRET", ""))
setup_logging("INFO")

broker_url = get_secret("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = get_secret("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery("manual", broker=broker_url, backend=result_backend)

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
    task_default_queue="manual",
)

# Explicitly import task modules
app.conf.imports = ("tasks.extraction",)
