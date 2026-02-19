"""
DSPy Signatures — Requirement Extraction & Processing

Defines the 4 core DSPy Signatures used by the extraction pipeline:
    1. RequirementExtraction — Extract requirements from document chunks
    2. RequirementDeMerger — Split composite requirements
    3. RequirementClassifier — Validate candidates as real requirements
    4. RequirementConsolidation — Merge overlapping requirements

These signatures define the AI prompt structure and expected inputs/outputs.
Moved from: extract_requirements.py lines 63–132, 564–574
"""

import dspy


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
