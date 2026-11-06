"""Estimate textual input without generation; this is not an exact OpenAI tokenizer."""

from openai import OpenAI

client = OpenAI(api_key="0", base_url="http://localhost:8090/v1")
print(client.responses.input_tokens.count(model="GigaChat", input="Hello, world!"))
