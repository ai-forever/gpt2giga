"""Shared API path normalization for routing and early error projection."""

from collections.abc import Collection

GATEWAY_API_ROOTS = (
    "v1",
    "v2",
    "v1beta",
    "upload",
    "chat",
    "models",
    "embeddings",
    "messages",
    "responses",
    "model",
    "files",
    "batches",
    "bridge",
    "health",
    "ping",
    "ready",
)


def normalize_api_path(
    path: str, valid_roots: Collection[str] = GATEWAY_API_ROOTS
) -> str | None:
    """Rewrite from the first recognized API root, or return None if unchanged."""
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None

    for index, segment in enumerate(segments):
        if segment not in valid_roots:
            continue
        normalized_segments = segments[index:]
        # Claude gateway v2 can wrap an inner API version segment.
        if (
            len(normalized_segments) > 2
            and normalized_segments[0] == "v2"
            and normalized_segments[1] in {"v1", "v2"}
            and normalized_segments[2] in valid_roots
        ):
            normalized_segments.pop(1)

        while (
            len(normalized_segments) > 1
            and normalized_segments[0] in {"v1", "v2"}
            and normalized_segments[1] == normalized_segments[0]
        ):
            normalized_segments.pop(1)

        if index == 0 and normalized_segments == segments:
            return None
        return "/" + "/".join(normalized_segments)

    return None
