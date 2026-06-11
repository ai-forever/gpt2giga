from examples.gemini.common import print_json, request_json

model = "GigaChat-2-Max"

response = request_json(
    "POST",
    f"/models/{model}:countTokens",
    {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "How many tokens are in this request?"}],
            }
        ],
        "systemInstruction": {"parts": [{"text": "Count all text parts."}]},
    },
)

print_json(response)
