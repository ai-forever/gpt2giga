"""MIME and attachment-kind detection helpers."""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath

from gpt2giga.harness.attachments.models import AttachmentKind

TEXT_MIME_TYPES = {
    "application/json",
    "application/jsonl",
    "application/toml",
    "application/x-ndjson",
    "application/x-python-code",
    "application/x-sh",
    "application/x-yaml",
    "application/xml",
    "image/svg+xml",
}
TEXT_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".log",
    ".lua",
    ".md",
    ".php",
    ".py",
    ".rb",
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
    ".zsh",
}
DOCUMENT_MIME_TYPES = {
    "application/msword",
    "application/pdf",
    "application/rtf",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".odt", ".pdf", ".rtf"}
IMAGE_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/svg+xml",
    "image/webp",
}


def detect_mime_type(
    filename: str,
    provided: str | None = None,
    data: bytes | None = None,
) -> str:
    """Return a best-effort MIME type without trusting empty user input."""
    normalized = _clean_mime_type(provided)
    if normalized:
        return normalized
    signature = _mime_from_signature(data or b"")
    if signature:
        return signature
    guessed, _encoding = mimetypes.guess_type(filename)
    return _clean_mime_type(guessed) or "application/octet-stream"


def detect_attachment_kind(
    filename: str,
    mime_type: str,
    data: bytes | None = None,
) -> AttachmentKind:
    """Classify an attachment for safety checks and render planning."""
    normalized_mime = _clean_mime_type(mime_type) or "application/octet-stream"
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if normalized_mime in IMAGE_MIME_TYPES:
        return AttachmentKind.IMAGE
    if normalized_mime.startswith("text/"):
        return AttachmentKind.TEXT
    if normalized_mime in TEXT_MIME_TYPES or extension in TEXT_EXTENSIONS:
        return AttachmentKind.TEXT
    if normalized_mime in DOCUMENT_MIME_TYPES or extension in DOCUMENT_EXTENSIONS:
        return AttachmentKind.DOCUMENT
    if data is not None and _looks_like_utf8_text(data):
        return AttachmentKind.TEXT
    return AttachmentKind.BINARY


def _clean_mime_type(value: str | None) -> str | None:
    if value is None:
        return None
    mime_type = value.split(";", 1)[0].strip().lower()
    if not mime_type or "/" not in mime_type:
        return None
    return mime_type


def _mime_from_signature(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _looks_like_utf8_text(data: bytes) -> bool:
    if not data:
        return True
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
