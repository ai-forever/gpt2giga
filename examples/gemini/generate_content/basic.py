from examples.gemini.common import print_json, request_json

model = "GigaChat-2-Max"

response = request_json(
    "POST",
    f"/models/{model}:generateContent",
    {
        "systemInstruction": {"parts": [{"text": "Answer concisely."}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Write a short haiku about proxy servers."}],
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 128,
        },
    },
)

print_json(response)
