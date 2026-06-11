from examples.gemini.common import stream_sse

model = "GigaChat-2-Max"

for chunk in stream_sse(
    f"/models/{model}:streamGenerateContent?alt=sse",
    {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Stream one sentence about API gateways."}],
            }
        ],
        "generationConfig": {"maxOutputTokens": 128},
    },
):
    for candidate in chunk.get("candidates", []):
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            if "text" in part:
                print(part["text"], end="", flush=True)
        if candidate.get("finishReason"):
            print(f"\nfinishReason: {candidate['finishReason']}")

usage = chunk.get("usageMetadata") if "chunk" in locals() else None
if usage:
    print("usage:", usage)
