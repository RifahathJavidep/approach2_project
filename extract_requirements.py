"""
Requirements Extraction - Trained Approach
Run with F5 in VS Code
"""

import dspy
import json
import os
from pathlib import Path
from typing import List, Dict
import openpyxl
from dotenv import load_dotenv
import sys

# Load environment
load_dotenv()

# ============================================================================
# GENERIC TRAINING EXAMPLES
# ============================================================================

# POSITIVE: Things a user can SEE or DO in the application
POSITIVE_EXAMPLES = [
    {"text": "Display dashboard with key metrics and charts", "title": "Dashboard Display", "description": "Show key metrics and charts on main dashboard page", "type": "UI", "is_requirement": True},
    {"text": "Export data to CSV, PDF, Excel formats", "title": "Export Functionality", "description": "Allow users to export data in multiple formats including CSV, PDF, Excel, PNG, JPEG", "type": "Functional", "is_requirement": True},
    {"text": "Filter results by NAG group", "title": "NAG Group Filter", "description": "Implementation of NAG filter within dashboard screen", "type": "Functional", "is_requirement": True},
    {"text": "Click bar chart to view detailed breakdown", "title": "Chart Drilldown", "description": "User can click chart elements to see detailed data breakdown", "type": "Functional", "is_requirement": True},
    {"text": "Display usage summary with tabs for Data, Voice, Text", "title": "Usage Summary Tabs", "description": "Display tabs for Data, Voice, Long Distance, Text Messaging usage", "type": "UI", "is_requirement": True},
    {"text": "User can favorite items for quick access", "title": "Favorite Feature", "description": "Allow users to mark items as favorites for default view", "type": "Functional", "is_requirement": True},
    {"text": "Display 14 months billed and unbilled data usage in bar chart", "title": "Data Usage Bar Chart", "description": "Bar chart showing 14+ months of billed and unbilled data usage", "type": "UI", "is_requirement": True},
    {"text": "Display notification when task completes", "title": "Completion Notification", "description": "Show notification message when background task finishes", "type": "UI", "is_requirement": True},
    {"text": "Back button to navigate to previous screen", "title": "Back Button Navigation", "description": "Back button to return to previous view from detail tables", "type": "UI", "is_requirement": True},
    {"text": "Display latest orders in shopping widget", "title": "Shopping and Orders Widget", "description": "Display latest orders in the shopping and orders widget", "type": "UI", "is_requirement": True},
    {"text": "Show usage threshold donut wheel", "title": "Usage Threshold Donut", "description": "Display usage threshold donut wheel showing plan utilization percentage", "type": "UI", "is_requirement": True},
    {"text": "Display warranty expiry date on subscriber page", "title": "Warranty Display", "description": "Display warranty expiry date information on subscriber information page", "type": "UI", "is_requirement": True},
]

