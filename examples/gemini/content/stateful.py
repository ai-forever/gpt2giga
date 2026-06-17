"""Gemini generateContent stateful conversation example via gpt2giga."""

from google import genai
from google.genai import types

api_version = "v2"
CONVERSATION_ID = "gemini-stateful-demo"

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
        headers={"x-gpt2giga-conversation-id": CONVERSATION_ID},
    ),
)

MODEL = "GigaChat-2-Max"

# Stateful Gemini requests require GPT2GIGA_CONVERSATION_STITCHING_ENABLED=True
# on the proxy side. The /v2 route executes through GigaChat v2/chat/completions.
first_response = client.models.generate_content(
    model=MODEL,
    contents=(
        "Remember this context for the next response: "
        "we are planning a two-day trip to Kazan focused on architecture."
    ),
)

print("First response:")
print(first_response.text)

second_response = client.models.generate_content(
    model=MODEL,
    contents="Using the saved context, suggest three places to visit.",
)

print("\nSecond response:")
print(second_response.text)
