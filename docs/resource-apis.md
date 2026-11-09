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
Cancellation atomically removes only an active session. Once finalization has claimed
the session, cancel returns HTTP 409; if cancel wins first, no native upload starts.
Finalizing local JSONL adopts its upload blob without requiring a second blob quota.

## Upload admission and profile selection

Set `X-GPT2GIGA-Profile: <configured-gigachat-profile-id>` on Files upload to target
the same GigaChat account as your model alias. An absent header keeps the default
account. Unknown and non-GigaChat profiles return 400 before upload. Metadata,
content and deletion keep the existing owner/profile checks. Gemini resumable
uploads fix the target at session start; subsequent headers cannot switch it.

Native upload reserves durable resource count and metadata capacity before the
provider POST. Exhausted local capacity returns 413 without uploading. If a known
success cannot be published, the gateway attempts native deletion with a five-second
upstream timeout. An unknown outcome or unsuccessful cleanup retains a non-expiring
`file_upload` intent that still consumes quota. Reconcile these intents with the
provider before retrying; there is no automatic upload retry or cross-system atomicity.
Storage cleanup drains transactions already started, so this upstream timeout is not
a total request deadline. SQLite admission waits asynchronously before taking an
executor thread. Expired-row cleanup commits independently of rejected publications.

Local file creation checks count, metadata and blob quotas before opening a blob;
admission refusal returns 413 without creating a file. Resumable appends admit
metadata and blob capacity before writing only the new chunk.
Committed offsets define the visible bytes. Failed writes trim unpublished bytes under
the SQLite writer lock; if cleanup fails, the remaining bytes still consume the aggregate
blob quota until retry, expiry cleanup, deletion or startup recovery removes them.
The same cleanup accounting covers failed local file creation and preserves the
original write or publication error when cleanup also fails. Batch lists validate the cursor
and select a page before polling its active jobs. Unchanged and terminal jobs do not
produce redundant metadata updates.

The native-file ownership ledger retains deleted IDs to prevent legacy fallback
across owners. Its disk usage is not yet covered by the resource metadata/count
quotas. Monitor durable-store disk usage in long-running native-file deployments;
do not delete ledger entries to reclaim space. A separate ledger admission quota
is a follow-up, without changing public file IDs.
