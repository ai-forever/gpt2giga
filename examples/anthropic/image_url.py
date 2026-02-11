"""Anthropic Messages API example with image from URL."""

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")

url = (
    "https://images.rawpixel.com/image_png_800/"
    "cHJpdmF0ZS9sci9pbWFnZXMvd2Vic2l0ZS8yMDIzLTA4L3Jhd3BpeGVsX29mZmljZV8z"
    "MF9hX3N0dWRpb19zaG90X29mX2NhdF93YXZpbmdfaW1hZ2VzZnVsbF9ib2R5XzZjNGYz"
    "ZjI4LTAwYmMtNDM1Ni1iMzdkLTk0MzQ1ODBjYWY0Ny5wbmc.png"
)

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Что изображено на картинке?"},
                {
                    "type": "image",
                    "source": {"type": "url", "url": url},
                },
            ],
        }
    ],
)

print(message.content[0].text)
