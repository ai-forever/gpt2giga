"""Prepared Gemini Files API example.

The default public Gemini router does not mount Files routes yet. Run this only
against an app that explicitly includes ``gpt2giga.routers.gemini.files``.
"""

from examples.gemini.common import print_json, request_json

created = request_json(
    "POST",
    "/files",
    {
        "file": {
            "displayName": "batch-input.jsonl",
            "mimeType": "application/json",
            "sizeBytes": "128",
        }
    },
)
print("created:")
print_json(created)

listed = request_json("GET", "/files")
print("\nlisted:")
print_json(listed)

name = created["file"]["name"]
retrieved = request_json("GET", f"/{name}")
print("\nretrieved:")
print_json(retrieved)
