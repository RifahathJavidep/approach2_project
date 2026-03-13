"""
Postprocessing Module — Deduplication & Consolidation

Post-processes extracted requirements:
    1. Deduplication — Removes similar/duplicate requirements using Jaccard similarity
    2. Consolidation — Uses LLM to merge overlapping requirements

Moved from: extract_requirements.py lines 496–675
"""

import json
import logging
import re
from typing import List, Dict

logger = logging.getLogger("prism.postprocessing")

import dspy

from .signatures import (
    RequirementConsolidation,
    RequirementDeMerger
)


# ============================================================================
# SIMILARITY FUNCTIONS
# ============================================================================

def _tokenize(text: str) -> set:
    """Tokenize text into words, stripping punctuation and normalizing plurals."""
    tokens = set(re.findall(r'[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?', text.lower()))
    # Simple plural normalization: strip trailing 's' (not 'ss', not short words)
    normalized = set()
    for t in tokens:
        if t.endswith('s') and not t.endswith('ss') and len(t) > 3:
            normalized.add(t[:-1])
        else:
            normalized.add(t)
    return normalized


def calculate_similarity(text1: str, text2: str) -> float:
    """Word overlap similarity (Jaccard) with punctuation handling."""
    words1 = _tokenize(text1)
    words2 = _tokenize(text2)
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

    # One title contains the other (substring)
    if t1 in t2 or t2 in t1:
        return 0.88

    # Word containment: all words of shorter title appear in longer title
    words1 = _tokenize(t1)
    words2 = _tokenize(t2)
    shorter, longer = (words1, words2) if len(words1) <= len(words2) else (words2, words1)
    if shorter and shorter.issubset(longer):
        return 0.85

    # Jaccard on title words
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


# ============================================================================
# DEDUPLICATION
# ============================================================================

def _is_subitem_of(candidate_title: str, existing: Dict) -> bool:
    """
    Check if a candidate requirement is a sub-item already covered by an
    existing requirement's acceptance criteria.

    Example: "DV-047 Display Name Change" is a sub-item of "Offering Name Adjustments"
    because the existing item's acceptance_criteria contains:
    "DV-047 display name is updated to 'Ad Hoc report or dashboard customization'"

    A candidate is considered a sub-item when ≥ 60% of its title tokens appear
    in the existing item's acceptance criteria text.
    """
    ac_list = existing.get('acceptance_criteria', [])
    if not ac_list:
        return False

    ac_text = ' '.join(str(ac) for ac in ac_list)
    ac_tokens = _tokenize(ac_text)
    title_tokens = _tokenize(candidate_title)

    if not title_tokens:
        return False

    found = sum(1 for w in title_tokens if w in ac_tokens)
    coverage = found / len(title_tokens)
    return coverage >= 0.60


def deduplicate_requirements(reqs: List[Dict], similarity_threshold: float = 0.55) -> List[Dict]:
    """Remove duplicate requirements using multi-strategy similarity.
    Compares titles separately (tighter match) and full text (looser match).
    Also detects sub-items: candidates whose title tokens are substantially
    covered by an existing item's acceptance criteria.
    """
    unique = []
    for req in reqs:
        is_dup = False
        req_title = req.get('title', '')
        req_desc = req.get('description', '')
        req_type = req.get('type', 'Functional')
        req_full = f"{req_title} {req_desc}".lower()

        for existing in unique:
            ex_title = existing.get('title', '')
            ex_desc = existing.get('description', '')
            ex_type = existing.get('type', 'Functional')
            ex_full = f"{ex_title} {ex_desc}".lower()

            # NEVER merge across types (preserve granularity layers)
            # Functional ≠ UI ≠ Workflow ≠ Architecture ≠ Data Model
            if req_type != ex_type:
                continue

            # Strategy 1: Title-to-title (catches cross-file duplicates)
            title_sim = _title_similarity(req_title, ex_title)
            # Strategy 2: Full text comparison
            full_sim = calculate_similarity(req_full, ex_full)
            # Strategy 3: Sub-item check — is this candidate a sub-item of existing?
            sub_item = _is_subitem_of(req_title, existing)
            # Use the best score
            best_sim = max(title_sim, full_sim)

            if best_sim > similarity_threshold or sub_item:
                is_dup = True
                # For similarity matches: keep the one with the longer description
                # For sub-item matches: always keep the parent (existing), discard candidate
                if not sub_item and len(req_desc) > len(ex_desc):
                    unique.remove(existing)
                    unique.append(req)
                break

        if not is_dup:
            unique.append(req)

    return unique


