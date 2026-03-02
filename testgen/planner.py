"""
Test Case Planner — AI-Powered Test Case Generator

Generates professional, detailed E2E test cases from structured requirements.
Uses a domain-agnostic prompt that adapts to any project type.

The planner:
1. Takes each requirement (with user_story, acceptance_criteria, test_steps)
2. Calls Groq LLM with a professional QA Engineer prompt
3. Returns structured test cases with 8-15 detailed steps each

Example:
    planner = TestCasePlanner()
    test_plan = planner.generate(requirements, project_name="PTW")
"""

import json
import os
import re
from typing import List, Dict, Any, Optional

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — Sets the AI's persona and methodology
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a Principal QA Architect with 15+ years of experience across \
enterprise software, SaaS platforms, e-commerce, healthcare, logistics, \
fintech, and telecom domains.

Your test cases are used by Fortune 500 companies for UAT sign-off. \
They are known for being:
- Executable by a junior tester with zero domain knowledge
- Detailed enough to catch edge cases that developers miss
- Structured for traceability back to the original requirement

You ALWAYS write from the END-USER's perspective. Never say \
"verify the system does X." Instead say "verify the user is able to X."

You return ONLY valid JSON. No markdown. No commentary."""


# ─────────────────────────────────────────────────────────────────────────────
# USER PROMPT — The detailed instruction for each requirement
# ─────────────────────────────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """\
Generate professional E2E test cases for the following requirement.

═══════════════════════════════════════════════════
REQUIREMENT DETAILS
═══════════════════════════════════════════════════

Requirement ID   : {requirement_id}
Title            : {title}
Type             : {req_type}
Description      : {description}
User Story       : {user_story}

Acceptance Criteria:
{acceptance_criteria_text}

Existing Test Hints (from document):
{existing_test_steps_text}

Assumptions:
{assumptions_text}
{dependency_text}

═══════════════════════════════════════════════════
TEST CASE GENERATION RULES
═══════════════════════════════════════════════════

▸ RULE 1 — USER PERSPECTIVE
  Every test step must describe what the USER does and sees.
  ✅ "Click the 'Submit Order' button"
  ✅ "Verify the confirmation message displays: 'Order placed successfully'"
  ❌ "System processes the order in the backend"
  ❌ "Database record is created"

▸ RULE 2 — VERBATIM TERMINOLOGY
  Use the EXACT names, labels, and terms from the requirement.
  If the requirement says "Warranty Dashboard" — write "Warranty Dashboard", 
  NOT "warranty page" or "the dashboard".

▸ RULE 3 — STEP GRANULARITY (8-15 steps per test case)
  Each step = ONE atomic action. Never combine two actions.
  ✅ Step 1: "Navigate to the Login page"
  ✅ Step 2: "Enter valid username in the 'Email' field"
  ✅ Step 3: "Enter valid password in the 'Password' field"
  ✅ Step 4: "Click the 'Sign In' button"
  ❌ Step 1: "Login with valid credentials"  ← TOO VAGUE

▸ RULE 4 — COMPLETE TEST JOURNEY
  Every test case must follow this flow:
  1. SETUP       → Login / Navigate to the starting point
  2. NAVIGATE    → Go to the specific page/section/module
  3. EXECUTE     → Perform the primary action being tested
  4. VERIFY      → Confirm the expected outcome is visible to the user
  5. EDGE CASE   → Test at least one boundary (empty input, max length, special chars)
  6. CLEANUP     → Navigate back / Logout / Confirm state is reset

▸ RULE 5 — MULTIPLE TEST CASES WHEN NEEDED
  If the requirement contains MULTIPLE distinct testable actions, 
  generate a SEPARATE test case for each:
  Example: "User can export in CSV, PDF, and Excel"
  → TC-1: Export in CSV format
  → TC-2: Export in PDF format  
  → TC-3: Export in Excel format

▸ RULE 6 — NEGATIVE TESTING
  For every positive flow, include at least ONE negative scenario:
  - Invalid input → verify error message
  - Missing required field → verify validation
  - Unauthorized access → verify permission denied
  - Network timeout → verify graceful error handling

▸ RULE 7 — TEST DATA
  Specify realistic test data in each step:
  ✅ "Enter 'john.doe@company.com' in the Email field"
  ✅ "Select 'Active' from the Status dropdown"
  ❌ "Enter a valid email" ← No specific data

▸ RULE 8 — PREREQUISITES
  List everything that must be TRUE before the test starts:
  - User role/permissions required
  - Test data that must exist (accounts, records, configurations)
  - System state (feature flags, environment settings)
  - Dependencies on other tests or requirements

═══════════════════════════════════════════════════
OUTPUT FORMAT (STRICT JSON)
═══════════════════════════════════════════════════

Return ONLY this JSON structure. Nothing else.

