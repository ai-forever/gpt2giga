import ast
import json
from typing import Any


def ensure_json_object_str(value: Any) -> str:
    """
    Ensures the value is a valid JSON object string.

    GigaChat requires function/tool results to be valid JSON objects.
    The SDK `gigachat.models.Messages` expects `content: str`.

    OpenAI-compatible clients often send:
    - dict (ok)
    - JSON string (needs json.loads)
    - double JSON string (needs json.loads multiple times)
    - python-like string (single quotes) — try ast.literal_eval

    Args:
        value: Any value that needs to be converted to JSON object string

    Returns:
        A valid JSON object string
    """
    if value is None:
        return "{}"

    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return json.dumps({"result": str(value)}, ensure_ascii=False)

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, str):
        s: Any = value.strip()
        for _ in range(3):
            if not isinstance(s, str):
                break
            if s == "":
                return "{}"
            try:
                s = json.loads(s)
                continue
            except json.JSONDecodeError:
                break

        if isinstance(s, dict):
            return json.dumps(s, ensure_ascii=False)
        if isinstance(s, (list, int, float, bool)) or s is None:
            return json.dumps({"result": s}, ensure_ascii=False)

        if isinstance(s, str):
            try:
                lit = ast.literal_eval(s)
                if isinstance(lit, dict):
                    return json.dumps(lit, ensure_ascii=False)
                return json.dumps({"result": lit}, ensure_ascii=False)
            except Exception:
                return json.dumps({"result": s}, ensure_ascii=False)

    return json.dumps({"result": value}, ensure_ascii=False)
