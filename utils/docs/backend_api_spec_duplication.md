# 🔴 Backend API Requirements — Duplication Detection Feature

**Date:** 2026-02-26  
**From:** AI Service (Python/FastAPI)  
**To:** Java Backend Developer  
**Priority:** High  

---

## 📌 Context

We are adding **duplication detection** to the PRISM AI Service. When a user uploads a document for manual requirement extraction, we need to:

1. **Check if the same document URL was already processed** for that project (before running AI extraction)
2. **Check if any newly extracted requirement is a duplicate** of an existing requirement in the same project (after AI extraction)
3. **Store all detected duplicates** in a separate table for audit and frontend display

---

## 📌 Existing APIs We Already Use (No Changes Needed)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/requirements/project/{projectId}` | Store extracted requirements |
| `GET` | `/api/requirements/project/{projectId}` | Fetch all requirements for a project |
| `POST` | `/api/document-statuses/projects/{projectId}` | Track document processing status |

---

## 🆕 NEW API 1: Get Document URLs for a Project

### Purpose
Before running the expensive AI extraction, we fetch all document URLs already processed for this project. The **AI service (Python)** will compare the incoming URL against this list to decide if it's a duplicate. No special check logic needed on the Java side — just return the list.

### Endpoint

```
GET /api/document-statuses/project/{projectId}/urls
```

### Request

| Parameter | Location | Type | Required | Description |
|-----------|----------|------|----------|-------------|
| `projectId` | Path | Long/String | ✅ | Project ID |

### Example Request

```
GET /api/document-statuses/project/42/urls
```

### Expected Response

Just return a flat list of document URL strings that are already processed for this project:

```json
[
    "uploads/42/SRS_Document.pdf",
    "uploads/42/Functional_Spec.pdf",
    "uploads/42/UI_Wireframes.pptx"
]
```

If no documents exist for this project, return an empty list:

```json
[]
```

### Backend Logic (SQL Pseudocode)

```sql
-- Return all distinct document URLs for this project
SELECT DISTINCT document_url FROM document_statuses
WHERE project_id = :projectId;
```

### ⚠️ Important Note
The AI service will do the URL comparison on its side. The backend only needs to return the list — no matching or filtering logic required.

---

## 🆕 NEW API 2: Store Detected Duplicates

### Purpose
After AI extraction, we detect duplicate requirements using semantic similarity. We need to store these detections in a **separate table** for audit, display on the frontend, and allowing the user to override (confirm/reject).

We store the **full requirement details** for both the newly extracted requirement and the existing requirement it matched against.

### New Database Table: `requirement_duplicates`

```sql
CREATE TABLE requirement_duplicates (
    id                              BIGSERIAL PRIMARY KEY,
    project_id                      BIGINT NOT NULL,
    
    -- =====================================================
    -- FULL DETAILS of the NEWLY extracted requirement
    -- =====================================================
    new_requirement_title           TEXT NOT NULL,
    new_requirement_description     TEXT,
    new_requirement_type            VARCHAR(50),            -- 'Functional', 'Non-Functional', 'Business', etc.
    new_requirement_id_label        VARCHAR(50),            -- AI-generated ID like 'REQ-001'
    new_user_story                  TEXT,
    new_acceptance_criteria         JSONB,                  -- JSON array of strings
    new_test_steps                  JSONB,                  -- JSON array of {step_num, action, expected_result}
    new_test_scenarios              JSONB,                  -- JSON array of strings
    new_assumptions                 JSONB,                  -- JSON array of strings
    new_ambiguities                 JSONB,                  -- JSON array of strings
    new_confidence                  VARCHAR(20),            -- 'high', 'medium', 'low'
    
    -- =====================================================
    -- FULL DETAILS of the EXISTING requirement it matched
    -- =====================================================
    existing_requirement_id         BIGINT REFERENCES requirements(id),
    existing_requirement_title      TEXT NOT NULL,
    existing_requirement_description TEXT,
    existing_requirement_type       VARCHAR(50),
    existing_requirement_id_label   VARCHAR(50),
    existing_user_story             TEXT,
    existing_acceptance_criteria    JSONB,
    existing_test_steps             JSONB,
    existing_test_scenarios         JSONB,
    existing_assumptions            JSONB,
    existing_ambiguities            JSONB,
    existing_confidence             VARCHAR(20),
    
    -- =====================================================
    -- SIMILARITY & STATUS
    -- =====================================================
    similarity_score                DOUBLE PRECISION NOT NULL,  -- 0.0 to 1.0
    duplication_type                VARCHAR(30) NOT NULL,       -- 'DOCUMENT_LEVEL' or 'REQUIREMENT_LEVEL'
    
    -- User-resolvable status
    status                          VARCHAR(30) NOT NULL DEFAULT 'FLAGGED',
    -- Possible values: 'FLAGGED', 'CONFIRMED_DUPLICATE', 'NOT_DUPLICATE'
    
    -- Source info
    document_url                    TEXT,
    
    -- Timestamps
    detected_at                     TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at                     TIMESTAMP,
    resolved_by                     VARCHAR(100),
    
    -- Foreign key
    CONSTRAINT fk_project FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Index for fast lookups
CREATE INDEX idx_req_dup_project ON requirement_duplicates(project_id);
CREATE INDEX idx_req_dup_status ON requirement_duplicates(project_id, status);
```

