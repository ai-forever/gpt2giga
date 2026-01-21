from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Как дела?"},
    ],
    stream=True,
)
for event in completion:
    print(event.choices[0].delta.content)
