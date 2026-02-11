"""Anthropic Messages API example with base64-encoded image."""

import base64

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090/v1", api_key="any-key")


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


image_path = "../../image.png"
base64_image = encode_image(image_path)

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Опиши что ты видишь на изображении."},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64_image,
                    },
                },
            ],
        }
    ],
)

print(message.content[0].text)
