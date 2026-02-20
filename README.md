# Requirements Extraction - Trained Approach

## Overview
This project provides a robust, multi-layer extraction pipeline to identify user requirements from various document formats (PDF, PPTX). It features a semantic evaluation system to measure extraction accuracy against ground truth data.

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
   - Input files (PDF/PPTX) → `input/{project_name}/`
   - Ground truth Excel → `ground_truth/`

4. Update `config/config.json` with your project configurations.

## The New Flow (Multi-Project Pipeline)

This project has been updated with a universal flow that supports multiple projects and batch processing.

### 1. Run Extraction
The `run_extraction.py` script uses a multi-layer pipeline to extract requirements:
- **UI Elements**: Captures screens, buttons, and layouts.
- **Workflows**: Extracts logical sequences and steps.
- **Business Logic**: Identifies rules, constraints, and features.

**Usage:**
```bash
# Run for a specific project
python3 run_extraction.py ptw

# Run for all projects defined in config.json
python3 run_extraction.py all
```
*Extracted requirements are saved to `output/{project}_requirements.json`.*

### 2. Run Evaluation
The `run_evaluation.py` script compares extracted requirements with ground truth using semantic matching to calculate Precision, Recall, and F1 Score.

**Usage:**
```bash
# Evaluate a specific project
python3 run_evaluation.py ptw

# Evaluate all projects and show a summary table
python3 run_evaluation.py all
```
*Evaluation results are saved to `output/{project}_evaluation.json`.*

## Progress Tracking
We aim for an **F1 Score ≥ 80%** across all projects. The `run_evaluation.py all` command includes a summary table and highlights projects falling below this threshold.

---

## Legacy Flow (Single Project)

While the new flow is recommended, you can still run extraction using the original scripts:
1. Open `extract_requirements.py` and run it.
2. Open `evaluate.py` and run it.

---

## Background Processing (Celery & Redis)

For long-running extractions, the project uses Celery and Redis.

### 1. Prerequisite: Redis
```bash
# macOS (Homebrew)
brew install redis
brew services start redis
```

### 2. Start Celery Worker
```bash
celery -A celery_app worker --loglevel=info
```

### 3. API Usage
- **Trigger Extraction**: `POST /extract-async`
- **Poll Status**: `GET /status/{task_id}`

## Folder Structure

```
approach2_project/
├── run_extraction.py        # NEW: Universal extraction script
├── run_evaluation.py        # NEW: Universal evaluation script
├── extraction/              # Core pipeline logic
│   ├── pipeline.py          # Multi-layer orchestration
│   ├── extractors/          # Screen/Workflow/Logic extractors
│   └── processors/          # Text and image processing
├── app.py                   # FastAPI service
├── config/
│   └── config.json          # Multi-project configuration
├── input/                   # Input directories by project
├── ground_truth/            # Ground truth Excel files
└── output/                  # Results and metrics
```

## Monitoring
Monitor background tasks using Flower:
```bash
celery -A celery_app flower
```
Access at: `http://localhost:5555`

## Training Data
The system currently uses:
- 8 positive examples (User features)
- 11 negative examples (Implementation details, NFRs)
- Fine-tuned semantic matching thresholds for accuracy.
