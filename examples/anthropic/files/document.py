"""Upload a text document and use its owner-scoped file reference in Messages."""

from anthropic import Anthropic

client = Anthropic(api_key="0", base_url="http://localhost:8090")
uploaded = client.beta.files.upload(
    file=(
        "document.txt",
        b"The meeting is on Friday at 10:00. Bring the draft report.",
        "text/plain",
    )
)
try:
    result = client.messages.create(
        model="GigaChat",
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "file", "file_id": uploaded.id},
                    },
                    {"type": "text", "text": "Summarize the document."},
                ],
            }
        ],
    )
    print(result.content)
finally:
    client.beta.files.delete(uploaded.id)
