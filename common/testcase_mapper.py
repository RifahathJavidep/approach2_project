"""
Test Case Mapper — converts generated test cases into the
Java backend payload format (TestCaseEditorDTO).
"""

def _trunc(text: str, length: int = 250) -> str:
    """Helper to ensure fields don't exceed DB varchar(255) limits."""
    if not text:
        return ""
    return text[:length] if len(text) > length else text

def to_test_case_payload(tc: dict, requirement_id: int = None) -> dict:
    """
    Convert a single AI-generated test case into a TestCaseEditorDto.
    Matches com.katsu.testcase.dto.TestCaseEditorDto exactly.
    """
    # 1. Map Steps to TestCaseStepDto
    steps = []
    raw_steps = tc.get("steps", tc.get("test_steps", []))
    for i, s in enumerate(raw_steps):
        description = s.get("action", s.get("step", ""))
        expected = s.get("expected_result", s.get("expectedResult", ""))
        
        steps.append({
            "id": None,
            "type": "TestCaseStepDto",  # Matches Java class name case
            "orderNumber": i,
            "description": _trunc(description, 500), # Steps often allow more, but truncating to be safe
            "expectedResult": _trunc(expected, 500),
            "blocked": False
        })

    # 2. Build the main DTO (TestCaseEditorDto)
    return {
        "id": None,
        "requirementId": requirement_id or tc.get("requirement_id"),
        "title": _trunc(tc.get("title", tc.get("name", "Test Case created using AI")), 250),
        "description": _trunc(tc.get("description", ""), 250),
        "status": "DRAFT",
        "complexity": tc.get("complexity", 1),
        "authorId": tc.get("author_id", "AI_GENERATOR"),
        "testPhases": [
            "FUNCTIONAL_TESTING",
            "END_TO_END_TESTING",
            "DEPLOYMENT_VERIFICATION_TESTING"
        ],
        "testTypes": [
            "UI"
        ],
        "prerequisites": _trunc(tc.get("preconditions", tc.get("prerequisites", "")), 250),
        "expectedResult": _trunc(tc.get("expected_result", tc.get("expectedResult", "")), 250),
        "testCaseSteps": steps,
        "assignedTags": [],
        "relatedSystems": [],
        "watcherIds": []
    }

def map_test_plan_to_payload(result: dict, requirements_with_ids: list = None) -> list:
    """
    Takes the full TestGenPipeline result and flattens it into a list 
    of mapped TestCaseEditorDTOs.
    """
    all_mapped = []
    
    # Map requirement short_title to its DB ID for easy lookup
    id_map = {}
    if requirements_with_ids:
        for r in requirements_with_ids:
            title = r.get("short_title")
            db_id = r.get("id")
            if title and db_id:
                id_map[title] = db_id

    test_plans = result.get("test_plan", {}).get("test_plans", [])
    for plan in test_plans:
        req_title = plan.get("requirement_title")
        req_id = id_map.get(req_title)
        
        test_cases = plan.get("test_cases", [])
        for tc in test_cases:
            all_mapped.append(to_test_case_payload(tc, requirement_id=req_id))
            
    return all_mapped
