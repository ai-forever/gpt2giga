import base64

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


image_path = "../../image.png"

# Getting the base64 string
base64_image = encode_image(image_path)
response = client.responses.create(
    model="gpt-4o",
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
