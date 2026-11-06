"""Anthropic Message Batches API structured output example.

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
            "custom_id": "extract-contact",
            "params": {
                "model": "GigaChat-2-Max",
                "max_tokens": 256,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Extract contact data: "
                            "Sergey Petrov, sergey@example.com, operations."
                        ),
                    }
                ],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "email": {"type": "string"},
                                "department": {"type": "string"},
                            },
                            "required": ["name", "email", "department"],
                            "additionalProperties": False,
                        },
                    }
                },
            },
        },
        {
            "custom_id": "extract-task",
            "params": {
                "model": "GigaChat-2-Max",
                "max_tokens": 256,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Extract task data: "
                            "Prepare the release notes by Friday, priority high."
                        ),
                    }
                ],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "task": {"type": "string"},
                                "due": {"type": "string"},
                                "priority": {"type": "string"},
                            },
                            "required": ["task", "due", "priority"],
                            "additionalProperties": False,
                        },
                    }
                },
            },
        },
    ]
)

print("Created message batch:", batch.id, batch.processing_status, batch.results_url)

retrieved = client.messages.batches.retrieve(batch.id)
print("Retrieved message batch:", retrieved.id, retrieved.processing_status)

if retrieved.results_url:
    print("Structured output batch results:")
    for result in client.messages.batches.results(batch.id):
        print(result)
else:
    print("Batch results are not ready yet.")
