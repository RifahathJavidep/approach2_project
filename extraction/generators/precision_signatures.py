"""
Precision Requirement Extraction Signatures

New DSPy signatures focused on HIGH PRECISION extraction:
- Every requirement MUST cite the exact source sentence (source_quote)
- No inferred or assumed requirements — only what is explicitly stated
- Confidence gating: low-confidence extractions are rejected downstream

Used by: extraction/pipeline.py (precision_mode=True)
Validated by: extraction/generators/evidence_validator.py
"""

import dspy


class PrecisionRequirementExtractor(dspy.Signature):
    """Extract ONLY requirements that are DIRECTLY AND EXPLICITLY STATED in the document.

    MANDATORY: Each requirement MUST include an exact verbatim quote (source_quote)
    copied from the document that PROVES it is a requirement.
    If you cannot find the exact sentence, DO NOT extract the requirement.

    WHAT COUNTS AS A REQUIREMENT INDICATOR — extract ONLY if you see these:
    - "shall", "must", "will", "should" + action verb
      → e.g. "The system shall display the warranty expiry date"
    - "The system/application/user [verb]..." in imperative/declarative form
      → e.g. "The dashboard displays active subscribers, suspended subscribers..."
    - "User can / is able to [action]"
      → e.g. "Users can toggle between data, voice, and text usage summaries"
    - A named feature with EXPLICIT BEHAVIOR described
      → e.g. "The Warranty Expiry Notification feature sends an email alert 30 days before expiry"
    - An explicit constraint with a measurable target
      → e.g. "Page must load within 3 seconds"

    WHAT TO REJECT — DO NOT extract these:
    - Background context, project history, executive summaries
    - Meeting notes, status updates, decisions not yet implemented
    - Assumptions or constraints listed as project context only
    - Anything you had to INFER, GUESS, or ADD that isn't in the source text
    - Paraphrased versions of what the document says — use the EXACT WORDS

    CRITICAL RULES:
    1. source_quote MUST be copied verbatim (word-for-word) from the document
    2. If you paraphrase or can't find the exact sentence → set confidence to "low"
    3. Only "high" and "medium" confidence requirements pass the evidence gate
    4. Title MUST use EXACT terminology from the document (do not rename/generalize)
    5. Return [] if no clear, directly stated requirements are found
    """

    document_text = dspy.InputField(
        desc="The source document text to extract requirements from"
    )
    requirements_json = dspy.OutputField(
        desc="""JSON array of precision-extracted requirements. Return [] if no clear requirements found.
[{
  "title": "Short, specific title using EXACT domain terms from the document (3-8 words)",
  "description": "What the requirement states, using the EXACT words from the document — no paraphrasing",
  "type": "Functional | UI | Workflow | Non-Functional | Security | Architecture",
  "source_quote": "EXACT verbatim sentence(s) copied from the document that proves this is a requirement. Must be findable in the document.",
  "extraction_type": "direct_mandate | feature_description | explicit_behavior | explicit_constraint",
  "confidence": "high (direct quote) | medium (clear but slightly paraphrased) | low (inferred — will be rejected)",
  "user_story": "As a [role explicitly mentioned in doc], I want [action stated in doc], so that [benefit stated in doc]",
  "acceptance_criteria": ["Criterion directly derived from the source_quote, not invented"]
}]

EXAMPLE of correct extraction:
Document says: "The system shall display a warranty expiry notification to users 30 days before the device warranty expires."
Correct output:
{
  "title": "Warranty Expiry Notification — 30-Day Alert",
  "description": "The system displays a warranty expiry notification to users 30 days before the device warranty expires",
  "source_quote": "The system shall display a warranty expiry notification to users 30 days before the device warranty expires.",
  "extraction_type": "direct_mandate",
  "confidence": "high"
}

EXAMPLE of incorrect extraction (DO NOT DO THIS):
Document says: "The device information page shows warranty details."
Wrong output (inferred requirement not stated in doc):
{
  "title": "Warranty Information for Invalid Devices",  ← INVENTED — not in source
  "source_quote": "The device information page shows warranty details."  ← Quote doesn't support this title
}"""
    )


class PrecisionRequirementExtractorModule(dspy.Module):
    """
    DSPy module that wraps PrecisionRequirementExtractor with chain-of-thought.

    Each requirement must pass evidence validation before being returned.
    Call forward() with document_text, returns dict with:
        - requirements: List of validated precision requirements
        - filtered_out: List of rejected candidates with rejection reasons
    """

    def __init__(self):
        super().__init__()
        self.extractor = dspy.ChainOfThought(PrecisionRequirementExtractor)

    def forward(self, document_text: str) -> dict:
        import json

        try:
            result = self.extractor(document_text=document_text)
            raw = result.requirements_json

            # Strip markdown fences if present
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            candidates = json.loads(raw.strip())
        except Exception as e:
            print(f"    ⚠ Precision extractor parse error: {e}")
            candidates = []

        # Filter out low-confidence immediately (before evidence validation)
        kept = []
        filtered = []
        for c in candidates:
            conf = c.get("confidence", "medium").lower()
            if conf == "low":
                c["_rejection_reason"] = "Low confidence (inferred requirement)"
                filtered.append(c)
            else:
                # Enrich with standard fields
                c.setdefault("user_story", "")
                c.setdefault("acceptance_criteria", [])
                c.setdefault("test_steps", [])
                c.setdefault("test_scenarios", [])
                c.setdefault("assumptions", [])
                c.setdefault("ambiguities", [])
                kept.append(c)

        return {"requirements": kept, "filtered_out": filtered}
