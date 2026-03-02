"""
Ground Truth Evaluator — Semantic Precision / Recall / F1 Scoring

Compares generated requirements and test cases against ground truth using
TF-IDF cosine similarity instead of string equality, giving a realistic
score even when generated text is worded slightly differently from GT.

Key improvement over the existing comparison_results.json approach:
  - Uses semantic similarity (TF-IDF + cosine) with threshold 0.45
    instead of exact string match → much more fair evaluation
  - Evaluates at requirement level AND test-case level AND step level
  - Computes industry-standard Precision / Recall / F1

Usage:
    from evaluation.gt_evaluator import RequirementEvaluator, TestCaseEvaluator

    req_eval  = RequirementEvaluator()
    tc_eval   = TestCaseEvaluator()

    req_results = req_eval.evaluate(extracted_reqs, gt_requirements)
    tc_results  = tc_eval.evaluate(generated_test_plan, gt_test_cases)
"""

import re
from typing import Dict, List, Optional, Tuple

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# Default threshold for a "match" between two items
DEFAULT_MATCH_THRESHOLD = 0.35
# Default threshold for a step-level match (lower because steps are short)
DEFAULT_STEP_THRESHOLD = 0.25


# ─────────────────────────────────────────────────────────────────────────────
# Shared similarity utilities
# ─────────────────────────────────────────────────────────────────────────────

def _build_sim_matrix(texts_a: List[str], texts_b: List[str]):
    """
    Compute a pairwise TF-IDF cosine similarity matrix between two text lists.

    Returns:
        numpy array of shape (len(texts_a), len(texts_b)), or None on failure.
    """
    if not SKLEARN_AVAILABLE or not texts_a or not texts_b:
        return None

    combined = texts_a + texts_b
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        max_features=10_000,
        stop_words="english",
        sublinear_tf=True,  # log-normalise TF to reduce effect of very long texts
    )
    try:
        tfidf = vectorizer.fit_transform(combined)
        a_vecs = tfidf[: len(texts_a)]
        b_vecs = tfidf[len(texts_a) :]
        return cosine_similarity(a_vecs, b_vecs)
    except Exception:
        return None


def _greedy_match(
    n_a: int,
    n_b: int,
    sim_matrix,
    threshold: float,
) -> List[Tuple[int, int, float]]:
    """
    Greedy one-to-one matching between A and B using the similarity matrix.

    Each item in A is matched to at most one item in B, and vice versa.
    Sorted by score descending so the best pairs are claimed first.

    Returns:
        List of (a_idx, b_idx, score) tuples for matched pairs.
    """
    if sim_matrix is None:
        return []

    # Collect all (score, a_idx, b_idx) triples above threshold
    candidates = []
    for i in range(n_a):
        for j in range(n_b):
            score = float(sim_matrix[i, j])
            if score >= threshold:
                candidates.append((score, i, j))

    candidates.sort(reverse=True)  # highest score first

    matched_a, matched_b = set(), set()
    matches = []

    for score, i, j in candidates:
        if i in matched_a or j in matched_b:
            continue
        matched_a.add(i)
        matched_b.add(j)
        matches.append((i, j, score))

    return matches


# ─────────────────────────────────────────────────────────────────────────────
# Requirement-level evaluator
# ─────────────────────────────────────────────────────────────────────────────

