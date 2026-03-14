FROM python:3.11-slim

WORKDIR /app

# System deps for PaddleOCR and OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY extraction-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utils and extraction pipeline
COPY utils/ ./utils/
COPY extraction/ ./extraction/

# Service-specific code
COPY extraction-service/app.py ./
COPY extraction-service/celery_app.py ./
COPY extraction-service/api/ ./api/
COPY extraction-service/services/ ./services/
COPY extraction-service/tasks/ ./tasks/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
