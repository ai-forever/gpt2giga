"""Schemas for the explicitly named GigaChat utility operations."""


def utility_openapi_extra(operation: str) -> dict:
    """Describe the native JSON input without implying vendor API parity."""
    if operation == "functions/validate":
        schema = {
            "type": "object",
            "description": "Native GigaChat function schema.",
            "additionalProperties": True,
        }
    else:
        text = {"type": "string"}
        if operation == "tokens/count":
            text = {
                "oneOf": [
                    text,
                    {"type": "array", "minItems": 1, "items": {"type": "string"}},
                ]
            }
        schema = {
            "type": "object",
            "required": ["input"],
            "properties": {"input": text, "model": {"type": "string"}},
        }
    return {
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": schema}},
        }
    }
