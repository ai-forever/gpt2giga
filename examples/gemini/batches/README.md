# Gemini batch examples

Run `uv run python examples/gemini/batches/batches.py` against a configured gateway
and a GigaChat account with native batch access. The example uploads JSONL to the
local resource store, submits native `batchGenerateContent`, polls once and lists
jobs. If complete, it downloads the generated result JSONL. Poll again later when
pending; the gateway does not run a background scheduler.

Use `api_version="v1beta"`, including with a base URL ending in `/v1` or `/v2`.
Batch execution uses GigaChat's native batch service, with no native cancellation
or processing-time SLA. Cancel/delete return an explicit unsupported error.
Custom functions are accepted; hosted tools and streaming are rejected. One job
uses one model and operation family. `batches.create_embeddings` is also supported
for text embeddings through the same backend.

`batch_generate_content.jsonl` supplies request/metadata rows. IDs/order are retained
across restart and shuffled native output. Gemini results use actual operation
metadata so the SDK exposes `BatchJob.dest`.

Русский контракт и ограничения: [Files/Batches](../../../docs-site/i18n/ru/docusaurus-plugin-content-docs/current/gemini-resources.md).
