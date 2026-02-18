# Celery Implementation Guide

## AI Test Case Generator — Parallel Processing Architecture

---

## Table of Contents

1. [Why Celery for This Project](#1-why-celery-for-this-project)
2. [Architecture Overview](#2-architecture-overview)
3. [Infrastructure Setup](#3-infrastructure-setup)
4. [Implementation — Step by Step](#4-implementation--step-by-step)
5. [Task Definitions](#5-task-definitions)
6. [Workflow Orchestration with Chains & Chords](#6-workflow-orchestration-with-chains--chords)
7. [Rate Limiting & Retry Strategy](#7-rate-limiting--retry-strategy)
8. [Monitoring & Observability](#8-monitoring--observability)
9. [Deployment Patterns](#9-deployment-patterns)
10. [Comparison: Celery vs Ray vs ThreadPoolExecutor](#10-comparison-celery-vs-ray-vs-threadpoolexecutor)
11. [Complete Code Reference](#11-complete-code-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Why Celery for This Project

### The Problem

The current pipeline processes everything sequentially:

```
PDF-1 → Extract → Parse → TestGen ──→ PDF-2 → Extract → Parse → TestGen ──→ ...
                                                                              │
Total: ~60 minutes for 10 PDFs ◄─────────────────────────────────────────────┘
```

Each PDF involves **two types of expensive operations**:

| Operation | Type | Example | Avg Time |
|-----------|------|---------|----------|
| PaddleOCR on images | **CPU-bound** | Extracting text from 15 embedded images | ~30s per image |
| Groq/OpenAI API calls | **I/O-bound** | Requirement parsing, test case generation | ~3-8s per call |

### Why Celery Solves Both

Celery uniquely handles **both** CPU-bound and I/O-bound workloads:

```
┌──────────────────────────────────────────────────────────────────┐
│                         CELERY BROKER (Redis)                     │
│                                                                   │
│  Queue: ocr_tasks        Queue: api_tasks       Queue: export     │
│  ┌─────┬─────┬─────┐   ┌─────┬─────┬─────┐   ┌─────┐           │
│  │IMG-1│IMG-2│IMG-3│   │REQ-1│REQ-2│REQ-3│   │EXCEL│           │
│  └─────┴─────┴─────┘   └─────┴─────┴─────┘   └─────┘           │
└──────────────────────────────────────────────────────────────────┘
       │                        │                      │
       ▼                        ▼                      ▼
  ┌─────────┐             ┌─────────┐            ┌─────────┐
  │ Worker 1 │             │ Worker 3 │            │ Worker 5 │
  │ (CPU)    │             │ (I/O)    │            │ (I/O)    │
  │ OCR      │             │ Groq API │            │ Excel    │
  │ prefork  │             │ eventlet │            │ Export   │
  └─────────┘             └─────────┘            └─────────┘
  ┌─────────┐             ┌─────────┐
  │ Worker 2 │             │ Worker 4 │
  │ (CPU)    │             │ (I/O)    │
  │ OCR      │             │ Groq API │
  │ prefork  │             │ eventlet │
  └─────────┘             └─────────┘

Total: ~8 minutes for 10 PDFs (7.5x speedup)
```

### What Celery Gives You That ThreadPoolExecutor Does Not

| Feature | ThreadPoolExecutor | Celery |
|---------|-------------------|--------|
| Parallel execution | Yes | Yes |
| Automatic retry on failure | No (manual) | **Yes — built-in** |
| Rate limiting per task type | No (manual) | **Yes — `rate_limit='30/m'`** |
| Task chaining (A → B → C) | No (manual) | **Yes — `chain()`, `chord()`** |
| Monitoring dashboard | No | **Yes — Flower UI** |
| Persistent task queue | No (in-memory) | **Yes — survives crashes** |
| Separate CPU vs I/O workers | No | **Yes — routing queues** |
| Dead letter queue (failed tasks) | No | **Yes** |
| Progress tracking | No | **Yes — task state + metadata** |
| Distributed across machines | No | **Yes** |

---

## 2. Architecture Overview

### Current Sequential Pipeline

```
User submits 10 PDFs
        │
        ▼
┌─ FOR EACH PDF (sequential) ─────────────────────────┐
│   1. Extract text from PDF            (~2s)          │
│   2. Extract embedded images          (~1s)          │
│   3. FOR EACH IMAGE (sequential):                    │
│      a. PaddleOCR                     (~30s)         │
│      b. Classify image (OpenAI)       (~3s)          │
│      c. Extract workflow graph        (~5s)          │
│   4. Parse requirements (Groq)        (~8s)          │
│   5. FOR EACH REQUIREMENT (sequential):              │
│      a. Generate test case (Groq)     (~5s)          │
└──────────────────────────────────────────────────────┘
        │
        ▼
   Export to Excel
```

**For 10 PDFs with 5 images and 8 requirements each:**
- Step 3: 10 × 5 × 38s = **31 minutes** (images)
- Step 5: 10 × 8 × 5s = **6.6 minutes** (test cases)
- Total: **~40-60 minutes**

### Proposed Celery Pipeline

```
User submits 10 PDFs
        │
        ▼
   submit_batch_job()
        │
        ▼
┌─ CELERY CHORD (all 10 PDFs in parallel) ─────────────────┐
│                                                            │
│  ┌─ PDF-1 Chain ──────────────────────────────┐           │
│  │  Task: extract_text        ──→ (2s)        │           │
│  │  Task: extract_images      ──→ (1s)        │           │
│  │  Chord: process_images ──→ [OCR×5 parallel]│  (30s)    │
│  │  Task: parse_requirements  ──→ (8s)        │           │
│  │  Chord: gen_test_cases ──→ [TC×8 parallel] │  (5s)     │
│  └────────────────────────────────────────────┘           │
│                                                            │
│  ┌─ PDF-2 Chain ──┐  ┌─ PDF-3 Chain ──┐  ... (×10)       │
│  │  (same flow)   │  │  (same flow)   │                   │
│  └────────────────┘  └────────────────┘                   │
│                                                            │
└───────────────────────────┬────────────────────────────────┘
                            │ all 10 complete
                            ▼
                   Task: merge_and_export()
                            │
                            ▼
                    BRD_Combined.json
                    TestPlan_Combined.json
                    TestPlan_Combined.xlsx
```

**With Celery (5 PDF workers, 4 OCR workers, 3 API workers):**
- Images: 50 images / 4 workers × 30s = **6 minutes**
- Test cases: 80 requirements / 3 workers × 5s = **2 minutes**
- Total: **~8-12 minutes** (5-7x speedup)

---

## 3. Infrastructure Setup

### Prerequisites

```bash
# 1. Install Redis (the message broker)
# macOS:
brew install redis
brew services start redis

# Ubuntu/Debian:
sudo apt install redis-server
sudo systemctl start redis

# Docker (recommended for consistency):
docker run -d --name redis -p 6379:6379 redis:7-alpine

# 2. Verify Redis is running
redis-cli ping
# Expected output: PONG
```

### Python Dependencies

```bash
# Add to requirements.txt:
celery[redis]==5.4.0
redis==5.0.0
flower==2.0.1          # Monitoring dashboard (optional but recommended)
tenacity==8.2.3        # Smart retry logic for API calls
```

```bash
# Install
pip install celery[redis] redis flower tenacity
```

### Project Structure After Implementation

```
ai_test_case/
├── test_case_generator/
│   ├── core/
│   │   ├── workflow.py          # Modified — Celery-aware orchestration
│   │   └── planner.py           # Modified — individual task extraction
│   ├── extractors/
│   ├── processors/
│   ├── exporters/
│   ├── display/
│   ├── utils/
│   │   ├── json_utils.py
│   │   └── rate_limiter.py      # NEW — Thread-safe rate limiter
│   └── celery_app/              # NEW — All Celery infrastructure
│       ├── __init__.py
│       ├── celery_config.py     # Celery app configuration
│       ├── tasks.py             # Task definitions
│       ├── workflows.py         # Chain/Chord orchestration
│       └── callbacks.py         # Progress & error callbacks
├── celeryconfig.py              # NEW — Root Celery settings
├── requirements.txt             # Updated with new deps
└── start_workers.sh             # NEW — Worker startup script
```

---

## 4. Implementation — Step by Step

### Step 1: Celery App Configuration

```python
# test_case_generator/celery_app/__init__.py
"""
Celery application for parallel test case generation.
"""
from .celery_config import celery_app
from .tasks import (
    extract_text_task,
    process_images_task,
    process_single_image_task,
    parse_requirements_task,
    generate_single_test_case_task,
    merge_and_export_task
)
from .workflows import (
    process_single_pdf_workflow,
    process_batch_workflow
)

__all__ = ['celery_app']
```

```python
# test_case_generator/celery_app/celery_config.py
"""
Celery application instance and configuration.

This is the central Celery app that all tasks register with.
Configuration is optimized for a mixed CPU-bound (OCR) and
I/O-bound (API calls) workload.
"""

from celery import Celery

# Create the Celery application
celery_app = Celery('ai_test_case')

# Configure from a settings object
celery_app.conf.update(
    # ─── Broker (Redis) ────────────────────────────────────────
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/1',

    # ─── Serialization ─────────────────────────────────────────
    # JSON is safest for cross-process communication
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],

    # ─── Task Routing ──────────────────────────────────────────
    # Route CPU-heavy tasks to dedicated workers
    task_routes={
        'tasks.process_single_image':  {'queue': 'ocr_queue'},
        'tasks.extract_text':          {'queue': 'default'},
        'tasks.parse_requirements':    {'queue': 'api_queue'},
        'tasks.generate_test_case':    {'queue': 'api_queue'},
        'tasks.merge_and_export':      {'queue': 'default'},
    },

    # ─── Rate Limiting ─────────────────────────────────────────
    # Groq free tier: 30 RPM, OpenAI: 60 RPM
    # Applied per-worker, so with 3 API workers: 10/m × 3 = 30/m total
    task_annotations={
        'tasks.parse_requirements':    {'rate_limit': '10/m'},
        'tasks.generate_test_case':    {'rate_limit': '10/m'},
        'tasks.process_single_image':  {'rate_limit': '20/m'},
    },

    # ─── Retry Policy ─────────────────────────────────────────
    # Default retry: 3 attempts with exponential backoff
    task_acks_late=True,             # Acknowledge AFTER completion (crash safety)
    task_reject_on_worker_lost=True, # Re-queue if worker dies mid-task
    worker_prefetch_multiplier=1,    # Don't prefetch (for fair distribution)

    # ─── Result Expiry ─────────────────────────────────────────
    result_expires=3600,  # Results expire after 1 hour

    # ─── Timeouts ──────────────────────────────────────────────
    task_soft_time_limit=300,   # Soft limit: 5 minutes per task
    task_time_limit=600,        # Hard kill: 10 minutes per task

    # ─── Concurrency Defaults ──────────────────────────────────
    worker_concurrency=4,       # Default workers per process
)

# Auto-discover tasks from the tasks module
celery_app.autodiscover_tasks(['test_case_generator.celery_app'])
```

### Step 2: Root Celery Configuration

```python
# celeryconfig.py (project root — alternative flat config)
"""
Celery configuration file.
Import this in your celery app or point CELERY_CONFIG_MODULE to it.
"""

# Broker
broker_url = 'redis://localhost:6379/0'
result_backend = 'redis://localhost:6379/1'

# Queues
from kombu import Queue

task_queues = (
    Queue('default',    routing_key='default'),
    Queue('ocr_queue',  routing_key='ocr'),
    Queue('api_queue',  routing_key='api'),
    Queue('export',     routing_key='export'),
)

task_default_queue = 'default'
task_default_routing_key = 'default'
```

---

## 5. Task Definitions

### Core Tasks

```python
# test_case_generator/celery_app/tasks.py
"""
Celery task definitions for the test case generation pipeline.

Each task is a self-contained, serializable unit of work that can:
- Run on any worker
- Be retried automatically on failure
- Be chained with other tasks
- Report progress

IMPORTANT: Tasks receive and return plain dicts/strings (JSON-serializable),
NOT Python objects. This is because tasks may run in different processes.
"""

import json
import os
from pathlib import Path
from celery import shared_task
from celery.utils.log import get_task_logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = get_task_logger(__name__)


# ─── Helper: Lazy initialization ───────────────────────────────
# Workers need their own instances (not shared across processes)
def _get_extractor():
    """Create a RequirementExtractor instance for this worker."""
    from test_case_generator.extractors import RequirementExtractor
    groq_key = os.getenv('GROQ_API_KEY')
    openai_key = os.getenv('OPENAI_API_KEY')
    return RequirementExtractor(groq_key, openai_key)


def _get_planner():
    """Create a TestCasePlanner instance for this worker."""
    from test_case_generator.core.planner import TestCasePlanner
    groq_key = os.getenv('GROQ_API_KEY')
    return TestCasePlanner(groq_key)


# ═══════════════════════════════════════════════════════════════
# TASK 1: Text Extraction (CPU-light, I/O-light)
# ═══════════════════════════════════════════════════════════════

@shared_task(
    name='tasks.extract_text',
    bind=True,
    max_retries=2,
    default_retry_delay=5
)
def extract_text_task(self, file_path: str) -> dict:
    """
    Extract text and image metadata from a document.

    This is the first task in the per-PDF chain. It extracts:
    - Raw text content from the document
    - List of embedded image metadata (base64 data, source identifiers)

    Args:
        file_path: Absolute path to the PDF/DOCX/PPTX file

    Returns:
        dict with keys:
            - file_path: Original file path
            - file_name: Just the filename
            - text: Extracted text content
            - images: List of image dicts (base64, source, page)
            - file_type: File extension
    """
    try:
        logger.info(f"Extracting text from: {Path(file_path).name}")
        self.update_state(state='PROGRESS', meta={'step': 'text_extraction'})

        extractor = _get_extractor()
        file_ext = Path(file_path).suffix.lower()

        # Extract text based on file type
        if file_ext == '.pdf':
            text = extractor.extract_from_pdf(file_path)
            images = extractor.extract_images_from_pdf(file_path)
        elif file_ext == '.docx':
            text = extractor.extract_from_docx(file_path)
            images = extractor.extract_images_from_docx(file_path)
        elif file_ext == '.pptx':
            text = extractor.extract_from_pptx(file_path)
            images = extractor.extract_images_from_pptx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")

        logger.info(f"Extracted {len(text)} chars, {len(images)} images from {Path(file_path).name}")

        return {
            'file_path': file_path,
            'file_name': Path(file_path).name,
            'text': text,
            'images': images,  # List of dicts with base64, source, page
            'file_type': file_ext
        }

    except Exception as exc:
        logger.error(f"Text extraction failed for {file_path}: {exc}")
        raise self.retry(exc=exc)


# ═══════════════════════════════════════════════════════════════
# TASK 2: Single Image Processing (CPU-heavy: OCR + API: classify)
# ═══════════════════════════════════════════════════════════════

@shared_task(
    name='tasks.process_single_image',
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    rate_limit='20/m'  # Max 20 image API calls per minute per worker
)
def process_single_image_task(self, image_data: dict, file_name: str) -> dict:
    """
    Process a single embedded image: OCR + classify + extract structure.

    This runs on the 'ocr_queue' dedicated to CPU-heavy workers.
    Each image goes through:
    1. PaddleOCR text extraction (CPU-bound, ~30s)
    2. Image classification via OpenAI Vision (I/O-bound, ~3s)
    3. If workflow diagram: extract graph structure (I/O-bound, ~5s)
    4. If informational: extract content description (I/O-bound, ~3s)

    Args:
        image_data: Dict with 'base64', 'source', 'page' keys
        file_name: Parent document filename (for logging)

    Returns:
        dict with keys:
            - source: Image source identifier
            - type: 'workflow' or 'informational'
            - ocr_text: Extracted OCR text
            - classification: Classification result
            - content: Extracted content (graph_json or description)
    """
    try:
        source = image_data.get('source', 'unknown')
        logger.info(f"[{file_name}] Processing image: {source}")
        self.update_state(state='PROGRESS', meta={
            'step': 'image_processing',
            'image': source
        })

        extractor = _get_extractor()

        # Step A: OCR
        ocr_text = ""
        ocr_confidence = 0.0
        if extractor.diagram_extractor and extractor.diagram_extractor.ocr_extractor:
            ocr_result = extractor.diagram_extractor.extract_text_with_ocr(
                image_data, verify=True
            )
            ocr_text = ocr_result.get('text', '')
            ocr_confidence = ocr_result.get('ocr_confidence', 0.0)

        # Step B: Classify
        classification = {}
        is_workflow = False
        if extractor.diagram_extractor:
            classification = extractor.diagram_extractor.classify_image(image_data)
            is_workflow = classification.get('is_workflow', False)
            confidence = classification.get('confidence', 0.0)

        # Step C: Extract structure based on classification
        content = {}
        img_type = 'informational'

        if is_workflow and classification.get('confidence', 0) > 0.7:
            img_type = 'workflow'
            graph_json = extractor.diagram_extractor.extract_workflow_graph(image_data)
            narrative = extractor.diagram_extractor.convert_diagram_to_narrative(graph_json)
            content = {
                'graph_json': graph_json,
                'narrative': narrative,
                'node_count': len(graph_json.get('nodes', [])),
                'connection_count': len(graph_json.get('connections', []))
            }
        elif extractor.diagram_extractor:
            info = extractor.diagram_extractor.extract_image_info(
                image_data,
                classification.get('image_type', 'unknown')
            )
            content = info

        result = {
            'source': source,
            'type': img_type,
            'ocr_text': ocr_text,
            'ocr_confidence': ocr_confidence,
            'classification': classification,
            'content': content
        }

        logger.info(f"[{file_name}] Image {source}: type={img_type}, ocr={len(ocr_text)} chars")
        return result

    except Exception as exc:
        logger.error(f"[{file_name}] Image processing failed for {image_data.get('source')}: {exc}")
        # Return a graceful fallback instead of crashing the entire PDF
        return {
            'source': image_data.get('source', 'unknown'),
            'type': 'failed',
            'ocr_text': '',
            'error': str(exc)
        }


# ═══════════════════════════════════════════════════════════════
# TASK 3: Requirement Parsing (I/O-heavy: Groq API)
# ═══════════════════════════════════════════════════════════════

@shared_task(
    name='tasks.parse_requirements',
    bind=True,
    max_retries=3,
    rate_limit='10/m',  # Groq rate limit protection
    autoretry_for=(Exception,),
    retry_backoff=True,        # Exponential backoff: 1s, 2s, 4s
    retry_backoff_max=60,      # Max wait: 60 seconds
    retry_jitter=True          # Add randomness to prevent thundering herd
)
def parse_requirements_task(self, extraction_result: dict, image_results: list) -> dict:
    """
    Parse requirements from combined text + image content.

    This is the "brain" task — it sends the consolidated document content
    to the Groq LLM for AI-powered requirement extraction.

    Args:
        extraction_result: Output from extract_text_task
            Contains: text, file_name, file_path, file_type
        image_results: List of outputs from process_single_image_task
            Contains: source, type, ocr_text, content per image

    Returns:
        BRD dictionary with all extracted requirements
    """
    file_name = extraction_result['file_name']
    logger.info(f"Parsing requirements from: {file_name}")
    self.update_state(state='PROGRESS', meta={
        'step': 'requirement_parsing',
        'file': file_name
    })

    # Rebuild combined_content structure from task results
    workflow_diagrams = [r for r in image_results if r.get('type') == 'workflow']
    informational_images = [r for r in image_results if r.get('type') == 'informational']
    ocr_texts = [
        {'source': r['source'], 'text': r['ocr_text'], 'confidence': r.get('ocr_confidence', 0)}
        for r in image_results if r.get('ocr_text', '').strip()
    ]

    combined_content = {
        'file_name': file_name,
        'file_type': extraction_result['file_type'],
        'extracted_text': extraction_result['text'],
        'workflow_diagrams': workflow_diagrams,
        'informational_images': informational_images,
        'ocr_extracted_texts': ocr_texts,
    }

    # Build combined text for parsing
    from test_case_generator.processors.document_processor import build_combined_text_for_parsing
    combined_text = build_combined_text_for_parsing(combined_content)

    # Parse requirements with Groq LLM
    extractor = _get_extractor()
    brd = extractor.parse_requirements(combined_text, file_name)

    # Add metadata
    brd['source_type'] = 'document'
    brd['extracted_text'] = combined_text
    brd['workflow_diagrams'] = workflow_diagrams
    brd['informational_images'] = informational_images

    logger.info(f"Parsed {len(brd.get('requirements', []))} requirements from {file_name}")
    return brd


# ═══════════════════════════════════════════════════════════════
# TASK 4: Single Test Case Generation (I/O-heavy: Groq API)
# ═══════════════════════════════════════════════════════════════

@shared_task(
    name='tasks.generate_test_case',
    bind=True,
    max_retries=3,
    rate_limit='10/m',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def generate_single_test_case_task(self, requirement: dict,
                                    req_map: dict,
                                    source_texts: dict) -> dict:
    """
    Generate test case(s) for a single requirement.

    This task is submitted once per requirement. When 80 requirements
    exist across 10 PDFs, 80 of these tasks run with 3 concurrent
    API workers — completing in ~2 minutes instead of ~7 minutes.

    Args:
        requirement: Single requirement dict from the BRD
        req_map: Full requirement lookup map (for resolving depends_on)
        source_texts: Document text mapping (for context injection)

    Returns:
        Test plan dict for this single requirement
    """
    req_id = requirement.get('requirement_id', requirement.get('id', 'N/A'))
    logger.info(f"Generating test case for: {req_id}")
    self.update_state(state='PROGRESS', meta={
        'step': 'test_case_generation',
        'requirement': req_id
    })

    planner = _get_planner()

    # Use the planner's existing logic for a single requirement
    # (This calls the method we'll extract in Step 4 of implementation)
    result = planner._generate_single_test_case(
        requirement, req_map, source_texts, rate_limiter=None
    )

    logger.info(f"Generated test case for {req_id}: "
                f"{len(result.get('test_cases', []))} cases")
    return result


# ═══════════════════════════════════════════════════════════════
# TASK 5: Merge & Export (I/O-light)
# ═══════════════════════════════════════════════════════════════

@shared_task(
    name='tasks.merge_and_export',
    bind=True,
    max_retries=1
)
def merge_and_export_task(self, brd_list: list, test_plan_list: list,
                           output_dir: str) -> dict:
    """
    Final task: merge all BRDs, consolidate test plans, export to Excel.

    This runs AFTER all PDFs have been processed and all test cases
    generated. It's the callback of the outermost chord.

    Args:
        brd_list: List of BRD dicts (one per successfully processed PDF)
        test_plan_list: List of test plan dicts (one per requirement)
        output_dir: Directory to save output files

    Returns:
        dict with output file paths and summary statistics
    """
    from test_case_generator.core.workflow import TestCaseWorkflow
    from test_case_generator.exporters import export_test_plan_to_excel
    from test_case_generator.utils import clean_for_json

    logger.info(f"Merging {len(brd_list)} BRDs and {len(test_plan_list)} test plans")

    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Create a minimal workflow instance for merge_brds()
    groq_key = os.getenv('GROQ_API_KEY')
    workflow = TestCaseWorkflow(groq_key, output_dir=output_dir)

    # Filter out failed BRDs
    successful_brds = [b for b in brd_list if b and b.get('requirements')]

    if not successful_brds:
        return {'status': 'error', 'message': 'No BRDs were successfully processed'}

    # Merge BRDs
    consolidated_brd = workflow.merge_brds(successful_brds)

    # Save consolidated BRD
    brd_path = output_path / "BRD_Combined.json"
    with open(brd_path, 'w') as f:
        json.dump(clean_for_json(consolidated_brd), f, indent=2)

    # Build consolidated test plan
    # Sort test plans by sequence order
    sorted_plans = sorted(test_plan_list, key=lambda p: p.get('sequence_order', 999))

    blocks_order = []
    for plan in sorted_plans:
        block = plan.get('requirement_block', 'General')
        if block not in blocks_order:
            blocks_order.append(block)

    consolidated_test_plan = {
        "test_plans": sorted_plans,
        "flow_sequence": blocks_order,
        "total_requirements": len(sorted_plans),
        "total_test_cases": sum(
            p.get('total_count', len(p.get('test_cases', [])))
            for p in sorted_plans
        )
    }

    # Save test plan JSON
    plan_path = output_path / "TestPlan_Combined.json"
    with open(plan_path, 'w') as f:
        json.dump(clean_for_json(consolidated_test_plan), f, indent=2)

    # Export Excel
    excel_path = output_path / "TestPlan_Combined.xlsx"
    export_test_plan_to_excel(consolidated_test_plan, consolidated_brd, str(excel_path))

    result = {
        'status': 'success',
        'files': {
            'brd': str(brd_path),
            'test_plan': str(plan_path),
            'excel': str(excel_path),
        },
        'stats': {
            'total_pdfs': len(brd_list),
            'successful_pdfs': len(successful_brds),
            'total_requirements': len(consolidated_brd.get('requirements', [])),
            'total_test_cases': consolidated_test_plan['total_test_cases'],
        }
    }

    logger.info(f"Export complete: {result['stats']}")
    return result
```

---

## 6. Workflow Orchestration with Chains & Chords

This is **the most powerful part of Celery** — composing tasks into complex workflows:

```python
# test_case_generator/celery_app/workflows.py
"""
Celery workflow compositions using chain, chord, and group.

Terminology:
- chain(A, B, C):  A → B → C (sequential, output of A feeds into B)
- group(A, B, C):  A | B | C (parallel, all run simultaneously)
- chord(group, D): (A | B | C) → D (parallel, then callback when ALL complete)

Our pipeline:
  For each PDF:
    chain(extract_text → chord(process_images) → parse_requirements)

  Across all PDFs:
    chord(all_pdf_chains → merge_and_export)
"""

from celery import chain, chord, group
from .tasks import (
    extract_text_task,
    process_single_image_task,
    parse_requirements_task,
    generate_single_test_case_task,
    merge_and_export_task
)


def process_single_pdf_workflow(file_path: str) -> chain:
    """
    Build a Celery chain for processing a single PDF.

    The chain:
    1. extract_text_task(file_path)
           │ returns: {text, images, file_name, ...}
           ▼
    2. _fan_out_images (callback that creates image chord)
           │ returns: {text, images results, ...}
           ▼
    3. parse_requirements_task(extraction_result, image_results)
           │ returns: BRD dict
           ▼
    4. _fan_out_test_cases (callback that creates test case chord)
           │ returns: [test_plan_1, test_plan_2, ...]

    Note: Steps 2 and 4 are dynamic — they create sub-workflows
    based on the number of images/requirements found.
    """
    # We can't use a simple chain() because the number of images
    # is unknown until step 1 completes. So we use a callback pattern.
    return extract_text_task.s(file_path) | process_pdf_images_and_parse.s()


# ─── Dynamic Fan-Out Tasks ────────────────────────────────────

from celery import shared_task

@shared_task(name='tasks.process_pdf_images_and_parse')
def process_pdf_images_and_parse(extraction_result: dict) -> dict:
    """
    Dynamic fan-out: process all images in parallel, then parse requirements.

    This task receives the output of extract_text_task and:
    1. Fans out image processing to parallel workers
    2. Waits for all images to complete
    3. Calls parse_requirements with the combined results

    This is a "canvas primitive" — it builds and executes a chord dynamically.
    """
    file_name = extraction_result['file_name']
    images = extraction_result.get('images', [])

    if images:
        # Create parallel image processing tasks
        image_tasks = group(
            process_single_image_task.s(img, file_name)
            for img in images
        )

        # Execute: process all images → then parse requirements
        # chord = group of tasks + a callback when all complete
        workflow = chord(image_tasks)(
            parse_requirements_task.s(extraction_result)
        )
        # Note: chord passes list of image results as first arg to callback

        # Wait for the chord to complete and return the BRD
        return workflow.get(timeout=600)  # 10 minute timeout

    else:
        # No images — go directly to parsing
        result = parse_requirements_task.delay(extraction_result, [])
        return result.get(timeout=300)


@shared_task(name='tasks.fan_out_test_cases')
def fan_out_test_cases(brd: dict, source_texts: dict = None) -> list:
    """
    Dynamic fan-out: generate test cases for all requirements in parallel.

    Takes a BRD and creates one generate_single_test_case_task per requirement.
    Independent requirements run in parallel; dependent ones are also
    submitted (Celery's rate_limit handles the throttling).

    Args:
        brd: BRD dictionary with 'requirements' list
        source_texts: Optional document text mapping

    Returns:
        List of test plan dicts (one per requirement)
    """
    requirements = brd.get('requirements', [])
    source_texts = source_texts or {}

    # Build requirement lookup map
    req_map = {
        r.get('requirement_id', r.get('id', '')): r
        for r in requirements
    }

    # For single-file BRDs, build source_texts from extracted_text
    if not source_texts and brd.get('extracted_text'):
        source_texts = {brd.get('document_name', 'unknown'): brd['extracted_text']}

    # Fan out: one task per requirement
    test_case_tasks = group(
        generate_single_test_case_task.s(req, req_map, source_texts)
        for req in requirements
    )

    # Execute all in parallel and collect results
    result = test_case_tasks.apply_async()
    test_plans = result.get(timeout=900)  # 15 minute timeout

    return test_plans


# ─── Batch Orchestration ──────────────────────────────────────

def process_batch_workflow(file_paths: list, output_dir: str = './output') -> str:
    """
    Orchestrate the full batch pipeline for multiple PDFs.

    This is the top-level function that the user calls.
    It builds and executes the entire Celery workflow:

        chord(
            [pdf_1_chain, pdf_2_chain, ..., pdf_10_chain],
            merge_and_export_task
        )

    Args:
        file_paths: List of PDF/DOCX/PPTX file paths
        output_dir: Output directory for results

    Returns:
        AsyncResult ID — use this to check progress

    Usage:
        from test_case_generator.celery_app.workflows import process_batch_workflow

        # Submit the batch (returns immediately)
        result_id = process_batch_workflow([
            "input/doc1.pdf",
            "input/doc2.pdf",
            "input/doc3.pdf",
        ])

        # Check status later
        from celery.result import AsyncResult
        result = AsyncResult(result_id)
        print(result.status)  # PENDING, PROGRESS, SUCCESS, FAILURE
        print(result.result)  # The final output dict
    """
    # Build per-PDF workflows
    pdf_workflows = []
    for fp in file_paths:
        # Each PDF gets: extract → images → parse → test cases
        pdf_chain = chain(
            extract_text_task.s(fp),
            process_pdf_images_and_parse.s(),
            fan_out_test_cases.s()
        )
        pdf_workflows.append(pdf_chain)

    # Execute all PDFs in parallel, then merge when all complete
    batch_workflow = chord(
        group(pdf_workflows),
        merge_and_export_task.s(output_dir)
    )

    # Fire it off (non-blocking)
    async_result = batch_workflow.apply_async()

    print(f"\n{'='*60}")
    print(f"BATCH JOB SUBMITTED")
    print(f"{'='*60}")
    print(f"  Task ID: {async_result.id}")
    print(f"  PDFs: {len(file_paths)}")
    print(f"  Monitor: celery -A test_case_generator.celery_app flower")
    print(f"  Status:  AsyncResult('{async_result.id}').status")
    print(f"{'='*60}\n")

    return async_result.id
```

---

## 7. Rate Limiting & Retry Strategy

### Celery's Built-in Rate Limiting

```python
# Per-task rate limits (applied per worker)
@shared_task(rate_limit='10/m')  # 10 calls per minute per worker
def parse_requirements_task(...):
    ...

# With 3 API workers: effective rate = 3 × 10 = 30 RPM
# Groq free tier = 30 RPM → perfect match
```

### Tenacity for Smart API Retries

```python
# test_case_generator/utils/api_resilience.py
"""
Resilient API call wrappers using Tenacity.

Tenacity handles the specific failure modes of LLM APIs:
- 429 Too Many Requests → wait and retry
- 500/502/503 Server Error → retry with backoff
- Timeout → retry with longer timeout
"""

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)
import logging

logger = logging.getLogger(__name__)


def resilient_groq_call(client, messages, model, temperature=0.1, max_tokens=4000):
    """
    Make a Groq API call with automatic retry on rate limits.

    Retry strategy:
    - Attempt 1: Immediate
    - Attempt 2: Wait 2 seconds
    - Attempt 3: Wait 4 seconds
    - Attempt 4: Wait 8 seconds
    - Attempt 5: Wait 16 seconds (max)
    - Give up after 5 attempts

    Usage:
        response = resilient_groq_call(
            client=self.client,
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant"
        )
    """
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.INFO)
    )
    def _call():
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response

    return _call()
```

### Rate Limiting Strategy Table

| API | Free Tier Limit | Workers | Per-Worker Limit | Effective Rate |
|-----|----------------|---------|-----------------|----------------|
| Groq | 30 RPM | 3 | `rate_limit='10/m'` | 30 RPM |
| OpenAI (Vision) | 60 RPM | 4 | `rate_limit='15/m'` | 60 RPM |
| Groq (test gen) | 30 RPM | 3 | `rate_limit='10/m'` | 30 RPM |

---

## 8. Monitoring & Observability

### Flower Dashboard (Real-Time Monitoring)

```bash
# Start Flower (web UI on port 5555)
celery -A test_case_generator.celery_app flower --port=5555

# Open in browser: http://localhost:5555
```

Flower provides:
- Live task progress (which PDFs are being processed right now)
- Worker status (CPU/memory usage per worker)
- Task history (success/failure rates, execution times)
- Rate limit monitoring (are we hitting Groq's limits?)

### Programmatic Progress Tracking

```python
# check_progress.py — Run this to monitor a batch job
"""
Check the status of a submitted batch job.
"""

from celery.result import AsyncResult
from test_case_generator.celery_app import celery_app
import sys
import time


def check_batch_progress(task_id: str):
    """Monitor a running batch job."""
    result = AsyncResult(task_id, app=celery_app)

    while not result.ready():
        state = result.state
        meta = result.info

        if state == 'PROGRESS':
            step = meta.get('step', 'unknown')
            file = meta.get('file', '')
            print(f"  Status: {state} — {step} {file}")
        elif state == 'PENDING':
            print(f"  Status: Waiting in queue...")
        else:
            print(f"  Status: {state}")

        time.sleep(2)

    # Job complete
    if result.successful():
        output = result.result
        print(f"\n{'='*60}")
        print(f"BATCH COMPLETE")
        print(f"{'='*60}")
        print(f"  PDFs processed: {output['stats']['successful_pdfs']}/{output['stats']['total_pdfs']}")
        print(f"  Requirements: {output['stats']['total_requirements']}")
        print(f"  Test cases: {output['stats']['total_test_cases']}")
        print(f"\n  Output files:")
        for name, path in output['files'].items():
            print(f"    {name}: {path}")
    else:
        print(f"\nBATCH FAILED: {result.result}")


if __name__ == '__main__':
    task_id = sys.argv[1] if len(sys.argv) > 1 else input("Enter task ID: ")
    check_batch_progress(task_id)
```

---

## 9. Deployment Patterns

### Local Development (Single Machine)

```bash
# start_workers.sh — Start all Celery workers locally

#!/bin/bash
echo "Starting Redis..."
redis-server --daemonize yes

echo "Starting OCR workers (CPU-bound, 4 processes)..."
celery -A test_case_generator.celery_app worker \
    --queues=ocr_queue \
    --concurrency=4 \
    --pool=prefork \
    --hostname=ocr@%h \
    --loglevel=info \
    --detach

echo "Starting API workers (I/O-bound, 3 threads)..."
celery -A test_case_generator.celery_app worker \
    --queues=api_queue \
    --concurrency=3 \
    --pool=threads \
    --hostname=api@%h \
    --loglevel=info \
    --detach

echo "Starting default worker..."
celery -A test_case_generator.celery_app worker \
    --queues=default,export \
    --concurrency=2 \
    --pool=threads \
    --hostname=default@%h \
    --loglevel=info \
    --detach

echo "Starting Flower monitor..."
celery -A test_case_generator.celery_app flower \
    --port=5555 \
    --detach

echo ""
echo "All workers started!"
echo "  Monitor: http://localhost:5555"
echo "  Redis:   redis-cli ping"
echo ""
echo "To stop all: pkill -f 'celery worker'"
```

### Docker Compose (Production)

```yaml
# docker-compose.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  ocr-worker:
    build: .
    command: >
      celery -A test_case_generator.celery_app worker
      --queues=ocr_queue
      --concurrency=4
      --pool=prefork
      --hostname=ocr@%h
      --loglevel=info
    environment:
      - GROQ_API_KEY=${GROQ_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 4G

  api-worker:
    build: .
    command: >
      celery -A test_case_generator.celery_app worker
      --queues=api_queue
      --concurrency=3
      --pool=threads
      --hostname=api@%h
      --loglevel=info
    environment:
      - GROQ_API_KEY=${GROQ_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - redis
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G

  default-worker:
    build: .
    command: >
      celery -A test_case_generator.celery_app worker
      --queues=default,export
      --concurrency=2
      --pool=threads
      --hostname=default@%h
      --loglevel=info
    environment:
      - GROQ_API_KEY=${GROQ_API_KEY}
    depends_on:
      - redis

  flower:
    build: .
    command: celery -A test_case_generator.celery_app flower --port=5555
    ports:
      - "5555:5555"
    depends_on:
      - redis

volumes:
  redis_data:
```

---

## 10. Comparison: Celery vs Ray vs ThreadPoolExecutor

### For YOUR Specific Use Case

| Factor | ThreadPoolExecutor | Celery + Redis | Ray |
|--------|-------------------|----------------|-----|
| **Setup time** | 0 (built-in) | ~2 hours (Redis + config) | ~1 hour (pip install) |
| **New dependencies** | None | celery, redis, flower | ray |
| **Infrastructure** | None | Redis server required | None (single machine) |
| **CPU-bound OCR** | Poor (GIL limits) | Excellent (prefork workers) | Excellent (multiprocess) |
| **I/O-bound API calls** | Good (threads) | Excellent (separate pool) | Good |
| **Auto retry on 429** | Manual code | Built-in | Manual code |
| **Rate limiting** | Manual code | `rate_limit='30/m'` | Manual code |
| **Task chaining** | Manual callbacks | `chain()`, `chord()` | `ray.get()` |
| **Monitoring UI** | None | Flower dashboard | Ray Dashboard |
| **Persistent queue** | No (in-memory) | Yes (survives crashes) | No |
| **Multi-machine** | No | Yes | Yes |
| **Learning curve** | Low | Medium-High | Medium |
| **Production ready** | For scripts | Industry standard | For ML pipelines |

### Decision Matrix

```
Is this a CLI script running locally?
├── Yes → Do you need auto-retry and monitoring?
│   ├── No  → ThreadPoolExecutor (simplest)
│   └── Yes → Celery (robust)
│
└── No → Is this a web app with background jobs?
    ├── Yes → Celery (industry standard for web backends)
    └── No → Is this a data/ML pipeline?
        ├── Yes → Ray (designed for ML workloads)
        └── No → Celery (general purpose)
```

### For Your Project Specifically

**If you plan to integrate this into a web application** (e.g., users upload PDFs via a web UI and get results later) → **Celery is the right choice**.

**If this stays as a CLI tool** → **ThreadPoolExecutor + Tenacity** gives you 80% of the benefit with 20% of the complexity.

**Recommended hybrid approach:**

```
Phase 1 (Now):     ThreadPoolExecutor + Tenacity  ← Quick win, 5x speedup
Phase 2 (Later):   Celery migration               ← When you add a web UI
Phase 3 (Scale):   Celery + multiple machines      ← When processing 1000+ PDFs
```

---

## 11. Complete Code Reference

### How to Run (After Full Implementation)

```bash
# Terminal 1: Start Redis
redis-server

# Terminal 2: Start OCR workers
celery -A test_case_generator.celery_app worker \
    --queues=ocr_queue --concurrency=4 --pool=prefork \
    --hostname=ocr@%h --loglevel=info

# Terminal 3: Start API workers
celery -A test_case_generator.celery_app worker \
    --queues=api_queue --concurrency=3 --pool=threads \
    --hostname=api@%h --loglevel=info

# Terminal 4: Start default worker
celery -A test_case_generator.celery_app worker \
    --queues=default,export --concurrency=2 --pool=threads \
    --hostname=default@%h --loglevel=info

# Terminal 5: Start Flower monitor
celery -A test_case_generator.celery_app flower --port=5555

# Terminal 6: Submit a batch job
python -c "
from test_case_generator.celery_app.workflows import process_batch_workflow

task_id = process_batch_workflow([
    'input/BBMBT-3917.pdf',
    'input/BBMBT-3918.pdf',
    'input/BBMBT-3919.pdf',
    'input/BBMBT-3920.pdf',
    'input/BBMBT-3921.pdf',
])
print(f'Job submitted: {task_id}')
"

# Terminal 6: Check progress
python check_progress.py <task_id>

# Browser: Monitor in real-time
open http://localhost:5555
```

### Integration with Existing workflow.py

```python
# Modified workflow.py — add Celery-aware method

class TestCaseWorkflow:
    def __init__(self, groq_api_key, openai_api_key=None, output_dir='./output',
                 tenant_id=None, project_id=None, use_celery=False):
        # ... existing init ...
        self.use_celery = use_celery

    def run_multiple(self, file_paths, max_pdf_workers=5):
        """Execute full pipeline — delegates to Celery or sequential."""
        if self.use_celery:
            return self._run_multiple_celery(file_paths)
        else:
            return self._run_multiple_sequential(file_paths)

    def _run_multiple_celery(self, file_paths):
        """Submit batch to Celery workers (non-blocking)."""
        from test_case_generator.celery_app.workflows import process_batch_workflow
        task_id = process_batch_workflow(file_paths, str(self.output_dir))
        return task_id  # Returns immediately — check progress separately

    def _run_multiple_sequential(self, file_paths):
        """Original sequential processing (fallback)."""
        # ... existing run_multiple code ...
```

---

## 12. Troubleshooting

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `ConnectionRefusedError: [Errno 61]` | Redis not running | `redis-server` or `brew services start redis` |
| `Task stuck in PENDING` | No worker listening on that queue | Check queue names match between config and worker startup |
| `kombu.exceptions.EncodeError` | Non-JSON-serializable data in task args | Ensure all task inputs/outputs are plain dicts, not Python objects |
| `WorkerLostError` | OCR worker ran out of memory | Reduce `--concurrency` for OCR workers, or increase memory |
| `TimeLimitExceeded` | Single task took too long | Increase `task_time_limit` in config |
| `429 Too Many Requests` from Groq | Rate limit exceeded | Lower `rate_limit` on tasks, or reduce API worker count |
| Images not processing | `diagram_extractor` is None | Ensure `OPENAI_API_KEY` is set in worker environment |

### Debugging Commands

```bash
# Check Redis is running
redis-cli ping

# List active workers
celery -A test_case_generator.celery_app inspect active

# Check queue lengths
celery -A test_case_generator.celery_app inspect reserved

# Purge all pending tasks (careful!)
celery -A test_case_generator.celery_app purge

# Check specific task status
python -c "
from celery.result import AsyncResult
from test_case_generator.celery_app import celery_app
r = AsyncResult('task-id-here', app=celery_app)
print(f'State: {r.state}')
print(f'Result: {r.result}')
"
```

---

## Summary: Implementation Checklist

- [ ] **Infrastructure**: Install Redis, verify with `redis-cli ping`
- [ ] **Dependencies**: `pip install celery[redis] redis flower tenacity`
- [ ] **Create**: `test_case_generator/celery_app/__init__.py`
- [ ] **Create**: `test_case_generator/celery_app/celery_config.py`
- [ ] **Create**: `test_case_generator/celery_app/tasks.py` (5 task definitions)
- [ ] **Create**: `test_case_generator/celery_app/workflows.py` (chain/chord compositions)
- [ ] **Create**: `test_case_generator/utils/api_resilience.py` (Tenacity wrappers)
- [ ] **Modify**: `test_case_generator/core/planner.py` (extract `_generate_single_test_case`)
- [ ] **Modify**: `test_case_generator/core/workflow.py` (add `use_celery` flag)
- [ ] **Create**: `start_workers.sh` (worker startup script)
- [ ] **Create**: `check_progress.py` (progress monitoring)
- [ ] **Test**: Single PDF through Celery pipeline
- [ ] **Test**: Batch of 5 PDFs through Celery pipeline
- [ ] **Monitor**: Verify rate limits via Flower dashboard

---

*Document generated for the AI Test Case Generator project.*
*Architecture: Celery 5.4 + Redis 7 + Tenacity 8.2*
