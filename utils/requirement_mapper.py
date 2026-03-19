"""
Requirement Mapper — converts an extracted requirement dict into the
Java backend payload format (RequirementDto).

Single source of truth for the JSON structure sent to the Java backend.
"""
from datetime import datetime, timezone


def _to_string_list(items) -> list:
    """Ensure every element in a list is a plain string (Java expects List<String>)."""
    if not items:
        return []
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            val = (
                item.get("criterion")
                or item.get("criteria")
                or item.get("scenario")
                or item.get("assumption")
                or item.get("ambiguity")
                or item.get("text")
                or item.get("description")
                or item.get("value")
                or str(item)
            )
            result.append(str(val))
        else:
            result.append(str(item))
    return result


def _to_test_steps(items) -> list:
    """
    Convert test steps into TestStepDto format:
      { "step_num": int, "action": str, "expected_result": str, "test_data": str }
    """
    if not items:
        return []
    result = []
    for i, item in enumerate(items, start=1):
        if isinstance(item, dict):
            result.append({
                "step_num": item.get("step_num", item.get("stepNum", i)),
                "action": str(item.get("action", item.get("step", ""))),
                "expected_result": str(item.get("expected_result", item.get("expectedResult", ""))),
                "test_data": str(item.get("test_data", item.get("testData", ""))),
            })
        elif isinstance(item, str):
            result.append({
                "step_num": i,
                "action": item,
                "expected_result": "",
                "test_data": "",
            })
    return result


def _to_supporting_context(items) -> list:
    """
    Convert supporting context into SupportingContextDto format:
      { "doc": str, "text": str, "relevance_score": int }
    """
    if not items:
        return []
    result = []
    for item in items:
        if isinstance(item, dict):
            result.append({
                "doc": str(item.get("doc", item.get("source_file", ""))),
                "text": str(item.get("text", "")),
                "relevance_score": item.get("relevance_score", 0),
            })
        elif isinstance(item, str):
            result.append({"doc": "", "text": item, "relevance_score": 0})
    return result


def to_payload(req: dict, validation_confirmed: bool = False) -> dict:
    """
    Convert an extracted requirement dict to the Java backend payload.
    Matches RequirementDto exactly.

    Args:
        req: Raw requirement from the extraction pipeline.
        validation_confirmed: Always False by default — requires manual human verification.
    """
    conf_raw = req.get("confidence", 0.95)

    if isinstance(conf_raw, (int, float)):
        conf_str = "high" if conf_raw >= 0.8 else "medium" if conf_raw >= 0.5 else "low"
        conf_score = float(conf_raw)
    else:
        conf_str = str(conf_raw)
        conf_score = 0.95

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "is_requirement": True,
        "short_title": req.get("title") or req.get("feature_name") or req.get("short_title", ""),
        "description": req.get("description", ""),
        "user_story": req.get("user_story", ""),

        # Top-level fields
        "system": req.get("system", ""),
        "category": req.get("category", ""),
        "requirements_text": req.get("requirements_text", ""),
        "confidence_score": conf_score,
        "is_duplicate": req.get("is_duplicate", False),

        # Lists — Java expects List<String> for these
        "acceptance_criteria": _to_string_list(req.get("acceptance_criteria", [])),
        "test_scenarios": _to_string_list(req.get("test_scenarios", [])),
        "assumptions": _to_string_list(req.get("assumptions", [])),
        "ambiguities": _to_string_list(req.get("ambiguities", [])),

        # List<TestStepDto>
        "test_steps": _to_test_steps(req.get("test_steps", [])),

        # List<SupportingContextDto>
        "supporting_context": _to_supporting_context(req.get("supporting_context", [])),

        "confidence": conf_str,
        "extraction_model": "llama-3.3-70b-versatile",
        "extraction_timestamp": now,
        "validation_confirmed": validation_confirmed,

        # MetadataDto — Java expects an OBJECT
        "metadata": {
            "source_file": req.get("source_file", ""),
            "page_start": req.get("page_start", 0),
            "page_end": req.get("page_end", 0),
            "start_line": req.get("line_start", 0),
            "end_line": req.get("line_end", 0),
            "verbatim_text": req.get("requirements_text", ""),
            "extraction_timestamp": now,
            "extraction_model": "llama-3.3-70b-versatile",
            "validation_confirmed": validation_confirmed,
        },
    }
