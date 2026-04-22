"""HTTP parsing helpers shared across route modules."""

from gpt2giga.core.http.client_ip import resolve_client_ip
from gpt2giga.core.http.form_body import read_request_multipart
from gpt2giga.core.http.json_body import read_request_json
from gpt2giga.core.http.sse import (
    format_chat_stream_chunk,
    format_chat_stream_done,
    format_responses_stream_event,
)

__all__ = [
    "resolve_client_ip",
    "read_request_json",
    "read_request_multipart",
    "format_chat_stream_chunk",
    "format_chat_stream_done",
    "format_responses_stream_event",
]
