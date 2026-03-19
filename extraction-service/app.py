"""
PRISM Extraction Service — FastAPI bootstrap.
Handles Phase 1: document ingestion and BR extraction.

Start: uvicorn app:app --host 0.0.0.0 --port 8000
Docs:  http://localhost:8000/docs
"""
import sys
from pathlib import Path

# Add project root to sys.path so 'utils' and 'extraction' are visible
root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import logging
import time

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from utils.logging import setup_logging

import os
load_dotenv()
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "extracter-service")
setup_logging("DEBUG")
logger = logging.getLogger("prism.extraction")

app = FastAPI(
    title="PRISM — Extraction Service",
    description="Extract business requirements from uploaded documents",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class APILoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("%s %s -- 500 -- %s", request.method, request.url.path, exc, exc_info=True)
            raise
        logger.info("%s %s -- %s  %.3fs", request.method, request.url.path, response.status_code, time.time() - start)
        return response


app.add_middleware(APILoggingMiddleware)

from api.routers import health, documents, requirements, manual_extract

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(requirements.router)
app.include_router(manual_extract.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
