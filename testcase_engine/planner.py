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

from fastapi import logger
from groq import Groq
from .context_builder import get_feature_context
from .scenario_generator import ScenarioBasedTCGenerator
from common.secrets import get_secret

# ─────────────────────────────────────────────────────────────────────────────
# ENUM MAPPINGS — Current string values → TestCaseEditorDTO enum arrays
# ─────────────────────────────────────────────────────────────────────────────

TEST_PHASE_MAP = {
    "E2E": "END_TO_END_TESTING",
    "Regression": "REGRESSION_TESTING",
    "Smoke": "SMOKE_TESTING",
    "UAT": "USER_ACCEPTANCE_TESTING",
    "Functional": "FUNCTIONAL_TESTING",
    "DVT": "DEPLOYMENT_VERIFICATION_TESTING",
}

TEST_TYPE_MAP = {
    "Functional": "UI",
    "Integration": "INTEGRATION",
    "Performance": "PERFORMANCE",
    "Security": "SECURITY",
    "Non-Functional": "NONFUNCTIONAL",
}

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
  "Click the 'Submit Order' button"
  "Verify the confirmation message displays: 'Order placed successfully'"
  "System processes the order in the backend"
  "Database record is created"

▸ RULE 2 — VERBATIM TERMINOLOGY
  Use the EXACT names, labels, and terms from the requirement.
  If the requirement says "Warranty Dashboard" — write "Warranty Dashboard", 
  NOT "warranty page" or "the dashboard".

