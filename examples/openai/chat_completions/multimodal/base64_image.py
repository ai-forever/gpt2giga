import base64
from pathlib import Path

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")


def encode_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


image_path = Path(__file__).resolve().parents[3] / "image.png"

# Getting the base64 string
base64_image = encode_image(image_path)
completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Что на изображении?"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpg;base64,{base64_image}"},
                },
            ],
        }
    ],
)

print(completion.choices[0].message.content)
