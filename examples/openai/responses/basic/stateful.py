from uuid import uuid4

from openai import OpenAI

api_version = "v2"
if api_version != "v2":
    print("Stored Responses require v2; v1 rejects store/previous_response_id.")
    raise SystemExit(0)
client = OpenAI(base_url=f"http://localhost:8090/{api_version}/", api_key="0")

MODEL = "GigaChat-2-Max"
headers = {"X-Session-ID": str(uuid4())}

# Explicit /v2 selects the contract regardless of the proxy default.
# Keep response.id locally: GET /responses/{id} is not implemented.
first_response = client.responses.create(
    model=MODEL,
    input=(
        "Remember this context for the next response: "
        "we are planning a two-day trip to Kazan focused on architecture."
    ),
    store=True,
    extra_headers=headers,
)

print("First response id:")
print(first_response.id)
print("\nFirst response:")
print(first_response.output_text)

second_response = client.responses.create(
    model=MODEL,
    previous_response_id=first_response.id,
    extra_headers=headers,
    # Only new input is sent; the gateway omits model on the upstream continuation.
    input="Using the saved context, suggest three places to visit.",
)

print("\nSecond response:")
print(second_response.output_text)
