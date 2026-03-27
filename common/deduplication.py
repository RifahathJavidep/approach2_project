"""
Deduplication Utility — TF-IDF cosine similarity for requirement matching.

Checks whether new requirements are semantically similar to existing ones.
Falls back to Jaccard keyword matching if scikit-learn is unavailable.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

from config import settings

logger = logging.getLogger("prism.deduplication")

DEFAULT_THRESHOLD = settings.DEFAULT_DEDUP_THRESHOLD

def find_duplicates(
    team_id: str,
    project_id: str,
    new_requirements: List[Dict],
    threshold: float = DEFAULT_THRESHOLD,
    tenant_id: Optional[str] = None,
) -> Tuple[List[Dict], int]:
    """
    Annotate each requirement with is_duplicate and duplicate_of.
    Fetches existing requirements from the Java backend for comparison.

    Returns:
        (annotated_requirements, duplicate_count)
    """
    from common.java_client import get_requirements

    existing = get_requirements(team_id, project_id, tenant_id)

    if not existing:
        for req in new_requirements:
            req["is_duplicate"] = False
            req["duplicate_of"] = None
        return new_requirements, 0

    duplicate_count: int = 0
    for req in new_requirements:
        match = _best_match(req, existing, threshold)
        if match:
            existing_req, score = match
            duplicate_count += 1
            req["is_duplicate"] = True
            req["duplicate_of"] = {
                "similarity_score": round(score, 2),
                "existing_requirement": _format_existing(existing_req),
            }
            logger.info(
                "Duplicate (%.0f%%): '%s' matches '%s'",
                score * 100,
                req.get("title") or req.get("short_title", ""),
                existing_req.get("short_title") or existing_req.get("title", ""),
            )
        else:
            req["is_duplicate"] = False
            req["duplicate_of"] = None

    logger.info(
        "Dedup result: %d duplicates, %d unique (threshold=%.2f)",
        duplicate_count, len(new_requirements) - duplicate_count, threshold,
    )
    return new_requirements, duplicate_count

def filter_unique(
    team_id: str,
    project_id: str,
    new_requirements: List[Dict],
    threshold: float = DEFAULT_THRESHOLD,
    tenant_id: Optional[str] = None,
) -> List[Dict]:
    """Return only requirements that are NOT duplicates of existing ones."""
    from common.java_client import get_requirements

    existing = get_requirements(team_id, project_id, tenant_id)
    if not existing:
        return new_requirements

    unique = []
    for req in new_requirements:
        match = _best_match(req, existing, threshold)
        if match:
            existing_req, score = match
            logger.info(
                "Removing duplicate (%.0f%%): '%s' matches '%s'",
                score * 100,
                req.get("title") or req.get("short_title", ""),
                existing_req.get("short_title") or existing_req.get("title", ""),
            )
        else:
            unique.append(req)

    return unique

def _best_match(
    req: Dict,
    existing: List[Dict],
    threshold: float,
) -> Optional[Tuple[Dict, float]]:
    """Return (best_match, score) if similarity >= threshold, else None."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        new_text = _to_text(req)
        if not new_text.strip():
            return None

        all_texts = [new_text] + [_to_text(r) for r in existing]

        vectorizer = TfidfVectorizer(stop_words="english", max_features=settings.TFIDF_MAX_FEATURES)
        matrix = vectorizer.fit_transform(all_texts)
        scores = cosine_similarity(matrix[0:1], matrix[1:])[0]

        best_idx = int(scores.argmax())
        best_score = float(scores[best_idx])

        return (existing[best_idx], best_score) if best_score >= threshold else None

    except ImportError:
        logger.warning("scikit-learn not installed — using keyword fallback")
        return _keyword_match(req, existing, threshold)
    except Exception as e:
        logger.error("TF-IDF error: %s", e, exc_info=True)
        return None

def _keyword_match(
    req: Dict,
    existing: List[Dict],
    threshold: float,
) -> Optional[Tuple[Dict, float]]:
    """Jaccard similarity fallback."""
    req_words = _keywords(_to_text(req))
    if not req_words:
        return None

    best, best_score = None, 0.0
    for r in existing:
        words = _keywords(_to_text(r))
        if not words:
            continue
        score = len(req_words & words) / len(req_words | words)
        if score > best_score:
            best_score, best = score, r

    return (best, best_score) if best and best_score >= threshold else None

def _to_text(req: Dict) -> str:
    """Combine key fields into a single string for similarity scoring."""
    parts = []

    title = req.get("title") or req.get("short_title") or req.get("shortTitle") or ""
    if title:
        parts.extend([title, title])  # Double weight for title

    desc = req.get("description") or ""
    if desc:
        parts.append(desc)

    story = req.get("user_story") or req.get("userStory") or ""
    if story:
        parts.append(story)

    criteria = req.get("acceptance_criteria") or req.get("acceptanceCriteria") or []
    if isinstance(criteria, list):
        parts.append(" ".join(str(c) for c in criteria))

    return " ".join(parts)

def _keywords(text: str) -> set:
    """Extract meaningful keywords, stripping stop words."""
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
        "this", "that", "these", "those", "has", "have", "had", "will",
        "shall", "should", "must", "can", "could", "may", "system", "user",
        "able", "want", "need", "feature", "also", "each", "when", "then",
    }
    return set(re.findall(r"[a-z]{3,}", text.lower())) - stop_words

def _format_existing(req: Dict) -> Dict:
    """Format an existing requirement for side-by-side duplicate comparison."""
    return {
        "id": req.get("id"),
        "short_title": req.get("short_title") or req.get("title") or req.get("shortTitle", ""),
        "description": req.get("description", ""),
        "type": req.get("type", ""),
        "requirement_id": req.get("requirement_id") or req.get("requirementId", ""),
        "user_story": req.get("user_story") or req.get("userStory", ""),
        "acceptance_criteria": req.get("acceptance_criteria") or req.get("acceptanceCriteria", []),
        "confidence": req.get("confidence", ""),
        "metadata": req.get("metadata", {}),
    }