# NEGATIVE: Things that are NOT user-facing requirements
NEGATIVE_EXAMPLES = [
    # Performance / Non-functional
    {"text": "Dashboard must load within 2 seconds", "title": "Dashboard Load Time", "description": "Page render time under 2 seconds", "type": "Performance", "is_requirement": False},
    {"text": "Support 1000 concurrent users", "title": "Concurrent User Capacity", "description": "System handles 1000 simultaneous users", "type": "Performance", "is_requirement": False},
    # Technical / Architecture
    {"text": "Implement REST API for data access", "title": "REST API Implementation", "description": "Build RESTful API endpoints", "type": "Technical", "is_requirement": False},
    {"text": "Use MongoDB for data storage", "title": "Database Technology", "description": "Store data in MongoDB database", "type": "Technical", "is_requirement": False},
    {"text": "Data integration via ETL pipeline", "title": "Data Integration", "description": "ETL process to sync data from source systems", "type": "Technical", "is_requirement": False},
    {"text": "System integrates with backend BBSSC service", "title": "Backend Integration", "description": "Integration with BBSSC backend service layer", "type": "Technical", "is_requirement": False},
    # Design specs / UI details (too granular — NOT actual requirements)
    {"text": "Display dates in YYYY-MM-DD format", "title": "Date Format Specification", "description": "Use ISO format for date display", "type": "UI Detail", "is_requirement": False},
    {"text": "Use blue color (#0066CC) for primary buttons", "title": "Button Color Scheme", "description": "Primary button color specification", "type": "UI Detail", "is_requirement": False},
    {"text": "Show tooltip when hovering over chart element", "title": "Hover for Tooltip", "description": "Tooltip displayed on mouse hover over chart bars", "type": "UI Detail", "is_requirement": False},
    {"text": "Use color delineation for different data categories", "title": "Color Delineation", "description": "Different colors for different data types in charts", "type": "UI Detail", "is_requirement": False},
    {"text": "Add loading spinner while data loads", "title": "Spin Button", "description": "Spinner animation during data loading", "type": "UI Detail", "is_requirement": False},
    {"text": "Auto-adjust layout when data is empty", "title": "Auto-Adjust Empty Data", "description": "Automatically adjust display when no data available", "type": "UI Detail", "is_requirement": False},
    {"text": "Sort data in table columns and paginate results", "title": "Sort and Paginate Data", "description": "Table sorting and pagination functionality", "type": "UI Detail", "is_requirement": False},
    {"text": "Display billing period information label", "title": "Billing Period Information", "description": "Show billing period label on dashboard", "type": "UI Detail", "is_requirement": False},
    {"text": "Display dashboard based on user role permissions", "title": "Role-Based Dashboard View", "description": "Show dashboard based on user roles and permissions", "type": "Technical", "is_requirement": False},
    # Vague / Generic
    {"text": "Ensure system security", "title": "Security", "description": "Implement security measures", "type": "Technical", "is_requirement": False},
    {"text": "Optimize performance", "title": "Performance Optimization", "description": "Improve system performance", "type": "Technical", "is_requirement": False},
    {"text": "System must be scalable", "title": "Scalability", "description": "Ensure system can scale", "type": "Technical", "is_requirement": False},
    {"text": "Navigate between pages", "title": "Navigation", "description": "General navigation between application pages", "type": "Vague", "is_requirement": False},
    {"text": "Display data visualization", "title": "Data Visualization", "description": "General data visualization capability", "type": "Vague", "is_requirement": False},
    # Process / Document noise
    {"text": "Conduct annual compliance audit", "title": "Compliance Audit", "description": "Yearly audit for regulatory compliance", "type": "Process", "is_requirement": False},
    {"text": "This document provides a detailed solution design", "title": "Document Overview", "description": "Introduction and executive summary of the document", "type": "Document Noise", "is_requirement": False},
    {"text": "The objective is to implement key enhancements", "title": "Project Objective", "description": "High-level project objective statement", "type": "Document Noise", "is_requirement": False},
    {"text": "Bell needs to introduce enhancements to streamline management", "title": "Problem Statement", "description": "Business problem statement from executive summary", "type": "Document Noise", "is_requirement": False},
    {"text": "Phase 1A scope includes dashboard and warranty features", "title": "Scope Summary", "description": "Summary of what is in scope for this phase", "type": "Document Noise", "is_requirement": False},
    {"text": "Impacted systems include BBSSC and eOrdering", "title": "Impacted Systems", "description": "List of systems affected by the project", "type": "Technical", "is_requirement": False},
    {"text": "High level CS flow diagram", "title": "CS Flow Diagram", "description": "Reference to a conceptual solution flow diagram", "type": "Document Noise", "is_requirement": False},
]

# ============================================================================
# DSPY SIGNATURES
# ============================================================================

