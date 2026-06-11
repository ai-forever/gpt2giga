"""Prepared Gemini Batch API example.

The default public Gemini router does not mount Batch routes yet. Run this only
against an app that explicitly includes ``gpt2giga.routers.gemini.batches``.
"""

from examples.gemini.common import print_json, request_json

model = "GigaChat-2-Max"

operation = request_json(
    "POST",
    f"/models/{model}:batchGenerateContent",
    {
        "batch": {
            "displayName": "demo-gemini-batch",
            "inputConfig": {
                "requests": {
                    "requests": [
                        {
                            "request": {
                                "contents": [
                                    {
                                        "role": "user",
                                        "parts": [{"text": "Say hello from batch."}],
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
            "outputConfig": {"inlineResponse": {}},
        }
    },
)

print("operation:")
print_json(operation)

batches = request_json("GET", "/batches")
print("\nbatches:")
print_json(batches)
