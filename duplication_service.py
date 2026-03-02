"""
Duplication Detection Service

Handles requirement-level duplication check:
  Is any new requirement semantically similar to existing ones?

Uses TF-IDF + Cosine Similarity for lightweight, zero-cost semantic matching.

Returns:
  Each requirement is annotated in-place with:
    - is_duplicate: bool
    - duplicate_of: { similarity_score, existing_requirement: { full details } } | null
"""

import os
import re
import requests
from typing import List, Dict, Tuple, Optional

from dotenv import load_dotenv

load_dotenv()

JAVA_BACKEND_BASE_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")

# Similarity threshold — requirements above this score are flagged as duplicates
DEFAULT_SIMILARITY_THRESHOLD = 0.80


# =============================================================================
# REQUIREMENT-LEVEL DUPLICATION CHECK
# =============================================================================

def find_duplicate_requirements(
    project_id: str,
    new_requirements: List[Dict],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Tuple[List[Dict], int]:
    """
    Compare new requirements against all existing requirements in the project.
    Uses TF-IDF + Cosine Similarity for semantic matching.

    Modifies each requirement IN-PLACE by adding:
      - is_duplicate: True/False
      - duplicate_of: { similarity_score, existing_requirement: {...} } or None

    Args:
        project_id: The project ID
        new_requirements: List of newly extracted requirement dicts
        threshold: Similarity threshold (0.0 to 1.0). Default 0.80

    Returns:
        Tuple of (annotated_requirements, duplicates_count):
        - annotated_requirements: Same list with is_duplicate + duplicate_of set on each
        - duplicates_count: Number of requirements flagged as duplicates
    """
    # Fetch existing requirements from Java backend
    existing_requirements = _fetch_existing_requirements(project_id)

    if not existing_requirements:
        print(f"  [Duplication] No existing requirements for project {project_id}. All are unique.")
        for req in new_requirements:
            req["is_duplicate"] = False
            req["duplicate_of"] = None
        return new_requirements, 0

    duplicates_count = 0

    for new_req in new_requirements:
        best_match = _find_best_match(new_req, existing_requirements, threshold)

        if best_match:
            existing_req, score = best_match
            duplicates_count += 1

            new_req["is_duplicate"] = True
            new_req["duplicate_of"] = {
                "similarity_score": round(score, 2),
                "existing_requirement": _format_existing_requirement(existing_req),
            }

            new_title = new_req.get('title') or new_req.get('short_title') or ''
            existing_title = existing_req.get('short_title') or existing_req.get('title') or ''
            print(
                f"  [Duplication] DUPLICATE ({score:.0%}): "
                f"'{new_title}' \u2248 '{existing_title}'"
            )
        else:
            new_req["is_duplicate"] = False
            new_req["duplicate_of"] = None

    print(
        f"  [Duplication] Results: {duplicates_count} duplicates, "
        f"{len(new_requirements) - duplicates_count} unique "
        f"(threshold={threshold})"
    )

    return new_requirements, duplicates_count


def filter_unique_requirements(
    project_id: str,
    new_requirements: List[Dict],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> List[Dict]:
    """
    Compare new requirements against existing ones and return ONLY the unique ones.
    Duplicates are strictly filtered out (removed).
    """
    existing_requirements = _fetch_existing_requirements(project_id)
    
    if not existing_requirements:
        return new_requirements
        
    unique_requirements = []
    
    for new_req in new_requirements:
        best_match = _find_best_match(new_req, existing_requirements, threshold)
        
        if not best_match:
            # No semantic match above threshold -> it is unique
            unique_requirements.append(new_req)
        else:
            # Skip/discard the duplicate
            existing_req, score = best_match
            new_title = new_req.get('title') or new_req.get('short_title') or ''
            existing_title = existing_req.get('short_title') or existing_req.get('title') or ''
            print(f"  [Filter] REMOVING DUPLICATE ({score:.0%}): '{new_title}' \u2248 '{existing_title}'")
            
    return unique_requirements


# =============================================================================
# BACKEND API CALLS
# =============================================================================

def _fetch_existing_requirements(project_id: str) -> List[Dict]:
    """
    Fetch all existing requirements for a project from the Java backend.
    Calls: GET /api/requirements/project/{projectId}
    """
    url = f"{JAVA_BACKEND_BASE_URL}/api/requirements/project/{project_id}"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            # Handle both list and dict-wrapped responses
            if isinstance(data, list):
                reqs = data
            elif isinstance(data, dict):
                reqs = data.get("requirements", data.get("content", []))
            else:
                reqs = []
            print(f"  [Duplication] Fetched {len(reqs)} existing requirements for project {project_id}")
            return reqs
        else:
            print(f"  [Duplication] Backend returned {response.status_code} for existing requirements")
            return []
    except Exception as e:
        print(f"  [Duplication] ERROR fetching existing requirements: {e}")
        return []


# =============================================================================
# SIMILARITY ENGINE
# =============================================================================

def _find_best_match(
    new_req: Dict,
    existing_reqs: List[Dict],
    threshold: float,
) -> Optional[Tuple[Dict, float]]:
    """
    Find the most similar existing requirement for a given new requirement.
    Uses TF-IDF + Cosine Similarity.

    Returns:
        Tuple of (best_matching_requirement, similarity_score) or None if below threshold
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        print("  [Duplication] WARNING: scikit-learn not installed. Falling back to keyword matching.")
        return _find_best_match_keyword(new_req, existing_reqs, threshold)

    new_text = _requirement_to_text(new_req)

    if not new_text.strip():
        return None

    # Build texts list: [new_req_text, existing_1, existing_2, ...]
    existing_texts = [_requirement_to_text(req) for req in existing_reqs]
    all_texts = [new_text] + existing_texts

    # Filter out empty texts
    valid_indices = [i for i, t in enumerate(all_texts) if t.strip()]
    if len(valid_indices) < 2:
        return None

    try:
        vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
        tfidf_matrix = vectorizer.fit_transform(all_texts)

        # Compute similarity of new_req (index 0) against all existing (index 1+)
        similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:])[0]

        best_idx = similarities.argmax()
        best_score = float(similarities[best_idx])

        if best_score >= threshold:
            return existing_reqs[best_idx], best_score

    except Exception as e:
        print(f"  [Duplication] TF-IDF error: {e}")

    return None


def _find_best_match_keyword(
    new_req: Dict,
    existing_reqs: List[Dict],
    threshold: float,
) -> Optional[Tuple[Dict, float]]:
    """
    Fallback keyword-overlap similarity when scikit-learn is not available.
    """
    new_words = _extract_keywords(_requirement_to_text(new_req))
    if not new_words:
        return None

    best_match = None
    best_score = 0.0

    for existing_req in existing_reqs:
        existing_words = _extract_keywords(_requirement_to_text(existing_req))
        if not existing_words:
            continue

        # Jaccard similarity
        intersection = new_words & existing_words
        union = new_words | existing_words
        score = len(intersection) / len(union) if union else 0

        if score > best_score:
            best_score = score
            best_match = existing_req

    if best_match and best_score >= threshold:
        return best_match, best_score

    return None


# =============================================================================
# TEXT PROCESSING HELPERS
# =============================================================================

def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text."""
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
        "this", "that", "these", "those", "has", "have", "had", "will",
        "shall", "should", "must", "can", "could", "may", "system", "user",
        "able", "want", "need", "feature", "also", "each", "when", "then",
    }
    words = set(re.findall(r"[a-z]{3,}", text.lower()))
    return words - stop_words


def _requirement_to_text(req: Dict) -> str:
    """
    Convert a requirement dict to a single text string for similarity comparison.
    Combines title + description + user_story + acceptance_criteria.
    Handles both new requirements (title) and existing backend (short_title).
    """
    parts = []

    # Title — most important, give it more weight by repeating
    title = req.get("title") or req.get("short_title") or req.get("shortTitle") or ""
    if title:
        parts.append(title)
        parts.append(title)  # Repeat for extra weight in TF-IDF

    # Description
    description = req.get("description") or ""
    if description:
        parts.append(description)

    # User story
    user_story = req.get("user_story") or req.get("userStory") or ""
    if user_story:
        parts.append(user_story)

    # Acceptance criteria (join as text)
    criteria = req.get("acceptance_criteria") or req.get("acceptanceCriteria") or []
    if isinstance(criteria, list):
        parts.append(" ".join(str(c) for c in criteria))

    return " ".join(parts)


# =============================================================================
# FORMAT EXISTING REQUIREMENT (full details for frontend comparison)
# =============================================================================

def _format_existing_requirement(req: Dict) -> Dict:
    """
    Format an existing requirement from Java backend with full details.
    This is included in duplicate_of so frontend can show side-by-side comparison.
    Handles the real backend field names (short_title, snake_case, etc.)
    """
    return {
        "id": req.get("id"),
        "short_title": req.get("short_title") or req.get("title") or req.get("shortTitle", ""),
        "description": req.get("description", ""),
        "type": req.get("type", ""),
        "requirement_id": req.get("requirement_id") or req.get("requirementId", ""),
        "user_story": req.get("user_story") or req.get("userStory", ""),
        "acceptance_criteria": req.get("acceptance_criteria") or req.get("acceptanceCriteria", []),
        "test_steps": req.get("test_steps") or req.get("testSteps", []),
        "test_scenarios": req.get("test_scenarios") or req.get("testScenarios", []),
        "assumptions": req.get("assumptions", []),
        "ambiguities": req.get("ambiguities", []),
        "confidence": req.get("confidence", ""),
        "metadata": req.get("metadata", {}),
    }
