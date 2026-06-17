"""Anthropic Messages API example with base64-encoded image."""

import base64
from pathlib import Path

from anthropic import Anthropic

api_version = "v2"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")


def encode_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


image_path = Path("image.png")
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
