"""Anthropic Messages API example with extended thinking (reasoning).

Параметр thinking транслируется в reasoning_effort для GigaChat:
  budget_tokens >= 8000  → reasoning_effort="high"
  budget_tokens >= 3000  → reasoning_effort="medium"
  budget_tokens <  3000  → reasoning_effort="low"

GigaChat вернёт reasoning_content, который прокси конвертирует
в блок thinking формата Anthropic.
"""

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=16000,
    thinking={
        "type": "enabled",
        "budget_tokens": 10000,
    },
    messages=[
        {
            "role": "user",
            "content": (
                "На складе было 847 коробок. Утром привезли ещё 3 партии "
                "по 156 коробок. Днём забрали 294 коробки. "
                "Сколько коробок осталось на складе? Реши пошагово."
            ),
        },
    ],
)

for block in message.content:
    if block.type == "thinking":
        print("=== Рассуждение ===")
        print(block.thinking)
        print()
    elif block.type == "text":
        print("=== Ответ ===")
        print(block.text)