def deduplicate_multi_layer_requirements(reqs: List[Dict]) -> List[Dict]:
    """
    Deduplicate while preserving layer distinctions.

    NEW FUNCTION: Layer-aware deduplication that ensures we NEVER merge across types.

    Rules:
    1. Merge EXACT duplicates (same title, same type)
    2. Merge near-duplicates WITHIN the same type
    3. NEVER merge across types (Functional ≠ UI ≠ Workflow ≠ Technical)

    This prevents over-consolidation like:
    - "Lead Management" (Functional) + "Lead List UI" (UI) → "Comprehensive Lead System"
    """
    # Group by type first
    by_type = {}
    for req in reqs:
        req_type = req.get('type', 'Functional')
        if req_type not in by_type:
            by_type[req_type] = []
        by_type[req_type].append(req)

    # Deduplicate within each type
    unique = []
    for req_type, type_reqs in by_type.items():
        logger.info("Deduplicating %s: %d items", req_type, len(type_reqs))
        deduped = deduplicate_requirements(type_reqs, similarity_threshold=0.65)
        logger.info("  %s: %d → %d unique", req_type, len(type_reqs), len(deduped))
        unique.extend(deduped)

    return unique


_SYSTEM_NAMES = frozenset({
    'maximo', 'servicenow', 'datavalet', 'bbssc', 'meraki', 'macd',
    'mcdo', 'mcd', 'nsmis', 'parbac', 'sadrstrang', 'sadefender',
    'omnitotoro'
})


def deduplicate_cross_layer(reqs: List[Dict], title_threshold: float = 0.40, desc_threshold: float = 0.40) -> List[Dict]:
    """
    Remove cross-layer duplicates where the SAME concept appears
    in multiple types (Functional + Workflow + Data Model, etc.)

    Uses MULTIPLE strategies to catch duplicates:
    1. Title similarity (Jaccard with plural normalization)
    2. Description similarity
    3. Cross-check title-to-description
    4. Shared system names (Maximo, ServiceNow, etc.)

    Keeps the version with the LONGEST/most detailed description.
    """
    unique = []
    removed_count = 0

    for req in reqs:
        is_cross_dup = False
        req_title = req.get('title', '')
        req_desc = req.get('description', '')
        req_type = req.get('type', 'Functional')
        req_full = f"{req_title} {req_desc}"

        for i, existing in enumerate(unique):
            ex_title = existing.get('title', '')
            ex_desc = existing.get('description', '')
            ex_type = existing.get('type', 'Functional')
            ex_full = f"{ex_title} {ex_desc}"

            # Skip if same type (already handled by within-type dedup)
            if req_type == ex_type:
                continue

            # Strategy 1: Title similarity
            title_sim = _title_similarity(req_title, ex_title)

            # Strategy 2: Description similarity (catches different titles, same concept)
            desc_sim = calculate_similarity(req_desc, ex_desc)

            # Strategy 3: Cross-check title-to-description
            title_in_desc = calculate_similarity(req_title.lower(), ex_desc.lower())
            desc_in_title = calculate_similarity(req_desc.lower(), ex_title.lower())

            # Strategy 4: Shared system names (strong signal for same domain concept)
            req_systems = _tokenize(req_full) & _SYSTEM_NAMES
            ex_systems = _tokenize(ex_full) & _SYSTEM_NAMES
            shared_systems = len(req_systems & ex_systems)

            # Match conditions (any of these indicates a duplicate):
            is_dup = (title_sim >= title_threshold or
                      desc_sim >= desc_threshold or
                      title_in_desc >= 0.45 or
                      desc_in_title >= 0.45 or
                      shared_systems >= 3 or  # 3+ shared system names = strong signal
                      (shared_systems >= 2 and title_sim >= 0.20))  # 2+ systems + title overlap

            if is_dup:
                is_cross_dup = True
                removed_count += 1
                # Keep the more detailed version
                if len(req_desc) > len(ex_desc):
                    unique[i] = req
                break

        if not is_cross_dup:
            unique.append(req)

    if removed_count > 0:
        logger.info("Cross-layer dedup: removed %d duplicates", removed_count)

    return unique


