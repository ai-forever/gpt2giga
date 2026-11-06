"""Gemini Files API example via gpt2giga."""

from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from google import genai
from google.genai import types

api_version = "v1beta"
client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
        # Resumable raw-byte uploads also need the gateway key on the transport.
        httpx_client=httpx.Client(headers={"x-api-key": "0"}),
    ),
)

with TemporaryDirectory() as tmp_dir:
    file_path = Path(tmp_dir) / "meeting_notes.txt"
    file_path.write_text(
        "Batch examples added for Gemini files and batchGenerateContent.\n",
        encoding="utf-8",
    )

    uploaded = client.files.upload(
        file=file_path,
        config=types.UploadFileConfig(
            display_name="meeting_notes.txt",
            mime_type="text/plain",
        ),
    )
    print("Uploaded file:", uploaded.name, uploaded.state)

    retrieved = client.files.get(name=uploaded.name)
    print("Retrieved file:", retrieved.name, retrieved.mime_type, retrieved.uri)

    listed_names = [item.name for item in client.files.list(config={"page_size": 10})]
    print("Known file names:", listed_names)

    response = client.models.generate_content(
        model="GigaChat-2-Max", contents=["Summarize this file:", uploaded]
    )
    print(response.text)
    # User-uploaded Gemini files are not downloadable; generated batch output is.

    client.files.delete(name=uploaded.name)
    print("Deleted file:", uploaded.name)
