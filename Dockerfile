# ============================================================================
# Dockerfile for PRISM AI — Python Individual Service
# ============================================================================

FROM python:3.10-slim

# Install system dependencies for OCR and OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Copy configuration
COPY configuration/ /app/configuration/

# 2. Copy source code
COPY source_code/ /app/source_code/

# 3. Install requirements
RUN pip install --no-cache-dir -r /app/source_code/requirements.txt

# 4. Set environment
WORKDIR /app/source_code
ENV PYTHONPATH=/app/source_code
ENV PORT=8000

# Default command for API (can be overridden in docker-compose for worker)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
