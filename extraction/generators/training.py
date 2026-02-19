"""
Training Module — DSPy BootstrapFewShot Training

Contains training examples (positive + negative), domain-specific weighting,
multi-project training data generation, and the BootstrapFewShot optimizer.

Moved from: extract_requirements.py lines 22–405
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

import dspy

from .signatures import RequirementExtraction


# ============================================================================
# TRAINING EXAMPLES
# ============================================================================

# POSITIVE: Concrete Business Features (What the user DOES)
POSITIVE_EXAMPLES = [
    # Sales & CRM
    {"text": "View 360-degree contact profile with activity timeline and account hierarchy", "title": "Comprehensive Contact Profile", "description": "Unified view of contact interactions, relationship mapping, and enriched company data", "type": "Functional", "domain": "crm", "is_requirement": "Yes"},
    {"text": "Drag-and-drop lead progression through customizable kanban pipeline stages", "title": "Interactive Deal Pipeline", "description": "Visual management of sales opportunities with stage-gate validation and automated task generation", "type": "Workflow", "domain": "crm", "is_requirement": "Yes"},
    {"text": "Generate AI-driven revenue forecasts based on historical win rates and pipeline health", "title": "Predictive Revenue Forecasting", "description": "Machine learning analysis of sales data to predict quarterly attainment and identify at-risk deals", "type": "Functional", "domain": "crm", "is_requirement": "Yes"},
    # UI / Interaction
    {"text": "Indigo navigation bar with global search, activity feed, and mini-Kanban widgets", "title": "Centralized Sales Workspace UI", "description": "High-productivity interface providing immediate access to critical KPIs and upcoming events", "type": "UI", "domain": "general", "is_requirement": "Yes"},
    {"text": "Color-coded lead scoring (0-100) with drill-down into specific positive/negative signals", "title": "Intelligent Lead Prioritization", "description": "Visual representation of lead quality with transparent reasoning for score calculation", "type": "UI", "domain": "crm", "is_requirement": "Yes"},
    # Operations
    {"text": "Automated email sequence creation with personalized templates and open-rate tracking", "title": "Sales Outreach Automation", "description": "Multi-step communication workflows with performance analytics and automated follow-up scheduling", "type": "Workflow", "domain": "general", "is_requirement": "Yes"},
    {"text": "Bulk export of validated customer records in GDPR-compliant formats", "title": "Secure Data Portability", "description": "Verified export of project data ensuring compliance with regional privacy regulations", "type": "Functional", "domain": "general", "is_requirement": "Yes"},
    # Healthcare Specifics (Golden Samples)
    {"text": "HIPAA-compliant video consultation with provider-patient screen sharing and chat", "title": "Secure Telehealth Consultation", "description": "Encrypted video session with integrated clinical tools and session recording", "type": "Workflow", "domain": "healthcare", "is_requirement": "Yes"},
    {"text": "Real-time sync of patient wearables (heart rate, glucose) with automated alerting", "title": "Remote Patient Monitoring", "description": "Biometric data integration for chronic care management with early warning triggers", "type": "Functional", "domain": "healthcare", "is_requirement": "Yes"},
]

# NEGATIVE: Technical Noise, Infrastructure, and Document Metadata
NEGATIVE_EXAMPLES = [
    # Infrastructure & Technical
    {"text": "Implement API Gateway for JWT-based authentication and rate limiting", "title": "API Gateway Infrastructure", "description": "Security layer for internal service communication and traffic control", "type": "Technical", "is_requirement": "No"},
    {"text": "Design multi-tenant RLS (Row Level Security) for database partitioning", "title": "Multi-Tenant Data Security", "description": "Internal database isolation logic to prevent data leaks between clients", "type": "Technical", "is_requirement": "No"},
    {"text": "Integrate with Clearbit API and Twilio via internal webhook handlers", "title": "API Integration Service", "description": "Backend connection logic for third-party enrichment and voice services", "type": "Technical", "is_requirement": "No"},
    {"text": "Partition activity tables by month for PostgreSQL performance optimization", "title": "Database Optimization", "description": "Internal storage strategy to maintain query speed at scale", "type": "Technical", "is_requirement": "No"},
    {"text": "Set up Elasticsearch CDC (Change Data Capture) indexing", "title": "Search Indexing Pipeline", "description": "Technical data sync between RDBMS and Search Engine", "type": "Technical", "is_requirement": "No"},
    # UI Micro-Details (Too Granular)
    {"text": "Use slide-in panel for lead details and color-coded score gradients", "title": "Lead Detail Animation", "description": "Specific CSS and animation effects for the lead interface", "type": "UI Detail", "is_requirement": "No"},
    {"text": "Show tooltip with company logo on deal card hover", "title": "UI Hover Effect", "description": "Interactive micro-transition for visual polish", "type": "UI Detail", "is_requirement": "No"},
    # SLAs & Performance (Non-functional)
    {"text": "Maintain 99.95% uptime with RTO less than 10 minutes", "title": "System Availability SLA", "description": "Standard service level agreement for platform reliability", "type": "Non-Functional", "is_requirement": "No"},
    {"text": "All API responses must return in under 200ms at p95", "title": "Latency Targets", "description": "Technical performance benchmark", "type": "Non-Functional", "is_requirement": "No"},
    # Document Noise
    {"text": "The objective of this phase is to streamline sales management", "title": "Project Objective", "description": "General summary statement from the executive overview", "type": "Document Noise", "is_requirement": "No"},
    {"text": "Phase 1A scope includes the baseline CRM modules", "title": "Scope Statement", "description": "Document metadata regarding project boundaries", "type": "Document Noise", "is_requirement": "No"},
]

# Skip keywords for pre-filtering (shared with TrainedExtractor)
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


# ============================================================================
# MULTI-PROJECT TRAINING DATA GENERATION
# ============================================================================

def _generate_training_from_projects(
    current_project: str,
    projects: Dict,
    process_pdf_fn=None,
    chunk_fn=None,
) -> List[Dict]:
    """
    Scan other projects' PDFs to generate additional training examples.
    Uses the LLM extractor to get candidates, then labels them as
    positive/negative using the keyword skip filter.

    Args:
        current_project: Name of the current project (excluded)
        projects: Dictionary of all project configs
        process_pdf_fn: Function to extract text from PDF (injected from pipeline)
        chunk_fn: Function to chunk text (injected from pipeline)

    Returns:
        List of dicts with: text, title, description, is_requirement (bool)
    """
    extra_examples = []
    extractor_sig = dspy.ChainOfThought(RequirementExtraction)

    # Lazy import for chunking if not provided
    if chunk_fn is None:
        from ..utils import chunk_document
        chunk_fn = chunk_document

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
                # Use injected PDF processor or import from extractors
                if process_pdf_fn:
                    doc_text = process_pdf_fn(str(pdf_file))
                else:
                    from ..extractors.pdf_extractor import PDFExtractor
                    pdf_ext = PDFExtractor()
                    doc_text = pdf_ext.extract_text(str(pdf_file))

                if not doc_text or len(doc_text.strip()) < 100:
                    continue

                # Take only first chunk to keep it fast
                chunks = chunk_fn(doc_text)
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

            except Exception:
                continue  # Skip files that fail

    return extra_examples


# ============================================================================
# TRAINING FUNCTION
# ============================================================================

def train_extractor(extractor, config: Dict = None):
    """
    Train the requirement classifier using BootstrapFewShot.

    Builds training set from:
    1. Hardcoded positive/negative examples (domain-weighted)
    2. Multi-project training data (from other projects' PDFs)

    Args:
        extractor: TrainedExtractor instance to train
        config: Multi-project config dictionary

    Returns:
        Trained extractor with optimized classifier
    """
    print("\nTraining extractor...")

    current_project = config.get('current_project', '').lower() if config else ""

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

    # 1. Hardcoded examples (with domain-specific weighting)
    for ex in POSITIVE_EXAMPLES:
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
        current_project_name = config.get('current_project', '')
        projects = config.get('projects', {})
        if len(projects) > 1:
            print(f"  Generating training data from other projects...")
            extra = _generate_training_from_projects(current_project_name, projects)
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
