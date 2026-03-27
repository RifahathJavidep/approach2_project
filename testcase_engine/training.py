import json
import logging
import dspy
from pathlib import Path
from datetime import datetime
from dspy.teleprompt import BootstrapFewShot
from typing import List, Dict, Any, Optional

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    TfidfVectorizer = None
    cosine_similarity = None

from .scenario_generator import ScenarioGeneratorModule, ScenarioBasedTCGenerator
from .context_builder import get_feature_context

logger = logging.getLogger("prism.testcase_engine.training")

class SimpleSemanticMatcher:
    """Basic semantic matching using TF-IDF and Cosine Similarity."""
    def __init__(self):
        if TfidfVectorizer is None:
            logger.warning("scikit-learn not installed. Semantic matching will use direct overlap.")
            self.vec = None
        else:
            self.vec = TfidfVectorizer(stop_words='english')

    def match_lists(self, list1: List[str], list2: List[str], threshold: float = 0.25) -> List[tuple]:
        if not list1 or not list2:
            return []
            
        if self.vec:
            try:
                tfidf = self.vec.fit_transform(list1 + list2)
                sim = cosine_similarity(tfidf[:len(list1)], tfidf[len(list1):])
                
                matches = []
                for i in range(len(list1)):
                    for j in range(len(list2)):
                        if sim[i][j] >= threshold:
                            matches.append((i, j, sim[i][j]))
                return matches
            except Exception as e:
                logger.error("TF-IDF match failed: %s", e)
        
        # Fallback keyword overlap
        matches = []
        for i, s1 in enumerate(list1):
            w1 = set(s1.lower().split())
            for j, s2 in enumerate(list2):
                w2 = set(s2.lower().split())
                score = len(w1 & w2) / max(len(w1 | w2), 1)
                if score >= threshold:
                    matches.append((i, j, score))
        return matches

def build_tc_training_examples(requirements: List[Dict], gt_test_cases: List[Dict], documents: Dict) -> List[dspy.Example]:
    """Ported from Archive-01: match requirements to GT test cases and build DSPy examples."""
    examples = []
    matcher = SimpleSemanticMatcher()

    req_texts = [f"{r.get('feature_name', r.get('title', ''))} {r.get('description', '')}" for r in requirements]
    gt_texts = [f"{tc.get('feature_name', tc.get('title', ''))} {tc.get('description', '')}" for tc in gt_test_cases]
    
    matches = matcher.match_lists(req_texts, gt_texts, threshold=0.3)

    for req_idx, gt_idx, score in matches:
        req = requirements[req_idx]
        gt_tc = gt_test_cases[gt_idx]

        context = get_feature_context(req, documents)
        
        # Build the expected JSON output for training
        expected = {
            "description": gt_tc.get("description", ""),
            "preconditions": gt_tc.get("preconditions", gt_tc.get("prerequisites", [])),
            "steps": gt_tc.get("steps", gt_tc.get("test_steps", []))
        }
        
        if isinstance(expected["preconditions"], str):
            expected["preconditions"] = [expected["preconditions"]]

        examples.append(dspy.Example(
            feature_name=req.get('feature_name', req.get('title', '')),
            scenario_name="Full Feature Test",
            feature_description=req.get('description', ''),
            acceptance_criteria="\n".join(req.get('acceptance_criteria', [])),
            scenario_steps_hint="Extract from matched ground truth.",
            deterministic_base_steps="N/A (using GT)", 
            document_context=context[:10000],
            test_case_json=json.dumps(expected)
        ).with_inputs("feature_name", "scenario_name", "feature_description", 
                       "acceptance_criteria", "scenario_steps_hint", "deterministic_base_steps", "document_context"))

    logger.info("Built %d TC training examples", len(examples))
    return examples

def tc_metric(example, prediction, trace=None):
    """Metric for TC quality based on step overlap and count ratio."""
    try:
        gt = json.loads(example.test_case_json)
        
        # Handle DSPy output format
        pred_raw = prediction.test_case_json
        if '```' in pred_raw:
            pred_raw = pred_raw.split('```')[1]
            if pred_raw.startswith('json'):
                pred_raw = pred_raw[4:]
        pred = json.loads(pred_raw.strip())
        
        gt_steps = [s.get('action', s if isinstance(s, str) else '') for s in gt.get('steps', [])]
        pred_steps = [s.get('action', s if isinstance(s, str) else '') for s in pred.get('steps', [])]
        
        gt_steps = [s for s in gt_steps if s]
        pred_steps = [s for s in pred_steps if s]

        if not gt_steps or not pred_steps:
            return 0.0

        matcher = SimpleSemanticMatcher()
        matches = matcher.match_lists(pred_steps, gt_steps, threshold=0.20)
        
        recall = len(matches) / len(gt_steps)
        precision = len(matches) / len(pred_steps)
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
        
        count_ratio = min(len(pred_steps), len(gt_steps)) / max(len(pred_steps), len(gt_steps))
        
        # Weighted score
        return 0.6 * f1 + 0.2 * count_ratio + 0.2 * recall
    except Exception:
        return 0.0

def train_scenario_generator(requirements: List[Dict], gt_test_cases: List[Dict], documents: Dict, model_save_path: str):
    """Train the ScenarioGenerator using BootstrapFewShot."""
    train_examples = build_tc_training_examples(requirements, gt_test_cases, documents)
    if not train_examples:
        logger.error("No training examples could be matched. Training aborted.")
        return None

    optimizer = BootstrapFewShot(
        metric=tc_metric,
        max_bootstrapped_demos=3,
        max_labeled_demos=3,
        max_rounds=1
    )
    
    generator = ScenarioGeneratorModule()
    logger.info("Starting DSPy compilation for TC Generator...")
    optimized = optimizer.compile(generator, trainset=train_examples)
    
    optimized.save(model_save_path)
    logger.info("✓ Saved trained model to %s", model_save_path)
    return optimized
