"""Helpers for calling the GigaChat resource-style async API."""

from __future__ import annotations

from typing import Any, AsyncIterator


def _resource_method(
    client: Any,
    resource_name: str,
    method_name: str,
    *,
    legacy_name: str | None = None,
):
    resource = getattr(client, resource_name, None)
    method = getattr(resource, method_name, None)
    if callable(method):
        return method

    if legacy_name is not None:
        legacy_method = getattr(client, legacy_name, None)
        if callable(legacy_method):
            return legacy_method

    raise AttributeError(
        f"GigaChat client does not expose `{resource_name}.{method_name}`."
    )


async def create_primary_chat(client: Any, chat: Any) -> Any:
    """Create a primary chat completion through the resource API."""
    method = _resource_method(client, "achat", "create", legacy_name="achat_v2")
    return await method(chat)


def stream_primary_chat(client: Any, chat: Any) -> AsyncIterator[Any]:
    """Stream a primary chat completion through the resource API."""
    method = _resource_method(client, "achat", "stream", legacy_name="astream_v2")
    return method(chat)


async def create_embeddings(client: Any, *, texts: list[Any], model: str) -> Any:
    """Create embeddings through the resource API."""
    method = _resource_method(
        client,
        "a_embeddings",
        "create",
        legacy_name="aembeddings",
    )
    return await method(texts=texts, model=model)


async def list_models(client: Any) -> Any:
    """List models through the resource API."""
    method = _resource_method(client, "a_models", "list", legacy_name="aget_models")
    return await method()


async def retrieve_model(client: Any, *, model: str) -> Any:
    """Retrieve a model through the resource API."""
    method = _resource_method(
        client,
        "a_models",
        "retrieve",
        legacy_name="aget_model",
    )
    return await method(model=model)


async def upload_file(
    client: Any,
    file: Any,
    *,
    purpose: str = "general",
) -> Any:
    """Upload a file through the resource API."""
    method = _resource_method(client, "a_files", "upload", legacy_name="aupload_file")
    try:
        return await method(file, purpose=purpose)
    except TypeError as exc:
        if "purpose" not in str(exc):
            raise
        return await method(file)


async def list_files(client: Any) -> Any:
    """List files through the resource API."""
    method = _resource_method(client, "a_files", "list", legacy_name="aget_files")
    return await method()


async def retrieve_file(client: Any, *, file: str) -> Any:
    """Retrieve file metadata through the resource API."""
    method = _resource_method(client, "a_files", "retrieve", legacy_name="aget_file")
    return await method(file=file)


async def delete_file(client: Any, *, file: str) -> Any:
    """Delete a file through the resource API."""
    method = _resource_method(client, "a_files", "delete", legacy_name="adelete_file")
    return await method(file=file)


async def retrieve_file_content(client: Any, *, file_id: str) -> Any:
    """Retrieve file content through the resource API."""
    method = _resource_method(
        client,
        "a_files",
        "retrieve_content",
        legacy_name="aget_file_content",
    )
    return await method(file_id=file_id)


async def create_batch(client: Any, file: bytes, *, method: str) -> Any:
    """Create a batch through the resource API."""
    create = _resource_method(
        client, "a_batches", "create", legacy_name="acreate_batch"
    )
    return await create(file, method=method)


async def list_batches(client: Any) -> Any:
    """List batches through the resource API."""
    method = _resource_method(client, "a_batches", "list", legacy_name="aget_batches")
    return await method()


async def retrieve_batch(client: Any, *, batch_id: str) -> Any:
    """Retrieve a batch through the resource API."""
    method = _resource_method(
        client,
        "a_batches",
        "retrieve",
        legacy_name="aget_batches",
    )
    return await method(batch_id=batch_id)