class RequirementExtraction(dspy.Signature):
    """Extract HIGH-LEVEL software requirements from the document text.
    
    Cover ALL categories: Functional, UI/Wireframe, Workflow, Architecture,
    Data Model, Non-Functional (SLAs/performance), Security/Compliance.
    
    CRITICAL: Extract only 3-5 TOP-LEVEL requirements per chunk.
    Merge related sub-items into ONE parent requirement.
    
    GOOD (high-level, merged):
    - 'API Gateway Architecture' (covers auth, versioning, rate limiting)
    - 'Payment Checkout Workflow' (covers the full 10-step flow)
    - 'PCI DSS Compliance' (covers encryption, audit, TLS)
    
    BAD (too granular - merge these UP):
    - 'Rate Limiting' (part of API Gateway)
    - 'Bearer Token Auth' (part of API Gateway)  
    - 'Hover for tooltip', 'Color code bars' (UI micro-details - skip)
    
    RULES:
    - Maximum 3-5 requirements per chunk, NOT more
    - Each requirement should represent a MAJOR capability area
    - Merge ALL sub-features into their parent requirement
    - Skip: tooltips, colors, animations, document metadata, scope statements
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of 3-5 HIGH-LEVEL requirements: 
    [{
      'title': '...', 
      'description': '...', 
      'type': 'Functional'|'UI'|'Workflow'|'Architecture'|'Data Model'|'Non-Functional'|'Security',
      'user_story': 'As a [role], I want [action], so that [benefit]',
      'acceptance_criteria': ['criterion 1', 'criterion 2'],
      'test_steps': [{'step_num': 1, 'action': '...', 'expected_result': '...', 'test_data': '...'}],
      'test_scenarios': ['scenario 1'],
      'assumptions': ['assumption 1'],
      'ambiguities': ['ambiguity 1'],
      'confidence': 'high'|'medium'|'low'
    }]. Max 5 items. Merge sub-features.""")

class RequirementClassifier(dspy.Signature):
    """Classify if this is a genuine software requirement of ANY type.
    
    Answer 'yes' if ANY of these are true:
    1. User can SEE it on screen or DO/interact with it (functional/UI)
    2. It describes a workflow or end-to-end process flow
    3. It specifies architecture, API design, or system integration
    4. It defines a data model, entity relationship, or schema
    5. It sets a performance target, SLA, or scalability requirement
    6. It defines security, compliance, or data protection standards
    
    Answer 'no' ONLY if it is:
    - Document noise (executive summary, project objectives, scope statements)
    - A UI micro-detail (tooltip text, color hex code, hover animation)
    - Vague/generic with no specifics (e.g., 'ensure security', 'optimize performance')
    """
    text = dspy.InputField()
    title = dspy.InputField()
    description = dspy.InputField()
    is_requirement = dspy.OutputField(desc="'yes' if this is a specific, actionable requirement of any type, 'no' if document noise or vague")
    reason = dspy.OutputField(desc="Brief explanation of why this is or isn't a valid requirement")

# ============================================================================
# EXTRACTOR MODULE
# ============================================================================

class TrainedExtractor(dspy.Module):
    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(RequirementExtraction)
        self.classifier = dspy.ChainOfThought(RequirementClassifier)
        
    def forward(self, document_text: str) -> Dict:
        result = self.extractor(document_text=document_text)
        
        try:
            raw = result.requirements_json
            # Handle markdown-wrapped JSON
            if '```' in raw:
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            candidates = json.loads(raw.strip())
        except:
            candidates = []
        
        valid_requirements = []
        filtered_out = []
        
        for candidate in candidates:
            title = candidate.get('title', '')
            desc = candidate.get('description', '')
            
            # Pre-filter: skip obviously bad candidates
            combined = f"{title} {desc}".lower()
            if any(kw in combined for kw in SKIP_KEYWORDS):
                filtered_out.append(candidate)
                continue
            
            classification = self.classifier(
                text=f"{title} - {desc}",
                title=title,
                description=desc
            )
            
            if classification.is_requirement.lower().strip() in ['yes', 'true']:
                # Ensure all fields exist with fallback values for richness
                candidate['user_story'] = candidate.get('user_story', f"As a user, I want to use {title} so that I can achieve my goal.")
                candidate['acceptance_criteria'] = candidate.get('acceptance_criteria', [f"Verify {title} functionality"])
                candidate['test_steps'] = candidate.get('test_steps', [{'step_num': 1, 'action': f'Interact with {title}', 'expected_result': 'System responds correctly', 'test_data': 'N/A'}])
                candidate['test_scenarios'] = candidate.get('test_scenarios', [f"Successful {title} interaction"])
                candidate['assumptions'] = candidate.get('assumptions', [])
                candidate['ambiguities'] = candidate.get('ambiguities', [])
                candidate['confidence'] = candidate.get('confidence', 'medium')
                valid_requirements.append(candidate)
            else:
                filtered_out.append(candidate)
        
        return {
            'requirements': valid_requirements,
            'filtered_out': filtered_out
        }

