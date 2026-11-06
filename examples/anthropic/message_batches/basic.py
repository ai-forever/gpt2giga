"""Anthropic Message Batches API example.

Requires GigaChat batch access. Poll before the 24h gateway acceptance deadline:
first polling later can expire a job that finished upstream in time. Native jobs
may continue and be billed after expiry; cancellation/deletion are unsupported.
"""

from anthropic import Anthropic

api_version = "v1"
client = Anthropic(base_url=f"http://localhost:8090/{api_version}/", api_key="any-key")

batch = client.messages.batches.create(
    requests=[
        {
            "custom_id": "req-1",
            "params": {
                "model": "GigaChat-2-Max",
                "max_tokens": 128,
                "messages": [
                    {
                        "role": "user",
                        "content": "Say hello from Anthropic batch item one.",
                    }
                ],
            },
        },
        {
            "custom_id": "req-2",
            "params": {
                "model": "GigaChat-2-Max",
                "max_tokens": 128,
                "messages": [
                    {
                        "role": "user",
                        "content": "Say hello from Anthropic batch item two.",
                    }
                ],
            },
        },
    ]
)

print("Created message batch:", batch.id, batch.processing_status, batch.results_url)

retrieved = client.messages.batches.retrieve(batch.id)
print(
    "Retrieved message batch:",
    retrieved.id,
    retrieved.processing_status,
    retrieved.request_counts,
)

listed = client.messages.batches.list(limit=10)
print("Known message batch ids:", [item.id for item in listed.data])

if retrieved.results_url:
    print("Batch results:")
    for result in client.messages.batches.results(batch.id):
        print(result)
else:
    print("Batch results are not ready yet.")
