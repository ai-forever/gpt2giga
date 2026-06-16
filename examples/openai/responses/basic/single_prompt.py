from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

response = client.responses.create(
    input="Write a one-sentence bedtime story about a unicorn.", model="GigaChat-2-Max"
)
print(response.output_text)
