"""Gemini embeddings example via gpt2giga."""

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)

model_name = "EmbeddingsGigaR"
texts = [
    "hello from gpt2giga",
    "gemini compatibility layer",
]

print("Using embeddings model:", model_name)
response = client.models.embed_content(
    model=model_name,
    contents=texts,
)

for index, (source_text, embedding) in enumerate(zip(texts, response.embeddings)):
    preview = embedding.values[:5] if embedding.values else []
    print(f"{index}: {source_text!r} -> {preview}")
