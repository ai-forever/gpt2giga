"""Validate Anthropic batch rows via /batches/validate."""

from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GPT2GIGA_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("GPT2GIGA_API_KEY", "0")

payload = {
    "api_format": "anthropic",
    "requests": [
        {
            "custom_id": "req-1",
            "params": {
                "model": "GigaChat-2-Max",
                "max_tokens": 64,
                "messages": [
                    {
                        "role": "user",
                        "content": "Summarize Python in one sentence.",
                    }
                ],
            },
        },
        {
            "custom_id": "req-2",
            "params": {
                "model": "GigaChat-2-Max",
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "Explain adapters briefly."}],
            },
        },
    ],
}

response = httpx.post(
    f"{BASE_URL}/batches/validate",
    headers={"x-api-key": API_KEY},
    json=payload,
    timeout=30.0,
)
response.raise_for_status()

body = response.json()
print("Valid:", body["valid"])
print("Detected format:", body.get("detected_format"))
print("Summary:", body["summary"])
print(json.dumps(body["issues"], ensure_ascii=False, indent=2))
