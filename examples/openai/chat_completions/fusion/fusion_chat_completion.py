from openai import OpenAI


api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

completion = client.chat.completions.create(
    model="gpt2giga/fusion-code",
    messages=[
        {
            "role": "user",
            "content": "Review this release checklist and name the highest risk.",
        },
    ],
)

print(completion.choices[0].message.content)

metadata = getattr(completion, "metadata", None)
if metadata:
    print("Fusion preset:", metadata.get("gpt2giga_fusion_preset"))
