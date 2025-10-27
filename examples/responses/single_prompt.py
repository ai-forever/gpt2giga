from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000", api_key="0")

response = client.responses.create(
    input="Write a one-sentence bedtime story about a unicorn."
)
print(response.output_text)
