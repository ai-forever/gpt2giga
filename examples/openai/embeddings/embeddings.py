"""OpenAI embeddings example via gpt2giga."""

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

model_name = "EmbeddingsGigaR"
dimensions = 2560
texts = [
    "hello from gpt2giga",
    "openai compatibility layer",
]

print("Using embeddings model:", model_name)
response = client.embeddings.create(
    model=model_name,
    input=texts,
    dimensions=dimensions,
    encoding_format="float",
)

for item, source_text in zip(response.data, texts):
    preview = item.embedding[:5]
    print(f"{item.index}: {source_text!r} -> {preview}")

base64_response = client.embeddings.create(
    model=model_name,
    input=texts,
    dimensions=dimensions,
    encoding_format="base64",
)
print("base64 embedding preview:", base64_response.data[0].embedding[:80])
