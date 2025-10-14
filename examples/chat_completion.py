from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000",
                api_key="0")
completion = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user","content": "Как дела?"},
    ],
)
print(completion)