class RequirementEvaluator:
    """
    Evaluate extracted requirements against ground truth at the requirement level.

    Computes:
        Precision  = matched / n_extracted
        Recall     = matched / n_gt
        F1         = harmonic mean of precision and recall
    """

    def __init__(self, threshold: float = DEFAULT_MATCH_THRESHOLD):
        self.threshold = threshold

    def evaluate(
        self,
        extracted: List[Dict],
        ground_truth: List[Dict],
    ) -> Dict:
        """
        Args:
            extracted:    List of extracted requirement dicts (need 'title', 'description')
            ground_truth: List of GT requirement dicts (need 'title', 'description')

        Returns:
            {
              precision, recall, f1,
              n_extracted, n_gt, n_matched,
              matched_pairs:         [{extracted_title, gt_title, similarity}]
              unmatched_extracted:   [title, ...]
              unmatched_gt:          [title, ...]
            }
        """
        empty = {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "n_extracted": len(extracted),
            "n_gt": len(ground_truth),
            "n_matched": 0,
            "matched_pairs": [],
            "unmatched_extracted": [r.get("title", "") for r in extracted],
            "unmatched_gt": [r.get("title", "") for r in ground_truth],
        }

        if not extracted or not ground_truth:
            return empty

        ext_texts = [
            f"{r.get('title', '')} {r.get('description', '')}" for r in extracted
        ]
        gt_texts = [
            f"{r.get('title', '')} {r.get('description', '')}" for r in ground_truth
        ]

        sim_matrix = _build_sim_matrix(ext_texts, gt_texts)
        matches = _greedy_match(len(extracted), len(ground_truth), sim_matrix, self.threshold)

        matched_ext = {i for i, _, _ in matches}
        matched_gt = {j for _, j, _ in matches}

        matched_pairs = [
            {
                "extracted_title": extracted[i].get("title", ""),
                "gt_title": ground_truth[j].get("title", ""),
                "similarity": round(score, 4),
            }
            for i, j, score in sorted(matches, key=lambda x: -x[2])
        ]
        unmatched_extracted = [
            extracted[i].get("title", "")
            for i in range(len(extracted))
            if i not in matched_ext
        ]
        unmatched_gt = [
            ground_truth[j].get("title", "")
            for j in range(len(ground_truth))
            if j not in matched_gt
        ]

        tp = len(matches)
        precision = tp / len(extracted)
        recall = tp / len(ground_truth)
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "n_extracted": len(extracted),
            "n_gt": len(ground_truth),
            "n_matched": tp,
            "matched_pairs": matched_pairs,
            "unmatched_extracted": unmatched_extracted,
            "unmatched_gt": unmatched_gt,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Test-case-level evaluator
# ─────────────────────────────────────────────────────────────────────────────

