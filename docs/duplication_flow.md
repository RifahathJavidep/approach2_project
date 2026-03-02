# 🔄 Duplication Detection — Flow Documentation

**Feature:** Document & Requirement Duplication Detection  
**Endpoint:** `POST /manual-extract-dspy`  
**Date:** 2026-02-26  
**Service:** PRISM AI Service (Python/FastAPI)

---

## 📊 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Angular)                             │
│                                                                             │
│   User uploads document → Selects page → Enters description → Submit        │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  POST /manual-extract-dspy
                                   │  { project_id, document_url,
                                   │    description, page_no }
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AI SERVICE (Python/FastAPI)                          │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    duplication_service.py                           │    │
│  │  • is_document_duplicate()     → Document URL check                │    │
│  │  • find_duplicate_requirements() → TF-IDF similarity check         │    │
│  │  • store_duplicates()          → Save to duplicates table          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                extraction/manual_dspy.py                           │    │
│  │  • ManualDSPyExtractor.extract_from_page()                        │    │
│  │  • Uses trained DSPy models (Business, Functional, Workflow, Tech) │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   │  HTTP calls to Java Backend
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        JAVA BACKEND (Spring Boot)                           │
│                                                                             │
│  ┌──────────────────────┐  ┌──────────────────────┐  ┌─────────────────┐   │
│  │  document_statuses   │  │    requirements      │  │  requirement_   │   │
│  │       table          │  │       table           │  │  duplicates     │   │
│  │                      │  │                       │  │     table       │   │
│  │  • project_id        │  │  • project_id         │  │                 │   │
│  │  • document_url      │  │  • short_title        │  │  • new_req      │   │
│  │  • status            │  │  • description        │  │  • existing_req │   │
│  │                      │  │  • user_story         │  │  • similarity   │   │
│  │                      │  │  • acceptance_criteria │  │  • status       │   │
│  └──────────────────────┘  └──────────────────────┘  └─────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Complete Flow Diagram

```
                    ┌──────────────────────────┐
                    │   Frontend sends request  │
                    │   POST /manual-extract-   │
                    │        dspy               │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  STEP 1: Document Check   │
                    │                           │
                    │  Fetch all document URLs   │
                    │  from Java backend:        │
                    │  GET /api/document-        │
                    │  statuses/project/{id}/    │
                    │  urls                      │
                    │                           │
                    │  Compare incoming URL      │
                    │  against existing URLs     │
                    └────────────┬─────────────┘
                                 │
                        ┌────────┴────────┐
                        │                 │
                   URL EXISTS         URL IS NEW
                   (Duplicate)        (Continue)
                        │                 │
                        ▼                 ▼
              ┌──────────────┐  ┌──────────────────────────┐
              │ Return:       │  │  STEP 2: DSPy Extraction  │
              │ status:       │  │                           │
              │ "duplicate_   │  │  • Download file from S3   │
              │  document"    │  │  • Extract text from page  │
              │               │  │  • Run 4 DSPy extractors:  │
              │ (STOP HERE)   │  │    - Business Features     │
              │               │  │    - Functional Details     │
              └──────────────┘  │    - Workflow Requirements  │
                                │    - Technical Requirements  │
                                │  • Filter by description     │
                                └────────────┬────────────────┘
                                             │
                                    ┌────────┴────────┐
                                    │                 │
                              NO REQUIREMENTS    REQUIREMENTS
                              FOUND              FOUND
                                    │                 │
                                    ▼                 ▼
                          ┌──────────────┐  ┌──────────────────────────┐
                          │ Return:       │  │  STEP 3: Requirement     │
                          │ status:       │  │  Duplication Check       │
                          │ "no_          │  │                          │
                          │ requirements" │  │  • Fetch ALL existing    │
                          │               │  │    requirements from     │
                          │ (STOP HERE)   │  │    Java backend:         │
                          └──────────────┘  │    GET /api/requirements/ │
                                            │    project/{id}           │
                                            │                          │
                                            │  • For EACH new req:     │
                                            │    Compare against ALL    │
                                            │    existing reqs using    │
                                            │    TF-IDF + Cosine        │
                                            │    Similarity             │
                                            │                          │
                                            │  • If score > 0.80:      │
                                            │    Flag as DUPLICATE      │
                                            │                          │
                                            │  • If score < 0.80:      │
                                            │    Mark as UNIQUE         │
                                            └────────────┬─────────────┘
                                                         │
                                                         ▼
                                            ┌──────────────────────────┐
                                            │  STEP 4: Store ALL BRs   │
                                            │                          │
                                            │  POST /api/requirements/ │
                                            │  project/{id}            │
                                            │                          │
                                            │  Saves ALL extracted     │
                                            │  requirements to DB      │
                                            │  (both unique AND        │
                                            │   duplicates - full BR)  │
                                            └────────────┬─────────────┘
                                                         │
                                                         ▼
                                            ┌──────────────────────────┐
                                            │  STEP 5: Store Duplicate │
                                            │  Records (Audit)         │
                                            │                          │
                                            │  If any duplicates found:│
                                            │  POST /api/duplicates/   │
                                            │  project/{id}            │
                                            │                          │
                                            │  Sends full details of:  │
                                            │  • New requirement       │
                                            │  • Matched existing req  │
                                            │  • Similarity score      │
                                            └────────────┬─────────────┘
                                                         │
                                                         ▼
                                            ┌──────────────────────────┐
                                            │  STEP 6: Return Response │
                                            │  (Only duplicate details │
                                            │   sent to frontend)      │
                                            │                          │
                                            │  {                       │
                                            │   status: "success",     │
                                            │   total_requirements_    │
                                            │     stored: 5,           │
                                            │   duplicates_found: true,│
                                            │   duplicates: [          │
                                            │    { new_requirement,    │
                                            │      existing_requirement│
                                            │      similarity_score }  │
                                            │   ],                     │
                                            │   duplicates_summary: {  │
                                            │     total_extracted: 5,  │
                                            │     duplicates_found: 2, │
                                            │     unique_new: 3 }      │
                                            │  }                       │
                                            └──────────────────────────┘
```

