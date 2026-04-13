"""Translate a Gemini generateContent payload into the internal GigaChat format."""

from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GPT2GIGA_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("GPT2GIGA_API_KEY", "0")

payload = {
    "from": "gemini",
    "to": "gigachat",
    "kind": "chat",
    "payload": {
        "model": "models/gemini-2.5-pro",
        "systemInstruction": {"parts": [{"text": "Answer in one sentence."}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "What does a request adapter do?"}],
            }
        ],
        "generationConfig": {"temperature": 0.1},
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
print("Warnings:", body.get("warnings"))
print(json.dumps(body["payload"], ensure_ascii=False, indent=2))
