"""Anthropic Messages API token counting example.

Count input tokens before sending a request, useful for
estimating costs and staying within context limits.
"""

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

# 1. Simple message token count
result = client.messages.count_tokens(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Расскажи коротко о Python."},
    ],
)

print(f"Простое сообщение: {result.input_tokens} токенов")

# 2. Token count with system prompt
result_with_system = client.messages.count_tokens(
    model="GigaChat-2-Max",
    system="Ты — опытный программист. Отвечай кратко и по делу.",
    messages=[
        {"role": "user", "content": "Что такое декораторы в Python?"},
    ],
)

print(f"С системным промптом: {result_with_system.input_tokens} токенов")

# 3. Token count with tools
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

result_with_tools = client.messages.count_tokens(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Какая погода в Москве?"},
    ],
    tools=tools,
)

print(f"С определениями инструментов: {result_with_tools.input_tokens} токенов")

# 4. Multi-turn conversation token count
result_multi = client.messages.count_tokens(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Привет!"},
        {"role": "assistant", "content": "Здравствуйте! Чем могу помочь?"},
        {"role": "user", "content": "Расскажи о машинном обучении."},
    ],
)

print(result_multi)
print(f"Многоходовый диалог: {result_multi.input_tokens} токенов")
