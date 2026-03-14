"""
Requirement Mapper — converts an extracted requirement dict into the
Java backend payload format.

Single source of truth. Previously duplicated in three places with inconsistencies.
"""
from datetime import datetime, timezone


def to_payload(req: dict, validation_confirmed: bool = True) -> dict:
    """
    Convert an extracted requirement dict to the Java backend payload.

    Args:
        req: Raw requirement from the extraction pipeline.
        validation_confirmed: True for pipeline-validated reqs, False for drafts.
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
        "acceptance_criteria": req.get("acceptance_criteria", []),
        "test_steps": req.get("test_steps", []),
        "test_scenarios": req.get("test_scenarios", []),
        "assumptions": req.get("assumptions", []),
        "ambiguities": req.get("ambiguities", []),
        "confidence": conf_str,
        "extraction_model": "llama-3.3-70b-versatile",
        "extraction_timestamp": now,
        "validation_confirmed": validation_confirmed,
        "metadata": {
            "system": req.get("system", ""),
            "category": req.get("category", ""),
            "requirements_text": req.get("requirements_text", ""),
            "confidence_score": conf_score,
            "source_file": req.get("source_file", ""),
            "page_start": req.get("page_start", 0),
            "page_end": req.get("page_end", 0),
            "start_line": req.get("line_start", 0),
            "end_line": req.get("line_end", 0),
            "verbatim_text": req.get("requirements_text", ""),
            "supporting_context": req.get("supporting_context", []),
            "extraction_model": "llama-3.3-70b-versatile",
            "extraction_timestamp": now,
            "validation_confirmed": validation_confirmed,
        },
    }
