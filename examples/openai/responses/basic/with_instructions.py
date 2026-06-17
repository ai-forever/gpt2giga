from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

response = client.responses.create(
    model="GigaChat-2-Max",
    instructions="Talk like a pirate.",
    input="Are semicolons optional in JavaScript?",
)

print(response.output_text)
