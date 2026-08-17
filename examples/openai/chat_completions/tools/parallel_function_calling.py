"""Parallel function calling through OpenAI Chat Completions."""

import json

from openai import OpenAI

api_version = "v2"
if api_version != "v2":
    print("Parallel function calling requires the GigaChat v2 contract; skipping.")
    raise SystemExit(0)
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Получить текущую погоду для города.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_rate",
            "description": "Получить курс валюты к рублю.",
            "parameters": {
                "type": "object",
                "properties": {"currency": {"type": "string"}},
                "required": ["currency"],
            },
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

response = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=messages,
    tools=tools,
    parallel_tool_calls=True,
)
assistant = response.choices[0].message
tool_calls = assistant.tool_calls or []
names = [tool_call.function.name for tool_call in tool_calls]
if len(tool_calls) != 2 or set(names) != set(functions):
    raise RuntimeError(f"Ожидались два параллельных вызова, получено: {names}")
if any(not tool_call.id for tool_call in tool_calls):
    raise RuntimeError("Каждый параллельный вызов должен иметь собственный id")

messages.append(assistant.model_dump(exclude_none=True))
for tool_call in tool_calls:
    arguments = json.loads(tool_call.function.arguments)
    result = functions[tool_call.function.name](**arguments)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False),
        }
    )

final = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=messages,
    tools=tools,
    tool_choice="none",
)

print("Параллельные вызовы:")
for tool_call in tool_calls:
    print(f"- {tool_call.id}: {tool_call.function.name}")
print("\nФинальный ответ:")
print(final.choices[0].message.content)
