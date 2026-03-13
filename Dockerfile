# ============================================================================
# Dockerfile for PRISM AI — Requirements & Test Cases
# Organized Structure: configuration/ and source_code/
# ============================================================================

FROM python:3.10-slim

# Install system dependencies for OCR, OpenCV and Python builds
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

# 2. Copy source code and requirements
COPY source_code/ /app/source_code/

# 3. Install dependencies from source_code/requirements.txt
RUN pip install --no-cache-dir -r /app/source_code/requirements.txt

# 4. Set working directory to source_code for execution
WORKDIR /app/source_code

# Ensure the source_code directory is in PYTHONPATH
ENV PYTHONPATH=/app/source_code
ENV PORT=8000
ENV LOG_LEVEL=INFO

# Expose the API port
EXPOSE 8000

# Default Command: Start FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
