# Files and batch resources

All protocols share the [durable resource store](configuration.md#resource-storage).
Use a persistent volume across worker/process restarts. The resource namespace includes
trusted identity and upstream credentials/profile; an opaque pass-through token rotation
changes that namespace. Anonymous mode is one shared namespace.

## Files

OpenAI `/files` upload/list/retrieve/content/delete is mounted at root, `/v1`, `/v2`.
The original purpose, filename and MIME survive restarts. Upstream documents retain their
upstream IDs and bytes are returned without a base64 round trip. Unknown legacy upstream
IDs are resolved under the request's GigaChat credentials; previously lost metadata cannot
be reconstructed. Local batch JSONL receives an opaque `file_g2g_...` ID and is never sent
to GigaChat's document upload endpoint. It cannot be used as a document attachment.

The same `/files` routes dispatch Anthropic when `anthropic-version` or `anthropic-beta`
is present; `x-api-key` alone does not select a protocol. Anthropic upload requires `file`
only. Metadata contains native size, persisted MIME and RFC3339 creation time.
User-uploaded files are not downloadable through the Anthropic contract; generated batch
output can be downloaded when the resource is marked downloadable. Custom scope/expiry
requests are rejected. Messages accepts user document/image blocks with
`source={"type":"file","file_id":"..."}`; ownership and MIME are checked before the
reference becomes a GigaChat attachment. Other document source forms are rejected.

Default/2023-06-01 Files pagination uses after_id/limit. Explicit 2026-10-21 uses
page/next_page with limit. This does not change Models pagination.
Gemini upload/download requirements are described in [Gemini resources](gemini-resources.md).

## Batches

Native GigaChat batch execution requires a pay-as-you-go account. Supported inputs are
OpenAI chat/completions, stateless responses or embeddings; Anthropic Messages; Gemini
GenerateContent or embeddings. Each job has one endpoint family and native model.
Built-in/hosted tools, streaming and stateful Responses input are rejected before submission.
Custom function tools remain supported. OpenAI/Anthropic custom_id values are required
and unique; Gemini rows receive stable keys when omitted. Result association uses these
keys, not the order returned by the backend.

The gateway submits raw JSONL through SDK `acreate_batch`, polls with `aget_batches`,
and creates protocol output/error files or inline results. It never starts a job while
polling, retries an ambiguous submission, or fabricates results from missing counters.
Metadata and converted results survive restarts. There is no background scheduler.
Cancel/delete returns the protocol's explicit unsupported error and never changes a
native job's status locally.

**24h is a gateway result acceptance deadline, not a native completion SLA.** A poll
before the deadline can persist confirmed results. On the first poll after the deadline,
unresolved rows become expired permanently, even if the native job completed earlier:
the SDK has no confirmed completion timestamp proving that outcome. Native work can
continue and incur charges after gateway expiry; cancellation is unavailable. Retention
of metadata/results is a separate setting and does not erase results at the deadline.

See `examples/openai/batches/` and `examples/anthropic/message_batches/` in the repository.
These examples require a configured running gateway and a batch-enabled account; the
offline SDK tests do not establish live account entitlement.

## Text token estimates and caching

`POST /responses/input_tokens` returns `{"object":"response.input_tokens","input_tokens":N}`.
It uses the same normalized textual input mapping, includes instructions, function names/
arguments/schemas and response schema, and calls only GigaChat `tokens/count`. Images,
files, prior response/conversation state and hosted tools are rejected. This is a text
estimate, not exact OpenAI tokenization or the full billable cost of multimodal input.

An explicit OpenAI `prompt_cache_key` selects a hashed GigaChat `X-Session-ID` even when
automatic prompt-prefix caching is disabled. The hash separates owner/profile and model
and contains no raw prompt/key. Explicit user session headers take priority, followed by
the global GIGACHAT session setting, then prompt_cache_key, then enabled automatic prefix
caching. This does not implement OpenAI cache retention TTL; usage comes only from upstream.


### Failure and ownership guarantees

A durable submission intent is written before a batch POST. If local storage is
unavailable, no POST is sent. An ambiguous submission or failure to persist its native
ID leaves a failed intent with `submission_outcome_unknown`; polling never resubmits it.
The operator must reconcile that record with the provider before submitting another job.
This cannot provide an atomic transaction across SQLite and the provider.
Every terminal batch accounts for each input ID exactly once, retaining confirmed partial
results and explicit errors for missing rows. Polling after a restart uses the stored
provider profile and the caller's matching credential namespace.

Registered file ownership is enforced for native `attachments`, attachment headers and
protocol file references before generation. Explicit image/document upload or download
failure stops the request; it never silently becomes a text-only success. Attachment
cache reuse is scoped to provider/profile/credentials and retains size/type accounting.
Anthropic `expires_in_seconds` is rejected before upload until native expiry is supported.
Concurrent resumable writes at the same offset yield one success and one HTTP 409.
Finalizing local JSONL adopts its upload blob without requiring a second blob quota.
