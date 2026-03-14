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

from .signatures import BusinessFeatureExtraction

# POSITIVE EXAMPLES - Organized by extraction layer
# Teaches the LLM to recognize PATTERNS, not domain-specific content

POSITIVE_EXAMPLES_BY_LAYER = {
    # Layer 1: Business Features (High-level capabilities - the WHAT)
    "business_features": [
        # Pattern: [Entity] Management with [Capability]
        {"text": "Contact management with 360-degree profile views and relationship mapping", "title": "Contact Management", "description": "Unified view of contact interactions, account hierarchy, and enriched data", "type": "Functional", "pattern": "Entity management", "is_requirement": "Yes"},
        {"text": "Lead management with scoring, assignment, and qualification workflows", "title": "Lead Management", "description": "Capture, qualify, and convert leads with automated routing and prioritization", "type": "Functional", "pattern": "Entity management", "is_requirement": "Yes"},
        {"text": "Inventory tracking with stock levels, reorder alerts, and supplier management", "title": "Inventory Management", "description": "Real-time tracking of inventory levels with automated reorder points and supplier coordination", "type": "Functional", "pattern": "Asset tracking", "is_requirement": "Yes"},
        # Pattern: [Process] Processing with [Capability]
        {"text": "Deal pipeline tracking with stage progression and win/loss analysis", "title": "Pipeline Management", "description": "Visual tracking of sales opportunities through lifecycle stages with forecasting", "type": "Functional", "pattern": "Process tracking", "is_requirement": "Yes"},
        {"text": "Payment processing with multiple gateways and refund handling", "title": "Payment Processing", "description": "Secure transaction processing supporting credit cards, ACH, and digital wallets with reconciliation", "type": "Functional", "pattern": "Transaction processing", "is_requirement": "Yes"},
        {"text": "Order fulfillment with picking, packing, and shipping coordination", "title": "Order Fulfillment", "description": "End-to-end order processing from warehouse picking to carrier shipment tracking", "type": "Functional", "pattern": "Fulfillment processing", "is_requirement": "Yes"},
        # Pattern: [Feature Area] with [Capability]
        {"text": "Analytics and reporting with custom dashboards and scheduled exports", "title": "Analytics Platform", "description": "Business intelligence with drag-and-drop report builder and automated delivery", "type": "Functional", "pattern": "Analytics capability", "is_requirement": "Yes"},
        {"text": "Email integration with Gmail and Outlook sync, tracking, and templates", "title": "Email Integration", "description": "Bidirectional email sync with open/click tracking and template library", "type": "Functional", "pattern": "Communication integration", "is_requirement": "Yes"},
        {"text": "Appointment scheduling with calendar sync and automated reminders", "title": "Scheduling System", "description": "Appointment booking with Google/Outlook integration and SMS/email notifications", "type": "Functional", "pattern": "Scheduling/booking", "is_requirement": "Yes"},
    ],

    # Layer 2: UI Components (Specific screens, layouts, interactions)
    "ui_components": [
        # Pattern: [Screen Name] with [Layout] and [Components]
        {"text": "Sales Dashboard with KPI widgets in 3-column grid showing revenue, pipeline, and win rate", "title": "Sales Dashboard Screen", "description": "Dashboard with revenue chart, pipeline funnel, win rate gauge, and top deals table", "type": "UI", "pattern": "Dashboard layout", "is_requirement": "Yes"},
        {"text": "Analytics Dashboard with chart panels and date range selector", "title": "Analytics Dashboard", "description": "Multi-panel dashboard with line charts, bar graphs, and interactive filters", "type": "UI", "pattern": "Dashboard layout", "is_requirement": "Yes"},
        # Pattern: Kanban/Board Interface
        {"text": "Deal Pipeline Board with drag-drop cards across stage columns", "title": "Deal Kanban Board UI", "description": "Visual board with stage columns (Prospecting, Qualification, Proposal, Negotiation, Closed), drag-drop deal cards with company logo and value", "type": "UI", "pattern": "Kanban interface", "is_requirement": "Yes"},
        {"text": "Task Board with swimlanes for team members and drag-drop task cards", "title": "Task Management Board", "description": "Kanban-style board with user swimlanes, task cards with priority badges, and drag-drop reordering", "type": "UI", "pattern": "Kanban interface", "is_requirement": "Yes"},
        # Pattern: Tabbed/Multi-Section View
        {"text": "Contact Profile page with tabbed sections (Timeline, Emails, Deals, Files, Notes)", "title": "Contact 360° View UI", "description": "Full-page contact view with header showing contact details and action buttons, tabbed content area, right sidebar with company enrichment data", "type": "UI", "pattern": "Tabbed profile view", "is_requirement": "Yes"},
        {"text": "Order Details page with tabs for Items, Shipments, Payments, and History", "title": "Order Detail View", "description": "Order profile with header summary, tabbed sections, and sidebar with customer info", "type": "UI", "pattern": "Tabbed detail view", "is_requirement": "Yes"},
        # Pattern: Data Table/List Interface
        {"text": "Lead List table with column sorting, filters, bulk actions, and pagination", "title": "Lead List UI", "description": "Searchable table with columns for name, score, status, owner, and last activity. Supports multi-select with bulk edit/delete/assign", "type": "UI", "pattern": "Data table", "is_requirement": "Yes"},
        {"text": "Invoice List with search, status filters, and export button", "title": "Invoice Management Table", "description": "Table view with columns for invoice number, customer, amount, status, due date. Includes CSV export", "type": "UI", "pattern": "Data table", "is_requirement": "Yes"},
        # Pattern: Calendar/Timeline View
        {"text": "Appointment Calendar with week/month view toggle and drag-drop rescheduling", "title": "Booking Calendar UI", "description": "Interactive calendar with color-coded appointments, drag-drop to reschedule, click to view details", "type": "UI", "pattern": "Calendar view", "is_requirement": "Yes"},
        {"text": "Activity Timeline with chronological event cards and filter by type", "title": "Activity Feed UI", "description": "Vertical timeline showing calls, emails, meetings, notes with timestamp and user avatar", "type": "UI", "pattern": "Timeline view", "is_requirement": "Yes"},
    ],

    # Layer 3: Workflows (Step-by-step processes with numbered steps)
    "workflows": [
        # Pattern: Multi-step conversion/qualification process
        {"text": "9-step Lead Conversion Workflow: Capture → Deduplication → AI Scoring → Territory Assignment → Rep Review → BANT Qualification → Conversion Wizard → Deal Creation → Task Generation. Alternate paths: Nurture (score < 50), Disqualify (no fit)", "title": "Lead Conversion Workflow", "description": "End-to-end lead qualification process from initial capture to deal creation with branching logic for nurture and disqualification", "type": "Workflow", "pattern": "Multi-step process", "is_requirement": "Yes"},
        {"text": "Patient Intake Workflow: Registration → Insurance Verification → Medical History → Consent Forms → Appointment Scheduling → Confirmation. Error path: Insurance Rejection → Self-Pay Option", "title": "Patient Onboarding Process", "description": "Healthcare intake workflow with verification steps and error handling for insurance issues", "type": "Workflow", "pattern": "Multi-step process", "is_requirement": "Yes"},
        # Pattern: Transaction/Payment flow
        {"text": "Checkout Workflow: Cart Review → Shipping Address → Delivery Method → Payment → Order Confirmation → Fulfillment Trigger → Email Receipt", "title": "E-commerce Checkout Process", "description": "Complete purchase workflow from cart to order confirmation with validation at each step", "type": "Workflow", "pattern": "Transaction flow", "is_requirement": "Yes"},
        {"text": "Refund Workflow: Request Submission → Manager Approval → Financial Review → Refund Processing → Customer Notification", "title": "Refund Approval Process", "description": "Multi-stage refund workflow with approval gates and automated notifications", "type": "Workflow", "pattern": "Approval chain", "is_requirement": "Yes"},
        # Pattern: Approval/Review process
        {"text": "Purchase Order Approval: Requestor Submit → Manager Review → Procurement Review → Finance Approval → Vendor PO Generation → Goods Receipt", "title": "PO Approval Workflow", "description": "Multi-tier approval chain with role-based gates and automatic vendor notification", "type": "Workflow", "pattern": "Approval chain", "is_requirement": "Yes"},
        {"text": "Content Publishing Workflow: Draft → Peer Review → Editorial Review → Legal Approval → Scheduled Publication → Archive", "title": "Content Approval Process", "description": "Publishing workflow with review stages, approvals, and scheduling", "type": "Workflow", "pattern": "Approval chain", "is_requirement": "Yes"},
        # Pattern: Automated sequence/campaign
        {"text": "Email Campaign Workflow: Template Selection → Recipient Segmentation → Sequence Configuration (Day 1, Day 3, Day 7) → Personalization → Engagement Tracking → Rep Notification → Completion Handling", "title": "Email Drip Campaign", "description": "Automated email sequence with performance tracking and conditional follow-up triggers", "type": "Workflow", "pattern": "Automated sequence", "is_requirement": "Yes"},
        {"text": "Onboarding Automation: Welcome Email → Training Module 1 → Quiz → Training Module 2 → Quiz → Completion Certificate → Manager Notification", "title": "Employee Onboarding Sequence", "description": "Automated training workflow with checkpoint quizzes and completion tracking", "type": "Workflow", "pattern": "Automated sequence", "is_requirement": "Yes"},
    ],

    # Layer 4: Technical Requirements (Architecture, data models, integrations, SLAs)
    "technical": [
        # Pattern: Integration with specific technology and metric
        {"text": "OAuth 2.0 integration with Gmail API for bidirectional email sync within 60 seconds", "title": "Gmail Email Integration", "description": "Real-time email synchronization using Gmail API with OAuth authentication, sync latency < 60s", "type": "Architecture", "pattern": "Integration spec", "is_requirement": "Yes"},
        {"text": "Stripe payment gateway integration with webhook support for payment status updates", "title": "Stripe Payment Integration", "description": "Payment processing via Stripe API with real-time webhook notifications for charge success/failure", "type": "Architecture", "pattern": "Integration spec", "is_requirement": "Yes"},
        {"text": "Twilio voice API integration for click-to-call with automatic call logging", "title": "Voice Integration", "description": "Twilio-based calling with automatic CRM activity creation and call recording storage", "type": "Architecture", "pattern": "Integration spec", "is_requirement": "Yes"},
        # Pattern: Data model with entities and relationships
        {"text": "CRM Data Model: Lead, Contact, Company, Deal, Activity entities with foreign key relationships. Multi-tenant row-level security. Elasticsearch CDC indexing for search. Activity tables partitioned by month.", "title": "CRM Database Schema", "description": "Relational data model with multi-tenancy, search indexing, and performance optimizations", "type": "Data Model", "pattern": "Data model", "is_requirement": "Yes"},
        {"text": "E-commerce Data Model: Product, Order, OrderItem, Payment, Shipment entities. Inventory tracking with real-time stock updates. Order state machine (Pending, Processing, Shipped, Delivered).", "title": "Order Management Schema", "description": "Transactional data model with inventory tracking and order lifecycle management", "type": "Data Model", "pattern": "Data model", "is_requirement": "Yes"},
        # Pattern: Performance SLA with quantified metrics
        {"text": "Dashboard load time < 1.5s at p95 for 100,000 records with 5 concurrent widgets", "title": "Dashboard Performance SLA", "description": "Sub-second dashboard rendering with complex queries and multiple data sources", "type": "Non-Functional", "pattern": "Performance SLA", "is_requirement": "Yes"},
        {"text": "Search results return in < 300ms at p95 with full-text relevance across 1M+ documents", "title": "Search Performance Target", "description": "Fast search with relevance ranking and faceted filtering", "type": "Non-Functional", "pattern": "Performance SLA", "is_requirement": "Yes"},
        {"text": "API response time < 200ms at p95 with rate limiting at 1000 req/min per tenant", "title": "API Performance SLA", "description": "Low-latency API with tenant-level rate limiting and throttling", "type": "Non-Functional", "pattern": "Performance SLA", "is_requirement": "Yes"},
        # Pattern: Availability/Reliability with quantified uptime
        {"text": "99.95% uptime SLA with multi-region deployment, RTO < 10 minutes, RPO < 30 seconds, 30-day backup retention", "title": "Platform Availability SLA", "description": "High-availability architecture with disaster recovery and backup policies", "type": "Non-Functional", "pattern": "Availability SLA", "is_requirement": "Yes"},
        # Pattern: Security/Compliance with specific protocols
        {"text": "Multi-tenant row-level security (RLS) on PostgreSQL with tenant isolation policies enforced at database layer", "title": "Multi-Tenant Data Security", "description": "Database-enforced tenant isolation preventing cross-tenant data access", "type": "Security", "pattern": "Data security", "is_requirement": "Yes"},
        {"text": "AES-256 encryption at rest for sensitive fields (SSN, credit card) with key rotation every 90 days", "title": "Data Encryption Policy", "description": "Field-level encryption for PII/PCI data with automated key management", "type": "Security", "pattern": "Data security", "is_requirement": "Yes"},
    ],
#     # Layer 5: Domain-Specific CRM Examples
#     "crm": [
#         {"text": "Lead Deduplication with email and phone matching", "title": "Lead Deduplication", "description": "Prevent duplicate records by matching on primary email and mobile phone with manual merge capability", "type": "Functional", "pattern": "CRM Feature", "is_requirement": "Yes"},
#         {"text": "ML-driven revenue forecasting with best-case and committed amounts", "title": "AI Revenue Forecasting", "description": "Sales predictions using historical win rates and current pipeline status", "type": "Functional", "pattern": "CRM Feature", "is_requirement": "Yes"},
#         {"text": "Bidirectional Gmail and Outlook sync for sales activities", "title": "Email and Calendar Sync", "description": "Real-time sync of emails and meetings with auto-logging to contact records", "type": "Functional", "pattern": "CRM Feature", "is_requirement": "Yes"},
#         {"text": "Click-to-call integration with Twilio for automated call logging", "title": "Sales Call Integration", "description": "In-app dialing with automatic CRM activity creation and recording", "type": "Functional", "pattern": "CRM Feature", "is_requirement": "Yes"},
#     ],
#     # Layer 6: Domain-Specific Fintech Examples

#     "fintech": [
#         {"text": "Goal-Based Savings with automated round-ups and recurring transfers", "title": "Goal-Based Savings", "description": "Users can set financial goals, automate round-ups on purchases, and track progress with visualizations", "type": "Functional", "pattern": "Fintech Feature", "is_requirement": "Yes"},
#         {"text": "Instant P2P transfers using mobile number with FedNow settlement", "title": "P2P Instant Transfers", "description": "Send money instantly to users via phone number with immediate clearing and receipt sharing", "type": "Functional", "pattern": "Fintech Feature", "is_requirement": "Yes"},
#         {"text": "Fractional stock and ETF trading from $1 per trade with real-time charts", "title": "Fractional Stock Trading", "description": "Purchase portions of stocks and ETFs using market or limit orders with automated portfolio rebalancing", "type": "Functional", "pattern": "Fintech Feature", "is_requirement": "Yes"},
#         {"text": "Buy/Sell top 20 cryptocurrencies with secure wallet integration", "title": "Crypto Trading", "description": "Interactive crypto trading with price alerts and integrated portfolio view of top digital assets", "type": "Functional", "pattern": "Fintech Feature", "is_requirement": "Yes"},
#         {"text": "Interactive budget tracker with spending insights by category", "title": "Budget Tracker", "description": "Automated transaction categorization with monthly spending bar charts and budget threshold alerts", "type": "Functional", "pattern": "Fintech Feature", "is_requirement": "Yes"},
#     ]
}

