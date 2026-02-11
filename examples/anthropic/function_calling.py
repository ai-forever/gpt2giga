"""Anthropic Messages API function calling (tool use) example."""

import json

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

# 1. Define tools
tools = [
    {
        "name": "get_weather",
        "description": "Получить текущую погоду для указанного города.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Название города, например: Москва",
                },
            },
            "required": ["city"],
        },
    },
]


def get_weather(city: str) -> str:
    """Stub function — replace with real API call."""
    return json.dumps({"city": city, "temp": "+5°C", "conditions": "облачно"})


# 2. Send initial request with tools
message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "Какая погода в Москве?"}],
)

print("Первый ответ:", message.stop_reason)

# 3. Process tool use if the model decided to call a function
if message.stop_reason == "tool_use":
    # Find the tool_use block
    tool_use = next(block for block in message.content if block.type == "tool_use")
    print(f"Вызов функции: {tool_use.name}({tool_use.input})")

    # Execute the function
    result = get_weather(**tool_use.input)

    # 4. Send tool result back
    final_message = client.messages.create(
        model="GigaChat-2-Max",
        max_tokens=1024,
        tools=tools,
        messages=[
            {"role": "user", "content": "Какая погода в Москве?"},
            {"role": "assistant", "content": message.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result,
                    }
                ],
            },
        ],
    )

    print("Финальный ответ:", final_message.content[0].text)
else:
    print("Ответ:", message.content[0].text)
