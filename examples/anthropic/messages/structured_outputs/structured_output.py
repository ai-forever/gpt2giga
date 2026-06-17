"""Anthropic Messages API structured output example."""

import json

from anthropic import Anthropic

api_version = "v2"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=512,
    messages=[
        {
            "role": "user",
            "content": (
                "Extract contact data from this note: "
                "Maria Ivanova, maria@example.com, product lead."
            ),
        },
    ],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "role": {"type": "string"},
                },
                "required": ["name", "email", "role"],
                "additionalProperties": False,
            },
        }
    },
)

data = json.loads(message.content[0].text)
print(json.dumps(data, ensure_ascii=False, indent=2))
