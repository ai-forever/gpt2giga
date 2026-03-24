from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
url = "https://images.rawpixel.com/image_png_800/cHJpdmF0ZS9sci9pbWFnZXMvd2Vic2l0ZS8yMDIzLTA4L3Jhd3BpeGVsX29mZmljZV8zMF9hX3N0dWRpb19zaG90X29mX2NhdF93YXZpbmdfaW1hZ2VzZnVsbF9ib2R5X182YzRmM2YyOC0wMGJjLTQzNTYtYjM3ZC05NDM0NTgwY2FmNDcucG5n.png"

response = client.responses.create(
    model="gpt-4.1-mini",
    input=[
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "what's in this image?"},
                {
                    "type": "input_image",
                    "image_url": f"{url}",
                },
            ],
        }
    ],
)

print(response.output_text)
