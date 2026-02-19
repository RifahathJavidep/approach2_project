"""
Trained Extractor — DSPy Module for Requirement Extraction

The core DSPy module that chains together:
    1. RequirementExtraction — Extract candidates from text
    2. RequirementClassifier — Validate each candidate
    3. RequirementDeMerger — Split composite requirements

Moved from: extract_requirements.py lines 138–218
"""

import json
from typing import Dict

import dspy

from .signatures import RequirementExtraction, RequirementClassifier, RequirementDeMerger
from .training import SKIP_KEYWORDS


class TrainedExtractor(dspy.Module):
    """
    DSPy module that extracts validated requirements from document text.

    Pipeline:
        1. Extract candidate requirements using ChainOfThought
        2. Pre-filter candidates using keyword skip list
        3. Classify each candidate (yes/no) using trained classifier
        4. De-merge composite requirements into granular items
        5. Enrich each requirement with fallback field values

    Returns:
        Dict with 'requirements' (accepted) and 'filtered_out' (rejected)
    """

    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(RequirementExtraction)
        self.classifier = dspy.ChainOfThought(RequirementClassifier)
        self.de_merger = dspy.ChainOfThought(RequirementDeMerger)

    def forward(self, document_text: str) -> Dict:
        result = self.extractor(document_text=document_text)

        try:
            raw = result.requirements_json
            # Handle markdown-wrapped JSON
            if '```' in raw:
                raw = raw.split('```')[1]
                if raw.startswith('json'):
                    raw = raw[4:]
            candidates = json.loads(raw.strip())
        except Exception:
            candidates = []

        valid_requirements = []
        filtered_out = []

        for candidate in candidates:
            title = candidate.get('title', '')
            desc = candidate.get('description', '')

            # Pre-filter: skip obviously bad candidates
            combined = f"{title} {desc}".lower()
            if any(kw in combined for kw in SKIP_KEYWORDS):
                filtered_out.append(candidate)
                continue

            classification = self.classifier(
                text=f"{title} - {desc}",
                title=title,
                description=desc
            )

            if classification.is_requirement.lower().strip() in ['yes', 'true']:
                # Second Pass: De-merger
                try:
                    de_merged = self.de_merger(
                        composite_requirement_title=title,
                        composite_requirement_desc=desc
                    )
                    raw_dm = de_merged.requirements_json
                    if '```' in raw_dm:
                        raw_dm = raw_dm.split('```')[1]
                        if raw_dm.startswith('json'):
                            raw_dm = raw_dm[4:]
                    distinct_items = json.loads(raw_dm.strip())

                    if len(distinct_items) > 1:
                        for item in distinct_items:
                            # Inherit metadata from parent
                            new_item = candidate.copy()
                            new_item['title'] = item['title']
                            new_item['description'] = item['description']
                            valid_requirements.append(new_item)
                        continue  # Skip adding the original parent
                except Exception:
                    pass

                # Ensure all fields exist with fallback values
                candidate['user_story'] = candidate.get('user_story', f"As a user, I want to use {title} so that I can achieve my goal.")
                candidate['acceptance_criteria'] = candidate.get('acceptance_criteria', [f"Verify {title} functionality"])
                candidate['test_steps'] = candidate.get('test_steps', [{'step_num': 1, 'action': f'Interact with {title}', 'expected_result': 'System responds correctly', 'test_data': 'N/A'}])
                candidate['test_scenarios'] = candidate.get('test_scenarios', [f"Successful {title} interaction"])
                candidate['assumptions'] = candidate.get('assumptions', [])
                candidate['ambiguities'] = candidate.get('ambiguities', [])
                candidate['confidence'] = candidate.get('confidence', 'medium')
                valid_requirements.append(candidate)
            else:
                filtered_out.append(candidate)

        return {
            'requirements': valid_requirements,
            'filtered_out': filtered_out
        }
