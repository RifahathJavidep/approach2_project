# Enterprise Strategy: High-Precision Requirement Extraction

To achieve industrial-grade accuracy and eliminate the "over-creation" of technical noise, we must move beyond simple prompting into a rigorous **Data-Centric AI** approach.

## 1. The "Signal vs. Noise" Problem
The current model extracts "Architecture" and "Infrastructure" because it sees them in the text. However, in a 10-year veteran's view, these are **Implementation Details**, not **Business Requirements**.

### The Strict Taxonomy
| Category | Requirement (KEEP) | Technical Noise (DROP) |
| :--- | :--- | :--- |
| **Functional** | "Allow user to reset password" | "Update the user table in DB" |
| **UI** | "Display 14-month trend chart" | "Use blue color #0066CC" |
| **Architecture** | "Sync with BBSSC via REST API" | "Implement API Gateway routes" |
| **Data Model** | "Track Lead and Deal history" | "Define NVARCHAR(255) fields" |

---

## 2. Multi-Project Transfer Learning (Professional Workflow)

Instead of just dumping data, we use a **Curated Knowledge Transfer** workflow:

### Phase A: Golden Dataset Creation
*   **Source**: Extract 20+ "Golden" examples from each project.
*   **Manual Audit**: Ensure every positive example has a clear "User Action" and "Business Value".
*   **Negative Injection**: Deliberately include 50+ examples of technical noise labeled as `is_requirement: False`.

### Phase B: DSPy Pipeline Optimization
*   **Step 1: Raw Extraction**: Extract candidates from chunks.
*   **Step 2: Role-Based Classifier**: A "Senior Business Analyst" Critic that asks: *"Does this provide value to the end-user or only to a developer?"*
*   **Step 3: Deduplication/Merging**: Use semantic clustering to merge "Customer Search" and "Search by Name" into one single parent requirement.

---

## 3. Technical Implementation Plan

### 1. Advanced Signature Refinement
We will update the `RequirementClassifier` to include a **"Reasoning Path"**. The model must justify why a technical detail is being promoted to a requirement.

### 2. Semantic Evaluation (Real Accuracy)
The 24.5% score is misleading because it uses word-matching. We will implement **Semantic Similarity**:
-   Use an LLM Critic to compare Extracted vs. Ground Truth.
-   Score based on **Intent Matching**, not string matching.

### 3. Optimizer Tuning
We will use `BootstrapFewShotWithRandomSearch` on a larger, cleaner dataset. This prevents the model from "overfitting" on technical keywords from one specific project.

---

## 4. Expected Results
- **Over-creation**: Reduction by ~80% by ignoring system-internal details.
- **Accuracy (Semantic)**: Target > 85% F1-Score.
- **Reliability**: Consistent output across different domains (PTW, CRM, Fintech).
