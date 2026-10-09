"""Parallel tool use through the Anthropic Messages API."""

import json

from anthropic import Anthropic

api_version = "v2"
if api_version != "v2":
    print("Parallel tool use requires the GigaChat v2 contract; skipping.")
    raise SystemExit(0)
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

tools = [
    {
        "name": "get_weather",
        "description": "Получить текущую погоду для города.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
    {
        "name": "get_rate",
        "description": "Получить курс валюты к рублю.",
        "input_schema": {
            "type": "object",
            "properties": {"currency": {"type": "string"}},
            "required": ["currency"],
        },
    },
]


def get_weather(city: str) -> dict:
    """Return a deterministic weather stub."""
    return {"city": city, "temperature_c": 5, "conditions": "облачно"}


def get_rate(currency: str) -> dict:
    """Return a deterministic exchange-rate stub."""
    return {"currency": currency, "rubles": 90.5}


functions = {"get_weather": get_weather, "get_rate": get_rate}
messages = [
    {
        "role": "user",
        "content": (
            "Одновременно вызови обе функции одним ответом: узнай погоду в Москве "
            "и курс USD. Не отвечай текстом до получения результатов функций."
        ),
    }
]

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=messages,
    tools=tools,
    tool_choice={"type": "auto", "disable_parallel_tool_use": False},
)
tool_uses = [block for block in message.content if block.type == "tool_use"]
names = [tool_use.name for tool_use in tool_uses]
if len(tool_uses) != 2 or set(names) != set(functions):
    raise RuntimeError(f"Ожидались два параллельных вызова, получено: {names}")
if any(not tool_use.id for tool_use in tool_uses):
    raise RuntimeError("Каждый параллельный вызов должен иметь собственный id")

messages.append({"role": "assistant", "content": message.content})
messages.append(
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(
                    functions[tool_use.name](**tool_use.input),
                    ensure_ascii=False,
                ),
            }
            for tool_use in tool_uses
        ],
    }
)

final = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=messages,
    tools=tools,
    tool_choice={"type": "none"},
)

print("Параллельные вызовы:")
for tool_use in tool_uses:
    print(f"- {tool_use.id}: {tool_use.name}")
print("\nФинальный ответ:")
print("\n".join(block.text for block in final.content if block.type == "text"))
