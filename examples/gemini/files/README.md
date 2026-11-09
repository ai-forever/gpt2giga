# Gemini Files examples

Run `uv run python examples/gemini/files/files.py` against a configured gateway.
The example uses `google-genai` resumable upload, get/list, generation with the
returned file URI, and delete. Use `api_version="v1beta"`; to select GigaChat v2,
set `base_url="http://localhost:8090/v2"` and keep `api_version="v1beta"`.

Metadata, MIME, owner mapping and upload sessions use the configured durable
resource directory. Mount it persistently for multiple workers/restarts.
Uploads enforce configured limits and expire unfinished sessions after 24 hours.
User-uploaded files have no `download_uri`. Only generated batch output is
available through `files.download`; a local batch JSONL file is not an attachment.

В примере проверяется загрузка настоящих bytes и использование файла при генерации.
Одни JSON metadata не создают ACTIVE file; произвольный URI не становится attachment.
См. [контракт Files/Batches](../../../docs/gemini-resources.md).
