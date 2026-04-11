"""Responses API v2 threading helpers."""

from typing import Any, Dict, Optional


class ResponsesV2ThreadingMixin:
    """Resolve Responses API thread identifiers."""

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

        return None