# NEGATIVE EXAMPLES - Patterns to REJECT
NEGATIVE_EXAMPLES = [
    # Vague/Generic requirements (no specifics)
    {"text": "Advanced reporting and analytics capabilities", "title": "Advanced Reporting", "description": "Comprehensive analytics tools for business insights", "type": "Functional", "is_requirement": "No", "reason": "Too generic - no specific reports, metrics, or UI details"},
    {"text": "Robust security and access control", "title": "Security Features", "description": "Secure platform with user authentication and authorization", "type": "Functional", "is_requirement": "No", "reason": "Vague - no specific protocols, encryption methods, or access patterns"},
    {"text": "Intuitive user interface and experience", "title": "User-Friendly Design", "description": "Easy-to-use interface with modern design patterns", "type": "UI", "is_requirement": "No", "reason": "Generic - no specific screens, layouts, or components mentioned"},
    {"text": "Scalable and performant architecture", "title": "System Scalability", "description": "Platform designed to handle growing user base and data volumes", "type": "Non-Functional", "is_requirement": "No", "reason": "NFR without quantified metrics (no throughput, latency, or capacity numbers)"},
    {"text": "Comprehensive customer support and training", "title": "Customer Support Services", "description": "24/7 support with documentation and onboarding assistance", "type": "Functional", "is_requirement": "No", "reason": "Service offering, not software feature"},
    # Service/Operational items (not software features)
    {"text": "User training program with webinars and documentation", "title": "Training Services", "description": "Onboarding materials and live training sessions for new users", "type": "Service", "is_requirement": "No", "reason": "Service item, not software requirement"},
    {"text": "Technical support with SLA-backed response times", "title": "Support SLA", "description": "Dedicated support team with 4-hour response guarantee", "type": "Service", "is_requirement": "No", "reason": "Operational service, not software feature"},
    {"text": "System implementation and data migration services", "title": "Implementation Services", "description": "Professional services for initial setup and legacy data import", "type": "Service", "is_requirement": "No", "reason": "Service offering, not product requirement"},
    # Infrastructure/Backend (internal technical details)
    {"text": "Implement API Gateway for JWT-based authentication and rate limiting", "title": "API Gateway Infrastructure", "description": "Security layer for internal service communication and traffic control", "type": "Technical", "is_requirement": "No", "reason": "Internal infrastructure, not user-facing feature"},
    {"text": "Set up Elasticsearch CDC (Change Data Capture) indexing pipeline", "title": "Search Indexing Pipeline", "description": "Technical data sync between RDBMS and Search Engine", "type": "Technical", "is_requirement": "No", "reason": "Backend implementation detail, not requirement"},
    {"text": "Configure load balancer with auto-scaling policies", "title": "Load Balancing Config", "description": "Infrastructure setup for horizontal scaling under load", "type": "Technical", "is_requirement": "No", "reason": "Internal architecture, not user requirement"},
    # UI Micro-Details (too granular)
    {"text": "Show tooltip with company logo on hover over deal card", "title": "UI Hover Effect", "description": "Interactive micro-transition for visual polish", "type": "UI Detail", "is_requirement": "No", "reason": "Too granular - minor UI polish, not a requirement"},
    {"text": "Color-coded status badges with green/yellow/red indicators", "title": "Status Badge Colors", "description": "Visual color scheme for status representation", "type": "UI Detail", "is_requirement": "No", "reason": "Too granular - color choice is a design detail"},
    # Document Noise (executive summaries, project metadata)
    {"text": "The objective of this project is to modernize sales operations", "title": "Project Objective", "description": "High-level goal statement from executive summary", "type": "Document Noise", "is_requirement": "No", "reason": "Document metadata, not a requirement"},
    {"text": "Phase 1 scope includes core CRM modules and integrations", "title": "Scope Statement", "description": "Project boundary definition from planning documents", "type": "Document Noise", "is_requirement": "No", "reason": "Project metadata, not software requirement"},
    {"text": "This system will streamline operations and improve efficiency", "title": "Business Benefit", "description": "General value proposition statement", "type": "Document Noise", "is_requirement": "No", "reason": "Vague benefit statement, not actionable requirement"},
]