class TestCaseEvaluator:
    """
    Evaluate generated test cases against GT test cases.

    Two-level evaluation:
      1. Test case level — does each generated TC match a GT TC?
      2. Step level      — for matched TCs, how well do steps align?
    """

    def __init__(
        self,
        tc_threshold: float = DEFAULT_MATCH_THRESHOLD,
        step_threshold: float = DEFAULT_STEP_THRESHOLD,
    ):
        self.tc_threshold = tc_threshold
        self.step_threshold = step_threshold

    def evaluate(
        self,
        generated_plan: Dict,
        gt_test_cases: List[Dict],
    ) -> Dict:
        """
        Args:
            generated_plan:  Output from TestCasePlanner.generate()
                             Must have 'test_plans' → [{'test_cases': [...]}]
            gt_test_cases:   List of GT TC dicts (need 'title', 'steps'/'description')

        Returns:
            {
              tc_precision, tc_recall, tc_f1,
              avg_step_accuracy,
              n_generated, n_gt, n_matched,
              comparisons: [{
                  generated_title, matched, similarity,
                  gt_match_title, step_accuracy,
                  n_generated_steps, n_gt_steps
              }]
            }
        """
        # Flatten all generated TCs from all requirement plans
        gen_tcs = []
        for plan in generated_plan.get("test_plans", []):
            for tc in plan.get("test_cases", []):
                gen_tcs.append(
                    {
                        "title": tc.get("title", ""),
                        "description": tc.get("description", ""),
                        "steps": tc.get("test_steps", []),
                        "requirement_id": plan.get("requirement_id", ""),
                    }
                )

        empty = {
            "tc_precision": 0.0,
            "tc_recall": 0.0,
            "tc_f1": 0.0,
            "avg_step_accuracy": 0.0,
            "n_generated": len(gen_tcs),
            "n_gt": len(gt_test_cases),
            "n_matched": 0,
            "comparisons": [],
        }

        if not gen_tcs or not gt_test_cases:
            return empty

        gen_texts = [
            f"{tc['title']} {tc['description']}" for tc in gen_tcs
        ]
        gt_texts = [
            f"{tc.get('title', '')} {tc.get('description', tc.get('steps', ''))}"
            for tc in gt_test_cases
        ]

        sim_matrix = _build_sim_matrix(gen_texts, gt_texts)
        matches = _greedy_match(
            len(gen_tcs), len(gt_test_cases), sim_matrix, self.tc_threshold
        )

        matched_gen = {i for i, _, _ in matches}
        matched_gt_set = {j for _, j, _ in matches}

        step_accuracies: List[float] = []
        comparisons: List[Dict] = []

        # Build per-match details
        match_lookup = {i: (j, score) for i, j, score in matches}

        for i, gen_tc in enumerate(gen_tcs):
            if i in match_lookup:
                j, score = match_lookup[i]
                gt_tc = gt_test_cases[j]
                step_acc = self._step_accuracy(
                    gen_tc.get("steps", []),
                    self._parse_gt_steps(gt_tc),
                )
                step_accuracies.append(step_acc)
                comparisons.append(
                    {
                        "generated_title": gen_tc["title"],
                        "matched": True,
                        "similarity": round(score, 4),
                        "gt_match_title": gt_tc.get("title", ""),
                        "step_accuracy": round(step_acc, 4),
                        "n_generated_steps": len(gen_tc.get("steps", [])),
                        "n_gt_steps": len(self._parse_gt_steps(gt_tc)),
                    }
                )
            else:
                # Find closest GT even if below threshold (for diagnostic info)
                best_score = 0.0
                best_gt_title = None
                if sim_matrix is not None and i < sim_matrix.shape[0]:
                    row = sim_matrix[i]
                    best_j = int(row.argmax())
                    best_score = float(row[best_j])
                    best_gt_title = gt_test_cases[best_j].get("title", "")

                comparisons.append(
                    {
                        "generated_title": gen_tc["title"],
                        "matched": False,
                        "similarity": round(best_score, 4),
                        "gt_match_title": best_gt_title,
                        "step_accuracy": None,
                        "n_generated_steps": len(gen_tc.get("steps", [])),
                        "n_gt_steps": None,
                    }
                )

        tp = len(matches)
        precision = tp / len(gen_tcs)
        recall = tp / len(gt_test_cases)
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        avg_step_acc = (
            sum(step_accuracies) / len(step_accuracies) if step_accuracies else 0.0
        )

        return {
            "tc_precision": round(precision, 4),
            "tc_recall": round(recall, 4),
            "tc_f1": round(f1, 4),
            "avg_step_accuracy": round(avg_step_acc, 4),
            "n_generated": len(gen_tcs),
            "n_gt": len(gt_test_cases),
            "n_matched": tp,
            "comparisons": comparisons,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_gt_steps(self, gt_tc: Dict) -> List[str]:
        """Parse GT test steps from various formats (string, list, newline-separated)."""
        raw = gt_tc.get("steps", gt_tc.get("description", ""))

        if isinstance(raw, list):
            return [str(s).strip() for s in raw if s]

        if isinstance(raw, str) and raw.strip():
            # Split by numbered bullets or newlines
            parts = re.split(r"\n|\r\n|\d+[\.\)]\s+", raw)
            return [p.strip() for p in parts if p.strip()]

        return []

    def _step_accuracy(self, gen_steps: List, gt_steps: List[str]) -> float:
        """
        Calculate what fraction of GT steps are covered by generated steps.

        For each GT step, find if at least one generated step has similarity
        >= step_threshold. Returns covered_gt_steps / total_gt_steps.
        """
        if not gen_steps or not gt_steps:
            return 0.0

        # Normalise generated steps to plain strings
        gen_texts = []
        for s in gen_steps:
            if isinstance(s, dict):
                gen_texts.append(
                    f"{s.get('action', '')} {s.get('expected_result', '')}"
                )
            else:
                gen_texts.append(str(s))

        sim_matrix = _build_sim_matrix(gen_texts, gt_steps)
        if sim_matrix is None:
            return 0.0

        # Count GT steps that have at least one generated step above threshold
        covered = 0
        for j in range(len(gt_steps)):
            col = sim_matrix[:, j]
            if float(col.max()) >= self.step_threshold:
                covered += 1

        return covered / len(gt_steps)
