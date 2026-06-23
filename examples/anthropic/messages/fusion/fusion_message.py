"""Anthropic Messages API example using local GigaFusion."""

from anthropic import Anthropic


api_version = "v1"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

message = client.messages.create(
    model="gpt2giga/fusion-code",
    max_tokens=2048,
    messages=[
        {
            "role": "user",
            "content": "Compare two rollout plans and identify the safer one.",
        },
    ],
)

for block in message.content:
    if block.type == "text":
        print(block.text)
