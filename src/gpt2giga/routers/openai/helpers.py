"""Shared helpers for OpenAI-compatible API routes."""

import re
from typing import Optional

from fastapi import HTTPException, Request

from gpt2giga.protocol.files import _serialize_file_object as _serialize_file_object

GPT2GIGA_ATTACHMENT_IDS_HEADER = "x-gpt2giga-attachment-ids"
_FILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_MAX_REQUEST_ATTACHMENT_IDS = 10


def request_attachment_ids(request: Request) -> tuple[str, ...]:
    """Parse GigaChat file ids supplied by a trusted local Harness request."""
    raw_value = request.headers.get(GPT2GIGA_ATTACHMENT_IDS_HEADER)
    if not raw_value:
        return ()
    file_ids = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    if (
        not file_ids
        or len(file_ids) > _MAX_REQUEST_ATTACHMENT_IDS
        or len(set(file_ids)) != len(file_ids)
        or any(_FILE_ID_PATTERN.fullmatch(file_id) is None for file_id in file_ids)
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": (
                        f"`{GPT2GIGA_ATTACHMENT_IDS_HEADER}` must contain up to "
                        f"{_MAX_REQUEST_ATTACHMENT_IDS} unique GigaChat file ids."
                    ),
                    "type": "invalid_request_error",
                    "param": GPT2GIGA_ATTACHMENT_IDS_HEADER,
                    "code": "invalid_attachment_ids",
                }
            },
        )
    return file_ids


def _paginate_items(
    items: list, after: Optional[str], limit: Optional[int]
) -> tuple[list, bool]:
    """Apply simple cursor pagination."""
    if after:
        for index, item in enumerate(items):
            if item.get("id") == after:
                items = items[index + 1 :]
                break
    if limit is None:
        return items, False
    return items[:limit], len(items) > limit
