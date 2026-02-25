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

# POSITIVE: Concrete Business Features (What the user DOES)
# 10-year Pro Tip: Focus on verbs and business outcomes.
POSITIVE_EXAMPLES = [
    # Sales & CRM
    {"text": "View 360-degree contact profile with activity timeline and account hierarchy", "title": "Comprehensive Contact Profile", "description": "Unified view of contact interactions, relationship mapping, and enriched company data", "type": "Functional", "domain": "crm"},
    {"text": "Drag-and-drop lead progression through customizable kanban pipeline stages", "title": "Interactive Deal Pipeline", "description": "Visual management of sales opportunities with stage-gate validation and automated task generation", "type": "Workflow", "domain": "crm"},
    {"text": "Generate AI-driven revenue forecasts based on historical win rates and pipeline health", "title": "Predictive Revenue Forecasting", "description": "Machine learning analysis of sales data to predict quarterly attainment and identify at-risk deals", "type": "Functional", "domain": "crm"},
    # UI / Interaction
    {"text": "Indigo navigation bar with global search, activity feed, and mini-Kanban widgets", "title": "Centralized Sales Workspace UI", "description": "High-productivity interface providing immediate access to critical KPIs and upcoming events", "type": "UI", "domain": "general"},
    {"text": "Color-coded lead scoring (0-100) with drill-down into specific positive/negative signals", "title": "Intelligent Lead Prioritization", "description": "Visual representation of lead quality with transparent reasoning for score calculation", "type": "UI", "domain": "crm"},
    # Operations
    {"text": "Automated email sequence creation with personalized templates and open-rate tracking", "title": "Sales Outreach Automation", "description": "Multi-step communication workflows with performance analytics and automated follow-up scheduling", "type": "Workflow", "domain": "general"},
    {"text": "Bulk export of validated customer records in GDPR-compliant formats", "title": "Secure Data Portability", "description": "Verified export of project data ensuring compliance with regional privacy regulations", "type": "Functional", "domain": "general"},
    # Healthcare Specifics (Golden Samples)
    {"text": "HIPAA-compliant video consultation with provider-patient screen sharing and chat", "title": "Secure Telehealth Consultation", "description": "Encrypted video session with integrated clinical tools and session recording", "type": "Workflow", "domain": "healthcare"},
    {"text": "Real-time sync of patient wearables (heart rate, glucose) with automated alerting", "title": "Remote Patient Monitoring", "description": "Biometric data integration for chronic care management with early warning triggers", "type": "Functional", "domain": "healthcare"},
]

# NEGATIVE: Technical Noise, Infrastructure, and Document Metadata (The "How", not the "What")
NEGATIVE_EXAMPLES = [
    # Infrastructure & Technical
    {"text": "Implement API Gateway for JWT-based authentication and rate limiting", "title": "API Gateway Infrastructure", "description": "Security layer for internal service communication and traffic control", "type": "Technical", "is_requirement": False},
    {"text": "Design multi-tenant RLS (Row Level Security) for database partitioning", "title": "Multi-Tenant Data Security", "description": "Internal database isolation logic to prevent data leaks between clients", "type": "Technical", "is_requirement": False},
    {"text": "Integrate with Clearbit API and Twilio via internal webhook handlers", "title": "API Integration Service", "description": "Backend connection logic for third-party enrichment and voice services", "type": "Technical", "is_requirement": False},
    {"text": "Partition activity tables by month for PostgreSQL performance optimization", "title": "Database Optimization", "description": "Internal storage strategy to maintain query speed at scale", "type": "Technical", "is_requirement": False},
    {"text": "Set up Elasticsearch CDC (Change Data Capture) indexing", "title": "Search Indexing Pipeline", "description": "Technical data sync between RDBMS and Search Engine", "type": "Technical", "is_requirement": False},
    # UI Micro-Details (Too Granular)
    {"text": "Use slide-in panel for lead details and color-coded score gradients", "title": "Lead Detail Animation", "description": "Specific CSS and animation effects for the lead interface", "type": "UI Detail", "is_requirement": False},
    {"text": "Show tooltip with company logo on deal card hover", "title": "UI Hover Effect", "description": "Interactive micro-transition for visual polish", "type": "UI Detail", "is_requirement": False},
    # SLAs & Performance (Non-functional)
    {"text": "Maintain 99.95% uptime with RTO less than 10 minutes", "title": "System Availability SLA", "description": "Standard service level agreement for platform reliability", "type": "Non-Functional", "is_requirement": False},
    {"text": "All API responses must return in under 200ms at p95", "title": "Latency Targets", "description": "Technical performance benchmark", "type": "Non-Functional", "is_requirement": False},
    # Document Noise
    {"text": "The objective of this phase is to streamline sales management", "title": "Project Objective", "description": "General summary statement from the executive overview", "type": "Document Noise", "is_requirement": False},
    {"text": "Phase 1A scope includes the baseline CRM modules", "title": "Scope Statement", "description": "Document metadata regarding project boundaries", "type": "Document Noise", "is_requirement": False},
]

