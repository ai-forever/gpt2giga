"""Basic Gemini generate_content example via gpt2giga."""

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)

response = client.models.generate_content(
    model="GigaChat-2-Max",
    contents="Расскажи в двух предложениях, что такое Python.",
)

print(response.text)
