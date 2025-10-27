from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000", api_key="0")

response = client.responses.create(
    model="gpt-5",
    instructions="Talk like a pirate.",
    input="Are semicolons optional in JavaScript?",
)

print(response.output_text)
