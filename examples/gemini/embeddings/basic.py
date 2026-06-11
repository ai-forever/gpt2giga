from examples.gemini.common import print_json, request_json

model = "Embeddings"

single = request_json(
    "POST",
    f"/models/{model}:embedContent",
    {"content": {"parts": [{"text": "Embed this sentence."}]}},
)

batch = request_json(
    "POST",
    f"/models/{model}:batchEmbedContents",
    {
        "requests": [
            {"content": {"parts": [{"text": "First sentence."}]}},
            {"content": {"parts": [{"text": "Second sentence."}]}},
        ]
    },
)

print("single embedding:")
print_json(
    {
        "value_count": len(single["embedding"]["values"]),
        "usageMetadata": single.get("usageMetadata"),
    }
)

print("\nbatch embeddings:")
print_json({"count": len(batch["embeddings"])})
