from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
model = "Embeddings"
dimensions = 1024
inputs = ["Hello", "itsme"]

float_response = client.embeddings.create(
    model=model,
    input=inputs,
    dimensions=dimensions,
    encoding_format="float",
)
print("float embeddings")
print("model:", float_response.model)
print("usage:", float_response.usage)
print("first vector length:", len(float_response.data[0].embedding))
print("first vector preview:", float_response.data[0].embedding[:5])

base64_response = client.embeddings.create(
    model=model,
    input=inputs,
    dimensions=dimensions,
    encoding_format="base64",
)
base64_embedding = base64_response.data[0].embedding
print("\nbase64 embeddings")
print("model:", base64_response.model)
print("usage:", base64_response.usage)
print("first embedding type:", type(base64_embedding).__name__)
print("first embedding preview:", base64_embedding[:80])