# ============================================================================
# MULTI-PROJECT TRAINING
# ============================================================================

# Skip keywords used both in classifier pre-filter and training label generation
SKIP_KEYWORDS = [
    # Document noise
    'executive summary', 'objective', 'problem statement',
    'solution scope', 'impacted system', 'this document',
    'conceptual solution',
    # UI implementation details (too granular)
    'tooltip', 'hover for', 'color delineation', 'colour coded',
    'spin button', 'spinner', 'loading indicator',
    'paginate', 'pagination', 'sort and paginate',
    'billing period information', 'billing period label',
    'auto-adjust', 'auto adjust',
    'clickable order id', 'clickable id',
    'metric tile link', 'data grouping selection',
]


def _generate_training_from_projects(current_project: str, projects: Dict) -> List[Dict]:
    """
    Scan other projects' PDFs to generate additional training examples.
    Uses the LLM extractor to get candidates, then labels them as
    positive/negative using the keyword skip filter.
    
    Returns list of dicts with: text, title, description, is_requirement (bool)
    """
    extra_examples = []
    extractor_sig = dspy.ChainOfThought(RequirementExtraction)

    for project_name, project_config in projects.items():
        if project_name == current_project:
            continue  # Skip — this is the extraction target

        input_dir = Path(project_config['input_dir'])
        if not input_dir.exists():
            print(f"    Skipping {project_name}: directory not found")
            continue

        # Get PDF files (skip non-requirement files)
        pdf_files = sorted(input_dir.glob('*.pdf'))
        skip_file_patterns = ['test_strategy', 'test strategy', 'traceability', 'about']
        pdf_files = [f for f in pdf_files if not any(p in f.name.lower() for p in skip_file_patterns)]

        if not pdf_files:
            continue

        print(f"    {project_name}: scanning {len(pdf_files)} files...")

        for pdf_file in pdf_files[:3]:  # Limit to 3 files per project for speed
            try:
                doc_text = process_pdf(str(pdf_file))
                if not doc_text or len(doc_text.strip()) < 100:
                    continue

                # Take only first chunk to keep it fast
                chunks = chunk_document(doc_text)
                chunk = chunks[0] if chunks else ""
                if not chunk:
                    continue

                # Run LLM extraction
                result = extractor_sig(document_text=chunk)
                raw = result.requirements_json
                if '```' in raw:
                    raw = raw.split('```')[1]
                    if raw.startswith('json'):
                        raw = raw[4:]
                candidates = json.loads(raw.strip())

                # Label each candidate using skip keywords
                for candidate in candidates:
                    title = candidate.get('title', '')
                    desc = candidate.get('description', '')
                    combined = f"{title} {desc}".lower()

                    is_positive = not any(kw in combined for kw in SKIP_KEYWORDS)
                    extra_examples.append({
                        'text': f"{title} - {desc}",
                        'title': title,
                        'description': desc,
                        'is_requirement': is_positive
                    })

            except Exception as e:
                continue  # Skip files that fail

    return extra_examples


