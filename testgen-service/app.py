"""
PRISM TestGen Service — FastAPI bootstrap.
Handles Phase 2: test case generation from requirements.

Start: uvicorn app:app --host 0.0.0.0 --port 8001
Docs:  http://localhost:8001/docs
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
logger = logging.getLogger("prism.testgen")

app = FastAPI(
    title="PRISM — TestGen Service",
    description="Generate test cases from extracted business requirements",
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

from api.routers import health, testcases

app.include_router(health.router)
app.include_router(testcases.router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002, reload=False)
