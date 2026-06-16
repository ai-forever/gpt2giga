import base64
from pathlib import Path

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090/v2", api_key="0")


def encode_image(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


image_path = Path(__file__).resolve().parents[3] / "image.png"

# Getting the base64 string
base64_image = encode_image(image_path)
response = client.responses.create(
    model="GigaChat-2-Max",
    input=[
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "what's in this image?"},
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpg;base64,{base64_image}",
                },
            ],
        }
    ],
)

print(response.output_text)
