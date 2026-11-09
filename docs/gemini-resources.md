# Gemini Files and asynchronous batches

Use `google-genai` with `api_version="v1beta"` and a gateway base URL. A base URL
ending in `/v1` or `/v2` selects the existing gateway API mode while preserving the
Gemini wire format. Files and batch metadata use the configured durable resource
store; share its persistent directory across workers and retain it across restart.
Ownership follows the authenticated gateway identity and selected credential
context. Anonymous local mode shares one namespace. Opaque pass-through token
rotation does not imply the same owner.

## Files

The SDK's `files.upload` starts a resumable session at `/upload/v1beta/files`, then
posts raw bytes to the returned `X-Goog-Upload-URL`. Upload/query/finalize validate
byte offsets and declared length. Sessions expire after 24 hours. The configured
blob limit bounds buffered uploads; upstream document MIME/size limits still apply.
Metadata-only POST and multipart/form-data do not emulate Google's upload protocol.

Accepted path aliases such as `/proxy/upload/v1beta/files` and
`/v2/v1/upload/v1beta/files` retain the Gemini error format even when the
pass-token client pool rejects a request before routing: HTTP 503,
`Retry-After: 1`, numeric `error.code: 503` and `error.status: UNAVAILABLE`.

`files.get`, `files.list` and `files.delete` preserve the known filename, display
name, MIME, byte length and creation time. `fileData.fileUri` must reference an
owned gateway file; it resolves to its actual native attachment. Arbitrary URIs,
unknown IDs and local batch JSONL cannot become attachments. User-uploaded files
are not downloadable. Generated batch output exposes `downloadUri` and is served
at `/v1beta/files/{id}:download?alt=media` for the real SDK download flow.

JSONL inputs are retained locally and sent as raw bytes to native batch submission;
they are not uploaded as GigaChat documents. Keep the resource volume private.

## Batches

`batches.create` and `batches.create_embeddings` use actual native create/poll
operations. Supported inputs are inline requests or an owned local JSONL resource.
Each job has one GigaChat model and either chat or text-embedding requests. Streaming,
stateful continuation, external output destinations, webhooks and hosted tools
are rejected before submission. Custom functions use the existing adapters.
Embedding options retain the existing accepted/ignored policy; vectors are not
truncated to simulate arbitrary output dimensions.

Create/get return Operations named `batches/{id}`; list returns `operations` and
page tokens. Ready output appears in `metadata.output` so the SDK reads
`BatchJob.dest`. Inline responses retain row metadata and order, even if native
results are shuffled. File input produces downloadable JSONL. Per-item failures
remain failures alongside successful rows. Repeated polls reuse retained results.

The gateway polls only when the client requests it. Submission is not retried after
an ambiguous timeout. Native batch access depends on the GigaChat account; availability
is not implied by an SDK method. Cancel/delete return 501 `UNIMPLEMENTED`; no local
state change pretends to stop the native job. Gemini has no emulated completion
window or processing-time SLA. Resource retention is separate from job processing.

## Authenticated resumable uploads

`google-genai` 2.14 sends final raw bytes directly through its HTTP transport and
may omit the `api_key` used on normal API requests. With gateway authentication
enabled, also set `x-api-key` in a custom HTTPX client's default headers:
`httpx.Client(headers={"x-api-key": gateway_key})`, passed as
`types.HttpOptions(httpx_client=http_client)`. Async callers use `httpx.AsyncClient`
and `httpx_async_client`. Pass-token Authorization must likewise accompany both
stages. Authentication is enforced on every stage; session metadata never stores
credentials.