def _extract_domain_terms(text: str) -> set:
    """Extract domain-specific terms (capitalized words, IDs, system names)."""
    import re
    terms = set()
    # Capitalized multi-word terms (e.g., "Service Now", "Managed Services")
    for match in re.finditer(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', text):
        term = match.group().lower()
        if len(term) > 3:
            terms.add(term)
    # Technical identifiers (e.g., MCDO-03, mx_DATAVALET, SADRSTRANG-13583)
    for match in re.finditer(r'[A-Z_][A-Z0-9_-]{2,}', text):
        terms.add(match.group().lower())
    # Key system names and domain concepts
    text_lower = text.lower()
    domain_keywords = [
        'maximo', 'servicenow', 'datavalet', 'meraki', 'bbssc', 'mcdo',
        'catalog', 'offering', 'taxonomy', 'template', 'profile',
        'ci selection', 'ci filtering', 'ci visibility',
        'service request', 'external ticket', 'job plan',
        'bell', 'mcd', 'nsmis', 'parbac'
    ]
    for kw in domain_keywords:
        if kw in text_lower:
            terms.add(kw)
    return terms


def deduplicate_by_topic(reqs: list, min_shared_terms: int = 3) -> list:
    """
    Remove requirements that share too many domain-specific terms,
    indicating they cover the same topic from different angles.

    E.g., "System Mapping and Data Integration" and "SR Creation and Sync Workflow"
    both mention Maximo, ServiceNow, Datavalet, sync → same topic → keep best one.
    """
    unique = []
    removed_count = 0

    for req in reqs:
        req_text = f"{req.get('title', '')} {req.get('description', '')}"
        req_terms = _extract_domain_terms(req_text)
        is_topic_dup = False

        for i, existing in enumerate(unique):
            ex_text = f"{existing.get('title', '')} {existing.get('description', '')}"
            ex_terms = _extract_domain_terms(ex_text)

            # Count shared domain terms
            shared = req_terms & ex_terms
            if len(shared) >= min_shared_terms:
                is_topic_dup = True
                removed_count += 1
                # Keep the more detailed version
                if len(req.get('description', '')) > len(existing.get('description', '')):
                    unique[i] = req
                break

        if not is_topic_dup:
            unique.append(req)

    if removed_count > 0:
        logger.info("Topic-based dedup: removed %d topic duplicates", removed_count)

    return unique


# ============================================================================
# LLM-BASED CONSOLIDATION
# ============================================================================

def _clean_llm_json(raw: str) -> str:
    """Clean LLM JSON output by removing markdown wrappers."""
    clean = raw.strip()
    if '```' in clean:
        clean = clean.split('```')[1]
        if clean.startswith('json'):
            clean = clean[4:]
    return clean.strip()


def _parse_json_safe(raw: str, fallback: List[Dict] = None) -> List[Dict]:
    """Safely parse JSON from LLM output with fallback strategies."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try regex extraction
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return fallback or []


def _run_consolidation_pass(reqs: List[Dict], consolidator, target_count: int) -> List[Dict]:
    """Run a single pass of LLM-based consolidation.

    Pre-sorts items by type so related items are batched together,
    then runs LLM consolidation on each batch.
    """
    MAX_BATCH = 30

    # Sort by type so related items (all Functionals, all Workflows, etc.)
    # end up in the same batch — this helps the LLM see sub-features together
    sorted_reqs = sorted(reqs, key=lambda r: r.get('type', 'Functional'))

    if len(sorted_reqs) <= MAX_BATCH:
        batch_target = str(target_count)
        try:
            result = consolidator(requirements_json=json.dumps(sorted_reqs), target_count=batch_target)
            raw = _clean_llm_json(result.consolidated_json)
            consolidated = _parse_json_safe(raw, fallback=sorted_reqs)
            return consolidated
        except Exception as e:
            logger.error("Consolidation ERROR: %s — keeping original", e, exc_info=True)
            return sorted_reqs
    else:
        batches = [sorted_reqs[i:i + MAX_BATCH] for i in range(0, len(sorted_reqs), MAX_BATCH)]
        intermediate = []

        for i, batch in enumerate(batches, 1):
            types_in_batch = set(r.get('type', '?') for r in batch)
            # Calculate per-batch target proportionally
            batch_target = max(3, int(target_count * len(batch) / len(sorted_reqs)))
            logger.info("Batch %d/%d (%d items → target ~%d, types: %s)...", i, len(batches), len(batch), batch_target, ', '.join(types_in_batch))
            try:
                result = consolidator(requirements_json=json.dumps(batch), target_count=str(batch_target))
                raw = _clean_llm_json(result.consolidated_json)
                batch_consolidated = _parse_json_safe(raw, fallback=batch)
                intermediate.extend(batch_consolidated)
                logger.info("  → %d items", len(batch_consolidated))
            except Exception as e:
                logger.error("  Batch ERROR: %s — using dedup fallback", e, exc_info=True)
                batch_dedup = deduplicate_requirements(batch, similarity_threshold=0.7)
                intermediate.extend(batch_dedup)

        return intermediate


def consolidate_requirements(reqs: List[Dict]) -> List[Dict]:
    """Use iterative LLM consolidation to merge sub-features into parent features.

    Runs multiple rounds, stopping when the count reaches a reasonable range (≤25)
    or when reductions stall (<15% per round).

    Key improvements over single-pass:
    1. Items pre-sorted by type so related items land in same batch
    2. Multiple rounds catch cross-batch duplicates missed in round 1
    3. Dedup after each round catches near-duplicates created by LLM phrasing
    """
    if len(reqs) <= 25:
        logger.info("Consolidation: %d items — within target range, skipping", len(reqs))
        return reqs

    consolidator = dspy.ChainOfThought(RequirementConsolidation)
    current = reqs

    for round_num in range(1, 4):  # Max 3 rounds
        prev_count = len(current)
        # Calculate target: aim for 60% of current count each round
        target = max(15, int(prev_count * 0.6))
        logger.info("Consolidation round %d: %d items → target ~%d...", round_num, prev_count, target)

        # Run LLM consolidation pass
        current = _run_consolidation_pass(current, consolidator, target_count=target)

        # Dedup after each round to catch near-duplicates from LLM rephrasing
        current = deduplicate_requirements(current, similarity_threshold=0.45)

        reduction = (prev_count - len(current)) / prev_count if prev_count > 0 else 0
        logger.info("Round %d result: %d → %d (%.0f%% reduction)", round_num, prev_count, len(current), reduction * 100)

        # Stop if we reached target range or reduction stalled
        if len(current) <= 25:
            logger.info("✓ Reached target range (≤25)")
            break
        if reduction < 0.15:
            logger.info("⚠ Reduction stalled (<15%%), stopping consolidation")
            break

    return current


def merge_semantic_siblings(reqs: List[Dict], threshold: float = 0.40) -> List[Dict]:
    """Post-consolidation step: merge remaining sub-features that describe
    aspects of the SAME parent concept.

    This catches items like:
    - "Packing Slip Generation" + "Certificate of Origin" → keep the more descriptive one
    - "Temperature Sensors" + "GPS Trackers" → keep the more descriptive one
    - "Shipment Service UI" + "Shipment Creation Screen" → keep the more descriptive one

    Uses a lower similarity threshold than regular dedup because these items
    have different titles but overlapping descriptions.
    """
    unique = []
    merged_count = 0

    for req in reqs:
        is_sibling = False
        req_title = req.get('title', '')
        req_desc = req.get('description', '')
        req_full = f"{req_title} {req_desc}"

        for i, existing in enumerate(unique):
            ex_title = existing.get('title', '')
            ex_desc = existing.get('description', '')
            ex_full = f"{ex_title} {ex_desc}"

            # Check multiple signals for semantic sibling relationship:
            # 1. Full-text overlap (title+desc combined)
            full_sim = calculate_similarity(req_full, ex_full)

            # 2. Description-to-description overlap
            desc_sim = calculate_similarity(req_desc, ex_desc)

            # 3. Title-to-title overlap
            title_sim = _title_similarity(req_title, ex_title)

            # Items are siblings if they share significant overlap
            # (lower than regular dedup — catches items with different titles
            #  but overlapping domain content)
            if full_sim >= threshold or desc_sim >= 0.45 or title_sim >= 0.55:
                is_sibling = True
                merged_count += 1
                # Keep the version with the longer (more detailed) description
                if len(req_desc) > len(ex_desc):
                    unique[i] = req
                break

        if not is_sibling:
            unique.append(req)

    if merged_count > 0:
        logger.info("Semantic sibling merge: %d → %d (%d merged)", len(reqs), len(unique), merged_count)

    return unique


def split_composite_requirements(reqs: List[Dict]) -> List[Dict]:
    """Identify and split requirements that cover multiple distinct features (e.g., 'A and B')."""
    de_merger = dspy.ChainOfThought(RequirementDeMerger)
    
    final = []
    logger.info("De-merging composite requirements...")
    for req in reqs:
        title = req.get('title', '')
        # Detect composites: "and", "&", "/", multiple CAPITALIZED domain terms
        is_composite = (
            ' and ' in title.lower() or 
            ' & ' in title or 
            ' / ' in title or
            (',' in title and len(title.split(',')) > 2)
        )
        
        if is_composite:
            try:
                result = de_merger(
                    composite_requirement_title=title, 
                    composite_requirement_desc=req.get('description', '')
                )
                raw = _clean_llm_json(result.requirements_json)
                split_data = _parse_json_safe(raw)
                
                if isinstance(split_data, list) and len(split_data) > 1:
                    logger.info("Split '%s' → %d items", title, len(split_data))
                    for s in split_data:
                        new_req = req.copy()
                        new_req['title'] = s.get('title', title)
                        new_req['description'] = s.get('description', req.get('description', ''))
                        final.append(new_req)
                    continue
            except Exception as e:
                logger.error("Error de-merging '%s': %s", title, e)
                
        final.append(req)
    
    if len(final) != len(reqs):
        logger.info("De-merger: %d → %d requirements", len(reqs), len(final))
    return final

