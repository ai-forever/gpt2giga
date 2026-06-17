from openai import OpenAI

api_version = "v2"
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

MODEL = "GigaChat-2-Max"

# Stateful Responses require GPT2GIGA_GIGACHAT_API_MODE=v2 on the proxy side.
first_response = client.responses.create(
    model=MODEL,
    input=(
        "Remember this context for the next response: "
        "we are planning a two-day trip to Kazan focused on architecture."
    ),
    store=True,
)

print("First response id:")
print(first_response.id)
print("\nFirst response:")
print(first_response.output_text)

second_response = client.responses.create(
    model=MODEL,
    previous_response_id=first_response.id,
    input="Using the saved context, suggest three places to visit.",
)

print("\nSecond response:")
print(second_response.output_text)
