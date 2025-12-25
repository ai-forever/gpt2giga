from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
response = client.embeddings.create(model="gpt-4o", input=["Hello", "itsme"])
print(response)
