"""
Utility helpers for test case generation.
Ported from ai_test_case with minimal changes.
"""

import re
from typing import Any


def clean_for_json(obj: Any) -> Any:
    """
    Recursively clean an object for JSON serialization.
    Handles non-serializable types gracefully.
    """
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [clean_for_json(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    else:
        return str(obj)


def to_excel_safe(value: Any) -> str:
    """
    Convert a value to an Excel-safe string.
    Strips illegal XML characters that openpyxl would reject.
    """
    if value is None:
        return ""
    text = str(value)
    # Remove XML-illegal characters (control chars except \t, \n, \r)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def safe_json_serialize(obj: Any) -> str:
    """Serialize to JSON, handling non-standard types."""
    import json
    return json.dumps(clean_for_json(obj), indent=2, ensure_ascii=False)
