from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000",
                api_key="0")
response = client.models.list()
print(response)

response = client.models.retrieve("GigaChat-3") # 404
print(response)