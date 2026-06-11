from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

response = client.responses.create(
    model="GigaChat-3-Ultra",
    input="Столица Франции",
    reasoning={"effort": "high"},
)

for element in response.output:
    print(element)
