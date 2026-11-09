"""Shared durable batch execution through the public GigaChat SDK."""

import json
import sqlite3
import time
import uuid
from copy import deepcopy
from typing import Any

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder

from gpt2giga.app.providers import bind_gigachat_profile
from gpt2giga.app_state import get_request_transformer
from gpt2giga.app_state import (
    get_gigachat_client,
    get_resource_owner,
    get_resource_store,
)
from gpt2giga.common.files import validate_model_attachments
from gpt2giga.common.gigachat_options import (
    extract_gigachat_request_options,
    gigachat_request_options,
)
from gpt2giga.protocol.batches import (
    extract_batch_result_body,
    parse_jsonl,
    get_batch_target,
)
from gpt2giga.protocol.embeddings import transform_embedding_body
from gpt2giga.providers.gigachat.model_resolution import (
    resolve_upstream_model,
    UpstreamModelRequiredError,
)
from gpt2giga.providers.profiles.errors import ProviderAliasError
from gpt2giga.storage.resources import (
    Resource,
    ResourceStoreError,
    ResourceNotFoundError,
)

TERMINAL = frozenset({"completed", "failed", "expired"})
_STATUS = {
    "created": "validating",
    "in_progress": "in_progress",
    "completed": "completed",
    "failed": "failed",
}


def batch_error(message: str, status: int = 400) -> HTTPException:
    """Use the existing protocol-aware exception serializer."""
    return HTTPException(status, detail=message)


def resolve_batch_model(
    request: Request, model: str | None, *, embeddings: bool = False
) -> str:
    """Resolve exact configured aliases; reject non-GigaChat batch backends."""
    config = request.app.state.config
    requested = model
    if embeddings and not config.proxy_settings.pass_model:
        requested = config.proxy_settings.embeddings
    registry = getattr(request.app.state, "provider_registry", None)
    if registry is not None and requested in registry.public_aliases():
        route = registry.resolve(requested)
        if route.provider_kind.value != "gigachat":
            raise batch_error("Batches require a GigaChat provider profile.")
        previous_profile = getattr(request.state, "batch_provider_profile", None)
        if previous_profile is not None and previous_profile != route.profile_id:
            raise batch_error("A batch cannot mix upstream provider profiles.")
        request.state.batch_provider_profile = route.profile_id
        return route.upstream_model
    if registry is not None and any(
        profile.profile_id != "native-gigachat" for profile in registry.config.profiles
    ):
        try:
            registry.resolve(requested)
        except ProviderAliasError as exc:
            raise batch_error("Unknown batch model alias.") from exc
    try:
        return resolve_upstream_model({"model": requested}, config).model
    except UpstreamModelRequiredError as exc:
        raise batch_error("A GigaChat model is required for batch execution.") from exc


def batch_owner(request: Request, resource: Resource | None = None) -> str:
    """Bind batch ownership to its selected provider profile."""
    profile = (
        resource.metadata.get("provider_profile")
        if resource is not None
        else getattr(request.state, "batch_provider_profile", None)
    )
    return get_resource_owner(request, profile=profile)


def _batch_owners(request: Request) -> set[str]:
    owners = {get_resource_owner(request)}
    registry = getattr(request.app.state, "provider_registry", None)
    if registry is not None:
        owners.update(
            get_resource_owner(request, profile=p.profile_id)
            for p in registry.config.profiles
            if p.provider_kind.value == "gigachat"
        )
    return owners


def validate_batch_body(body: dict[str, Any]) -> None:
    """Reject stateful, streaming and hosted-tool semantics before submission."""
    if body.get("stream"):
        raise batch_error("Streaming is not supported in batches.")
    for name in (
        "previous_response_id",
        "conversation",
        "background",
        "assistant_id",
        "storage",
    ):
        if body.get(name):
            raise batch_error(f"Stateful `{name}` is not supported in batches.")
    if body.get("store"):
        raise batch_error("Stored Responses are not supported in batches.")
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict) or tool.get("type") not in {
            None,
            "function",
            "custom",
        }:
            raise batch_error("Hosted tools are not supported in batches.")
        if tool.get("name") in {
            "WebSearch",
            "WebFetch",
            "CodeExecution",
            "text2image",
            "image_generate",
        }:
            raise batch_error("Hosted tools are not supported in batches.")
    for function in body.get("functions") or []:
        if isinstance(function, dict) and function.get("name") in {
            "text2image",
            "WebSearch",
            "WebFetch",
            "CodeExecution",
            "image_generate",
        }:
            raise batch_error("Hosted functions are not supported in batches.")
    extra = body.get("extra_body")
    if isinstance(extra, dict):
        validate_batch_body(extra)


