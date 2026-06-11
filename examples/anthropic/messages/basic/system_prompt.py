"""Anthropic Messages API example with system prompt."""

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    system="Ты — пират. Отвечай как пират, используя морской сленг.",
    messages=[
        {"role": "user", "content": "Как добраться до ближайшего магазина?"},
    ],
)

print(message.content[0].text)
