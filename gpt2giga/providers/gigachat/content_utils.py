import ast
import json
from typing import Any


def ensure_json_object_str(value: Any) -> str:
    """Ensure a tool result is serialized as a JSON-object string."""
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
        parsed: Any = value.strip()
        for _ in range(3):
            if not isinstance(parsed, str):
                break
            if parsed == "":
                return "{}"
            try:
                parsed = json.loads(parsed)
                continue
            except json.JSONDecodeError:
                break

        if isinstance(parsed, dict):
            return json.dumps(parsed, ensure_ascii=False)
        if isinstance(parsed, (list, int, float, bool)) or parsed is None:
            return json.dumps({"result": parsed}, ensure_ascii=False)

        if isinstance(parsed, str):
            try:
                literal_value = ast.literal_eval(parsed)
                if isinstance(literal_value, dict):
                    return json.dumps(literal_value, ensure_ascii=False)
                return json.dumps({"result": literal_value}, ensure_ascii=False)
            except Exception:
                return json.dumps({"result": parsed}, ensure_ascii=False)

    return json.dumps({"result": value}, ensure_ascii=False)
