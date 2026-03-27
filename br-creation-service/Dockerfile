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
COPY br-creation-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities (s3, java_client, deduplication, secrets, logging) and global config
COPY common/ ./common/
COPY config.py ./config.py
COPY config.yaml ./config.yaml

# Extraction pipeline (DSPy, OCR, file routing, generators)
COPY requirement_engine/ ./extraction/

# Service code (flattened structure)
COPY br-creation-service/app.py ./
COPY br-creation-service/celery_app.py ./
COPY br-creation-service/schemas.py ./
COPY br-creation-service/br_extraction_handler.py ./
COPY br-creation-service/br_extraction_task.py ./
COPY br-creation-service/document_handler.py ./

# Non-root user — required for production and Kubernetes security policy
RUN useradd -m -u 1001 prism && chown -R prism:prism /app
USER prism

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
