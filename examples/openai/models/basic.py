from openai import OpenAI

api_version = "v1"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="sk-1234")
response = client.models.list()
print(response)

response = client.models.retrieve("GigaChat-2-Max")
print(response)
