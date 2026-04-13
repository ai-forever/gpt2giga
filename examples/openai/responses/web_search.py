from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

response = client.responses.create(
    model="gpt-5",
    input="Курс доллара на сегодня",
    store=False,
    tools=[{"type": "web_search"}],
)

print(response)
