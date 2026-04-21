"""Anthropic Message Batches example using the bundled JSONL input."""

import json
from pathlib import Path

from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8090", api_key="any-key")

input_path = Path(__file__).with_name("message_batches.jsonl")
requests = [
    json.loads(line)
    for line in input_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

print("Loaded batch requests:", [item["custom_id"] for item in requests])

batch = client.messages.batches.create(requests=requests)
print("Created message batch:", batch.id, batch.processing_status, batch.results_url)

retrieved = client.messages.batches.retrieve(batch.id)
print(
    "Retrieved message batch:",
    retrieved.id,
    retrieved.processing_status,
    retrieved.request_counts,
)

if retrieved.results_url:
    print("Batch results:")
    for result in client.messages.batches.results(batch.id):
        print(result)
else:
    print("Batch results are not ready yet.")
