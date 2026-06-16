"""Anthropic Messages API streaming example."""

from anthropic import Anthropic

api_version = "v2"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

with client.messages.stream(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Напиши сказку про кота в трёх предложениях."},
    ],
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)

print()
