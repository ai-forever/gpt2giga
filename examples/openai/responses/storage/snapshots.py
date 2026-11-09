"""Requires GPT2GIGA_RESPONSES_STORAGE_MODE=gateway and persistent resources."""

from openai import OpenAI

client = OpenAI(api_key="0", base_url="http://localhost:8090/v1")
conversation = client.conversations.create()
response = client.responses.create(
    model="GigaChat", input="Say hello.", conversation=conversation.id
)
print(client.responses.retrieve(response.id).output_text)
print(client.responses.input_items.list(response.id).data)
client.responses.delete(response.id)
client.conversations.delete(conversation.id)
