"""
PRISM AI — FastAPI Service Bootstrap

Start: python app.py
Docs:  http://localhost:8000/docs
"""
import logging
import time

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from utils.logging import setup_logging

load_dotenv()
setup_logging("DEBUG")
logger = logging.getLogger("prism.api")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="PRISM AI — Requirements & Test Cases",
    description="Extract requirements from documents and generate professional test cases",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Logging ────────────────────────────────────────────────

class APILoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        query = f"?{request.query_params}" if request.query_params else ""
        client = request.client.host if request.client else "unknown"
        logger.info("->  %s %s%s  (client=%s)", request.method, request.url.path, query, client)

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("<-  %s %s -- 500 in %.3fs -- %s",
                         request.method, request.url.path, time.time() - start, exc, exc_info=True)
            raise

        logger.info("<-  %s %s -- %s in %.3fs",
                    request.method, request.url.path, response.status_code, time.time() - start)
        return response


app.add_middleware(APILoggingMiddleware)


# ── Routers ───────────────────────────────────────────────────────────────────

from api.routers import health, documents, requirements, manual_extract, testcases

app.include_router(health.router)
app.include_router(documents.router)
app.include_router(requirements.router)
app.include_router(manual_extract.router)
app.include_router(testcases.router)


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting PRISM AI Service -- http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False, log_level="info")