---

## 📝 Step-by-Step Flow (Simple)

### STEP 1 — Document URL Check
| Detail | Value |
|--------|-------|
| **What** | Check if this document URL was already processed |
| **API Call** | `GET /api/document-statuses/project/{projectId}/urls` |
| **Returns** | List of existing URLs: `["doc1.pdf", "doc2.pdf"]` |
| **Logic** | Compare incoming `document_url` against this list |
| **If Duplicate** | Return `status: "duplicate_document"` → **STOP** |
| **If New** | Continue to Step 2 |

### STEP 2 — DSPy Extraction
| Detail | Value |
|--------|-------|
| **What** | Extract requirements from the document page using AI |
| **Download** | Download file from S3 to temp directory |
| **Extract** | Read text from specific page number |
| **AI Models** | Run 4 trained DSPy extractors (Business, Functional, Workflow, Technical) |
| **Filter** | Filter results by user's description (relevance score) |
| **Output** | List of structured requirement objects |

### STEP 3 — Requirement Similarity Check
| Detail | Value |
|--------|-------|
| **What** | Check if any new requirement matches existing ones |
| **API Call** | `GET /api/requirements/project/{projectId}` |
| **Returns** | All existing requirements for this project |
| **Algorithm** | TF-IDF Vectorization + Cosine Similarity |
| **Threshold** | Score ≥ 0.80 = **DUPLICATE** |
| **Compares** | title + description + user_story + acceptance_criteria |
| **Output** | Two lists: `duplicates[]` and `unique[]` |

### STEP 4 — Store ALL Requirements (Full BR)
| Detail | Value |
|--------|-------|
| **What** | Save ALL new requirements to main requirements table |
| **API Call** | `POST /api/requirements/project/{projectId}` |
| **Payload** | Full requirement objects with metadata (source_file, extraction_method) |
| **Note** | Both duplicates AND unique requirements are saved — full BR data |
| **Order** | This happens FIRST before storing duplicates |

### STEP 5 — Store Duplicate Records (Audit)
| Detail | Value |
|--------|-------|
| **What** | Save detected duplicates to separate table for audit/tracking |
| **API Call** | `POST /api/duplicates/project/{projectId}` |
| **Payload** | Full new requirement + full existing requirement + similarity score |
| **Condition** | Only called if duplicates were found |

### STEP 6 — Return Response (Only Duplicate Details)
| Detail | Value |
|--------|-------|
| **What** | Return results to frontend |
| **Includes** | `total_requirements_stored` — confirmation all BRs were saved |
| **Includes** | `duplicates[]` — full details of ONLY the duplicated BRs |
| **Includes** | `duplicates_summary` — counts of total, duplicates, unique |
| **Frontend** | Uses `duplicates[]` array to show which BRs are duplicated |

---

## 🔧 Files Involved

```
approach2_project/
├── app.py                        ← API endpoint /manual-extract-dspy
│                                    (orchestrates the full flow)
│
├── duplication_service.py        ← NEW: Duplication detection engine
│   ├── is_document_duplicate()       → Step 1
│   ├── find_duplicate_requirements() → Step 3
│   ├── store_duplicates()            → Step 4
│   └── get_project_duplicates()      → For frontend queries
│
├── extraction/
│   └── manual_dspy.py            ← DSPy extraction engine
│       └── ManualDSPyExtractor       → Step 2
│
├── document_status.py            ← Existing document status tracking
│
├── s3_utils.py                   ← S3 download/upload
│
└── docs/
    ├── backend_api_spec_duplication.md  ← Backend dev spec
    └── duplication_flow.md             ← THIS FILE
```

---

## 🌐 API Calls Made by AI Service