def _status(batch: Any) -> str:
    value = getattr(batch, "status", None)
    if value not in _STATUS:
        raise batch_error("Unknown upstream batch status.", 502)
    return _STATUS[value]


async def create_batch(
    request: Request,
    *,
    protocol: str,
    method: str,
    model: str,
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> Resource:
    """Persist an intent before one submit; never retry an unknown outcome."""
    rows = jsonable_encoder(rows, by_alias=True, exclude_none=True)
    if method not in {"chat_completions", "embedder"} or not rows:
        raise batch_error("A non-empty supported batch is required.")
    seen = set()
    for row in rows:
        key = row.get("id")
        if not isinstance(key, str) or not key or len(key) > 64 or key in seen:
            raise batch_error(
                "Each batch row requires a unique non-empty ID of at most 64 characters."
            )
        seen.add(key)
        body = row.get("request")
        if not isinstance(body, dict):
            raise batch_error("Each batch row requires an object request.")
        validate_batch_body(body)
        if body.get("model") != model:
            raise batch_error("All batch rows must use one upstream model.")
    content = (
        "\n".join(
            json.dumps({"id": row["id"], "request": row["request"]}, ensure_ascii=False)
            for row in rows
        )
        + "\n"
    ).encode()
    store = get_resource_store(request)
    if len(content) > store.max_blob_bytes:
        raise batch_error("Batch input exceeds the resource size limit.", 413)
    profile_id = getattr(request.state, "batch_provider_profile", None)
    if profile_id is not None:
        await bind_gigachat_profile(request, profile_id)
    now = time.time()
    public_id = "batch_g2g_" + uuid.uuid4().hex
    owner = batch_owner(request)
    # A failed/unknown intent is durable before any network effect. A crash or
    # timeout cannot safely prove whether the remote service accepted the job.
    data = {
        **(metadata or {}),
        "protocol": protocol,
        "provider": "gigachat",
        "provider_profile": getattr(request.state, "batch_provider_profile", None),
        "upstream_id": None,
        "method": method,
        "model": model,
        "rows": deepcopy(rows),
        "status": "failed",
        "submission_state": "unknown",
        "created_at": now,
        "ended_at": now,
        "deadline": now + 86400 if protocol in {"openai", "anthropic"} else None,
        "results": [
            {
                "id": row["id"],
                "error": {
                    "code": "submission_outcome_unknown",
                    "type": "api_error",
                    "message": "Submission outcome is unknown; automatic resubmission is disabled. Inspect the upstream job before retrying.",
                },
            }
            for row in rows
        ],
        "native_output_file_id": None,
    }
    await store.put(owner, "batch", public_id, data)
    options = extract_gigachat_request_options(request)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        batch = await client.with_options(max_retries=0).acreate_batch(
            content, method=method
        )
    status = _status(batch)
    # ResourceStore drains this transaction if the request is cancelled. The
    # pre-existing intent remains available even when this publication fails.
    resource = await store.update(
        owner,
        "batch",
        public_id,
        {
            "upstream_id": batch.id_,
            "status": "in_progress" if status in TERMINAL else status,
            "submission_state": "submitted",
            "ended_at": None,
            "results": [],
            "native_output_file_id": batch.output_file_id,
        },
    )
    if resource is None:
        raise ResourceStoreError("Batch submission mapping could not be published")
    return resource


async def get_batch(request: Request, batch_id: str, protocol: str) -> Resource:
    """Resolve only registered jobs of this owner and protocol."""
    for owner in _batch_owners(request):
        resource = await get_resource_store(request).get(owner, "batch", batch_id)
        if resource is not None and resource.metadata.get("protocol") == protocol:
            return resource
    raise batch_error("Batch not found.", 404)


def _expire(metadata: dict[str, Any], now: float) -> dict[str, Any]:
    if (
        metadata["status"] in TERMINAL
        or metadata.get("deadline") is None
        or now < metadata["deadline"]
    ):
        return metadata
    confirmed = {row["id"]: row for row in metadata.get("results", [])}
    metadata["results"] = [
        confirmed.get(row["id"], {"id": row["id"], "expired": True})
        for row in metadata["rows"]
    ]
    metadata["status"] = "expired"
    metadata["ended_at"] = metadata["deadline"]
    return metadata


def _results(content: bytes, rows: list[dict]) -> list[dict]:
    expected = {row["id"] for row in rows}
    found = {}
    try:
        parsed = parse_jsonl(content)
    except HTTPException as exc:
        raise batch_error("Invalid upstream batch output JSONL.", 502) from exc
    for row in parsed:
        key = row.get("id") or row.get("custom_id")
        if key not in expected or key in found:
            raise batch_error("Invalid or duplicate upstream batch row ID.", 502)
        response = row.get("response")
        status = response.get("status_code", 200) if isinstance(response, dict) else 200
        error = row.get("error")
        if error is not None or not isinstance(status, int) or status >= 400:
            found[key] = {"id": key, "error": error or extract_batch_result_body(row)}
        else:
            body = extract_batch_result_body(row)
            if not any(
                name in row for name in ("result", "response", "body")
            ) or not isinstance(body, dict):
                raise batch_error("Invalid upstream batch result body.", 502)
            found[key] = {
                "id": key,
                "result": body,
                "request_id": row.get("request_id") or key,
            }
    return [found[row["id"]] for row in rows if row["id"] in found]


async def poll_batch(request: Request, batch_id: str, protocol: str) -> Resource:
    """Poll on demand; persist confirmed outcomes and enforce acceptance deadlines."""
    resource = await get_batch(request, batch_id, protocol)
    store = get_resource_store(request)
    owner = batch_owner(request, resource)
    if resource.metadata["status"] in TERMINAL:
        return resource
    if (
        resource.metadata.get("deadline") is not None
        and time.time() >= resource.metadata["deadline"]
    ):
        resource = await store.update(
            owner, "batch", batch_id, lambda m: _expire(m, time.time())
        )
    if resource.metadata["status"] in TERMINAL:
        return resource
    profile_id = resource.metadata.get("provider_profile")
    if profile_id is not None:
        await bind_gigachat_profile(request, profile_id)
    options = extract_gigachat_request_options(request)
    async with gigachat_request_options(
        get_gigachat_client(request), options, include_body=False
    ) as client:
        response = await client.aget_batches(batch_id=resource.metadata["upstream_id"])
        matching = [
            b for b in response.batches if b.id_ == resource.metadata["upstream_id"]
        ]
        if len(matching) != 1:
            raise batch_error("Upstream batch was not found.", 502)
        batch = matching[0]
        status = _status(batch)
        results = []
        if batch.output_file_id:
            content = await client.aget_file_content(file_id=batch.output_file_id)
            if len(content) > store.max_blob_bytes:
                raise batch_error(
                    "Upstream batch output exceeds the resource size limit.", 502
                )
            results = _results(content, resource.metadata["rows"])

    def apply(metadata):
        metadata = _expire(metadata, time.time())
        if metadata["status"] in TERMINAL:
            return metadata
        confirmed = {row["id"]: row for row in metadata.get("results", [])}
        confirmed.update({row["id"]: row for row in results})
        if status in TERMINAL:
            for row in metadata["rows"]:
                confirmed.setdefault(
                    row["id"],
                    {
                        "id": row["id"],
                        "error": {
                            "type": "api_error",
                            "code": "missing_batch_result",
                            "message": "Upstream batch ended without a result for this row.",
                        },
                    },
                )
        metadata.update(
            status=status,
            native_output_file_id=batch.output_file_id,
            results=[
                confirmed[row["id"]]
                for row in metadata["rows"]
                if row["id"] in confirmed
            ],
        )
        if status in TERMINAL:
            # Observation time, never upstream updated_at as a completion proof.
            metadata["ended_at"] = time.time()
        return metadata

    return await store.update(owner, "batch", batch_id, apply)


async def list_batches(
    request: Request,
    protocol: str,
    *,
    limit: int | None = None,
    after: str | None = None,
    before: str | None = None,
) -> list[Resource]:
    """Validate pagination locally, then refresh only returned active jobs."""
    if limit is not None:
        try:
            stored = await get_resource_store(request).page(
                _batch_owners(request),
                "batch",
                protocol=protocol,
                limit=limit,
                after=after,
                before=before,
            )
        except ResourceNotFoundError as exc:
            raise batch_error("Invalid batch cursor.") from exc
        return [
            await poll_batch(request, row.public_id, protocol) for row in stored[:limit]
        ] + stored[limit:]
    stored = []
    for owner in _batch_owners(request):
        stored.extend(await get_resource_store(request).list(owner, "batch"))
    stored.sort(key=lambda row: (row.created_at, row.public_id), reverse=True)
    return [
        await poll_batch(request, row.public_id, protocol)
        for row in stored
        if row.metadata.get("protocol") == protocol
    ]


async def result_file(request: Request, resource, suffix: str, content: bytes) -> str:
    """Publish a deterministic result file once, preserving it across restarts."""
    file_id = f"file_g2g_{resource.public_id}_{suffix}"
    store, owner = get_resource_store(request), batch_owner(request, resource)
    if await store.get(owner, "file", file_id) is None:
        metadata = {
            "id": file_id,
            "object": "file",
            "bytes": len(content),
            "created_at": int(resource.created_at),
            "filename": f"{suffix}.jsonl",
            "purpose": "batch_output",
            "mime_type": "application/jsonl",
            "protocol": resource.metadata["protocol"],
            "provider_profile": resource.metadata.get("provider_profile"),
            "local": True,
            "downloadable": True,
            "upstream_id": None,
        }
        try:
            await store.put(
                owner,
                "file",
                file_id,
                metadata,
                blob=content,
                expires_at=resource.expires_at,
            )
        except sqlite3.IntegrityError:
            # Another worker materialized the same immutable terminal result.
            pass
    return file_id


async def prepare_rows(
    request: Request, source_rows: list[dict], endpoint: str
) -> tuple[list[dict], str]:
    """Validate and transform a single stateless endpoint/model family."""
    target = get_batch_target(endpoint)
    rows = []
    seen = set()
    selected_model = None
    # Validate every row before an attachment transformer can perform I/O.
    for row in source_rows:
        key, body = row.get("custom_id"), row.get("body")
        if not isinstance(key, str) or not key or len(key) > 64 or key in seen:
            raise batch_error("custom_id must be unique and contain 1–64 characters.")
        seen.add(key)
        if not isinstance(body, dict):
            raise batch_error("Each batch row needs an object body.")
        if (
            row.get("method") != "POST"
            or get_batch_target(row.get("url", "")).kind != target.kind
        ):
            raise batch_error("All rows must POST to the batch endpoint family.")
        validate_batch_body(body)
        model = resolve_batch_model(
            request, body.get("model"), embeddings=target.kind == "embeddings"
        )
        if selected_model is not None and selected_model != model:
            raise batch_error("A batch cannot mix upstream models.")
        selected_model = model
    if not source_rows:
        raise batch_error("Batch input must not be empty.")
    profile_id = getattr(request.state, "batch_provider_profile", None)
    if profile_id is not None:
        await bind_gigachat_profile(request, profile_id)
    for row in source_rows:
        await validate_model_attachments(request, row["body"])
    for row in source_rows:
        body = deepcopy(row["body"])
        body["model"] = selected_model
        if target.kind == "chat":
            native = await get_request_transformer(request).prepare_chat(
                body, get_gigachat_client(request), forced_model=selected_model
            )
        elif target.kind == "responses":
            native = await get_request_transformer(request).prepare_response_chat(
                body, get_gigachat_client(request)
            )
        else:
            native = await transform_embedding_body(
                body, selected_model, pass_model=True
            )
        native["model"] = selected_model
        rows.append(
            {"id": row["custom_id"], "request": native, "original": row["body"]}
        )
    return rows, selected_model
