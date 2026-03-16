from email.parser import BytesParser
from email.policy import default
from typing import Any, Dict

from fastapi import HTTPException
from starlette.requests import Request


async def read_request_multipart(request: Request) -> Dict[str, Any]:
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

    form: Dict[str, str] = {}
    files: Dict[str, Dict[str, Any]] = {}
    for part in message.iter_parts():
        field_name = part.get_param("name", header="content-disposition")
        if not field_name:
            continue

        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is None:
            charset = part.get_content_charset() or "utf-8"
            form[field_name] = payload.decode(charset)
            continue

        files[field_name] = {
            "filename": filename,
            "content": payload,
            "content_type": part.get_content_type(),
        }

    return {"form": form, "files": files}
