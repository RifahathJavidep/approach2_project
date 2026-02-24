"""
Requirement Validation & Quality Checks
Filters out false positives and enforces specificity.

This module provides post-extraction validation to reject vague, generic,
or non-requirement items (like service descriptions, document metadata, etc.)
"""

import re
from typing import Dict, Tuple

# ============================================================================
# VALIDATION KEYWORDS & PATTERNS
# ============================================================================

VAGUE_MODIFIERS = [
    'advanced', 'comprehensive', 'robust', 'flexible',
    'intuitive', 'powerful', 'modern', 'efficient'
]

SERVICE_KEYWORDS = [
    'training', 'support', 'documentation', 'onboarding',
    'help desk', 'customer support', 'technical support',
    'user training', 'training materials', 'webinar'
]

NFR_WITHOUT_METRICS = [
    'scalability', 'performance', 'availability',
    'reliability', 'maintainability'
]

CHECKLIST_KEYWORDS = [
    'verification checklist', 'final verification', 'test checklist',
    'sign-off', 'go-live checklist', 'deployment checklist',
    'project tracking', 'ryg', 'rag status', 'release checklist'
]

# UI micro-detail patterns (isolated controls without page context)
MICRO_DETAIL_PATTERNS = [
    'dropdown menu', 'radio button', 'tooltip',
    'hover effect', 'badge color', 'icon set', 'spinner',
    'toggle switch', 'scrollbar'
]


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_requirement(req: Dict) -> Tuple[bool, str]:
    """
    Validate a requirement for specificity and quality.

    Returns:
        (is_valid, rejection_reason)
        - is_valid: True if requirement passes validation
        - rejection_reason: String explaining why it was rejected (empty if valid)
    """
    title = req.get('title', '').lower()
    desc = req.get('description', '').lower()
    combined = f"{title} {desc}"

    # Rule 1: Reject service/operational items
    if any(kw in combined for kw in SERVICE_KEYWORDS):
        return False, "Service item, not software feature"

    # Rule 2: Reject NFRs without quantified metrics
    if any(nfr in title for nfr in NFR_WITHOUT_METRICS):
        # Check if description contains metrics (numbers with units)
        if not re.search(r'\d+\s*(%|ms|s|sec|min|MB|GB|TB|req/s|tps|uptime|p\d+)', desc):
            return False, "NFR without measurable metric"

    # Rule 3: Require specificity for vague modifiers
    if any(vague in title for vague in VAGUE_MODIFIERS):
        if not has_specific_details(desc):
            return False, "Too generic - no specific UI/workflow/entity details"

    # Rule 4: Description length check (too short = likely vague)
    if len(desc) < 30:
        return False, "Description too short - likely vague"

    # Rule 5: Title length check (too long = likely composite requirement)
    if len(title) > 100:
        return False, "Title too long - likely a paragraph, not a requirement title"

    # Rule 6: Reject project management checklists
    if any(kw in combined for kw in CHECKLIST_KEYWORDS):
        return False, "Project management checklist, not software requirement"

    # Rule 7: Reject isolated UI micro-details without page context
    if is_micro_detail(req.get('title', ''), req.get('description', '')):
        return False, "Isolated UI micro-detail without page context"

    return True, ""