▸ RULE 3 — STEP GRANULARITY (8-15 steps per test case)
  Each step = ONE atomic action. Never combine two actions.
  Step 1: "Navigate to the Login page"
  Step 2: "Enter valid username in the 'Email' field"
  Step 3: "Enter valid password in the 'Password' field"
  Step 4: "Click the 'Sign In' button"
  Step 1: "Login with valid credentials"  ← TOO VAGUE

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
  "Enter 'john.doe@company.com' in the Email field"
  "Select 'Active' from the Status dropdown"
  "Enter a valid email" ← No specific data

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
      "title": "Brief descriptive title of what is being tested",
      "description": "Verify that the user is able to [specific action from requirement]",
      "test_type": "Functional | Non-Functional | Integration | Security | Performance",
      "test_phase": "E2E | Regression | Smoke | UAT",
      "prerequisites": "Specific preconditions that must be met before execution",
      "testCaseSteps": [
        {{
          "description": "Single atomic user action with specific UI elements and test data",
          "expectedResult": "Specific observable outcome the tester should see"
        }}
      ],
      "expectedResult": "The overall expected outcome of the entire test case"
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

    def __init__(self, model: str = "llama-3.3-70b-versatile", mode: str = "hybrid", model_state_path: Optional[str] = None):
        api_key = get_secret("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in AWS Secrets Manager or environment")
        self.client = Groq(api_key=api_key)
        self.model = model
        self.mode = mode
        
        if mode == "hybrid":
            self.scenario_gen = ScenarioBasedTCGenerator(model_state_path=model_state_path)
        else:
            self.scenario_gen = None

    def generate(
        self,
        requirements: List[Dict[str, Any]],
        project_name: str = "Project",
        documents: Optional[Dict[str, Any]] = None,
        source_texts: Optional[Dict[str, str]] = None,
        doc_file_map: Optional[Dict[str, str]] = None,
        status_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Generate test cases for a list of requirements.

        Args:
            requirements: List of requirement dicts from Phase 1
            project_name: Name of the project (for logging)
            documents: Optional dict of document objects (for hybrid mode)
            source_texts: Optional dict mapping document filenames to their
                         full extracted text (for prompt mode fallback)
            status_callback: Optional fn(message) for progress updates

        Returns:
            Test plan dict with test_plans, total_requirements, total_test_cases
        """
        test_plans = []
        total_test_cases = 0
        source_texts = source_texts or {}
        documents = documents or {}
        doc_file_map = doc_file_map or {}

        print(f"\n{'='*60}")
        print(f"TEST CASE GENERATION — {project_name.upper()} ({self.mode.upper()} MODE)")
        print(f"{'='*60}")
        print(f"  Requirements to process: {len(requirements)}")
        
        if self.mode == "hybrid":
            print(f"  Documents loaded: {len(documents)}")
        elif source_texts:
            print(f"  Document context: {len(source_texts)} source document(s) loaded")
        else:
            print(f"  Document context: None (requirements-only mode)")
        print()

        for idx, req in enumerate(requirements, 1):
            req_id = req.get("requirement_id", f"REQ-{idx:03d}")
            title = req.get("title", req.get("feature_name", "Untitled"))

            if status_callback:
                status_callback(f"Generating test cases for {req_id}: {title}")

            print(f"  [{idx}/{len(requirements)}] {req_id}: {title}...", end=" ")

            try:
                if self.mode == "hybrid":
                    # Hybrid Archive-01 style generation
                    plan = self._generate_hybrid(req, documents)
                else:
                    # Original prompt-only generation
                    plan = self._generate_for_requirement(req, idx, source_texts, doc_file_map)
                
                tc_count = len(plan.get("test_cases", []))
                total_test_cases += tc_count
                test_plans.append(plan)
                print(f"✓ {tc_count} test case(s)")

            except Exception as e:
                print(f"✗ Error: {e}")
                logger.error("Generation failed for %s: %s", req_id, e, exc_info=True)
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
            "generation_mode": self.mode
        }

        print(f"\n{'='*60}")
        print(f"GENERATION COMPLETE")
        print(f"  Requirements processed: {len(requirements)}")
        print(f"  Total test cases: {total_test_cases}")
        print(f"{'='*60}\n")

        return result

    def _generate_hybrid(self, req: Dict, documents: Dict) -> Dict:
        """Ported Archive-01 logic: loop through scenarios and generate hybrid TCs."""
        # 1. Build rich context
        context = get_feature_context(req, documents)
        
        # 2. Get scenarios
        scenarios = req.get('test_scenarios', [])
        if not scenarios:
            scenarios = ["Full feature functionality"]
            
        test_cases = []
        for i, sc in enumerate(scenarios, 1):
            if isinstance(sc, dict):
                sc_name = sc.get('scenario_name', f"Scenario {i}")
            elif isinstance(sc, str) and sc.startswith('{'):
                # Handle stringified dicts sometimes returned by Phase 1
                try:
                    import ast
                    sc_dict = ast.literal_eval(sc)
                    sc_name = sc_dict.get('scenario_name', f"Scenario {i}") if isinstance(sc_dict, dict) else sc
                except:
                    sc_name = sc
            else:
                sc_name = sc if sc else f"Scenario {i}"
            
            # 3. Generate hybrid TC
            tc_data = self.scenario_gen.generate_for_scenario(req, sc_name, context)
            
            # 4. Map to TestCaseEditorDTO
            title_prefix = req.get('title') or req.get('feature_name') or 'Requirement'
            preconditions = tc_data.get('preconditions', [])
            prerequisites_str = "\n".join([f"• {p}" for p in preconditions]) if preconditions else ""
            tc_steps = [
                {
                    "type": "TestCaseStepDTO",
                    "orderNumber": idx,
                    "description": s.get("action", ""),
                    "expectedResult": s.get("expected_result", ""),
                    "blocked": False
                }
                for idx, s in enumerate(tc_data.get('steps', []))
            ]
            test_cases.append({
                "type": "TestCaseEditorDTO",
                "title": sc_name,
                "description": tc_data.get('description', f"Test {sc_name} Feature"),
                "requirementId": req.get('requirement_id', req.get('id', 1)),
                "status": "DRAFT",
                "testPhases": [
                    "FUNCTIONAL_TESTING",
                    "END_TO_END_TESTING",
                    "DEPLOYMENT_VERIFICATION_TESTING"
                ],
                "testTypes": ["UI"],
                "prerequisites": prerequisites_str,
                "expectedResult": f"<p>{tc_data.get('expected_result', 'Calculated per step')}</p>",
                "testCaseSteps": tc_steps,
                "assignedTags": [],
                "relatedSystems": [
                    {
                        "type": "SystemSummaryDTO",
                        "id": "bdd66fa1-9578-4d72-9a19-2012eaebf9d0",
                        "name": "Katsu Test",
                        "description": "Katsu product testing",
                        "primeId": "a87205d8-c33f-4f5a-8f56-e9ecbd5c3813"
                    }
                ],
                "executionConfigurations": [],
                "attachments": [],
                "links": [],
                "watcherIds": [],
                "executionConfiguration": None
            })
            
        return {
            "requirement_id": req.get("requirement_id", ""),
            "requirement_title": req.get("title", req.get("feature_name", "")),
            "test_cases": test_cases,
            "total_count": len(test_cases)
        }

    # ─── Private Methods ──────────────────────────────────────────────────

    def _generate_for_requirement(
        self,
        req: Dict,
        index: int,
        source_texts: Dict[str, str] = None,
        doc_file_map: Dict[str, str] = None,
    ) -> Dict:
        """Generate test cases for a single requirement."""
        source_texts = source_texts or {}
        doc_file_map = doc_file_map or {}

        # Build the prompt with all available context
        prompt = self._build_prompt(req, index)

        # Inject original document context — exact pages first, keyword fallback
        if doc_file_map or source_texts:
            context = self._extract_relevant_context(req, source_texts, doc_file_map)
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

        # Transform each TC into TestCaseEditorDTO
        req_id = req.get("requirement_id", f"REQ-{index:03d}")
        for tc in parsed.get("test_cases", []):
            # Map phase and type to enum arrays
            phase = tc.pop("test_phase", "E2E")
            tc_type = tc.pop("test_type", "Functional")
            tc["testPhases"] = [TEST_PHASE_MAP.get(phase, "END_TO_END_TESTING")]
            tc["testTypes"] = [TEST_TYPE_MAP.get(tc_type, "UI")]

            # Add orderNumber, type, blocked to each step
            raw_steps = tc.get("testCaseSteps", [])
            tc["testCaseSteps"] = [
                {
                    "type": "TestCaseStepDTO",
                    "orderNumber": idx,
                    "description": s.get("description", ""),
                    "expectedResult": s.get("expectedResult", ""),
                    "blocked": False
                }
                for idx, s in enumerate(raw_steps)
            ]

            # Set required fields
            tc["type"] = "TestCaseEditorDTO"
            tc["requirementId"] = req.get('id', req_id)
            tc["status"] = "DRAFT"
            
            # Use multi-phase default if not specified
            if not tc.get("testPhases"):
                tc["testPhases"] = [
                    "FUNCTIONAL_TESTING",
                    "END_TO_END_TESTING",
                    "DEPLOYMENT_VERIFICATION_TESTING"
                ]
                
            tc.setdefault("prerequisites", "Valid user credentials; access to the application")
            
            # Wrap overall expected result in <p> tag
            raw_expected = tc.get("expectedResult", "Feature works as described in requirement")
            if not raw_expected.startswith("<p>"):
                tc["expectedResult"] = f"<p>{raw_expected}</p>"
            
            tc.setdefault("assignedTags", [])
            tc.setdefault("relatedSystems", [
                {
                    "type": "SystemSummaryDTO",
                    "id": "bdd66fa1-9578-4d72-9a19-2012eaebf9d0",
                    "name": "Katsu Test",
                    "description": "Katsu product testing",
                    "primeId": "a87205d8-c33f-4f5a-8f56-e9ecbd5c3813"
                }
            ])
            tc.setdefault("executionConfigurations", [])
            tc.setdefault("attachments", [])
            tc.setdefault("links", [])
            tc.setdefault("watcherIds", [])
            tc.setdefault("executionConfiguration", None)

        return parsed

    def _extract_relevant_context(
        self,
        req: Dict,
        source_texts: Dict[str, str],
        doc_file_map: Dict[str, str] = None,
        max_chars: int = 4000,
    ) -> str:
        """
        Extract the most precise context for a requirement.

        Strategy 1 (PREFERRED): Exact page extraction
          - Uses metadata.source_file  → picks the exact PDF this BR came from
          - Uses metadata.page_start / page_end → extracts only those pages
          - No guessing, no keyword search — the exact source text

        Strategy 2 (FALLBACK): Keyword search on full pre-extracted text
          - Used when doc_file_map is not available or page extraction fails
        """
        doc_file_map = doc_file_map or {}

        # ── Read metadata from the BR ──────────────────────────────────────
        metadata = req.get("metadata", {})
        source_file = metadata.get("source_file") or req.get("source_file", "")
        page_start = metadata.get("page_start")
        page_end = metadata.get("page_end")

        # ── Strategy 1: Exact page extraction ─────────────────────────────
        if source_file and page_start is not None and doc_file_map:
            # Find the matching local file path (exact or partial filename match)
            file_path = doc_file_map.get(source_file)
            if not file_path:
                for fname, fpath in doc_file_map.items():
                    if source_file in fname or fname in source_file:
                        file_path = fpath
                        break

            if file_path and file_path.lower().endswith(".pdf"):
                try:
                    import fitz  # PyMuPDF
                    doc = fitz.open(file_path)
                    # page_start/page_end are 1-based; fitz uses 0-based index
                    p_start = max(0, int(page_start) - 1)
                    p_end = min(len(doc) - 1, int(page_end) if page_end is not None else p_start + 2)
                    pages_text = []
                    for p in range(p_start, p_end + 1):
                        pages_text.append(doc[p].get_text())
                    doc.close()
                    extracted = "\n".join(pages_text).strip()
                    if extracted:
                        logger.info(
                            "Exact page context: %s pages %s-%s → %d chars",
                            source_file, page_start, page_end, len(extracted),
                        )
                        return extracted[:max_chars]
                except Exception as e:
                    logger.warning(
                        "Exact page extraction failed for %s p%s-%s: %s",
                        source_file, page_start, page_end, e,
                    )

        # ── Strategy 2: Keyword search fallback ───────────────────────────
        if not source_texts:
            return ""

        # Pick the right document text
        doc_text = ""
        if source_file and source_file in source_texts:
            doc_text = source_texts[source_file]
        else:
            for name, text in source_texts.items():
                if source_file and (source_file in name or name in source_file):
                    doc_text = text
                    break
            if not doc_text and source_texts:
                doc_text = "\n\n".join(source_texts.values())

        if not doc_text:
            return ""

        doc_lower = doc_text.lower()
        title = req.get("title", "")
        title_words = [
            w for w in title.split()
            if len(w) > 3 and w.lower() not in {
                'the', 'and', 'for', 'with', 'from', 'that', 'this',
                'must', 'should', 'system', 'user', 'based', 'management', 'support',
            }
        ]

        for i in range(len(title_words) - 1):
            phrase = f"{title_words[i]} {title_words[i+1]}".lower()
            pos = doc_lower.find(phrase)
            if pos >= 0:
                return doc_text[max(0, pos - 300): pos + 2500][:max_chars]

        for word in reversed(title_words):
            pos = doc_lower.find(word.lower())
            if pos >= 0:
                return doc_text[max(0, pos - 300): pos + 2500][:max_chars]

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

        # Format existing test steps (from Phase 1 requirement_engine)
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
