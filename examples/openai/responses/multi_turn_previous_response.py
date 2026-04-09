from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")

first = client.responses.create(
    model="gpt-5",
    input="Remember this for the next turn: my favorite color is green.",
)
print("First response:")
print(first.output_text)
print(f"response.id={first.id}")
print(f"conversation.id={first.conversation.id if first.conversation else None}")

second = client.responses.create(
    model="gpt-5",
    input="What color did I ask you to remember?",
    previous_response_id=first.id,
)
print("\nSecond response:")
print(second.output_text)
