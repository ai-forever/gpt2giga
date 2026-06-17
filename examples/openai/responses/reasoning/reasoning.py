from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

response = client.responses.create(
    model="GigaChat-3-Ultra",
    input="Столица Франции",
    reasoning={"effort": "high"},
)

for element in response.output:
    print(element)
