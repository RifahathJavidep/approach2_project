"""
DSPy Signatures — Requirement Extraction & Processing

Defines the 7 core DSPy Signatures used by the extraction pipeline:
    1. BusinessFeatureExtraction — Extract high-level business capabilities
    2. UIRequirementExtraction — Extract UI components and screens
    3. WorkflowRequirementExtraction — Extract step-by-step processes
    4. TechnicalRequirementExtraction — Extract architecture and SLAs
    5. RequirementDeMerger — Split composite requirements
    6. RequirementClassifier — Validate candidates as real requirements
    7. RequirementConsolidation — Merge overlapping requirements

These signatures define the AI prompt structure and expected inputs/outputs.
Moved from: extract_requirements.py lines 63–132, 564–574
"""

import dspy


# ============================================================================
# MULTI-LAYER EXTRACTION SIGNATURES
# ============================================================================

class BusinessFeatureExtraction(dspy.Signature):
    """Extract HIGH-LEVEL BUSINESS FEATURES and capabilities.

    Focus on PRIMARY user-facing capabilities - the WHAT, not the HOW.

    INCLUDE:
    - Core business capabilities (Lead Management, Deal Pipeline, Order Processing)
    - Feature areas (Analytics, Reporting, Communication)
    - Integration capabilities (Email Integration, Payment Processing)

    EXCLUDE:
    - Specific UI layouts (extract those separately)
    - Detailed workflow steps (extract those separately)
    - Technical implementation (APIs, databases, architecture)

    CRITICAL: Extract the business VALUE and capability, not the implementation.
    Example: "Lead Management with scoring and assignment" NOT "Lead database table with indexes"

    RULES:
    - Title should be descriptive (3-8 words)
    - Description must explain the business value
    - Focus on WHAT users can do, not HOW it works
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of business feature requirements:
    [{
      'title': '...',
      'description': '...',
      'type': 'Functional',
      'user_story': 'As a [role], I want [action], so that [benefit]',
      'acceptance_criteria': ['criterion 1', 'criterion 2'],
      'test_steps': [{'step_num': 1, 'action': '...', 'expected_result': '...', 'test_data': '...'}],
      'test_scenarios': ['scenario 1'],
      'assumptions': ['assumption 1'],
      'ambiguities': ['ambiguity 1'],
      'confidence': 'high'|'medium'|'low'
    }]""")


class UIRequirementExtraction(dspy.Signature):
    """Extract SPECIFIC USER INTERFACE requirements.

    Focus on CONCRETE UI elements - screens, components, layouts, and interactions.

    INCLUDE:
    - Named screens/pages (Sales Dashboard, Contact Profile Page, Deal Board)
    - UI components (buttons, forms, tables, charts, modals, tabs, panels)
    - Visual elements (color-coded badges, icons, indicators)
    - Interaction patterns (drag-and-drop, hover effects, click actions)
    - Layouts (3-column grid, sidebar navigation, tabbed sections)

    CRITICAL: Extract the EXACT UI element names and layouts from the document.
    Do NOT generalize "various dashboards" → Extract "Sales Dashboard with KPI widgets in 3-column grid"

    RULES:
    - Title must name the specific screen or component
    - Description must include layout/visual/interaction details
    - Type is always 'UI'
    - Extract even small UI details if they have specific functionality
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of UI requirements:
    [{
      'title': 'Sales Dashboard Screen',
      'description': 'Dashboard with KPI widgets in 3-column grid showing revenue, pipeline, and win rate',
      'type': 'UI',
      'user_story': 'As a sales manager, I want a visual dashboard, so that I can see key metrics at a glance',
      'acceptance_criteria': ['Dashboard loads in < 2s', 'Displays 3 KPI widgets', 'Supports real-time updates'],
      'test_steps': [{'step_num': 1, 'action': 'Navigate to dashboard', 'expected_result': 'Dashboard displays with widgets', 'test_data': 'Valid user'}],
      'test_scenarios': ['View dashboard', 'Refresh metrics'],
      'assumptions': ['User has dashboard access'],
      'ambiguities': [],
      'confidence': 'high'
    }]""")


class WorkflowRequirementExtraction(dspy.Signature):
    """Extract STEP-BY-STEP WORKFLOW and PROCESS requirements.

    Focus on BUSINESS PROCESSES with numbered steps, decision points, and flow paths.

    INCLUDE:
    - Multi-step business processes (Lead Conversion, Order Fulfillment, Approval Workflow)
    - Decision trees and conditional logic (if approved → next, if rejected → notify)
    - State machines and transitions (Draft → Pending → Approved → Completed)
    - Trigger conditions (When lead score > 80, auto-assign to sales rep)
    - Automated actions and sequences (Send email → Wait 3 days → Send follow-up)

    CRITICAL: Capture the EXACT flow steps from the document.
    A "9-step Lead Conversion Workflow" must list all 9 steps with arrows/transitions.

    RULES:
    - Title must include "Workflow" or "Process" and describe what it accomplishes
    - Description must list numbered steps or show flow with arrows (→)
    - Type is 'Workflow'
    - Include decision points (if/else branches) and error paths
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of workflow requirements:
    [{
      'title': '9-Step Lead Conversion Workflow',
      'description': 'Lead Capture → Deduplication → AI Scoring → Territory Assignment → Rep Review → BANT Qualification → Conversion Wizard → Deal Creation → Task Generation. Alternate paths: Nurture (score < 50), Disqualify (no fit)',
      'type': 'Workflow',
      'user_story': 'As a sales ops manager, I want an automated lead conversion process, so that leads move efficiently through qualification',
      'acceptance_criteria': ['All 9 steps execute in sequence', 'Scoring triggers auto-assignment', 'Tasks auto-created on conversion'],
      'test_steps': [{'step_num': 1, 'action': 'Submit new lead', 'expected_result': 'Lead enters workflow', 'test_data': 'Test lead'}],
      'test_scenarios': ['Happy path conversion', 'Nurture path', 'Disqualify path'],
      'assumptions': ['AI scoring model is trained'],
      'ambiguities': ['What happens if rep rejects lead?'],
      'confidence': 'high'
    }]""")


