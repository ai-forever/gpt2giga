"""OpenAI embeddings example via gpt2giga."""

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

model_name = "EmbeddingsGigaR"
texts = [
    "hello from gpt2giga",
    "openai compatibility layer",
]

print("Using embeddings model:", model_name)
response = client.embeddings.create(model=model_name, input=texts)

for item, source_text in zip(response.data, texts):
    preview = item.embedding[:5]
    print(f"{item.index}: {source_text!r} -> {preview}")