{{
  "requirement_id": "{requirement_id}",
  "requirement_title": "{title}",
  "test_cases": [
    {{
      "test_case_id": "TC-001",
      "title": "Brief descriptive title of what is being tested",
      "description": "Verify that the user is able to [specific action from requirement]",
      "test_type": "Functional | Non-Functional | Integration | Security | Performance",
      "test_phase": "E2E | Regression | Smoke | UAT",
      "priority": "Critical | High | Medium | Low",
      "prerequisites": "Specific preconditions that must be met before execution",
      "test_steps": [
        "Step described as a single atomic user action",
        "Next step with specific UI elements and test data",
        "..."
      ],
      "expected_result": "The specific, observable outcome the tester should verify",
      "test_data": "Specific data values used in this test case",
      "status": "Not Executed"
    }}
  ],
  "total_count": 1
}}"""


# ─────────────────────────────────────────────────────────────────────────────
# PLANNER CLASS
# ─────────────────────────────────────────────────────────────────────────────

class TestCasePlanner:
    """
    AI-powered test case generator.
    
    Takes structured requirements from Phase 1 and generates
    professional E2E test cases using Groq LLM.
    """

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in environment")
        self.client = Groq(api_key=api_key)
        self.model = model

    def generate(
        self,
        requirements: List[Dict[str, Any]],
        project_name: str = "Project",
        source_texts: Optional[Dict[str, str]] = None,
        status_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Generate test cases for a list of requirements.

        Args:
            requirements: List of requirement dicts from Phase 1
            project_name: Name of the project (for logging)
            source_texts: Optional dict mapping document filenames to their
                         full extracted text. When provided, the planner injects
                         relevant document context into each test case prompt
                         for richer, more detailed test steps.
            status_callback: Optional fn(message) for progress updates

        Returns:
            Test plan dict with test_plans, total_requirements, total_test_cases
        """
        test_plans = []
        total_test_cases = 0
        source_texts = source_texts or {}

        print(f"\n{'='*60}")
        print(f"TEST CASE GENERATION — {project_name.upper()}")
        print(f"{'='*60}")
        print(f"  Requirements to process: {len(requirements)}")
        if source_texts:
            print(f"  Document context: {len(source_texts)} source document(s) loaded")
        else:
            print(f"  Document context: None (requirements-only mode)")
        print()

        for idx, req in enumerate(requirements, 1):
            req_id = req.get("requirement_id", f"REQ-{idx:03d}")
            title = req.get("title", "Untitled")

            if status_callback:
                status_callback(f"Generating test cases for {req_id}: {title}")

            print(f"  [{idx}/{len(requirements)}] {req_id}: {title}...", end=" ")

            try:
                plan = self._generate_for_requirement(req, idx, source_texts)
                tc_count = len(plan.get("test_cases", []))
                total_test_cases += tc_count
                test_plans.append(plan)
                print(f"✓ {tc_count} test case(s)")

            except Exception as e:
                print(f"✗ Error: {e}")
                test_plans.append({
                    "requirement_id": req_id,
                    "requirement_title": title,
                    "test_cases": [],
                    "total_count": 0,
                    "error": str(e),
                })

        result = {
            "project_name": project_name,
            "test_plans": test_plans,
            "total_requirements": len(requirements),
            "total_test_cases": total_test_cases,
        }

        print(f"\n{'='*60}")
        print(f"GENERATION COMPLETE")
        print(f"  Requirements processed: {len(requirements)}")
        print(f"  Total test cases: {total_test_cases}")
        print(f"{'='*60}\n")

        return result

    # ─── Private Methods ──────────────────────────────────────────────────

    def _generate_for_requirement(self, req: Dict, index: int, source_texts: Dict[str, str] = None) -> Dict:
        """Generate test cases for a single requirement."""
        source_texts = source_texts or {}

        # Build the prompt with all available context
        prompt = self._build_prompt(req, index)

        # Inject original document context if available
        if source_texts:
            context = self._extract_relevant_context(req, source_texts)
            if context:
                prompt += f"""

═══════════════════════════════════════════════════
ORIGINAL DOCUMENT CONTEXT
═══════════════════════════════════════════════════

The following is the relevant section from the original source document.
MINE this text for VERBATIM details to use in your test steps:
- Exact field names, button labels, page titles
- Specific thresholds, limits, and business rules
- Column names, color codes, dropdown values
- Error messages and validation rules
- Navigation paths and UI layout descriptions

---
{context}
---

IMPORTANT: Use the EXACT terminology from this document context in your test steps.
"""

        # Call Groq
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
            max_tokens=4096,
        )

        raw = response.choices[0].message.content.strip()

        # Parse JSON from response
        parsed = self._parse_response(raw)

        # Validate and enrich each test case
        for tc in parsed.get("test_cases", []):
            tc.setdefault("test_type", "Functional")
            tc.setdefault("test_phase", "E2E")
            tc.setdefault("priority", "High")
            tc.setdefault("prerequisites", "Valid user credentials; access to the application")
            tc.setdefault("test_steps", ["Execute the test", "Verify the result"])
            tc.setdefault("expected_result", "Feature works as described in requirement")
            tc.setdefault("status", "Not Executed")
            tc.setdefault("test_data", "")

        return parsed

    def _extract_relevant_context(
        self, req: Dict, source_texts: Dict[str, str], max_chars: int = 3000
    ) -> str:
        """
        Find the most relevant section of the source document for this requirement.

        Strategy:
        1. Search for the requirement title keywords in the document
        2. Extract ±1500 chars around the match for context
        3. If no keyword match, search for description keywords
        4. Fallback: return the first chunk of the document
        """
        if not source_texts:
            return ""

        # Get the document text (try all available documents)
        doc_text = ""
        source_file = req.get("source_file", "")

        # Try exact match first
        if source_file and source_file in source_texts:
            doc_text = source_texts[source_file]
        else:
            # Try partial match, then fall back to first document
            for name, text in source_texts.items():
                if source_file and source_file in name:
                    doc_text = text
                    break
            if not doc_text and source_texts:
                # Use all documents combined (or just the first one)
                doc_text = "\n\n".join(source_texts.values())

        if not doc_text:
            return ""

        doc_lower = doc_text.lower()

        # Strategy 1: Search for title keywords
        title = req.get("title", "")
        title_words = [w for w in title.split() if len(w) > 3 and w.lower() not in {
            'the', 'and', 'for', 'with', 'from', 'that', 'this', 'must', 'should',
            'system', 'user', 'based', 'management', 'support'
        }]

        # Try multi-word match first (more specific)
        for i in range(len(title_words) - 1):
            phrase = f"{title_words[i]} {title_words[i+1]}".lower()
            pos = doc_lower.find(phrase)
            if pos >= 0:
                start = max(0, pos - 500)
                end = min(len(doc_text), pos + 2500)
                return doc_text[start:end][:max_chars]

        # Try single keyword match
        for word in reversed(title_words):  # Reversed = most specific words first
            pos = doc_lower.find(word.lower())
            if pos >= 0:
                start = max(0, pos - 500)
                end = min(len(doc_text), pos + 2500)
                return doc_text[start:end][:max_chars]

        # Strategy 2: Search for description keywords
        description = req.get("description", "")
        desc_words = [w for w in description.split() if len(w) > 5 and w.lower() not in {
            'should', 'system', 'users', 'allows', 'enable', 'provide',
            'support', 'ensure', 'including', 'specific', 'multiple'
        }]

        for word in reversed(desc_words):
            pos = doc_lower.find(word.lower())
            if pos >= 0:
                start = max(0, pos - 500)
                end = min(len(doc_text), pos + 2500)
                return doc_text[start:end][:max_chars]

        # Strategy 3: Fallback — return first chunk
        return doc_text[:max_chars]

    def _build_prompt(self, req: Dict, index: int) -> str:
        """Build the user prompt from requirement fields."""

        req_id = req.get("requirement_id", f"REQ-{index:03d}")
        title = req.get("title", "Untitled Requirement")
        description = req.get("description", "No description provided")
        req_type = req.get("type", "Functional")
        user_story = req.get("user_story", "Not provided")

        # Format acceptance criteria
        ac = req.get("acceptance_criteria", [])
        if isinstance(ac, list) and ac:
            acceptance_criteria_text = "\n".join([f"  • {c}" for c in ac])
        else:
            acceptance_criteria_text = "  • Not specified — infer from description"

        # Format existing test steps (from Phase 1 extraction)
        existing_steps = req.get("test_steps", [])
        if isinstance(existing_steps, list) and existing_steps:
            steps_lines = []
            for step in existing_steps:
                if isinstance(step, dict):
                    action = step.get("action", "")
                    expected = step.get("expected_result", "")
                    line = f"  • {action}"
                    if expected:
                        line += f" → Expected: {expected}"
                    steps_lines.append(line)
                else:
                    steps_lines.append(f"  • {step}")
            existing_test_steps_text = "\n".join(steps_lines)
        else:
            existing_test_steps_text = "  • None — generate from scratch"

        # Format assumptions
        assumptions = req.get("assumptions", [])
        if isinstance(assumptions, list) and assumptions:
            assumptions_text = "\n".join([f"  • {a}" for a in assumptions])
        else:
            assumptions_text = "  • None specified"

        # Dependencies
        dependency_text = ""
        test_scenarios = req.get("test_scenarios", [])
        if isinstance(test_scenarios, list) and test_scenarios:
            dependency_text = "\nTest Scenarios to Cover:\n" + "\n".join(
                [f"  • {s}" for s in test_scenarios]
            )

        return USER_PROMPT_TEMPLATE.format(
            requirement_id=req_id,
            title=title,
            description=description,
            req_type=req_type,
            user_story=user_story if user_story else "Not provided",
            acceptance_criteria_text=acceptance_criteria_text,
            existing_test_steps_text=existing_test_steps_text,
            assumptions_text=assumptions_text,
            dependency_text=dependency_text,
        )

    def _parse_response(self, raw: str) -> Dict:
        """Parse JSON from LLM response, handling markdown fences."""

        # Strip markdown code fences
        if "```" in raw:
            raw = re.sub(r"```json\s*", "", raw)
            raw = re.sub(r"```\s*", "", raw)

        # Find JSON object
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            raw = match.group()

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            # Try to fix common issues
            # Remove trailing commas
            cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                raise ValueError(f"Failed to parse LLM response as JSON: {e}\nRaw: {raw[:300]}")
