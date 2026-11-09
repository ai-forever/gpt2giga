import codecs
import mimetypes
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request

from gpt2giga.common.files import file_upload_size_limit
from gpt2giga.models.security import DEFAULT_MAX_REQUEST_BODY_BYTES


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


def _invalid_multipart(
    message: str = "Invalid multipart/form-data body.",
) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": None,
                "code": "invalid_multipart",
            }
        },
    )


class _CompleteMultipartParser(MultiPartParser):
    """Keep Starlette spooling while rejecting incomplete or invalid encodings."""

    complete = False

    def on_headers_finished(self) -> None:
        super().on_headers_finished()
        self._part_charset = self._charset
        for name, value in self._current_part.item_headers:
            if name == b"content-type":
                _, options = parse_options_header(value)
                if b"charset" in options:
                    self._part_charset = options[b"charset"].decode("ascii")
        codecs.lookup(self._part_charset)

    def on_part_end(self) -> None:
        charset = self._charset
        try:
            self._charset = self._part_charset
            super().on_part_end()
        finally:
            self._charset = charset

    def on_end(self) -> None:
        self.complete = True


async def read_request_multipart(request: Request) -> Dict[str, Any]:
    """Parse bounded multipart uploads using Starlette's spooled file storage."""
    content_type, options = parse_options_header(
        request.headers.get("content-type", "")
    )
    if content_type != b"multipart/form-data":
        raise _invalid_multipart("Request must be multipart/form-data.")
    try:
        codecs.lookup(options.get(b"charset", b"utf-8").decode("ascii"))
    except (LookupError, UnicodeError) as exc:
        raise _invalid_multipart("Invalid multipart character encoding.") from exc

    settings = getattr(
        getattr(getattr(request.scope.get("app"), "state", None), "config", None),
        "proxy_settings",
        None,
    )
    limit = getattr(settings, "max_request_body_bytes", DEFAULT_MAX_REQUEST_BODY_BYTES)

    async def chunks():
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise HTTPException(
                    413,
                    detail={
                        "error": {
                            "message": f"Request body too large: {received} bytes exceeds limit of {limit} bytes.",
                            "type": "invalid_request_error",
                            "param": None,
                            "code": "request_entity_too_large",
                        }
                    },
                )
            # Body validation may supply one large buffered ASGI message. Feeding
            # bounded slices avoids a second full-size multipart parser buffer.
            for offset in range(0, len(chunk), 64 * 1024):
                yield chunk[offset : offset + 64 * 1024]

    parser = _CompleteMultipartParser(request.headers, chunks(), max_part_size=limit)
    try:
        parsed = await parser.parse()
        if not parser.complete:
            raise _invalid_multipart()
        form = {
            name: value
            for name, value in parsed.multi_items()
            if isinstance(value, str)
        }
        files: Dict[str, Dict[str, Any]] = {}
        for field_name, value in parsed.multi_items():
            if isinstance(value, UploadFile):
                mime_type = _normalize_file_content_type(
                    value.content_type, value.filename
                )
                file_limit = (
                    file_upload_size_limit(
                        settings,
                        mime_type,
                        value.filename or "",
                        form.get("purpose", "user_data"),
                    )
                    if settings is not None
                    else limit
                )
                if value.size is not None and value.size > file_limit:
                    raise HTTPException(
                        413, detail="File exceeds the configured upload size limit."
                    )
                files[field_name] = {
                    "filename": value.filename,
                    "content": await value.read(),
                    "content_type": mime_type,
                }
        return {"form": form, "files": files}
    except (MultiPartException, MultipartParseError, LookupError, UnicodeError) as exc:
        raise _invalid_multipart() from exc
    finally:
        # Starlette's parser only closes these on selected parse errors. Close on
        # cancellation, malformed input and successful consumption as well.
        for file in parser._files_to_close_on_error:
            file.close()
