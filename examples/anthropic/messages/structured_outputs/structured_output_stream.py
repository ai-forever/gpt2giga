"""Anthropic Messages API streaming structured output example."""

from anthropic import Anthropic

api_version = "v2"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

with client.messages.stream(
    model="GigaChat-2-Max",
    max_tokens=512,
    messages=[
        {
            "role": "user",
            "content": (
                "Return project status as JSON. "
                "Project Atlas is on track, risk is low, next step is QA."
            ),
        },
    ],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "status": {"type": "string"},
                    "risk": {"type": "string"},
                    "next_step": {"type": "string"},
                },
                "required": ["project", "status", "risk", "next_step"],
                "additionalProperties": False,
            },
        }
    },
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)

print()
