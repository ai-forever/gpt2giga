"""Anthropic Messages example for GigaChat v2 image generation tool."""

from anthropic import Anthropic

api_version = "v2"
if api_version != "v2":
    print("SKIP: GigaChat built-in tools require /v2 chat completions.")
    raise SystemExit(0)

client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=2048,
    tools=[
        {
            "type": "image_generation",
            "name": "image_generation",
            "size": "1024x1024",
        }
    ],
    messages=[
        {
            "role": "user",
            "content": "Нарисуй красивую картинку с космосом.",
        }
    ],
)

print("Stop reason:", message.stop_reason)
for block in message.content:
    print(block)
