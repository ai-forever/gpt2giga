import mimetypes
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

_CONTENT_TYPE_OVERRIDES = {
    ".jsonl": "application/json",
}


def _guess_content_type(filename: str | None) -> str | None:
    """Guess a supported content type from a filename."""
    if not filename:
        return None

    guessed_type, _ = mimetypes.guess_type(filename)
    if guessed_type:
        return guessed_type

    return _CONTENT_TYPE_OVERRIDES.get(Path(filename).suffix.lower())


def _normalize_file_content_type(content_type: str | None, filename: str | None) -> str:
    """Prefer a filename-derived MIME type when the upload uses a generic one."""
    normalized_content_type = (content_type or "").split(";", maxsplit=1)[0].strip()
    inferred_content_type = _guess_content_type(filename)

    if inferred_content_type and normalized_content_type in {
        "",
        "application/octet-stream",
    }:
        return inferred_content_type

    return normalized_content_type or "application/octet-stream"


async def read_request_multipart(request: Request) -> dict[str, Any]:
    """Read and parse a multipart/form-data request body."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Request must be multipart/form-data.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_multipart",
                }
            },
        )

    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Request body is empty (expected multipart/form-data).",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_multipart",
                }
            },
        )

    raw_message = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    message = BytesParser(policy=default).parsebytes(raw_message)
    if not message.is_multipart():
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": "Invalid multipart/form-data body.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "invalid_multipart",
                }
            },
        )

    form: dict[str, str] = {}
    files: dict[str, dict[str, Any]] = {}
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if not isinstance(field_name, str) or not field_name:
            continue

        filename = part.get_filename()
        raw_payload = part.get_payload(decode=True)
        payload = raw_payload if isinstance(raw_payload, bytes) else b""
        if filename is None:
            charset = part.get_content_charset() or "utf-8"
            form[field_name] = payload.decode(charset)
            continue

        files[field_name] = {
            "filename": filename,
            "content": payload,
            "content_type": _normalize_file_content_type(
                part.get_content_type(), filename
            ),
        }

    return {"form": form, "files": files}