class TechnicalRequirementExtraction(dspy.Signature):
    """Extract TECHNICAL and ARCHITECTURAL requirements.

    Focus on SYSTEM DESIGN, data models, integrations, performance SLAs, and security.

    INCLUDE:
    - Data models (Lead/Contact/Deal entities with foreign keys, schema definitions)
    - Integration architecture (OAuth 2.0 with Gmail API, Salesforce REST API sync)
    - Performance SLAs (Dashboard < 1.5s at p95, Search < 300ms, 99.95% uptime)
    - System architecture (Multi-tenant RLS, Elasticsearch CDC indexing, Redis caching)
    - Security patterns (AES-256 encryption, JWT authentication, row-level security)
    - API specifications (REST endpoints, GraphQL schemas, webhook definitions)

    CRITICAL: Capture SPECIFIC technologies, quantified metrics, and technical patterns.
    "99.95% uptime with RTO < 10min" NOT "high availability"
    "OAuth 2.0 with Gmail API" NOT "email integration"

    RULES:
    - Title must name the technical component or pattern
    - Description must include specific technologies and metrics
    - Type is 'Architecture', 'Data Model', 'Non-Functional', or 'Security'
    - Always include quantified metrics where available (ms, %, MB, req/s)
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of technical requirements:
    [{
      'title': 'CRM Data Model with Multi-Tenant RLS',
      'description': 'Lead, Contact, Company, Deal, and Activity entities with foreign key relationships. PostgreSQL with row-level security (RLS) for multi-tenant isolation. Elasticsearch CDC indexing for real-time search. Activity tables partitioned by month for performance.',
      'type': 'Data Model',
      'user_story': 'As a system architect, I want a scalable data model, so that we can support enterprise customers securely',
      'acceptance_criteria': ['RLS enforced on all tables', 'Search sync < 5s', 'Query time < 200ms for 1M records'],
      'test_steps': [{'step_num': 1, 'action': 'Query cross-tenant data', 'expected_result': 'RLS blocks access', 'test_data': 'Tenant A/B data'}],
      'test_scenarios': ['RLS isolation test', 'Search performance test'],
      'assumptions': ['PostgreSQL 14+', 'Elasticsearch cluster available'],
      'ambiguities': [],
      'confidence': 'high'
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


class RequirementConsolidation(dspy.Signature):
    """Consolidate requirements by merging ONLY truly redundant items.

    CRITICAL RULES:
    1. Merge ONLY if describing the EXACT same feature with EXACT same scope and type
    2. PRESERVE different granularity levels - these are ALL DIFFERENT:
       - "Lead Management" (business feature, type: Functional)
       - "Lead List UI with filters and sorting" (UI component, type: UI)
       - "Lead Conversion Workflow with 9 steps" (process, type: Workflow)
       → DO NOT MERGE THESE - they are distinct layers

    3. PRESERVE technical vs business separation - KEEP BOTH:
       - "Email Integration" (business feature, type: Functional)
       - "OAuth 2.0 Gmail API integration" (technical spec, type: Architecture)

    4. NEVER merge across types:
       - Functional ≠ UI ≠ Workflow ≠ Architecture ≠ Data Model

    5. Target: 70-90% of input count (gentle consolidation, not aggressive reduction)

    Example of CORRECT consolidation:
    IN:
    - "Sales Dashboard with KPI widgets" (type: UI)
    - "Sales Performance Dashboard with metrics display" (type: UI)
    OUT:
    - "Sales Dashboard with KPI widgets and performance metrics" (type: UI)

    Example of INCORRECT consolidation (DO NOT DO THIS):
    IN:
    - "Lead Management" (type: Functional)
    - "Lead List UI" (type: UI)
    - "Lead Scoring Workflow" (type: Workflow)
    OUT:
    - "Comprehensive Lead Management System" ← WRONG! These are distinct layers with different types.

    PRESERVE specificity. DO NOT generalize.
    """
    requirements_json = dspy.InputField(desc="JSON array of requirements to consolidate")
    consolidated_json = dspy.OutputField(desc="JSON array of consolidated requirements: [{'title': '...', 'description': '...', 'type': '...'}]")
