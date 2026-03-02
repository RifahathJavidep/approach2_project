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
    """Extract BUSINESS FEATURES, capabilities, and configuration requirements.

    Focus on user-facing capabilities, configuration changes, and quality requirements.

    INCLUDE:
    - Core business capabilities (Lead Management, Deal Pipeline, Order Processing)
    - Feature areas (Analytics, Reporting, Communication)
    - Integration capabilities (Email Integration, Payment Processing)
    - Configuration/naming changes (rename offerings, update display names, change labels)
    - Defect prevention / regression requirements (prevent specific bug recurrence)
    - Version-specific actions (e.g., Bell version vs Datavalet version of same feature)

    EXCLUDE:
    - Specific UI layouts (extract those separately)
    - Detailed workflow steps (extract those separately)
    - Technical implementation (APIs, databases, architecture)

    ANTI-ABSTRACTION RULES (CRITICAL):
    1. PRESERVE all domain-specific terms, identifiers, and system names EXACTLY as written
       - If document says "mx_DATAVALET", use "mx_DATAVALET" — do NOT generalize to "legacy systems"
       - If document says "MCDO-03", include "MCDO-03" — do NOT drop identifiers
       - If document says "SADRSTRANG-13583", include the exact defect ID
    2. Use EXACT terminology from the document. Do NOT paraphrase or generalize.
       - WRONG: "Offering Reorganization" (too abstract)
       - RIGHT: "Meraki Wi-Fi Taxonomy Reorganization under Managed Services path" (preserves specifics)
    3. If a section describes MULTIPLE DISTINCT items (e.g., 3.1, 3.2, 4.1, 4.2),
       extract EACH as a SEPARATE requirement — do NOT combine them
    4. "Change display name of DV-047 to 'Ad Hoc report'" IS a valid requirement — extract it
    5. "Prevent regression of defect SADRSTRANG-13583" IS a valid requirement — extract it

    GRANULARITY RULES:
    6. Each NUMBERED SUBSECTION with a DISTINCT BUSINESS PURPOSE is its OWN requirement
       - If section says "1. Meraki Wi-Fi Taxonomy" and "2. MIS Battery Taxonomy",
         extract TWO separate requirements — they serve different business purposes
       - DO NOT extract every bullet inside a section as its own requirement
         (e.g., sub-steps of Card Controls like "freeze", "spending limit", "location lock"
          all belong to ONE "Card Controls" requirement, not three separate ones)
    7. Each DEFECT ID is its own defect prevention requirement
       - If document lists SADRSTRANG-13583, SADRSTRANG-13420, SADEFENDER-373,
         extract EACH as a separate "Prevent regression of [ID]" requirement
    8. Each VERSION-SPECIFIC ACTION is its own requirement
       - "Datavalet Version (MCDO-03)" and "Bell Version (MCDO-01)" are TWO requirements
       - "Datavalet Create Profile (MCDO-04)" and "Bell Create Profile" are TWO requirements
    9. TAXONOMY PATH definitions ARE valid requirements
       - "Path: Managed Services -> MIS -> Power supplies" IS a requirement to organize items
    10. CATALOG INCLUSION/EXCLUSION rules ARE valid requirements
       - "Add offerings from Managed WAN to MCD catalog, exclude MERAKI_113" IS a requirement

    RULES:
    - Title should be descriptive (3-8 words) and include domain identifiers where applicable
    - Description must preserve specific details from the document
    - Focus on WHAT users can do, not HOW it works
    - Extract at the RIGHT level of granularity: one requirement per DISTINCT FEATURE AREA,
      not one requirement per bullet point inside a feature
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
    """Extract SPECIFIC USER INTERFACE requirements — screens, pages, and forms.

    Focus on NAMED PAGES and FORMS, not isolated controls.

    INCLUDE:
    - Named screens/pages (Sales Dashboard, CI Selection Page, Technical Details Form)
    - Forms with their fields and validation rules
    - Selection pages with filtering criteria (e.g., "show only Datavalet-managed CIs")
    - Pages with specific data display requirements

    EXCLUDE:
    - Isolated UI micro-controls (a single dropdown, checkbox, or button without page context)
    - Generic screen names without specific content requirements

    ANTI-ABSTRACTION RULES (CRITICAL):
    1. PRESERVE all domain-specific terms EXACTLY as written in the document
    2. Use EXACT screen/page names from the document — do NOT invent generic names
       - WRONG: "Catalog Screen" (too generic)
       - RIGHT: "CI Selection Page with Datavalet/Bell device filtering" (preserves specifics)
    3. Include filtering rules, visibility conditions, and form field requirements in description
    4. If a page has specific filtering logic (e.g., "show only if managed by DATAVALET"),
       include that logic in the description

    RULES:
    - Title must name the specific screen, page, or form from the document
    - Description must include what the page displays, its fields, and filtering logic
    - Type is always 'UI'
    - Only extract pages/screens that are explicitly described in the document
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
    - Multi-step business processes (Lead Conversion, Order Fulfillment, MACD Flow)
    - Decision trees and conditional logic (if approved → next, if rejected → notify)
    - State machines and transitions (Draft → Pending → Approved → Completed)
    - Trigger conditions (When lead score > 80, auto-assign to sales rep)
    - Integration sync workflows (System A creates ticket → System B syncs status back)

    EXCLUDE:
    - Single-step actions that are NOT workflows (just a button click or form submit)
    - Rewriting a functional requirement as a workflow (e.g., "Catalog Consolidation Workflow"
      when the document describes consolidation as a feature, not a step-by-step process)

    ANTI-ABSTRACTION RULES (CRITICAL):
    1. PRESERVE all domain-specific terms EXACTLY as written in the document
    2. Only extract workflows that are EXPLICITLY described with steps in the document
       - Do NOT turn a functional requirement into a workflow by adding generic steps
    3. Include specific system names and identifiers in workflow steps
       - RIGHT: "SR Creation in BBSSC → Maximo Ticket → Payload to Datavalet ServiceNow"
       - WRONG: "Request Creation → Ticket Generation → External System Sync"

    RULES:
    - Title must include "Workflow" or "Process" and describe what it accomplishes
    - Description must list numbered steps or show flow with arrows (→)
    - Type is 'Workflow'
    - Only extract workflows that have actual process steps described in the document
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
    - Data models and field mappings (entity relationships, field-to-field mappings between systems)
    - Integration architecture (REST API sync between specific systems, webhook definitions)
    - Performance SLAs (page load < 3s, search < 300ms, 99.95% uptime)
    - Visibility/filtering rules (CI visibility matrix, role-based access controls)
    - Security patterns (encryption, authentication, row-level security)
    - Security patterns (encryption, authentication, row-level security)

    EXCLUDE:
    - Do NOT invent technologies not mentioned in the document
    - Do NOT add implementation details the document does not specify

    ANTI-ABSTRACTION RULES (CRITICAL):
    1. ONLY extract technical requirements that are EXPLICITLY stated in the document
       - If document says "REST API Synchronization", use those exact words
       - Do NOT invent "Elasticsearch CDC indexing" if the document never mentions Elasticsearch
    2. PRESERVE exact system names, field names, and identifiers
       - RIGHT: "Maximo to Datavalet ServiceNow REST API sync with Custom Reference # field mapping"
       - WRONG: "System integration with external ticketing" (too generic)
    3. Include specific metrics ONLY if the document provides them
       - If document says "load in under 3 seconds", use that exact metric
       - Do NOT invent metrics like "< 200ms" if not in the document

    RULES:
    - Title must name the technical component or pattern from the document
    - Description must use specific terms from the document
    - Type is 'Architecture', 'Data Model', 'Non-Functional', or 'Security'
    - Only include metrics that are EXPLICITLY stated in the document
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


