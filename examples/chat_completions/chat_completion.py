from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Как дела?"},
    ],
)
print(completion)
"GigaChat-2-Max:2.0.30.01"
