"""Optional OpenSearch traffic log mirror sink."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable, Sequence
from typing import Any

from gpt2giga.sinks.logs.serialization import traffic_event_to_json_dict

OpenSearchClientFactory = Callable[[], Any]


class OpenSearchTrafficLogSink:
    """Mirror traffic log events to OpenSearch using the Bulk API."""

    def __init__(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        index: str = "gpt2giga-traffic",
        data_stream: bool = True,
        client_factory: OpenSearchClientFactory | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.05,
        logger: Any | None = None,
    ):
        self.url = url
        self.username = username
        self.password = password
        self.index = index
        self.data_stream = data_stream
        self.client_factory = client_factory
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.logger = logger
        self._client: Any | None = None

    async def emit(self, event: Any) -> None:
        """Mirror one traffic log event."""
        await self.emit_many([event])

    async def emit_many(self, events: Sequence[Any]) -> None:
        """Mirror a batch of traffic log events best effort."""
        if not events:
            return

        body = build_opensearch_bulk_body(
            events,
            index=self.index,
            data_stream=self.data_stream,
        )
        for attempt in range(self.max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.bulk(body=body)
                if isinstance(response, dict) and response.get("errors"):
                    self._log_warning("OpenSearch traffic log bulk response had errors")
                return
            except Exception as exc:  # pragma: no cover - no-raise behavior tested
                if attempt >= self.max_retries:
                    self._log_warning(
                        "OpenSearch traffic log bulk write failed: {}", exc
                    )
                    return
                await asyncio.sleep(self.retry_backoff_seconds * (attempt + 1))

    async def flush(self) -> None:
        """Close the lazy OpenSearch client best effort."""
        if self._client is None:
            return
        client = self._client
        self._client = None
        close = getattr(client, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client = await self._create_client()
        return self._client

    async def _create_client(self) -> Any:
        if self.client_factory is not None:
            client = self.client_factory()
            if inspect.isawaitable(client):
                return await client
            return client
        try:
            from opensearchpy import AsyncOpenSearch
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install gpt2giga with the 'opensearch' extra to use OpenSearch traffic logs."
            ) from exc
        auth = None
        if self.username or self.password:
            auth = (self.username or "", self.password or "")
        return AsyncOpenSearch([self.url], http_auth=auth)

    def _log_warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)


def build_opensearch_bulk_body(
    events: Sequence[Any],
    *,
    index: str,
    data_stream: bool = True,
) -> str:
    """Build newline-delimited JSON for the OpenSearch Bulk API."""
    operation = "create" if data_stream else "index"
    lines: list[str] = []
    for event in events:
        payload = traffic_event_to_json_dict(event)
        event_id = payload.get("id")
        action = {operation: {"_index": index}}
        if event_id:
            action[operation]["_id"] = str(event_id)
        lines.append(json.dumps(action, ensure_ascii=False, separators=(",", ":")))
        lines.append(
            json.dumps(
                _document_from_event(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        )
    return "\n".join(lines) + "\n"


def _document_from_event(payload: dict[str, Any]) -> dict[str, Any]:
    document = dict(payload)
    created_at = document.get("created_at")
    if created_at is not None:
        document["@timestamp"] = created_at
    document["model"] = document.get("model_effective") or document.get(
        "model_requested"
    )
    status_code = document.get("status_code")
    document["has_error"] = bool(document.get("error_type")) or (
        isinstance(status_code, int) and status_code >= 400
    )
    return document
