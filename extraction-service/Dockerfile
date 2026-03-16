FROM python:3.11-slim

WORKDIR /app

# System libraries required by PaddleOCR and OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first — Docker caches this layer until requirements.txt changes
COPY extraction-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities (s3, java_client, deduplication, secrets, logging)
COPY utils/ ./utils/

# Extraction pipeline (DSPy, OCR, file routing, generators)
COPY extraction/ ./extraction/

# Global pipeline config (LLM model, document classification, training params)
COPY config.yaml ./config.yaml

# Service code
COPY extraction-service/app.py ./
COPY extraction-service/celery_app.py ./
COPY extraction-service/api/ ./api/
COPY extraction-service/services/ ./services/
COPY extraction-service/tasks/ ./tasks/

# Non-root user — required for production and Kubernetes security policy
RUN useradd -m -u 1001 prism && chown -R prism:prism /app
USER prism

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
