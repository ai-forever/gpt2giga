from examples.gemini.common import print_json, request_json

model = "GigaChat-2-Max"

response = request_json(
    "POST",
    f"/models/{model}:generateContent",
    {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Use the lookup tool for the weather in Moscow."}],
            }
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "lookup_weather",
                        "description": "Return weather by city.",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    }
                ]
            }
        ],
        "toolConfig": {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": ["lookup_weather"],
            }
        },
    },
)

print_json(response)