# ============================================================================
# DSPY SIGNATURES
# ============================================================================

class RequirementExtraction(dspy.Signature):
    """Extract DETAILED BUSINESS requirements across three granular layers.
    
    A 10-year professional focus:
    1. EXCLUDE: Technical implementation noise (e.g., 'API Gateway routes', 'DB schemas').
    2. INCLUDE:
       - LAYER 1 (Business Features): Primary user-facing capabilities.
       - LAYER 2 (UI Interface): Specific screens, widgets, navigation, and indicators.
       - LAYER 3 (Workflows): Step-by-step end-to-step business processes.
    
    RULES:
    - Extract ALL distinct requirements found in the text.
    - DO NOT merge a 'UI detail' into a 'Business Feature' if the UI has its own logic.
    - Title should be descriptive (3-8 words).
    - Description must provide specific context from the document.
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of ALL requirements found: 
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
    }]""")

class RequirementDeMerger(dspy.Signature):
    """Split a composite requirement into multiple granular requirements if it contains distinct features.
    
    Example:
    Input: 'Appointment Booking with Calendar View and Payment Integration'
    Output: 
    1. 'Appointment Booking' (Business Process)
    2. 'Calendar Booking Interface' (UI/Interface)
    3. 'Online Payment Integration' (Workflow/Functional)
    """
    composite_requirement_title = dspy.InputField()
    composite_requirement_desc = dspy.InputField()
    requirements_json = dspy.OutputField(desc="JSON array of distinct requirements (titles and descriptions)")

