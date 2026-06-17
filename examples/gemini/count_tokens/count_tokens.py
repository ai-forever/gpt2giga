"""Gemini count_tokens example via gpt2giga."""

from google import genai
from google.genai import types

api_version = "v1"
client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
    ),
)

result = client.models.count_tokens(
    model="GigaChat-2-Max",
    contents=[
        "Объясни, чем отличаются списки и кортежи в Python.",
        "Добавь короткий пример кода.",
    ],
)

print(f"Всего токенов во входе: {result.total_tokens}")
