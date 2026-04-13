"""Translate a Gemini generateContent payload into Anthropic Messages format."""

from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GPT2GIGA_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("GPT2GIGA_API_KEY", "0")

payload = {
    "from": "gemini",
    "to": "anthropic",
    "kind": "chat",
    "payload": {
        "model": "models/gemini-2.5-pro",
        "systemInstruction": {"parts": [{"text": "Answer briefly."}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Describe schema translation in one sentence."}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "thinkingConfig": {"thinkingLevel": "MEDIUM"},
        },
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
