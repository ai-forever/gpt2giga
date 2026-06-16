from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="ollama")

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Как дела?"},
    ],
    reasoning_effort="high",
)
print(completion)