# Flatten POSITIVE_EXAMPLES_BY_LAYER for backward compatibility with existing code
POSITIVE_EXAMPLES = []
for layer_name, examples in POSITIVE_EXAMPLES_BY_LAYER.items():
    for ex in examples:
        ex['layer'] = layer_name  # Tag with layer for potential future use
        POSITIVE_EXAMPLES.append(ex)

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
    # NEW: Specific technical noise items (F1 killers)
    'backups', 'sar auto-generation', 'ccpa compliance', 
    'mfa', 'multi-factor', 'pci dss', 'soc 2', 
    'disaster recovery', 'rto and rpo', '99.99%',
    'merchant logos', 'app size', 'offline mode',
    'entity management', 'crud operations', 'internal logs',
    'aws deployment', 'engagement and feedback', 'analytics and reporting',
    'customer support', 'fast transaction processing', 'settings management',
]

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
    """
    extra_examples = []
    extractor_sig = dspy.ChainOfThought(BusinessFeatureExtraction)

    # Lazy import for chunking if not provided
    if chunk_fn is None:
        from ..utils import chunk_document
        chunk_fn = chunk_document

    for project_name, project_config in projects.items():
        if project_name == current_project or project_name == 'bbmsa':
            continue

        input_dir = Path(project_config.get('input_dir', ''))
        if not input_dir or not input_dir.exists():
            continue

        # Get PDF files 
        pdf_files = sorted(input_dir.glob('*.pdf'))
        if not pdf_files:
            continue

        for pdf_file in pdf_files[:2]:  # Limit to 2 files per project for speed
            try:
                if process_pdf_fn:
                    doc_text = process_pdf_fn(str(pdf_file))
                else:
                    from ..extractors.pdf_extractor import PDFExtractor
                    pdf_ext = PDFExtractor()
                    doc_text = pdf_ext.extract_text(str(pdf_file))

                if not doc_text or len(doc_text.strip()) < 100:
                    continue

                chunks = chunk_fn(doc_text)
                chunk = chunks[0] if chunks else ""
                
                result = extractor_sig(document_text=chunk)
                raw = result.requirements_json
                if '```' in raw:
                    raw = raw.split('```')[1]
                    if raw.startswith('json'):
                        raw = raw[4:]
                candidates = json.loads(raw.strip())

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
                continue

    return extra_examples

def _read_gt_file(gt_path: Path) -> List[Dict]:
    """Read requirements from a ground truth file (JSON or Excel)."""
    if not gt_path.exists():
        return []
    
    try:
        if gt_path.suffix.lower() == '.json':
            with open(gt_path, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return data.get('requirements', [])
        
        elif gt_path.suffix.lower() in ['.xlsx', '.xls']:
            import pandas as pd
            df = pd.read_excel(gt_path)
            requirements = []
            for _, row in df.iterrows():
                requirements.append({
                    'title': str(row.get('Title', row.get('feature_name', 'Requirement'))),
                    'description': str(row.get('Description', row.get('description', ''))),
                    'type': str(row.get('Type', row.get('category', 'Functional')))
                })
            return requirements
    except Exception as e:
        print(f"    ⚠ Error reading GT file {gt_path.name}: {e}")
    
    return []

def _generate_training_from_ground_truth(gt_dir: str) -> List[Dict]:
    """Scan GT directory for requirements to use as positive training examples."""
    gt_examples = []
    gt_path = Path(gt_dir)
    if not gt_path.exists():
        return []

    gt_files = list(gt_path.glob('*.json')) + list(gt_path.glob('*.xlsx'))
    
    for gf in gt_files:
        items = _read_gt_file(gf)
        for item in items:
            title = item.get('title', item.get('feature_name', ''))
            desc = item.get('description', '')
            if title and desc:
                gt_examples.append({
                    'text': f"{title} - {desc}",
                    'title': title,
                    'description': desc,
                    'is_requirement': True,
                    'is_gt': True
                })
    
    return gt_examples

def train_extractor(extractor, config: Dict = None):
    """
    Train the requirement classifier using BootstrapFewShot.

    Uses PATTERN-BASED examples (domain-agnostic) organized by extraction layer:
    - Business Features (high-level capabilities)
    - UI Components (screens, layouts, interactions)
    - Workflows (step-by-step processes)
    - Technical (architecture, data models, SLAs)

    Builds training set from:
    1. Pattern-based positive/negative examples
    2. Multi-project training data (from other projects' PDFs)

    Args:
        extractor: TrainedExtractor instance to train
        config: Multi-project config dictionary

    Returns:
        Trained extractor with optimized classifier
    """
    print("\nTraining extractor with PATTERN-BASED examples...")

    train_examples = []

    # 1. Pattern-based positive examples (all layers, domain-agnostic)
    for ex in POSITIVE_EXAMPLES:
        layer = ex.get('layer', 'unknown')
        pattern = ex.get('pattern', 'generic')
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='yes',
                reason=f"Valid {pattern} pattern ({layer} layer)"
            ).with_inputs('text', 'title', 'description')
        )

    # 2. Negative examples (vague, service items, technical noise)
    for ex in NEGATIVE_EXAMPLES:
        reason = ex.get('reason', 'Not a specific software requirement')
        train_examples.append(
            dspy.Example(
                text=ex['text'],
                title=ex['title'],
                description=ex['description'],
                is_requirement='no',
                reason=reason
            ).with_inputs('text', 'title', 'description')
        )

    # 3. Ground Truth examples (Project-specific positives)
    if config:
        gt_dir = config.get('gt_dir') or config.get('br_gt_dir')
        if gt_dir:
            print(f"  Generating training data from Ground Truth: {gt_dir}")
            gt_examples = _generate_training_from_ground_truth(gt_dir)
            if gt_examples:
                print(f"  Got {len(gt_examples)} project-specific GT examples")
                for ex in gt_examples:
                    train_examples.append(
                        dspy.Example(
                            text=ex['text'],
                            title=ex['title'],
                            description=ex['description'],
                            is_requirement='yes',
                            reason="Ground Truth requirement"
                        ).with_inputs('text', 'title', 'description')
                    )

    # 4. Multi-project examples (from other projects' PDFs)
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
