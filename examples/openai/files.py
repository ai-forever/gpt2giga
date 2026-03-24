"""OpenAI Files API example."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from openai import OpenAI

client = OpenAI(base_url="http://localhost:8090", api_key="0")
model_name = "GigaChat-2-Max"
print("Using model:", model_name)


with TemporaryDirectory() as tmp_dir:
    input_path = Path(tmp_dir) / "batch-input.jsonl"
    row = {
        "custom_id": "req-1",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model_name,
            "messages": [{"role": "user", "content": "Say hello from a file example."}],
        },
    }
    input_path.write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )

    uploaded = client.files.create(
        file=(input_path.name, input_path.read_bytes(), "application/json"),
        purpose="batch",
    )
    print("Uploaded file:", uploaded.id, uploaded.filename, uploaded.purpose)

    retrieved = client.files.retrieve(uploaded.id)
    print("Retrieved file status:", retrieved.id, retrieved.status)

    listed = client.files.list(purpose="batch")
    print("Files with purpose=batch:", [item.id for item in listed.data])

    content = client.files.content(uploaded.id)
    print("Stored file content:")
    print(content)

    deleted = client.files.delete(uploaded.id)
    print("Deleted:", deleted.id, deleted.deleted)
