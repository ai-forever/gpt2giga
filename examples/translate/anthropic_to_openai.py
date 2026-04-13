"""Translate an Anthropic Messages payload into OpenAI chat format."""

from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GPT2GIGA_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("GPT2GIGA_API_KEY", "0")

payload = {
    "from": "anthropic",
    "to": "openai",
    "kind": "chat",
    "payload": {
        "model": "claude-compatible",
        "system": "Answer briefly.",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Explain normalizers."}],
            }
        ],
        "max_tokens": 256,
        "temperature": 0.3,
    },
}

response = httpx.post(
    f"{BASE_URL}/translate",
    headers={"x-api-key": API_KEY},
    json=payload,
    timeout=30.0,
)
response.raise_for_status()

body = response.json()
print("Endpoint:", body.get("endpoint"))
print("Warnings:", body.get("warnings"))
print(json.dumps(body["payload"], ensure_ascii=False, indent=2))
