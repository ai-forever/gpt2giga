"""Gemini batchGenerateContent example via gpt2giga."""

from pathlib import Path

from google import genai
from google.genai import types

client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)

batch_source_path = Path(__file__).with_name("batch_generate_content.jsonl")
uploaded = client.files.upload(
    file=batch_source_path,
    config=types.UploadFileConfig(
        display_name="Gemini Batch Input",
        mime_type="application/json",
    ),
)
print("Uploaded batch source:", uploaded.name)

batch = client.batches.create(
    model="GigaChat-2-Max",
    src=types.BatchJobSource(file_name=uploaded.name),
    config=types.CreateBatchJobConfig(display_name="Gemini Batch Example"),
)
print("Created batch:", batch.name, batch.state)

retrieved = client.batches.get(name=batch.name)
print("Retrieved batch:", retrieved.name, retrieved.state)

listed_names = [item.name for item in client.batches.list(config={"page_size": 10})]
print("Known batch names:", listed_names)

if retrieved.dest and retrieved.dest.file_name:
    output = client.files.download(file=retrieved.dest.file_name)
    print("Batch output:")
    print(output.decode("utf-8"))
else:
    print("Batch output is not ready yet.")
