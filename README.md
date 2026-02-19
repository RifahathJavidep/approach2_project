# Requirements Extraction - Trained Approach

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.template` to `.env` and add your GROQ API key:
```bash
cp .env.template .env
# Edit .env and add your key
```

3. Place your files:
   - Input PDF → `input/` folder
   - Ground truth Excel → `ground_truth/` folder

4. Update `config/config.json` with your file names

## Run (VS Code)

1. Open `extract_requirements.py`
2. Press F5 to run extraction
3. Open `evaluate.py`
4. Press F5 to run evaluation

## Run (Terminal)

```bash
python extract_requirements.py
python evaluate.py
```

## Background Processing (Celery & Redis)

For long-running extractions, the project uses Celery and Redis to handle tasks in the background.

### 1. Prerequisite: Redis
Redis must be installed and running.
```bash
# macOS (Homebrew)
brew install redis
brew services start redis
```

### 2. Start Celery Worker
Run the worker in its own terminal to process the queued jobs.
```bash
celery -A celery_app worker --loglevel=info
```

### 3. API Usage
The extraction can be triggered via a non-blocking asynchronous call.

- **Trigger Extraction**: `POST /extract-async`
  - Payload matches `POST /extract`
  - Returns a `task_id` immediately.
- **Poll Status**: `GET /status/{task_id}`
  - Track if the job is `PENDING`, `STARTED`, `PROGRESS`, or `SUCCESS`.

## Folder Structure

```
approach2_project/
├── app.py                   # FastAPI service
├── celery_app.py            # Celery application & tasks
├── extract_requirements.py  # AI extraction logic
├── CELERY_REDIS_ARCHITECTURE.md # Detailed system docs
├── models/                  # Locally saved trained models
├── config/
│   └── config.json          # Multi-project configuration
└── requirements.txt         # Dependencies (includes Celery/Redis)
```

## Monitoring
You can use **Flower** to monitor background tasks in a web dashboard:
```bash
celery -A celery_app flower
```
Access at: `http://localhost:5555`

## Training Data

- 8 positive examples (user features)
- 11 negative examples (implementation details, NFRs)
- Domain-agnostic: teaches "requirement vs non-requirement"

## Output Files

- `output/{project}_requirements.json` - Extracted requirements
- `output/{project}_evaluation.json` - Evaluation metrics
# approach2_project
