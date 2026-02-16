"""Shared project constants."""

DEFAULT_MAX_AUDIO_FILE_SIZE_BYTES = 35 * 1024 * 1024
DEFAULT_MAX_IMAGE_FILE_SIZE_BYTES = 15 * 1024 * 1024
DEFAULT_MAX_TEXT_FILE_SIZE_BYTES = 40 * 1024 * 1024
DEFAULT_MAX_AUDIO_IMAGE_TOTAL_SIZE_BYTES = 80 * 1024 * 1024

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
