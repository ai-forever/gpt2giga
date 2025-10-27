from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000", api_key="sk-J5xMzoniPAb11scsrA5j9Q")
response = client.models.list()
print(response)

response = client.models.retrieve("GigaChat-3")  # 404
print(response)
