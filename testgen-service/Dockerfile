FROM python:3.11-slim

WORKDIR /app

# curl needed for healthcheck only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first — Docker caches this layer until requirements.txt changes
COPY testgen-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utilities (s3, java_client, secrets, logging)
COPY utils/ ./utils/

# TestGen pipeline (planner, scenario generator, exporters)
COPY testgen/ ./testgen/

# Global pipeline config (LLM model, training params)
COPY config.yaml ./config.yaml

# Service code
COPY testgen-service/app.py ./
COPY testgen-service/celery_app.py ./
COPY testgen-service/api/ ./api/
COPY testgen-service/services/ ./services/
COPY testgen-service/tasks/ ./tasks/

# Non-root user — required for production and Kubernetes security policy
RUN useradd -m -u 1001 prism && chown -R prism:prism /app
USER prism

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "2"]
