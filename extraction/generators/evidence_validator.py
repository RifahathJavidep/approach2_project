"""
Evidence Validator — Anti-Hallucination Gate for Precision Extraction

Validates that each precision-extracted requirement has:
1. A non-empty source_quote (verbatim text from the document)
2. A source_quote that actually appears in the document (fuzzy match)
3. Key terms from the requirement title present in the source_quote
4. Confidence is not "low"

Any requirement failing these checks is rejected as a hallucination or
unsupported extraction.

Used by: extraction/pipeline.py (precision_mode=True)
Called after: PrecisionRequirementExtractorModule
"""

import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Stop words — excluded from key-term coverage checks
# ─────────────────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'for', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'from',
    'with', 'by', 'of', 'that', 'this', 'it', 'as', 'if', 'so',
    'must', 'should', 'can', 'will', 'all', 'each', 'every',
    'any', 'no', 'not', 'only', 'also', 'both', 'than', 'more',
    'most', 'other', 'into', 'their', 'its', 'has', 'have',
    'system', 'user', 'users', 'provide', 'support', 'allow', 'enable',
    'using', 'ensure', 'including', 'specific', 'based', 'which',
    'when', 'where', 'how', 'new', 'existing', 'current', 'following',
    'required', 'need', 'shall', 'may', 'type', 'requirement',
})


def _extract_key_terms(text: str) -> List[str]:
    """Extract meaningful terms from text, skipping stop words."""
    words = re.findall(r'[A-Za-z][A-Za-z0-9_-]*', text)
    return [w for w in words if len(w) > 2 and w.lower() not in _STOPWORDS]


def _quote_in_document(quote: str, document: str, min_ratio: float = 0.65) -> bool:
    """
    Check if the quote appears in the document using fuzzy matching.

    Strategy:
    1. Exact substring check (fast path)
    2. Sliding window fuzzy match over the document

    Args:
        quote: The source_quote to look for
        document: The full document text
        min_ratio: Minimum SequenceMatcher ratio to count as a match (0-1)

    Returns:
        True if the quote appears (exactly or approximately) in the document
    """
    if not quote or len(quote.strip()) < 15:
        return False

    doc_lower = document.lower()
    quote_lower = quote.lower().strip()

    # Fast path: exact substring match
    if quote_lower in doc_lower:
        return True

    # Fuzzy sliding window — avoid checking the entire document at once
    q_len = len(quote_lower)
    if q_len > len(doc_lower):
        return False

    # Only check a reasonable number of windows to keep it fast
    step = max(10, q_len // 5)
    for start in range(0, len(doc_lower) - q_len + 1, step):
        window = doc_lower[start : start + q_len]
        ratio = SequenceMatcher(None, quote_lower, window).ratio()
        if ratio >= min_ratio:
            return True

    return False


def validate_evidence(
    requirement: Dict,
    document_text: str,
    min_term_coverage: float = 0.35,
) -> Tuple[bool, str]:
    """
    Validate that a single requirement has proper source evidence.

    Checks (in order):
    1. Confidence must not be "low"
    2. source_quote must be present and ≥ 15 characters
    3. source_quote must appear (fuzzy) in the document
    4. At least `min_term_coverage` of title key terms must be in source_quote

    Args:
        requirement: A single requirement dict with at least 'title', 'source_quote', 'confidence'
        document_text: The full source document text
        min_term_coverage: Fraction of title key terms that must appear in source_quote

    Returns:
        (is_valid: bool, reason: str)
    """
    confidence = requirement.get("confidence", "medium").lower()
    source_quote = requirement.get("source_quote", "").strip()
    title = requirement.get("title", "")

    # Check 1: Confidence gate
    if confidence == "low":
        return False, "Low confidence — inferred requirement rejected"

    # Check 2: source_quote must exist and be meaningful
    if not source_quote or len(source_quote) < 15:
        return False, "No source_quote provided (or too short)"

    # Check 3: Quote must appear in document
    if not _quote_in_document(source_quote, document_text):
        preview = source_quote[:60] + ("..." if len(source_quote) > 60 else "")
        return False, f"source_quote not found in document: '{preview}'"

    # Check 4: Title key terms must be present in the quote
    title_terms = _extract_key_terms(title)
    if len(title_terms) >= 2:  # Only check if title has meaningful terms
        found = sum(1 for t in title_terms if t.lower() in source_quote.lower())
        coverage = found / len(title_terms)
        if coverage < min_term_coverage:
            return (
                False,
                f"Title terms poorly covered in source_quote ({coverage:.0%} < {min_term_coverage:.0%})",
            )

    return True, "Valid"


def filter_by_evidence(
    requirements: List[Dict],
    document_text: str,
    min_term_coverage: float = 0.35,
    verbose: bool = True,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Filter a list of requirements, keeping only those with valid source evidence.

    Args:
        requirements: List of requirement dicts from PrecisionRequirementExtractorModule
        document_text: The full source document text
        min_term_coverage: Minimum fraction of title terms that must appear in source_quote
        verbose: Print rejected requirements to stdout

    Returns:
        (valid_requirements, rejected_requirements)
        Rejected items have a '_rejection_reason' key added.
    """
    valid = []
    rejected = []

    for req in requirements:
        is_valid, reason = validate_evidence(req, document_text, min_term_coverage)
        if is_valid:
            valid.append(req)
        else:
            annotated = {**req, "_rejection_reason": reason}
            rejected.append(annotated)
            if verbose:
                title_preview = req.get("title", "N/A")[:55]
                print(f"    ✗ Evidence rejected: {title_preview} — {reason}")

    if rejected and verbose:
        print(
            f"    Evidence gate: {len(requirements)} → {len(valid)} valid "
            f"({len(rejected)} rejected)"
        )

    return valid, rejected
