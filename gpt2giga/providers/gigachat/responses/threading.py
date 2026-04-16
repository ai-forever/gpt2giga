"""Responses API v2 threading helpers."""

from typing import Any, Dict, Optional


class ResponsesV2ThreadingMixin:
    """Resolve Responses API thread identifiers."""

    def _resolve_response_storage(
        self,
        data: Dict[str, Any],
        response_store: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        raw_storage = data.get("storage")
        storage_config: Dict[str, Any] = {}
        enable_storage = False

        if raw_storage is not None:
            if isinstance(raw_storage, bool):
                raise self._invalid_request(
                    "Boolean `storage` is not supported yet.",
                    param="storage",
                )
            if not isinstance(raw_storage, dict):
                raise self._invalid_request(
                    "`storage` must be an object.",
                    param="storage",
                )
            enable_storage = True

            limit = raw_storage.get("limit")
            if limit is not None:
                if not isinstance(limit, int):
                    raise self._invalid_request(
                        "`storage.limit` must be an integer.",
                        param="storage.limit",
                    )
                storage_config["limit"] = limit

            metadata = raw_storage.get("metadata")
            if metadata is not None:
                if not isinstance(metadata, dict):
                    raise self._invalid_request(
                        "`storage.metadata` must be an object.",
                        param="storage.metadata",
                    )
                storage_config["metadata"] = metadata

        thread_id = self._resolve_response_thread_id(data, response_store)
        if thread_id:
            enable_storage = True
            storage_config["thread_id"] = thread_id
        elif isinstance(raw_storage, dict):
            raw_thread_id = raw_storage.get("thread_id")
            if raw_thread_id is not None:
                if not isinstance(raw_thread_id, str) or not raw_thread_id:
                    raise self._invalid_request(
                        "`storage.thread_id` must be a string.",
                        param="storage.thread_id",
                    )
                storage_config["thread_id"] = raw_thread_id

        if not enable_storage:
            store = data.get("store", True)
            enable_storage = store is not False

        if not enable_storage:
            return None

        return storage_config

    def _resolve_response_thread_id(
        self,
        data: Dict[str, Any],
        response_store: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        conversation = data.get("conversation")
        previous_response_id = data.get("previous_response_id")

        if conversation is not None and previous_response_id is not None:
            raise self._invalid_request(
                "`conversation` and `previous_response_id` cannot be used together.",
                param="conversation",
            )

        if conversation is not None:
            if not isinstance(conversation, dict) or not isinstance(
                conversation.get("id"),
                str,
            ):
                raise self._invalid_request(
                    "`conversation.id` must be a string.",
                    param="conversation",
                )
            return conversation["id"]

        if previous_response_id is not None:
            if not isinstance(previous_response_id, str):
                raise self._invalid_request(
                    "`previous_response_id` must be a string.",
                    param="previous_response_id",
                )
            metadata = (
                response_store.get(previous_response_id) if response_store else None
            )
            thread_id = (
                metadata.get("thread_id") if isinstance(metadata, dict) else None
            )
            if not isinstance(thread_id, str) or not thread_id:
                raise self._invalid_request(
                    f"Unknown `previous_response_id`: {previous_response_id}",
                    param="previous_response_id",
                )
            return thread_id

        raw_storage = data.get("storage")
        if isinstance(raw_storage, dict) and raw_storage.get("thread_id") is not None:
            thread_id = raw_storage.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id:
                raise self._invalid_request(
                    "`storage.thread_id` must be a string.",
                    param="storage.thread_id",
                )
            return thread_id

        return None
