"""Basic Anthropic Messages API example (non-streaming)."""

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Расскажи коротко о Python."},
    ],
)

print(message.content[0].text)