```
Frontend → AI Service:
    POST /manual-extract-dspy { project_id, document_url, description, page_no }

AI Service → Java Backend (in order):
    1. GET  /api/document-statuses/project/{id}/urls     ← Document check
    2. GET  /api/requirements/project/{id}               ← Fetch existing reqs
    3. POST /api/requirements/project/{id}               ← Store ALL BRs (first!)
    4. POST /api/duplicates/project/{id}                 ← Store duplicate records

AI Service → Frontend:
    Response { status, total_requirements_stored, duplicates[], duplicates_summary{} }
```

---

## 📊 Similarity Algorithm

```
┌────────────────────────────┐     ┌────────────────────────────┐
│   NEW Requirement           │     │   EXISTING Requirement      │
│                             │     │                             │
│   title: "Dashboard Export" │     │   title: "Dashboard Data    │
│   description: "Export      │     │           Export Feature"   │
│     reports as CSV/PDF"     │     │   description: "Export      │
│   user_story: "As a user"  │     │     analytics in CSV/PDF"   │
│   acceptance_criteria: [..] │     │   user_story: "As analyst"  │
└─────────────┬──────────────┘     └──────────────┬──────────────┘
              │                                    │
              ▼                                    ▼
        ┌───────────┐                        ┌───────────┐
        │  Combine   │                        │  Combine   │
        │  title +   │                        │  title +   │
        │  desc +    │                        │  desc +    │
        │  story +   │                        │  story +   │
        │  criteria  │                        │  criteria  │
        └─────┬─────┘                        └─────┬─────┘
              │                                    │
              ▼                                    ▼
    ┌──────────────────────────────────────────────────────┐
    │              TF-IDF Vectorizer                        │
    │                                                      │
    │   Converts text → numerical vectors based on          │
    │   word importance (Term Frequency × Inverse           │
    │   Document Frequency)                                 │
    └──────────────────────────┬───────────────────────────┘
                               │
                               ▼
    ┌──────────────────────────────────────────────────────┐
    │           Cosine Similarity                           │
    │                                                      │
    │   Measures angle between two vectors                  │
    │   Score = 0.0 (completely different)                  │
    │           to 1.0 (identical)                          │
    │                                                      │
    │   Threshold: ≥ 0.80 = DUPLICATE                      │
    └──────────────────────────┬───────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
              Score ≥ 0.80          Score < 0.80
              DUPLICATE             UNIQUE
                    │                     │
                    ▼                     ▼
            ┌──────────────┐      ┌──────────────┐
            │ is_duplicate: │      │ is_duplicate: │
            │    true       │      │    false      │
            │ similarity:   │      │ duplicate_    │
            │    0.91       │      │ info: null    │
            └──────────────┘      └──────────────┘
```

---

## 📋 Response Examples

### Response 1: Document Already Processed (Duplicate Document)

```json
{
    "status": "duplicate_document",
    "is_duplicate": true,
    "message": "This document has already been processed for this project.",
    "document_url": "uploads/42/SRS_Document.pdf",
    "requirements": []
}
```

### Response 2: Successful Extraction with Duplicates Found

```json
{
    "status": "success",
    "total_requirements_stored": 5,
    "duplicates_found": true,
    "duplicates_summary": {
        "total_extracted": 5,
        "duplicates_found": 2,
        "unique_new": 3
    },
    "duplicates": [
        {
            "new_requirement": {
                "title": "User Login with MFA",
                "description": "Allow users to log in with multi-factor authentication",
                "type": "Functional",
                "requirementId": "REQ-005",
                "userStory": "As a registered user...",
                "acceptanceCriteria": ["..."],
                "testSteps": [],
                "testScenarios": [],
                "assumptions": [],
                "ambiguities": [],
                "confidence": "high"
            },
            "existing_requirement": {
                "id": 101,
                "title": "User Authentication MFA",
                "description": "Users should be able to log in with MFA",
                "type": "Functional",
                "requirementId": "REQ-001",
                "userStory": "As a user...",
                "acceptanceCriteria": ["..."],
                "testSteps": [],
                "testScenarios": [],
                "assumptions": [],
                "ambiguities": [],
                "confidence": "high"
            },
            "similarity_score": 0.87
        }
    ],
    "source_page": 4,
    "source_file": "SRS_Document.pdf",
    "extraction_method": "dspy_trained"
}
```

### Response 3: Successful Extraction — No Duplicates

```json
{
    "status": "success",
    "total_requirements_stored": 3,
    "duplicates_found": false,
    "duplicates_summary": {
        "total_extracted": 3,
        "duplicates_found": 0,
        "unique_new": 3
    },
    "duplicates": [],
    "source_page": 4,
    "source_file": "SRS_Document.pdf",
    "extraction_method": "dspy_trained"
}
```

### Response 4: No Requirements Found

```json
{
    "status": "no_requirements",
    "message": "No matching requirements found on this page.",
    "requirements": []
}
```