def train_extractor(extractor: TrainedExtractor, config: Dict = None):
    print("\nTraining extractor...")

    train_examples = []

    # 1. Hardcoded examples
    for ex in POSITIVE_EXAMPLES:
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='yes',
                reason="User-facing feature that can be seen or interacted with"
            ).with_inputs('text', 'title', 'description')
        )

    for ex in NEGATIVE_EXAMPLES:
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='no',
                reason="Not a user-facing feature - technical/noise/vague"
            ).with_inputs('text', 'title', 'description')
        )

    # 2. Multi-project examples (from other projects' PDFs)
    if config:
        current_project = config.get('current_project', '')
        projects = config.get('projects', {})
        if len(projects) > 1:
            print(f"  Generating training data from other projects...")
            extra = _generate_training_from_projects(current_project, projects)
            pos_count = sum(1 for e in extra if e['is_requirement'])
            neg_count = len(extra) - pos_count
            print(f"  Got {len(extra)} extra examples ({pos_count} positive, {neg_count} negative)")

            for ex in extra:
                label = 'yes' if ex['is_requirement'] else 'no'
                reason = "Real document feature" if ex['is_requirement'] else "Technical/noise from document"
                train_examples.append(
                    dspy.Example(
                        text=ex['text'],
                        title=ex['title'],
                        description=ex['description'],
                        is_requirement=label,
                        reason=reason
                    ).with_inputs('text', 'title', 'description')
                )

    print(f"  Total training examples: {len(train_examples)}")

    from dspy.teleprompt import BootstrapFewShot

    def metric(example, prediction, trace=None):
        predicted = prediction.is_requirement.lower().strip() in ['yes', 'true']
        expected = example.is_requirement.lower().strip() in ['yes', 'true']
        return 1.0 if predicted == expected else 0.0

    optimizer = BootstrapFewShot(
        metric=metric,
        max_bootstrapped_demos=8,
        max_labeled_demos=8
    )

    extractor.classifier = optimizer.compile(extractor.classifier, trainset=train_examples)
    print("Training complete")
    return extractor

# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

def process_pdf(pdf_path: str) -> str:
    """Extract text from PDF, with OCR fallback for image-based PDFs."""
    # Try standard text extraction first
    try:
        import pymupdf4llm
        text = pymupdf4llm.to_markdown(pdf_path)
        if text and len(text.strip()) > 100:
            print("  ✓ Text extracted via pymupdf4llm")
            return text
    except Exception as e:
        print(f"  ⚠ pymupdf4llm failed: {e}")
    
    # Fallback: OCR for image-based PDFs
    print("  ⚠ Standard extraction returned empty — falling back to OCR...")
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
        import io
        
        doc = pymupdf.open(pdf_path)
        all_text = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render page at 200 DPI for good OCR quality
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes('png')))
            page_text = pytesseract.image_to_string(img)
            
            if page_text.strip():
                all_text.append(f"--- Page {page_num + 1} ---\n{page_text}")
                print(f"  ✓ Page {page_num + 1}: {len(page_text)} chars via OCR")
            else:
                print(f"  ⚠ Page {page_num + 1}: No text detected")
        
        doc.close()
        
        if all_text:
            combined = "\n\n".join(all_text)
            print(f"  ✓ OCR complete: {len(combined)} total chars from {len(all_text)} pages")
            return combined
    except Exception as e:
        print(f"  ✗ OCR failed: {e}")
    
    return ""

def chunk_document(text: str, max_chars: int = 6000) -> List[str]:
    chunks = []
    current = ""
    for para in text.split('\n\n'):
        if len(current) + len(para) < max_chars:
            current += para + "\n\n"
        else:
            if current:
                chunks.append(current)
            current = para + "\n\n"
    if current:
        chunks.append(current)
    return chunks

def calculate_similarity(text1: str, text2: str) -> float:
    """Word overlap similarity (Jaccard)."""
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)

def _title_similarity(title1: str, title2: str) -> float:
    """Compare two titles using multiple strategies."""
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()

    # Exact match
    if t1 == t2:
        return 1.0

    # One title contains the other
    if t1 in t2 or t2 in t1:
        return 0.85

    # Jaccard on title words
    return calculate_similarity(t1, t2)


