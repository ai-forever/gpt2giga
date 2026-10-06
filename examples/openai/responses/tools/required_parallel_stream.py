"""Replay all streamed calls by ID, even when they use the same function name."""

import json

from openai import OpenAI

api_version = "v2"
if api_version != "v2":
    print("Required/parallel tools need GigaChat v2; skipping.")
    raise SystemExit(0)
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")
tools = [
    {
        "type": "function",
        "name": "get_room",
        "description": "Узнать вместимость одной аудитории.",
        "parameters": {
            "type": "object",
            "properties": {"room": {"type": "string", "enum": ["A-101", "A-102"]}},
            "required": ["room"],
            "additionalProperties": False,
        },
    }
]
history = [
    {
        "role": "user",
        "content": "Вызови get_room для A-101 и A-102 параллельно и сравни вместимость.",
    }
]
completed = None
with client.responses.create(
    model="GigaChat-2-Max",
    input=history,
    tools=tools,
    tool_choice="required",
    parallel_tool_calls=True,
    max_output_tokens=1024,
    store=False,
    stream=True,
) as stream:
    for event in stream:
        if (
            event.type == "response.output_item.done"
            and event.item.type == "function_call"
        ):
            print(f"{event.item.call_id}: {event.item.name}({event.item.arguments})")
        elif event.type == "response.completed":
            completed = event.response
if completed is None:
    raise RuntimeError("Поток завершился без response.completed")
calls = [item for item in completed.output if item.type == "function_call"]
if not calls:
    raise RuntimeError("Upstream не вернул обязательный вызов функции")
# 'required' requires a call, not a particular count; process every returned call.
print(f"Число вызовов: {len(calls)}")
state_id = (completed.metadata or {}).get("gigachat_tool_state_id")
for item in completed.output:
    replay = item.model_dump(exclude_none=True)
    if item.type == "function_call" and state_id:
        replay["tools_state_id"] = state_id  # Gateway extension, separate from call_id.
    history.append(replay)
for call in reversed(calls):  # ID matching also works with reversed result order.
    if call.name != "get_room":
        raise ValueError(f"Неизвестная функция: {call.name}")
    room = json.loads(call.arguments)["room"]
    result = {"room": room, "capacity": {"A-101": 24, "A-102": 40}[room]}
    history.append(
        {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(result, ensure_ascii=False),
        }
    )
final = client.responses.create(
    model="GigaChat-2-Max",
    input=history,
    tools=tools,
    tool_choice="none",  # Finish using the collected results; do not require another call.
    max_output_tokens=256,
    store=False,
)
print(final.output_text)
print("Sampling defaults:", final.temperature, final.top_p)  # Unknown => None.
