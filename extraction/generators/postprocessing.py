"""
Postprocessing Module — Deduplication & Consolidation

Post-processes extracted requirements:
    1. Deduplication — Removes similar/duplicate requirements using Jaccard similarity
    2. Consolidation — Uses LLM to merge overlapping requirements

Moved from: extract_requirements.py lines 496–675
"""

import json
import re
from typing import List, Dict

import dspy

from .signatures import RequirementConsolidation


# ============================================================================
# SIMILARITY FUNCTIONS
# ============================================================================

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


# ============================================================================
# DEDUPLICATION
# ============================================================================

def deduplicate_requirements(reqs: List[Dict], similarity_threshold: float = 0.55) -> List[Dict]:
    """Remove duplicate requirements using multi-strategy similarity.
    Compares titles separately (tighter match) and full text (looser match).
    """
    unique = []
    for req in reqs:
        is_dup = False
        req_title = req.get('title', '')
        req_desc = req.get('description', '')
        req_type = req.get('type', 'Functional')  # NEW: Get type for layer-aware comparison
        req_full = f"{req_title} {req_desc}".lower()

        for existing in unique:
            ex_title = existing.get('title', '')
            ex_desc = existing.get('description', '')
            ex_type = existing.get('type', 'Functional')  # NEW: Get existing type
            ex_full = f"{ex_title} {ex_desc}".lower()

            # NEW: NEVER merge across types (preserve granularity layers)
            # Functional ≠ UI ≠ Workflow ≠ Architecture ≠ Data Model
            if req_type != ex_type:
                continue  # Skip comparison if different types

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
        print(f"    Deduplicating {req_type}: {len(type_reqs)} items", end='')
        deduped = deduplicate_requirements(type_reqs, similarity_threshold=0.65)
        print(f" → {len(deduped)} unique")
        unique.extend(deduped)

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


def consolidate_requirements(reqs: List[Dict]) -> List[Dict]:
    """Use LLM to merge overlapping requirements into fewer high-level items.

    CHANGED: Only consolidate if >80 items (was 45)
    Reason: Evaluation shows we're over-consolidating (11 vs 24 expected)
    """
    if len(reqs) <= 80:  # CHANGED from 45 to prevent over-consolidation
        print(f"  Consolidation: {len(reqs)} items — no consolidation needed")
        return reqs

    print(f"  Consolidating {len(reqs)} requirements via LLM...")

    consolidator = dspy.ChainOfThought(RequirementConsolidation)

    # If too many items, process in batches to avoid token limits
    MAX_BATCH = 60
    if len(reqs) > MAX_BATCH:
        batches = [reqs[i:i + MAX_BATCH] for i in range(0, len(reqs), MAX_BATCH)]
        intermediate = []

        for i, batch in enumerate(batches, 1):
            print(f"    Batch {i}/{len(batches)} ({len(batch)} items)...")
            try:
                result = consolidator(requirements_json=json.dumps(batch))
                raw = _clean_llm_json(result.consolidated_json)
                batch_consolidated = _parse_json_safe(raw, fallback=batch)
                intermediate.extend(batch_consolidated)
                print(f"      → {len(batch_consolidated)} items")
            except Exception as e:
                print(f"      ERROR: {e} — using local fast-dedup fallback for this batch")
                batch_dedup = deduplicate_requirements(batch, similarity_threshold=0.7)
                intermediate.extend(batch_dedup)

        # Second pass to merge across batches if too many items
        if len(intermediate) > 100:
            print(f"    Final merge pass ({len(intermediate)} items)...")
            try:
                result = consolidator(requirements_json=json.dumps(intermediate))
                raw = _clean_llm_json(result.consolidated_json)
                final = _parse_json_safe(raw)
                if final:
                    print(f"      → {len(final)} items")
                    return final
                else:
                    return deduplicate_requirements(intermediate, similarity_threshold=0.65)
            except Exception as e:
                print(f"      ERROR in final merge: {e} — using local fast-dedup fallback")
                return deduplicate_requirements(intermediate, similarity_threshold=0.6)

        return intermediate
    else:
        # Single batch
        try:
            result = consolidator(requirements_json=json.dumps(reqs))
            raw = _clean_llm_json(result.consolidated_json)
            consolidated = json.loads(raw)
            print(f"  Consolidated: {len(reqs)} → {len(consolidated)} requirements")
            return consolidated
        except Exception as e:
            print(f"  ERROR in consolidation: {e} — keeping original")
            return reqs
