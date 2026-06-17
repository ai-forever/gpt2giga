"""Basic Anthropic Messages API example (non-streaming)."""

from anthropic import Anthropic


api_version = "v1"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

message = client.messages.create(
    model="GigaChat-3-Ultra",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Расскажи коротко о Python."},
    ],
)

print(message.content[0].text)
