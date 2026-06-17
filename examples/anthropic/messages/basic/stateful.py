"""Anthropic Messages stateful conversation example via gpt2giga."""

from anthropic import Anthropic

api_version = "v2"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

MODEL = "GigaChat-2-Max"
CONVERSATION_ID = "anthropic-stateful-demo"
HEADERS = {"x-gpt2giga-conversation-id": CONVERSATION_ID}

# Stateful Messages require GPT2GIGA_CONVERSATION_STITCHING_ENABLED=True on the
# proxy side. The /v2 route executes through GigaChat v2/chat/completions.
first_message = client.messages.create(
    model=MODEL,
    max_tokens=1024,
    extra_headers=HEADERS,
    messages=[
        {
            "role": "user",
            "content": (
                "Remember this context for the next response: "
                "we are planning a two-day trip to Kazan focused on architecture."
            ),
        },
    ],
)

print("First response:")
print(first_message.content[0].text)

second_message = client.messages.create(
    model=MODEL,
    max_tokens=1024,
    extra_headers=HEADERS,
    messages=[
        {
            "role": "user",
            "content": "Using the saved context, suggest three places to visit.",
        },
    ],
)

print("\nSecond response:")
print(second_message.content[0].text)
