"""Gemini streaming example via gpt2giga."""

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)

for chunk in client.models.generate_content_stream(
    model="GigaChat-2-Max",
    contents="Напиши короткий список идей для pet-проекта на Python.",
):
    if chunk.text:
        print(chunk.text, end="", flush=True)

print()
