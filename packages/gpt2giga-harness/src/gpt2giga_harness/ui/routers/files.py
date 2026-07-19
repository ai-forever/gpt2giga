"""Safe previews for local files referenced by Harness messages."""

from __future__ import annotations

from html.parser import HTMLParser
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response

from gpt2giga_harness.attachments.limits import AttachmentLimits, is_denied_path
from gpt2giga_harness.generated_files import GeneratedFileError, generated_file_path
from gpt2giga_harness.safe_paths import (
    PathBoundaryError,
    resolve_operator_path,
    resolve_path_within,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute

_MAX_PREVIEW_BYTES = 25 * 1024 * 1024
# The iframe starts same-origin so browser-session auth is sent. This response
# sandbox deliberately omits allow-same-origin, making the executed document opaque.
_GENERATED_HTML_CSP = (
    "sandbox allow-scripts; default-src 'none'; "
    "script-src 'unsafe-inline' 'unsafe-eval' blob: data:; "
    "img-src data: blob:; style-src 'unsafe-inline'; font-src data: blob:; "
    "media-src data: blob:; connect-src 'none'; worker-src blob:; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)
_GENERATED_HTML_META_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: data:; "
    "img-src data: blob:; style-src 'unsafe-inline'; font-src data: blob:; "
    "media-src data: blob:; connect-src 'none'; worker-src blob:; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)
_SAFE_IMAGE_TYPES = frozenset(
    {
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)
_SAFE_TEXT_SUFFIXES = frozenset(
    {
        ".css",
        ".csv",
        ".go",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsonl",
        ".log",
        ".md",
        ".py",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)


def create_file_preview_router(data_dir: str | None = None) -> APIRouter:
    """Create the bounded local-file preview router."""
    router = APIRouter(route_class=ConformantAPIRoute)

    @router.get("/api/files/generated/{run_key}/{filename}", response_class=Response)
    def generated_file(
        run_key: str,
        filename: str,
        download: str | None = Query(default=None),
        preview: Literal["html"] | None = Query(default=None),
    ) -> Response:
        if data_dir is None:
            raise HTTPException(status_code=404, detail="Generated file not found")
        try:
            resolved = generated_file_path(data_dir, run_key, filename)
        except GeneratedFileError as exc:
            raise HTTPException(
                status_code=404, detail="Generated file not found"
            ) from exc
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="Generated file not found")
        if download is not None and preview is not None:
            raise HTTPException(
                status_code=400,
                detail="Generated file cannot be previewed and downloaded together",
            )
        is_html_preview = preview == "html" and resolved.suffix.lower() == ".html"
        if preview is not None and not is_html_preview:
            raise HTTPException(status_code=415, detail="Generated file type is unsafe")
        media_type = (
            "text/html; charset=utf-8"
            if is_html_preview
            else _preview_media_type(resolved)
        )
        if download is None and media_type not in _SAFE_IMAGE_TYPES:
            if not is_html_preview:
                raise HTTPException(
                    status_code=415, detail="Generated file type is unsafe"
                )
        if resolved.stat().st_size > _MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="Generated file is too large")
        headers = {
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        }
        if is_html_preview:
            headers.update(
                {
                    "Content-Security-Policy": _GENERATED_HTML_CSP,
                    "Referrer-Policy": "no-referrer",
                }
            )
            return HTMLResponse(
                _sandboxed_html_source(resolved),
                headers=headers,
            )
        return FileResponse(
            resolved,
            media_type=media_type or "application/octet-stream",
            filename=(
                _safe_download_name(download, resolved.suffix)
                if download is not None
                else None
            ),
            headers=headers,
        )

    @router.get("/api/files/preview", response_class=FileResponse)
    def preview_file(
        path: str = Query(min_length=1),
        workspace: str | None = Query(default=None),
    ) -> FileResponse:
        resolved, allowed_root = _resolve_preview_path(path, workspace)
        relative = resolved.relative_to(allowed_root).as_posix()
        if is_denied_path(relative, AttachmentLimits()):
            raise HTTPException(status_code=403, detail="File preview is denied")
        media_type = _preview_media_type(resolved)
        if media_type is None:
            raise HTTPException(
                status_code=415,
                detail="File type is not supported for inline preview",
            )
        size = resolved.stat().st_size
        if size > _MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="File is too large to preview")
        return FileResponse(
            resolved,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


def _sandboxed_html_source(path: Path) -> str:
    source = path.read_text(encoding="utf-8", errors="replace")
    metadata = (
        '<meta http-equiv="Content-Security-Policy" '
        f'content="{_GENERATED_HTML_META_CSP}">'
        '<meta name="referrer" content="no-referrer">'
    )
    locator = _HtmlInsertionLocator(source)
    locator.feed(source)
    locator.close()
    if locator.head_end is not None:
        offset = locator.head_end
        insertion = metadata
    elif locator.html_end is not None:
        offset = locator.html_end
        insertion = f"<head>{metadata}</head>"
    elif locator.body_start is not None:
        offset = locator.body_start
        insertion = f"<head>{metadata}</head>"
    else:
        offset = locator.doctype_end or 0
        insertion = f"<head>{metadata}</head>"
    return f"{source[:offset]}{insertion}{source[offset:]}"


class _HtmlInsertionLocator(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self._line_starts = [0]
        self._line_starts.extend(
            index + 1 for index, character in enumerate(source) if character == "\n"
        )
        self.body_start: int | None = None
        self.doctype_end: int | None = None
        self.head_end: int | None = None
        self.html_end: int | None = None

    def handle_decl(self, decl: str) -> None:
        if self.doctype_end is None and decl.lower().startswith("doctype"):
            self.doctype_end = self._offset() + len(decl) + 3

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        raw = self.get_starttag_text()
        offset = self._offset()
        if tag == "head" and self.head_end is None:
            self.head_end = offset + len(raw)
        elif tag == "html" and self.html_end is None:
            self.html_end = offset + len(raw)
        elif tag == "body" and self.body_start is None:
            self.body_start = offset

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column


def _safe_download_name(value: str, suffix: str) -> str:
    candidate = Path(value).name[:128]
    if (
        not candidate
        or Path(candidate).suffix.lower() != suffix.lower()
        or re.fullmatch(r"[A-Za-z0-9._ -]+", candidate) is None
    ):
        return f"generated-file{suffix.lower()}"
    return candidate


def _resolve_preview_path(path: str, workspace: str | None) -> tuple[Path, Path]:
    workspace_root = _directory_root(workspace) if workspace else None
    if os.path.isabs(path):
        resolved = resolve_operator_path(path)
    elif workspace_root is not None:
        try:
            resolved = resolve_path_within(workspace_root, path)
        except PathBoundaryError as exc:
            raise HTTPException(
                status_code=403,
                detail="File is outside the workspace and temporary directories",
            ) from exc
    else:
        raise HTTPException(
            status_code=400,
            detail="Relative file previews require a workspace",
        )
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    roots = [root for root in (workspace_root, *_temporary_roots()) if root is not None]
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved, root
    raise HTTPException(
        status_code=403,
        detail="File is outside the workspace and temporary directories",
    )


def _directory_root(value: str) -> Path:
    # A browser session is same-principal operator access: this root is the
    # operator-selected authority boundary, while _resolve_preview_path prevents
    # a requested child path from escaping it through traversal or symlinks.
    root = resolve_operator_path(value)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail="Workspace is not a directory")
    return root


def _temporary_roots() -> tuple[Path, ...]:
    roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
    }
    return tuple(sorted(roots, key=str))


def _preview_media_type(path: Path) -> str | None:
    media_type, _ = mimetypes.guess_type(path.name)
    if media_type in _SAFE_IMAGE_TYPES or media_type == "application/pdf":
        return media_type
    if path.suffix.lower() in _SAFE_TEXT_SUFFIXES:
        return "text/plain; charset=utf-8"
    return None
