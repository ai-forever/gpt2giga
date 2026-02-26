"""Shared project constants."""

import re

DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES = 35 * 1024 * 1024
DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES = 15 * 1024 * 1024
DEFAULT_MAX_TEXT_FILE_SIZE_BYTES = 40 * 1024 * 1024
DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES = 80 * 1024 * 1024
DEFAULT_MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024

SECURITY_FIELDS = frozenset(
    {
        "api_key",
        "enable_api_key_auth",
        "cors_allow_origins",
        "cors_allow_methods",
        "cors_allow_headers",
        "logs_ip_allowlist",
        "log_redact_sensitive",
        "max_request_body_bytes",
        "max_audio_file_size_bytes",
        "max_image_file_size_bytes",
        "max_text_file_size_bytes",
        "max_audio_image_total_size_bytes",
    }
)

SUPPORTED_TEXT_MIME_TYPES = frozenset(
    {
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
        "application/epub",
        "application/ppt",
        "application/pptx",
    }
)

SUPPORTED_IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/tiff", "image/bmp", "image/jpg"}
)

SUPPORTED_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/mp4",
        "audio/mp3",
        "audio/x-m4a",
        "audio/x-wav",
        "audio/wave",
        "audio/wav",
        "audio/x-pn-wav",
        "audio/webm",
        "audio/x-ogg",
        "audio/opus",
    }
)

SUPPORTED_TEXT_EXTENSIONS = frozenset(
    {"txt", "doc", "docx", "pdf", "epub", "ppt", "pptx"}
)
SUPPORTED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "tif", "tiff", "bmp"})
SUPPORTED_AUDIO_EXTENSIONS = frozenset(
    {"mp4", "mp3", "m4a", "wav", "weba", "ogg", "opus"}
)

# Sensitive field names to redact from log messages.
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "api-key",
        "x-api-key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "passwd",
        "credentials",
        "authorization",
        "secret",
        "secret_key",
        "key_file_password",
    }
)

_KEYS_PATTERN = "|".join(re.escape(k) for k in SENSITIVE_KEYS)

# "key": "value" or 'key': 'value' (JSON-style)
_JSON_KV_RE = re.compile(
    r"""(['"])({keys})\1\s*:\s*(['"])(.+?)\3""".format(keys=_KEYS_PATTERN),
    re.IGNORECASE,
)

# key=value (query-param / env-var style)
_KV_EQ_RE = re.compile(
    r"\b({keys})=([^\s&,;]+)".format(keys=_KEYS_PATTERN),
    re.IGNORECASE,
)

# Bearer <token>
_BEARER_RE = re.compile(r"(Bearer\s+)\S+", re.IGNORECASE)

_SENSITIVE_CLI_ARGS = frozenset(
    {
        "--proxy.api-key",
        "--gigachat.credentials",
        "--gigachat.password",
        "--gigachat.access-token",
        "--gigachat.key-file-password",
    }
)

_AUTH_KEYS = ("credentials", "user", "password", "access_token", "key_file_password")
