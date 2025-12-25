from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="sk-1234")
response = client.models.list()
print(response)

response = client.models.retrieve("GigaChat-3")  # 404
print(response)
