# Requirements Extraction API Documentation

## Base URL
```
http://localhost:8000
```

## Quick Start
```bash
cd approach2_project
./venv/bin/uvicorn app:app --reload --port 8000
```

---

## Endpoints

### 1. Health Check
**`GET /health`**

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "groq_key_set": true,
  "config_loaded": true
}
```

---

### 2. Extract Requirements
**`POST /extract`**

Runs the full AI pipeline and POSTs results to the backend.

**Request Body:**
```json
{
  "project_id": 1,
  "project_name": "ptw",
  "backend_url": "http://localhost:8080"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `project_id` | int | `1` | Backend project ID |
| `project_name` | string | `"ptw"` | Project identifier |
| `backend_url` | string | `"http://localhost:8080"` | Backend URL to POST results to |

**cURL:**
```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "project_name": "ptw",
    "backend_url": "http://localhost:8080"
  }'
```

**Response:**
```json
{
  "project": "ptw",
  "total_requirements": 26,
  "requirements": [
    {
      "is_requirement": true,
      "short_title": "Wireless Management Dashboard",
      "description": "Provide key wireless management insights...",
      "user_story": "As a wireless service manager, I want...",
      "acceptance_criteria": ["Dashboard displays active subscribers", "..."],
      "test_steps": [
        {"step_num": 1, "action": "Login to the system", "expected_result": "Logged in", "test_data": "Valid credentials"}
      ],
      "test_scenarios": ["Verify dashboard with zero subscribers"],
      "assumptions": ["System has necessary integrations"],
      "ambiguities": ["Exact layout not specified"],
      "confidence": "high",
      "extraction_model": "llama-3.3-70b-versatile",
      "extraction_timestamp": "2026-02-16T19:13:46.616054",
      "validation_confirmed": true,
      "metadata": { "source_file": "...", "extraction_model": "..." }
    }
  ],
  "backend_result": { "success": true, "status_code": 200 }
}
```

> After extraction, the service POSTs all requirements to:
> `POST {backend_url}/api/requirements/project/{project_id}`

---

### 3. Get Evaluation Results
**`GET /evaluation/{project_name}`**

```bash
curl http://localhost:8000/evaluation/ptw
```

**Response:**
```json
{
  "metrics": { "precision": 0.50, "recall": 0.59, "f1_score": 0.54 },
  "counts": { "gt": 22, "extracted": 26, "true_positives": 13 },
  "matched": [...],
  "missed": [...],
  "over_created": [...]
}
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ | API key for Groq LLM |

## Swagger Docs
Once running, visit **http://localhost:8000/docs** for interactive API docs.