### Endpoint: Store Duplicates

```
POST /api/duplicates/project/{projectId}
```

### Request Body (Full Requirement Details)

```json
[
    {
        "newRequirement": {
            "title": "Dashboard Data Export",
            "description": "Users must be able to export dashboard analytics data in CSV, PDF, and Excel formats with date range filtering.",
            "type": "Functional",
            "requirementId": "REQ-005",
            "userStory": "As a business analyst, I want to export dashboard data in multiple formats so that I can share reports with stakeholders.",
            "acceptanceCriteria": [
                "Export button is visible on the dashboard page",
                "User can select export format: CSV, PDF, or Excel",
                "User can filter data by custom date range before exporting",
                "Exported file contains the same data displayed on the dashboard",
                "File downloads within 30 seconds for up to 10,000 records"
            ],
            "testSteps": [
                {"stepNum": 1, "action": "Navigate to Dashboard", "expectedResult": "Dashboard loads with analytics data"},
                {"stepNum": 2, "action": "Click Export button", "expectedResult": "Export options dropdown appears"},
                {"stepNum": 3, "action": "Select format and date range", "expectedResult": "File downloads"}
            ],
            "testScenarios": ["Export as CSV", "Export as PDF", "Export as Excel", "Export with date filter"],
            "assumptions": ["User has export permissions"],
            "ambiguities": ["Maximum file size limit not specified"],
            "confidence": "high"
        },
        "existingRequirement": {
            "id": 102,
            "title": "Dashboard Export Feature",
            "description": "The dashboard should support exporting analytics reports in CSV and PDF formats.",
            "type": "Functional",
            "requirementId": "REQ-002",
            "userStory": "As a manager, I want to export reports so I can review them offline.",
            "acceptanceCriteria": [
                "Export button available on dashboard",
                "Supports CSV and PDF formats",
                "Downloaded file matches displayed data"
            ],
            "testSteps": [
                {"stepNum": 1, "action": "Go to Dashboard", "expectedResult": "Dashboard page loads"},
                {"stepNum": 2, "action": "Click Export", "expectedResult": "File downloads"}
            ],
            "testScenarios": ["Export as CSV", "Export as PDF"],
            "assumptions": ["User is logged in"],
            "ambiguities": [],
            "confidence": "high"
        },
        "similarityScore": 0.91,
        "duplicationType": "REQUIREMENT_LEVEL",
        "status": "FLAGGED",
        "documentUrl": "uploads/42/SRS_Document.pdf"
    },
    {
        "newRequirement": {
            "title": "User Authentication with MFA",
            "description": "The system must allow registered users to log in using email and password, with mandatory Multi-Factor Authentication (MFA) via SMS or authenticator app.",
            "type": "Functional",
            "requirementId": "REQ-006",
            "userStory": "As a registered user, I want to log in securely with MFA so that my account is protected from unauthorized access.",
            "acceptanceCriteria": [
                "User can enter email and password on the login page",
                "System sends a 6-digit OTP to the registered mobile number",
                "User must enter the OTP within 5 minutes",
                "After 3 failed OTP attempts, account is temporarily locked for 30 minutes",
                "User is redirected to the dashboard upon successful login"
            ],
            "testSteps": [
                {"stepNum": 1, "action": "Navigate to login page", "expectedResult": "Login page loads with email and password fields"},
                {"stepNum": 2, "action": "Enter valid credentials", "expectedResult": "MFA screen appears"},
                {"stepNum": 3, "action": "Enter the OTP", "expectedResult": "User is logged in and redirected to dashboard"}
            ],
            "testScenarios": ["Valid login with correct OTP", "Login with expired OTP", "Account lockout after 3 failed attempts"],
            "assumptions": ["User has a verified mobile number", "SMS gateway is operational"],
            "ambiguities": [],
            "confidence": "high"
        },
        "existingRequirement": {
            "id": 101,
            "title": "User Login with MFA",
            "description": "Users should be able to log in with email/password and MFA verification.",
            "type": "Functional",
            "requirementId": "REQ-001",
            "userStory": "As a user, I want to log in securely so my account is protected.",
            "acceptanceCriteria": [
                "Login page has email and password fields",
                "MFA is required after password verification",
                "Account locks after multiple failed attempts"
            ],
            "testSteps": [
                {"stepNum": 1, "action": "Go to login", "expectedResult": "Login form displayed"},
                {"stepNum": 2, "action": "Submit credentials", "expectedResult": "MFA prompt shown"}
            ],
            "testScenarios": ["Successful login", "Failed MFA"],
            "assumptions": ["SMS service is available"],
            "ambiguities": [],
            "confidence": "high"
        },
        "similarityScore": 0.85,
        "duplicationType": "REQUIREMENT_LEVEL",
        "status": "FLAGGED",
        "documentUrl": "uploads/42/SRS_Document.pdf"
    }
]
```

