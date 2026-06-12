"""Gemini chat session example via gpt2giga."""

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)

chat = client.chats.create(model="GigaChat-2-Max")

first = chat.send_message("Привет! Представься одной фразой.")
print("Первый ответ:")
print(first.text)

second = chat.send_message("Теперь скажи то же самое, но ещё короче.")
print("\nВторой ответ:")
print(second.text)