class FunctionalDetailExtraction(dspy.Signature):
    """Extract FUNCTIONAL DETAILS, including UI components and Workflows/Processes.

    Focus on HOW the system looks (Screens/UI) and HOW it behaves (Workflows/Steps).

    INCLUDE:
    - Named screens, pages, and forms (e.g., "Home Dashboard", "Order Entry Screen")
    - Multi-step business processes and workflows (e.g., "Lead Conversion Process", "Payment Flow")
    - Decision points and conditional logic within a process
    - Form fields, validation rules, and interactive components

    EXCLUDE:
    - High-level business capabilities (which are extracted separately)
    - Back-end technical architecture, databases, or non-functional SLAs

    ANTI-ABSTRACTION RULES:
    1. Use EXACT names for screens and processes from the document.
    2. List numbered steps for workflows explicitly in the description.
    3. Include filtering logic or page content details for UI screens.

    RULES:
    - Title should be specific to the UI screen or Workflow (3-7 words)
    - Description should be granular and detailed
    - Type should be 'UI' for screens or 'Workflow' for processes
    """
    document_text = dspy.InputField()
    requirements_json = dspy.OutputField(desc="""JSON array of functional detail requirements:
    [{
      'title': '...',
      'description': '...',
      'type': 'UI'|'Workflow',
      'user_story': 'As a [role], I want [action], so that [benefit]',
      'acceptance_criteria': ['criterion 1'],
      'test_steps': [{'step_num': 1, 'action': '...', 'expected_result': '...'}],
      'test_scenarios': ['scenario 1'],
      'assumptions': [],
      'ambiguities': [],
      'confidence': 'high'|'medium'
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
    7. It describes a configuration change (rename, reclassify, update display name)
    8. It describes defect prevention or regression test coverage requirements
    9. It defines visibility/filtering rules (what users can see under what conditions)

    Answer 'no' if it is:
    - Document noise (executive summary, project objectives, scope statements)
    - A project management item (go-live checklist, verification checklist, sign-off)
    - Vague/generic with no specifics (e.g., 'ensure security', 'optimize performance')
    - An isolated UI micro-detail without page context (just a tooltip or color)

    CRITICAL: Prioritize business features (the 'What') over technical implementation (the 'How').
    Configuration changes, naming changes, and defect prevention ARE valid requirements.
    """
    text = dspy.InputField()
    title = dspy.InputField()
    description = dspy.InputField()
    is_requirement = dspy.OutputField(desc="'yes' if this is a specific, actionable requirement of any type, 'no' if document noise or vague")
    reason = dspy.OutputField(desc="Brief explanation of why this is or isn't a valid requirement")


class RequirementConsolidation(dspy.Signature):
    """Consolidate a list of requirements by merging duplicates and sub-features into parent features.

    GOAL: Merge items that describe the SAME feature in different words, and merge sub-features
    into their parent feature. Aim to produce approximately the TARGET COUNT of items.

    RULES:
    1. DO NOT INVENT new requirements. Only output items that exist in the input list.
    2. INFRASTRUCTURE AGGREGATION (always merge these into single items):
       - Merge ALL security/encryption/audit/compliance items → ONE: "Security and Compliance Infrastructure"
       - Merge ALL uptime/latency/throughput/performance items → ONE: "System Performance and Scalability"
    3. SUB-FEATURE MERGING — merge items that are parts of the SAME parent feature:
       - "Wave Picking Optimization" + "Put-Away Rules" + "Pick-Pack-Ship" → ONE: "Warehouse Operations"
       - "FedEx API" + "UPS API" + "DHL API" + "Carrier Webhook" → ONE: "Carrier API Integration"
       - "Packing Slip" + "Commercial Invoice" + "Certificate of Origin" → ONE: "Customs Documentation"
       - "Inventory Audit Trail" + "Automated Reorder" + "Real-time Inventory" → ONE: "Inventory Management"
       - "Materialized Views" + "Time-Series Storage" + "Redis Caching" → ONE: "Data Architecture"
       - General rule: if multiple items describe DIFFERENT PARTS of a SINGLE business capability,
         merge them into ONE item that represents the full capability.
    4. PRESERVE DISTINCT business capabilities as SEPARATE items:
       - "GPS Tracking" ≠ "Route Optimization" — DIFFERENT capabilities, keep separate
       - "Warehouse Operations" ≠ "Shipment Management" — DIFFERENT domains, keep separate
       - "IoT Sensors" ≠ "Carrier Integration" — DIFFERENT systems, keep separate
       - "Dashboard UI" ≠ "Floor Plan UI" ≠ "Tracking Map UI" — DIFFERENT screens, keep separate
    5. When merging, keep the MOST DESCRIPTIVE title and combine descriptions.
    6. Merge the user_stories, acceptance_criteria, test_steps, and other lists into a single, cohesive, non-redundant set for the parent requirement.
    7. OUTPUT only items that exist in the input. Do NOT invent new features.
    """
    requirements_json = dspy.InputField(desc="JSON array of requirements to consolidate")
    target_count = dspy.InputField(desc="Target number of consolidated requirements to produce (approximate)")
    consolidated_json = dspy.OutputField(desc="""JSON array of consolidated requirements: 
    [{
      'title': '...', 
      'description': '...', 
      'type': '...',
      'user_story': '...',
      'acceptance_criteria': [...],
      'test_steps': [...],
      'test_scenarios': [...],
      'assumptions': [...],
      'ambiguities': [...],
      'confidence': '...'
    }]""")






