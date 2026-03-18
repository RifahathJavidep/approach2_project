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
COPY manual-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities
COPY utils/ ./utils/

# Extraction pipeline (DSPy, OCR, file routing, generators) — shared with extraction-service
COPY extraction/ ./extraction/

# Global pipeline config
COPY config.yaml ./config.yaml

# Service code
COPY manual-service/app.py ./
COPY manual-service/celery_app.py ./
COPY manual-service/api/ ./api/
COPY manual-service/services/ ./services/
COPY manual-service/tasks/ ./tasks/

# Non-root user
RUN useradd -m -u 1001 prism && chown -R prism:prism /app
USER prism

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "2"]