def deduplicate_requirements(reqs: List[Dict], similarity_threshold: float = 0.55) -> List[Dict]:
    """Remove duplicate requirements using multi-strategy similarity.
    Compares titles separately (tighter match) and full text (looser match).
    """
    unique = []
    for req in reqs:
        is_dup = False
        req_title = req.get('title', '')
        req_desc = req.get('description', '')
        req_full = f"{req_title} {req_desc}".lower()

        for existing in unique:
            ex_title = existing.get('title', '')
            ex_desc = existing.get('description', '')
            ex_full = f"{ex_title} {ex_desc}".lower()

            # Strategy 1: Title-to-title (catches cross-file duplicates)
            title_sim = _title_similarity(req_title, ex_title)
            # Strategy 2: Full text comparison
            full_sim = calculate_similarity(req_full, ex_full)
            # Use the best score
            best_sim = max(title_sim, full_sim)

            if best_sim > similarity_threshold:
                is_dup = True
                # Keep the one with the longer description
                if len(req_desc) > len(ex_desc):
                    unique.remove(existing)
                    unique.append(req)
                break

        if not is_dup:
            unique.append(req)

    return unique


# ============================================================================
# LLM-BASED CONSOLIDATION (merges overlapping requirements)
# ============================================================================

class RequirementConsolidation(dspy.Signature):
    """Consolidate a list of overlapping software requirements into fewer, high-level items.
    
    You are given a JSON array of requirements extracted from multiple document chunks.
    Many are duplicates or sub-features of the same parent capability.
    
    Your job:
    1. Merge related/overlapping requirements into ONE parent requirement
    2. Keep the most descriptive title and combine descriptions
    3. Target approximately 20-30 consolidated requirements total
    4. Preserve ALL distinct capability areas — do NOT drop unique requirements
    
    Examples of merging:
    - 'Rate Limiting' + 'API Versioning' + 'Bearer Token Auth' → 'API Gateway Architecture'
    - 'Refund Processing' + 'Refund Button' + 'Refund Transaction' → 'Refund Management'
    - 'Track Shipments' + 'Track Packages' + 'Shipment Status' → 'Real-Time Shipment Tracking'
    """
    requirements_json = dspy.InputField(desc="JSON array of raw requirements to consolidate")
    consolidated_json = dspy.OutputField(desc="JSON array of 20-30 consolidated requirements: [{'title': '...', 'description': '...', 'type': '...'}]. Merge overlapping items, keep unique ones.")


def consolidate_requirements(reqs: List[Dict]) -> List[Dict]:
    """Use LLM to merge overlapping requirements into fewer high-level items."""
    if len(reqs) <= 30:
        print(f"  Consolidation: {len(reqs)} items — no consolidation needed")
        return reqs
    
    print(f"  Consolidating {len(reqs)} requirements via LLM...")
    
    consolidator = dspy.ChainOfThought(RequirementConsolidation)
    
    # If too many items, process in batches to avoid token limits
    MAX_BATCH = 60
    if len(reqs) > MAX_BATCH:
        # Split into batches, consolidate each, then consolidate the results
        batches = [reqs[i:i+MAX_BATCH] for i in range(0, len(reqs), MAX_BATCH)]
        intermediate = []
        for i, batch in enumerate(batches, 1):
            print(f"    Batch {i}/{len(batches)} ({len(batch)} items)...")
            try:
                result = consolidator(requirements_json=json.dumps(batch))
                raw = result.consolidated_json
                if '```' in raw:
                    raw = raw.split('```')[1]
                    if raw.startswith('json'):
                        raw = raw[4:]
                batch_consolidated = json.loads(raw.strip())
                intermediate.extend(batch_consolidated)
                print(f"      → {len(batch_consolidated)} items")
            except Exception as e:
                print(f"      ERROR: {e} — keeping original batch")
                intermediate.extend(batch)
        
        # Second pass to merge across batches
        if len(intermediate) > 30:
            print(f"    Final merge pass ({len(intermediate)} items)...")
            try:
                result = consolidator(requirements_json=json.dumps(intermediate))
                raw = result.consolidated_json
                if '```' in raw:
                    raw = raw.split('```')[1]
                    if raw.startswith('json'):
                        raw = raw[4:]
                final = json.loads(raw.strip())
                print(f"      → {len(final)} items")
                return final
            except Exception as e:
                print(f"      ERROR in final merge: {e}")
                return intermediate
        return intermediate
    else:
        # Single batch
        try:
            result = consolidator(requirements_json=json.dumps(reqs))
            raw = result.consolidated_json
            if '```' in raw:
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            consolidated = json.loads(raw.strip())
            print(f"  Consolidated: {len(reqs)} → {len(consolidated)} requirements")
            return consolidated
        except Exception as e:
            print(f"  ERROR in consolidation: {e} — keeping original")
            return reqs

