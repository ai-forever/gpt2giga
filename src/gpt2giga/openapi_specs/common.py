"""Shared OpenAPI schema helpers."""

from typing import Any, Dict, Optional


def _request_body_oneof(
    *,
    minimal_schema: Dict[str, Any],
    full_schema: Dict[str, Any],
    minimal_example: Dict[str, Any],
    full_example: Dict[str, Any],
    extra_examples: Optional[Dict[str, Dict[str, Any]]] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Build OpenAPI requestBody with oneOf and examples."""
    examples: Dict[str, Dict[str, Any]] = {
        "minimal": {"summary": "Minimal request", "value": minimal_example},
        "full": {"summary": "Full request", "value": full_example},
    }
    if extra_examples:
        examples.update(extra_examples)

    request_body: Dict[str, Any] = {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"oneOf": [minimal_schema, full_schema]},
                "examples": examples,
            }
        },
    }
    if description:
        request_body["description"] = description

    return {"requestBody": request_body}
