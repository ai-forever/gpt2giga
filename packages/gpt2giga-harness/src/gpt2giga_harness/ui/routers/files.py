"""Safe previews for local files referenced by Harness messages."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
import tempfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from gpt2giga_harness.attachments.limits import AttachmentLimits, is_denied_path
from gpt2giga_harness.generated_files import GeneratedFileError, generated_file_path
from gpt2giga_harness.safe_paths import (
    PathBoundaryError,
    resolve_operator_path,
    resolve_path_within,
)
from gpt2giga_harness.ui.async_execution import ConformantAPIRoute

_MAX_PREVIEW_BYTES = 25 * 1024 * 1024
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

    @router.get(
        "/api/files/generated/{run_key}/{filename}", response_class=FileResponse
    )
    def generated_file(run_key: str, filename: str) -> FileResponse:
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
        media_type = _preview_media_type(resolved)
        if media_type not in _SAFE_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Generated file type is unsafe")
        if resolved.stat().st_size > _MAX_PREVIEW_BYTES:
            raise HTTPException(status_code=413, detail="Generated file is too large")
        return FileResponse(
            resolved,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
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