### Expected Response

```json
[
    {
        "id": 1,
        "projectId": 42,
        "newRequirement": {
            "title": "Dashboard Data Export",
            "description": "Users must be able to export dashboard analytics data in CSV, PDF, and Excel formats with date range filtering.",
            "type": "Functional",
            "requirementId": "REQ-005",
            "userStory": "As a business analyst, I want to export dashboard data...",
            "acceptanceCriteria": ["..."],
            "testSteps": [{"stepNum": 1, "action": "...", "expectedResult": "..."}],
            "testScenarios": ["..."],
            "assumptions": ["..."],
            "ambiguities": ["..."],
            "confidence": "high"
        },
        "existingRequirement": {
            "id": 102,
            "title": "Dashboard Export Feature",
            "description": "The dashboard should support exporting analytics reports...",
            "type": "Functional",
            "requirementId": "REQ-002",
            "userStory": "...",
            "acceptanceCriteria": ["..."],
            "testSteps": [{"stepNum": 1, "action": "...", "expectedResult": "..."}],
            "testScenarios": ["..."],
            "assumptions": ["..."],
            "ambiguities": [],
            "confidence": "high"
        },
        "similarityScore": 0.91,
        "duplicationType": "REQUIREMENT_LEVEL",
        "status": "FLAGGED",
        "detectedAt": "2026-02-26T12:30:00Z"
    },
    {
        "id": 2,
        "projectId": 42,
        "newRequirement": {
            "title": "User Authentication with MFA",
            "description": "The system must allow registered users to log in...",
            "type": "Functional",
            "requirementId": "REQ-006",
            "userStory": "...",
            "acceptanceCriteria": ["..."],
            "testSteps": [{"stepNum": 1, "action": "...", "expectedResult": "..."}],
            "testScenarios": ["..."],
            "assumptions": ["..."],
            "ambiguities": [],
            "confidence": "high"
        },
        "existingRequirement": {
            "id": 101,
            "title": "User Login with MFA",
            "description": "Users should be able to log in with email/password and MFA verification.",
            "type": "Functional",
            "requirementId": "REQ-001",
            "userStory": "...",
            "acceptanceCriteria": ["..."],
            "testSteps": [{"stepNum": 1, "action": "...", "expectedResult": "..."}],
            "testScenarios": ["..."],
            "assumptions": ["..."],
            "ambiguities": [],
            "confidence": "high"
        },
        "similarityScore": 0.85,
        "duplicationType": "REQUIREMENT_LEVEL",
        "status": "FLAGGED",
        "detectedAt": "2026-02-26T12:30:00Z"
    }
]
```