# ============================================================================
# DSPY SETUP HELPER
# ============================================================================

# Global LM instance to avoid re-configuring in async tasks
_global_lm = None

def _get_lm():
    global _global_lm
    if _global_lm is None:
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY not found in .env")
        _global_lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key)
    return _global_lm

def _setup_dspy(config: Dict = None):
    """Returns trained extractor using global settings."""
    lm = _get_lm()
    
    # Use context manager or configure once
    try:
        dspy.settings.configure(lm=lm)
    except Exception:
        # Already configured or in a restricted context
        pass
        
    print("DSPy settings checked")

    extractor = TrainedExtractor()
    extractor = train_extractor(extractor, config=config)
    return extractor

def _process_single_file(file_path: str, extractor) -> tuple:
    """Process a single file through extraction. Returns (reqs, filtered)."""
    print(f"\n  Processing: {file_path}")

    # Extract text (supports PDF with OCR fallback)
    ext = Path(file_path).suffix.lower()
    if ext == '.pdf':
        doc_text = process_pdf(file_path)
    else:
        # For non-PDF files, try reading as text
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                doc_text = f.read()
        except Exception:
            doc_text = ""

    if not doc_text:
        print(f"  WARNING: No text extracted from {file_path}")
        return [], []

    chunks = chunk_document(doc_text)
    print(f"  Split into {len(chunks)} chunks")

    all_reqs = []
    all_filtered = []
    for i, chunk in enumerate(chunks, 1):
        print(f"    Chunk {i}/{len(chunks)}...", end='')
        try:
            result = extractor(document_text=chunk)
            all_reqs.extend(result['requirements'])
            all_filtered.extend(result['filtered_out'])
            print(f" {len(result['requirements'])} accepted, {len(result['filtered_out'])} filtered")
        except Exception as e:
            print(f" ERROR: {e}")

    return all_reqs, all_filtered

def save_model_state(extractor) -> Dict:
    """Save the trained model demos/state as a serializable dict."""
    try:
        state = extractor.classifier.dump_state()
        return state
    except Exception as e:
        print(f"  WARNING: Could not save model state: {e}")
        return {}

# ============================================================================
# EXTRACT FROM FILES (FastAPI / S3 flow)
# ============================================================================

def extract_from_files(project_name: str, file_paths: List[str], output_dir: str = None) -> Dict:
    """
    Extract requirements from a list of local file paths.
    Called by FastAPI after downloading files from S3.

    Args:
        project_name: Project identifier (e.g. 'ptw_phase1')
        file_paths: List of local file paths to process
        output_dir: Optional local output directory to save results

    Returns:
        Dict with project, requirements, and model_state
    """
    print("=" * 80)
    print(f"REQUIREMENTS EXTRACTION - {str(project_name).upper()}")
    print("=" * 80)

    # Setup DSPy and train
    extractor = _setup_dspy()

    # Process each file
    all_reqs = []
    all_filtered = []

    for file_path in file_paths:
        reqs, filtered = _process_single_file(file_path, extractor)
        all_reqs.extend(reqs)
        all_filtered.extend(filtered)

    print(f"\n  Total raw: {len(all_reqs)} accepted, {len(all_filtered)} filtered out")

    # Deduplicate
    unique = deduplicate_requirements(all_reqs)
    print(f"  After dedup: {len(all_reqs)} -> {len(unique)} unique")

    # Consolidate overlapping requirements via LLM
    unique = consolidate_requirements(unique)
    print(f"  After consolidation: {len(unique)} requirements")

    # Add IDs
    for i, req in enumerate(unique, 1):
        req['requirement_id'] = f"{str(project_name).upper()}-{i:03d}"

    # Save model state for S3 upload
    model_state = save_model_state(extractor)

    # Build result
    result_data = {
        'project': project_name,
        'requirements': unique,
        'model_state': model_state,
    }

    # Optionally save locally
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        output_file = Path(output_dir) / f"{project_name}_requirements.json"
        with open(output_file, 'w') as f:
            json.dump(result_data, f, indent=2)
        print(f"  Saved locally to: {output_file}")

    print(f"\nDone! {len(unique)} requirements extracted")
    return result_data

