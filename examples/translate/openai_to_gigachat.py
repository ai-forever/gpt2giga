"""Translate an OpenAI chat payload into the internal GigaChat backend format."""

from __future__ import annotations

import json
import os

import httpx

BASE_URL = os.getenv("GPT2GIGA_BASE_URL", "http://localhost:8090")
API_KEY = os.getenv("GPT2GIGA_API_KEY", "0")

payload = {
    "from": "openai",
    "to": "gigachat",
    "kind": "chat",
    "payload": {
        "model": "GigaChat-2-Max",
        "messages": [
            {"role": "system", "content": "Answer in one sentence."},
            {"role": "user", "content": "What does this proxy do?"},
        ],
        "temperature": 0.1,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup_docs",
                    "description": "Find documentation snippets.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ],
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
