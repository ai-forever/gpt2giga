from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[
        {"role": "user", "content": "Как дела?"},
    ],
    reasoning_effort="low",
    max_completion_tokens=1024,
    # v1 maps this budget to reasoning_max_tokens; v2 to model_options.reasoning.
    extra_body={"reasoning": {"max_tokens": 256}},
)
print(completion)
