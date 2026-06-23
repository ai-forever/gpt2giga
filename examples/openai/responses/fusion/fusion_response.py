from openai import OpenAI


api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

response = client.responses.create(
    model="gpt2giga/fusion-benchmark-text",
    input="Compare two implementation strategies and recommend the safer one.",
)

print(response.output_text)

metadata = getattr(response, "metadata", None)
if metadata:
    print("Fusion preset:", metadata.get("gpt2giga_fusion_preset"))
