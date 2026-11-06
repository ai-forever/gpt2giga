# Response snapshots and Conversations

`GPT2GIGA_RESPONSES_STORAGE_MODE=native` is the default. Native v2 response IDs identify
GigaChat thread continuation, can repeat across turns, and are not immutable stored
Response objects. Existing native IDs retain their continuation path.

Set `GPT2GIGA_RESPONSES_STORAGE_MODE=gateway` to enable immutable `resp_g2g_...` snapshots
and `conv_g2g_...` Conversations using the common [resource store](configuration.md#resource-storage).
This mode supports textual message items and custom function_call/function_call_output
items with GigaChat execution. External provider routes are rejected before dispatch;
native storage mode retains their existing behavior. Snapshots use the selected
GigaChat profile namespace, and retrieval searches only profiles authorized by the
current deployment and credential identity. Unsupported multimodal, hosted-tool, reasoning and provider artifacts are rejected
rather than silently omitted. Background/cancel/compact/connect are not implemented.

Available at root, `/v1`, `/v2`:

- Responses create, GET/DELETE `/responses/{id}`, GET `/responses/{id}/input_items`.
- Conversations create/retrieve/update/delete, list/create/retrieve/delete items.

Gateway response IDs are unique snapshots of the actual expanded input and completed
output. A previous_response_id replays that snapshot's context into a new stateless
upstream request, so two branches from an earlier turn do not inherit later mutations.
A conversation supplies its durable items and receives successful response input/output;
concurrent modifications produce a conflict rather than overwriting changed history.
The snapshot and conversation turn are published in one SQLite transaction. Storage
failure during streaming produces a terminal error instead of a completed response.
conversation and previous_response_id are mutually exclusive. Unknown, deleted, expired
or foreign snapshots return 404; they never become arbitrary native thread IDs.

`store=false` does not create a durable response object. An error, incomplete stream or
observed disconnect does not persist a successful response. A completed stream uses one
snapshot ID consistently. Removing a response does not erase its independent descendants;
removing a conversation does not erase snapshots. Storage uses the resource retention
setting; file/batch delivery deadlines do not control snapshot retention.

Input/output text is stored deliberately for replay in the private resource directory.
Content capture in logs remains opt-in. Back up the directory and its namespace secret,
and keep the configured identity/profile consistent across workers and restarts.

Example: `examples/openai/responses/storage/snapshots.py` in the repository.
