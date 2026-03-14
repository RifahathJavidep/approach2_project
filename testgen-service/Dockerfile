FROM python:3.11-slim

WORKDIR /app

COPY testgen-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared utils and testgen pipeline
COPY utils/ ./utils/
COPY testgen/ ./testgen/

# Service-specific code
COPY testgen-service/app.py ./
COPY testgen-service/celery_app.py ./
COPY testgen-service/api/ ./api/
COPY testgen-service/services/ ./services/
COPY testgen-service/tasks/ ./tasks/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
