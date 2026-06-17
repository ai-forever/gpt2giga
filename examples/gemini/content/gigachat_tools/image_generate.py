"""Gemini-compatible raw request for GigaChat v2 image generation tool."""

import os

import httpx

api_version = "v2"
if api_version != "v2":
    print("SKIP: GigaChat built-in tools require /v2 chat completions.")
    raise SystemExit(0)

base_url = os.getenv("GPT2GIGA_EXAMPLE_BASE_URL", "http://localhost:8090")
api_key = os.getenv("GEMINI_API_KEY", os.getenv("OPENAI_API_KEY", "0"))

payload = {
    "contents": [
        {
            "role": "user",
            "parts": [{"text": "Нарисуй красивую картинку с космосом."}],
        }
    ],
    "tools": [{"imageGeneration": {"size": "1024x1024"}}],
}

response = httpx.post(
    f"{base_url.rstrip('/')}/{api_version}/models/GigaChat-2-Max:generateContent",
    headers={"x-api-key": api_key},
    json=payload,
    timeout=120,
)
response.raise_for_status()

print(response.json())
