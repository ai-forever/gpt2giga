"""Anthropic Messages API multi-turn conversation example."""

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

# First turn
message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Назови три столицы европейских стран."},
    ],
)

first_response = message.content[0].text
print("Ассистент:", first_response)

# Second turn — continue the conversation
message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Назови три столицы европейских стран."},
        {"role": "assistant", "content": first_response},
        {"role": "user", "content": "А теперь назови их население."},
    ],
)

print("Ассистент:", message.content[0].text)
