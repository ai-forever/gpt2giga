"""Translate an OpenAI chat payload into Gemini generateContent format."""

from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GPT2GIGA_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("GPT2GIGA_API_KEY", "0")

payload = {
    "from": "openai",
    "to": "gemini",
    "kind": "chat",
    "payload": {
        "model": "GigaChat-2-Max",
        "messages": [
            {"role": "system", "content": "Answer briefly."},
            {"role": "user", "content": "Write a haiku about request mappers."},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
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
