from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="ollama")

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Как дела?"},
    ],
    reasoning_effort="high",
)
print(completion)