class RequirementClassifier(dspy.Signature):
    """Classify if this is a genuine software requirement of ANY type.
    
    Answer 'yes' if ANY of these are true:
    1. User can SEE it on screen or DO/interact with it (functional/UI)
    2. It describes a workflow or end-to-end process flow
    3. It specifies architecture, API design, or system integration
    4. It defines a data model, entity relationship, or schema
    5. It sets a performance target, SLA, or scalability requirement
    6. It defines security, compliance, or data protection standards
    
    Answer 'no' if it is:
    - Technical infrastructure (e.g., 'API Gateway', 'Microservices', 'Database Schema', 'Backend Integration')
    - Internal architecture (e.g., 'SaaS multi-tenancy', 'Indexing policy', 'Load Balancing')
    - Document noise (executive summary, project objectives, scope statements)
    - A UI micro-detail (tooltip text, color hex code, hover animation)
    - Vague/generic with no specifics (e.g., 'ensure security', 'optimize performance')
    
    CRITICAL: Prioritize business features (the 'What') over technical implementation (the 'How').
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
        self.de_merger = dspy.ChainOfThought(RequirementDeMerger)
        
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
                # Second Pass: De-merger
                try:
                    de_merged = self.de_merger(
                        composite_requirement_title=title,
                        composite_requirement_desc=desc
                    )
                    raw_dm = de_merged.requirements_json
                    if '```' in raw_dm:
                        raw_dm = raw_dm.split('```')[1]
                        if raw_dm.startswith('json'):
                            raw_dm = raw_dm[4:]
                    distinct_items = json.loads(raw_dm.strip())
                    
                    if len(distinct_items) > 1:
                        for item in distinct_items:
                            # Inherit metadata from parent
                            new_item = candidate.copy()
                            new_item['title'] = item['title']
                            new_item['description'] = item['description']
                            valid_requirements.append(new_item)
                        continue # Skip adding the original parent
                except:
                    pass

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
    # Technical / Architecture (Frequent over-creation)
    'data modeling', 'entity relationship', 'api gateway',
    'saas architecture', 'multi-tenancy', 'load balancing',
    'indexing policy', 'database schema', 'rest api',
    'internal integration', 'backend service',
    'system architecture', 'application framework',
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

    current_project = str(config.get('current_project', '')).lower() if config else ""
    # Map project names to domains
    domain_map = {
        'healthcare': 'healthcare',
        'fintech': 'fintech',
        'crm': 'crm',
        'ecommerce': 'ecommerce',
        'logistics': 'logistics'
    }
    target_domain = next((v for k, v in domain_map.items() if k in current_project), 'general')
    print(f"  Target domain detected: {target_domain.upper()}")

    train_examples = []

    # 1. Hardcoded examples (with domain-specific weighting/selection)
    for ex in POSITIVE_EXAMPLES:
        # Boost examples from the target domain or general ones
        domain = ex.get('domain', 'general')
        if domain == target_domain or domain == 'general':
            train_examples.append(
                dspy.Example(
                    text=ex['text'],
                    title=ex['title'],
                    description=ex['description'],
                    is_requirement='yes',
                    reason=f"Valid {domain} business requirement"
                ).with_inputs('text', 'title', 'description')
            )
            # Add twice if exact domain match for stronger weighting
            if domain == target_domain and domain != 'general':
                train_examples.append(train_examples[-1])

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

def chunk_document(text: str, max_chars: int = 6000, overlap: float = 0.20) -> List[str]:
    """Split document into overlapping chunks to avoid cutting requirements."""
    chunks = []
    paras = text.split('\n\n')
    current_chunk = []
    current_len = 0
    
    overlap_chars = int(max_chars * overlap)
    
    for para in paras:
        para_len = len(para)
        if current_len + para_len > max_chars:
            # Save current chunk
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(chunk_text)
            
            # Start new chunk with some overlap from the END of the previous chunk
            # We keep as many paragraphs as fit within the overlap_chars
            overlap_buffer = []
            buffer_len = 0
            for p in reversed(current_chunk):
                if buffer_len + len(p) < overlap_chars:
                    overlap_buffer.insert(0, p)
                    buffer_len += len(p)
                else:
                    break
            
            current_chunk = overlap_buffer + [para]
            current_len = buffer_len + para_len
        else:
            current_chunk.append(para)
            current_len += para_len
            
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
        
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
    """Consolidate a list of requirements by merging TRULY redundant items.
    
    A 10-year professional focus:
    1. Merge items that describe the EXACT same feature with the same scope.
    2. KEEP distinct items even if related (e.g., KEEP 'Login Screen UI' separate from 'Login Workflow').
    3. If two items are similar, merge them and combine their descriptions into a more comprehensive one.
    4. Target a clean, non-redundant list (approx 50-70 items for large projects).
    """
    requirements_json = dspy.InputField(desc="JSON array of requirements to consolidate")
    consolidated_json = dspy.OutputField(desc="JSON array of consolidated requirements: [{'title': '...', 'description': '...', 'type': '...'}]")


def consolidate_requirements(reqs: List[Dict]) -> List[Dict]:
    """Use LLM to merge overlapping requirements into fewer high-level items."""
    if len(reqs) <= 45:
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
                # Robust JSON cleaning
                clean_raw = raw.strip()
                if '```' in clean_raw:
                    clean_raw = clean_raw.split('```')[1]
                    if clean_raw.startswith('json'):
                        clean_raw = clean_raw[4:]
                
                # Fix common LLM JSON errors (like unterminated strings)
                try:
                    batch_consolidated = json.loads(clean_raw.strip())
                except json.JSONDecodeError:
                    # Attempt a looser parse or regex-based fix if needed, 
                    # but for now, we'll try to just take the first part that parses
                    import re
                    match = re.search(r'\[.*\]', clean_raw, re.DOTALL)
                    if match:
                        try:
                            batch_consolidated = json.loads(match.group(0))
                        except:
                            batch_consolidated = batch
                    else:
                        batch_consolidated = batch
                
                intermediate.extend(batch_consolidated)
                print(f"      → {len(batch_consolidated)} items")
            except Exception as e:
                print(f"      ERROR: {e} — using local fast-dedup fallback for this batch")
                batch_dedup = deduplicate_requirements(batch, similarity_threshold=0.7)
                intermediate.extend(batch_dedup)
        
        # Second pass to merge across batches - only if we have a HUGE number of items
        if len(intermediate) > 100:
            print(f"    Final merge pass ({len(intermediate)} items)...")
            try:
                result = consolidator(requirements_json=json.dumps(intermediate))
                raw = result.consolidated_json
                
                # Robust cleaning for final pass
                clean_final = raw.strip()
                if '```' in clean_final:
                    clean_final = clean_final.split('```')[1]
                    if clean_final.startswith('json'):
                        clean_final = clean_final[4:]
                
                try:
                    final = json.loads(clean_final.strip())
                except:
                    import re
                    match = re.search(r'\[.*\]', clean_final, re.DOTALL)
                    if match:
                        try:
                            final = json.loads(match.group(0))
                        except:
                            final = deduplicate_requirements(intermediate, similarity_threshold=0.65)
                    else:
                        final = deduplicate_requirements(intermediate, similarity_threshold=0.65)
                        
                print(f"      → {len(final)} items")
                return final
            except Exception as e:
                print(f"      ERROR in final merge: {e} — using local fast-dedup fallback")
                return deduplicate_requirements(intermediate, similarity_threshold=0.6)
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
        _global_lm = dspy.LM('groq/llama-3.3-70b-versatile', api_key=groq_key, max_tokens=4096)
    return _global_lm

def _setup_dspy(config: Dict = None, model_state: Dict = None):
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
    
    if model_state:
        print("  ✓ Loading existing model state (skipping training)")
        try:
            extractor.classifier.load_state(model_state)
        except Exception as e:
            print(f"  ⚠ Failed to load model state: {e}. Falling back to training.")
            extractor = train_extractor(extractor, config=config)
    else:
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
            # Important: extract_from_files calls extractor as a module
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

def extract_from_files(project_name: str, file_paths: List[str], output_dir: str = None, model_state: Dict = None, config: Dict = None, status_callback=None) -> Dict:
    """
    Extract requirements from a list of local file paths.
    Called by FastAPI after downloading files from S3.

    Args:
        project_name: Project identifier (e.g. 'ptw_phase1')
        file_paths: List of local file paths to process
        output_dir: Optional local output directory to save results
        model_state: Optional pre-trained model state to skip training
        config: Optional multi-project config for training
        status_callback: Optional callback(file_path, status) for per-file status updates

    Returns:
        Dict with project, requirements, and model_state
    """
    print("=" * 80)
    print(f"REQUIREMENTS EXTRACTION - {str(project_name).upper()}")
    print("=" * 80)

    # Setup DSPy (load or train)
    extractor = _setup_dspy(model_state=model_state, config=config)

    # Process each file
    all_reqs = []
    all_filtered = []

    for file_path in file_paths:
        # Notify caller that this file is being processed
        if status_callback:
            try:
                status_callback(file_path, "IN_PROGRESS")
            except Exception as e:
                print(f"  ⚠ status_callback IN_PROGRESS failed: {e}")

        reqs, filtered = _process_single_file(file_path, extractor)
        all_reqs.extend(reqs)
        all_filtered.extend(filtered)

        # Notify caller that this file is done
        if status_callback:
            try:
                status_callback(file_path, "COMPLETED")
            except Exception as e:
                print(f"  ⚠ status_callback COMPLETED failed: {e}")

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
    new_model_state = save_model_state(extractor)

    # Build result
    result_data = {
        'project': project_name,
        'requirements': unique,
        'model_state': new_model_state,
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
        req['requirement_id'] = f"{current_project.upper().replace(' ', '_')}-{i:03d}"

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
