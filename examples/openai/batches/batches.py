"""OpenAI Batches API example."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
model_name = "GigaChat-2-Max"
print("Using model:", model_name)


with TemporaryDirectory() as tmp_dir:
    input_path = Path(tmp_dir) / "batch.jsonl"
    rows = [
        {
            "custom_id": "req-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model_name,
                "messages": [
                    {"role": "user", "content": "Say hello from request one."}
                ],
            },
        },
        {
            "custom_id": "req-2",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": model_name,
                "messages": [
                    {"role": "user", "content": "Say hello from request two."}
                ],
            },
        },
    ]
    input_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    uploaded = client.files.create(
        file=(input_path.name, input_path.read_bytes(), "application/json"),
        purpose="batch",
    )
    print("Uploaded input file:", uploaded.id)

    batch = client.batches.create(
        completion_window="24h",
        endpoint="/v1/chat/completions",
        input_file_id=uploaded.id,
        metadata={"source": "examples/openai/batches/batches.py"},
    )
    print("Created batch:", batch.id, batch.status, batch.output_file_id)
    retrieved = client.batches.retrieve(batch.id)
    print("Retrieved batch:", retrieved.id, retrieved.status, retrieved.output_file_id)

    listed = client.batches.list(limit=10)
    print("Known batch ids:", [item.id for item in listed.data])

    if retrieved.output_file_id:
        output_content = client.files.content(retrieved.output_file_id)
        print("Batch output file content:")
        print(output_content.text)
    else:
        print("Batch output is not ready yet.")
