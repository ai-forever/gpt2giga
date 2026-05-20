from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
response = client.embeddings.create(model="EmbeddingsGigaR", input=["Hello", "itsme"])
print(response)