def has_specific_details(text: str) -> bool:
    """
    Check if requirement contains concrete, specific details.

    Returns True if the text mentions:
    - Specific UI elements (button, form, dashboard)
    - Workflow indicators (step, flow, process)
    - Technical specifics (API, metric, SLA)
    - Business entities (lead, order, patient)
    - Configuration indicators (rename, update, change, modify)
    """
    text_lower = text.lower()

    # UI specifics
    ui_elements = [
        'button', 'form', 'dashboard', 'panel', 'modal', 'table', 'chart',
        'widget', 'tab', 'sidebar', 'header', 'footer', 'dropdown', 'checkbox',
        'radio', 'slider', 'calendar', 'grid', 'card', 'list', 'menu',
        'page', 'screen', 'selection'
    ]

    # Workflow specifics
    workflow_indicators = [
        'step', 'flow', 'process', 'workflow', '→', 'then', 'when', 'if',
        'trigger', 'action', 'sequence', 'path', 'route', 'decision'
    ]

    # Technical specifics
    tech_indicators = [
        'api', 'oauth', 'jwt', 'rest', 'graphql', 'webhook', 'endpoint',
        'ms', '< 1', '99.', 'sla', 'rto', 'rpo', 'p95', 'p99',
        'database', 'schema', 'entity', 'table', 'index',
        'sync', 'integration', 'payload', 'field mapping'
    ]

    # Entity specifics (common domain entities)
    entities = [
        'lead', 'contact', 'deal', 'account', 'opportunity',
        'order', 'product', 'invoice', 'payment', 'transaction',
        'patient', 'appointment', 'prescription', 'diagnosis',
        'inventory', 'shipment', 'warehouse', 'supplier',
        'user', 'customer', 'client', 'tenant', 'organization',
        'offering', 'catalog', 'service', 'ticket', 'request',
        'device', 'configuration', 'template', 'profile'
    ]

    # Configuration/naming change indicators
    config_indicators = [
        'change', 'rename', 'update display', 'modify',
        'display name', 'terminology', 'label',
        'classification', 'taxonomy', 'path', 'category',
        'decommission', 'migrate', 'consolidate',
        'defect', 'regression', 'prevent'
    ]

    # Check if text contains specific details
    return (any(ui in text_lower for ui in ui_elements) or
            any(wf in text_lower for wf in workflow_indicators) or
            any(tech in text_lower for tech in tech_indicators) or
            any(ent in text_lower for ent in entities) or
            any(cfg in text_lower for cfg in config_indicators))


def is_umbrella_requirement(title: str, desc: str) -> bool:
    """
    Check if requirement seems like an umbrella covering multiple sub-requirements.

    Umbrella requirements are too broad and should be decomposed.

    Returns True if:
    - Description lists 3+ items with commas
    - Contains umbrella language ("including", "such as", "various")
    """
    desc_lower = desc.lower()

    # Umbrella indicators
    umbrella_indicators = [
        'including', 'such as', 'various', 'multiple',
        'different types of', 'range of', 'variety of',
        'several', 'numerous', 'comprehensive set of'
    ]

    # Check for umbrella language
    if any(indicator in desc_lower for indicator in umbrella_indicators):
        return True

    # Check for excessive comma-separated lists (3+ items)
    if desc.count(',') >= 3:
        return True

    return False


def is_micro_detail(title: str, desc: str) -> bool:
    """
    Reject isolated UI micro-components that lack parent page/screen context.

    A "Template Dropdown Menu" by itself is a micro-detail.
    A "Technical Details Page with mandatory template dropdown" is a proper requirement.
    """
    title_lower = title.lower()

    # Check if title is JUST a UI control name
    if any(p in title_lower for p in MICRO_DETAIL_PATTERNS):
        # Check if description mentions the parent screen/page/form
        desc_lower = desc.lower()
        has_parent_context = any(w in desc_lower for w in [
            'page', 'screen', 'form', 'section', 'within',
            'part of', 'on the', 'in the', 'located in'
        ])
        if not has_parent_context:
            return True

    return False


def validate_and_enrich(req: Dict) -> Tuple[Dict, bool, str]:
    """
    Validate a requirement and optionally enrich it with warnings.

    Returns:
        (enriched_req, is_valid, rejection_reason)
    """
    is_valid, reason = validate_requirement(req)

    if not is_valid:
        return req, False, reason

    # Check for umbrella requirement (warning, not rejection)
    if is_umbrella_requirement(req.get('title', ''), req.get('description', '')):
        if 'ambiguities' not in req:
            req['ambiguities'] = []
        req['ambiguities'].append("Possible umbrella requirement - may need decomposition")

    return req, True, ""
