"""Require a v2 tool call, return its result, and inspect Anthropic cache usage."""

import json
from uuid import uuid4

from anthropic import Anthropic

api_version = "v2"
if api_version != "v2":
    print("tool_choice:any requires GigaChat v2; skipping.")
    raise SystemExit(0)
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
headers = {"X-Session-ID": str(uuid4())}
tools = [
    {
        "name": "get_room",
        "description": "Узнать вместимость аудитории A-101.",
        "input_schema": {
            "type": "object",
            "properties": {"room": {"type": "string", "enum": ["A-101"]}},
            "required": ["room"],
        },
    }
]
messages = [{"role": "user", "content": "Сколько мест в A-101? Используй инструмент."}]
first = client.messages.create(
    model="GigaChat-2-Max",
    messages=messages,
    tools=tools,
    tool_choice={"type": "any", "disable_parallel_tool_use": True},
    max_tokens=512,
    extra_headers=headers,
)
results = []
for block in first.content:
    if block.type == "tool_use":
        if block.name != "get_room" or block.input.get("room") != "A-101":
            raise ValueError("Неожиданные имя функции или аргументы")
        print("tool_use_id:", block.id)
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps({"room": "A-101", "capacity": 24}),
            }
        )
if not results:
    raise RuntimeError("Upstream не вернул обязательный tool_use")
messages.extend(
    [
        {
            "role": "assistant",
            "content": [block.model_dump() for block in first.content],
        },
        {"role": "user", "content": results},
    ]
)
final = client.messages.create(
    model="GigaChat-2-Max",
    messages=messages,
    tools=tools,
    tool_choice={"type": "none"},
    max_tokens=256,
    extra_headers=headers,
)
for block in final.content:
    if block.type == "text":
        print(block.text)
# Anthropic input_tokens excludes cache reads, unlike OpenAI prompt_tokens.
print("Usage:", final.usage.model_dump(exclude_none=True))