# ============================================================================
# EXTRACT FROM CONFIG (standalone CLI flow)
# ============================================================================

def extract_requirements(config: Dict = None) -> Dict:
    """Core extraction logic using multi-project config.
    Reads current_project from config, processes all PDFs in that project's input_dir.
    """
    print("=" * 80)
    print("REQUIREMENTS EXTRACTION - TRAINED APPROACH")
    print("=" * 80)

    # Load config
    if config is None:
        config_file = Path("config/config.json")
        if not config_file.exists():
            raise FileNotFoundError(f"Config not found: {config_file}")
        with open(config_file) as f:
            config = json.load(f)

    # Read current project
    current_project = config.get('current_project')
    if not current_project:
        raise ValueError("'current_project' not set in config.json")

    projects = config.get('projects', {})
    if current_project not in projects:
        raise ValueError(f"Project '{current_project}' not found in config.projects. Available: {list(projects.keys())}")

    project_config = projects[current_project]
    input_dir = Path(project_config['input_dir'])
    output_dir = Path(config.get('output_dir', 'output'))

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    output_dir.mkdir(exist_ok=True)

    # Find all PDF files in the project's input directory
    pdf_files = sorted(input_dir.glob('*.pdf'))
    pptx_files = sorted(input_dir.glob('*.pptx'))
    all_files = pdf_files + pptx_files

    # Skip files that are NOT requirement sources
    skip_patterns = ['test_strategy', 'test strategy', 'traceability', 'about.txt']
    filtered_files = []
    for f in all_files:
        fname = f.name.lower()
        if any(pat in fname for pat in skip_patterns):
            print(f"  Skipping (not a requirements source): {f.name}")
        else:
            filtered_files.append(f)
    all_files = filtered_files

    if not all_files:
        raise FileNotFoundError(f"No PDF/PPTX files found in {input_dir}")

    print(f"\nProject: {current_project}")
    print(f"Input dir: {input_dir}")
    print(f"Files to process: {len(all_files)}")
    for f in all_files:
        print(f"  - {f.name}")

    # Setup DSPy and train (with multi-project training data)
    extractor = _setup_dspy(config=config)

    # Process each file
    all_reqs = []
    all_filtered = []

    for file_path in all_files:
        reqs, filtered = _process_single_file(str(file_path), extractor)
        all_reqs.extend(reqs)
        all_filtered.extend(filtered)

    print(f"\n  Total raw: {len(all_reqs)} accepted, {len(all_filtered)} filtered out")

    # Deduplicate using similarity
    unique = deduplicate_requirements(all_reqs)
    print(f"  After dedup: {len(all_reqs)} -> {len(unique)} unique")

    # Consolidate overlapping requirements via LLM
    unique = consolidate_requirements(unique)
    print(f"  After consolidation: {len(unique)} requirements")

    # Add IDs
    for i, req in enumerate(unique, 1):
        req['requirement_id'] = f"{current_project.upper()}-{i:03d}"

    # Build result
    result_data = {'project': current_project, 'requirements': unique}

    # Save
    output_file = output_dir / f"{current_project}_requirements.json"
    with open(output_file, 'w') as f:
        json.dump(result_data, f, indent=2)

    print(f"Saved to: {output_file}")
    print(f"\nDone! {len(unique)} requirements extracted from {len(all_files)} files")

    return result_data

def main():
    try:
        extract_requirements()
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
