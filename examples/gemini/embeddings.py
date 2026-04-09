"""Gemini embeddings example via gpt2giga."""

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)

response = client.models.embed_content(
    model="EmbeddingsGigaR",
    contents=[
        "hello from gpt2giga",
        "gemini compatibility layer",
    ],
)

for index, embedding in enumerate(response.embeddings):
    preview = embedding.values[:5] if embedding.values else []
    print(f"{index}: {preview}")