---

## 🆕 NEW API 3: Get All Duplicates for a Project

### Purpose
Frontend needs to display all detected duplicates for a project so the user can review them.

### Endpoint

```
GET /api/duplicates/project/{projectId}
```

### Example Request

```
GET /api/duplicates/project/42
```

### Expected Response

Return all duplicate records for this project, with full requirement details:

```json
[
    {
        "id": 1,
        "projectId": 42,
        "newRequirement": {
            "title": "Dashboard Data Export",
            "description": "Users must be able to export...",
            "type": "Functional",
            "requirementId": "REQ-005",
            "userStory": "...",
            "acceptanceCriteria": ["..."],
            "testSteps": [{"stepNum": 1, "action": "...", "expectedResult": "..."}],
            "testScenarios": ["..."],
            "assumptions": ["..."],
            "ambiguities": ["..."],
            "confidence": "high"
        },
        "existingRequirement": {
            "id": 102,
            "title": "Dashboard Export Feature",
            "description": "...",
            "type": "Functional",
            "requirementId": "REQ-002",
            "userStory": "...",
            "acceptanceCriteria": ["..."],
            "testSteps": [{"stepNum": 1, "action": "...", "expectedResult": "..."}],
            "testScenarios": ["..."],
            "assumptions": ["..."],
            "ambiguities": [],
            "confidence": "high"
        },
        "similarityScore": 0.91,
        "duplicationType": "REQUIREMENT_LEVEL",
        "status": "FLAGGED",
        "documentUrl": "uploads/42/SRS_Document.pdf",
        "detectedAt": "2026-02-26T12:30:00Z"
    }
]
```

---

## 📋 Summary: All New APIs Needed

| # | Method | Endpoint | Purpose |
|---|--------|----------|---------|
| 1 | `GET` | `/api/document-statuses/project/{projectId}/urls` | Get all processed document URLs for a project |
| 2 | `POST` | `/api/duplicates/project/{projectId}` | Store detected duplicates (full requirement details) |
| 3 | `GET` | `/api/duplicates/project/{projectId}` | Get all duplicates for a project (frontend display) |

## 📋 New Database Table Needed

| Table | Purpose |
|-------|---------|
| `requirement_duplicates` | Stores all detected duplicates (both document-level and requirement-level) |

---

## 🔄 How the AI Service Will Call These APIs

```
STEP 1: User uploads document for manual extraction
         AI calls → GET /api/document-statuses/project/{id}/urls
         → Returns ["url1.pdf", "url2.pdf", ...]
         → AI compares incoming document_url against this list
         
         If URL found in list → Return "duplicate_document" to frontend (STOP)
         If URL NOT in list → Continue to Step 2

STEP 2: AI runs DSPy extraction → gets list of new requirements

STEP 3: AI calls → GET /api/requirements/project/{id} 
         (fetches all existing requirements to compare against)

STEP 4: AI computes semantic similarity (TF-IDF) between new and existing requirements
         Any pair with similarity > 0.80 is flagged as duplicate

STEP 5: AI calls → POST /api/duplicates/project/{id}
         (stores all detected duplicates with full requirement details)

STEP 6: AI calls → POST /api/requirements/project/{id}
         (stores the new requirements — all of them, including duplicates)

STEP 7: AI returns response to frontend with:
         - All requirements (each has is_duplicate flag)
         - Duplicate flags + similarity scores
         - Summary (X total, Y duplicates, Z unique)
```

---

## ❓ Questions for Backend Dev

1. Should the `project_id` in `requirement_duplicates` be a `BIGINT` or `VARCHAR`? (We currently send it as a string from the AI service)
2. Do we need cascade delete — if a project is deleted, should all its duplicates be deleted too?
