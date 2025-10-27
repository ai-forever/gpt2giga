from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000", api_key="0")
url = "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/2023_06_08_Raccoon1.jpg/1599px-2023_06_08_Raccoon1.jpg"
completion = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Что на изображении?"},
                {"type": "image_url", "image_url": {"url": f"{url}"}},
            ],
        }
    ],
)

print(completion.choices[0].message.content)
