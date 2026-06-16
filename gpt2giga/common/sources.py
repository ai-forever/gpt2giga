"""Helpers for rendering GigaChat source metadata."""

import re
from collections.abc import Mapping
from typing import Any

SOURCE_MARKER_RE = re.compile(r"\[sources=\[([^\]]+)\]\]")
_SOURCE_MARKER_START = "[sources=["


def extract_sources(inline_data: Any) -> dict[str, dict[str, Any]]:
    """Return normalized GigaChat source metadata keyed by source id."""
    if not isinstance(inline_data, Mapping):
        return {}

    sources = inline_data.get("sources")
    if not isinstance(sources, Mapping):
        return {}

    normalized_sources: dict[str, dict[str, Any]] = {}
    for key, source in sources.items():
        if isinstance(source, Mapping):
            normalized_sources[str(key)] = dict(source)
    return normalized_sources


def merge_inline_data(target: dict[str, Any], inline_data: Any) -> None:
    """Merge GigaChat inline_data payloads, preserving source maps."""
    if not isinstance(inline_data, Mapping):
        return

    for key, value in inline_data.items():
        if key == "sources" and isinstance(value, Mapping):
            sources = target.setdefault("sources", {})
            if isinstance(sources, dict):
                sources.update(value)
            else:
                target["sources"] = dict(value)
        elif isinstance(value, list):
            items = target.setdefault(key, [])
            if isinstance(items, list):
                items.extend(value)
            else:
                target[key] = value
        elif value is not None:
            target[key] = value


def render_text_with_sources(text: str, inline_data: Mapping[str, Any]) -> str:
    """Replace GigaChat source markers with a visible markdown Sources section."""
    sources = extract_sources(inline_data)
    if not sources:
        return text

    source_ids = _extract_source_ids(text)
    cleaned_text = SOURCE_MARKER_RE.sub("", text).rstrip()
    appendix = _format_sources_appendix(sources, source_ids)
    if not appendix:
        return cleaned_text
    return f"{cleaned_text}{appendix}" if cleaned_text else appendix.lstrip()


def has_source_marker_start(text: Any) -> bool:
    """Return whether text contains the start of a GigaChat source marker."""
    return isinstance(text, str) and _SOURCE_MARKER_START in text


class SourceMarkerStreamRenderer:
    """Remove streamed source markers and append markdown sources at stream end."""

    def __init__(self) -> None:
        self.inline_data: dict[str, Any] = {}
        self._buffer = ""
        self._source_ids: list[str] = []
        self._source_id_set: set[str] = set()
        self._emitted_text = False

    def merge_inline_data(self, inline_data: Any) -> None:
        """Merge inline source metadata from a stream chunk."""
        merge_inline_data(self.inline_data, inline_data)

    def mark_emitted_text(self) -> None:
        """Record that surrounding stream text was already emitted."""
        self._emitted_text = True

    def feed(self, text: str) -> str:
        """Return text safe to emit for this chunk."""
        if not text:
            return ""
        self._buffer += text
        return self._drain(final=False)

    def finish(self) -> str:
        """Flush buffered text and append markdown sources when available."""
        text = self._drain(final=True)
        appendix = _format_sources_appendix(
            extract_sources(self.inline_data),
            self._source_ids,
        )
        if appendix:
            if text:
                text = f"{text.rstrip()}{appendix}"
            elif self._emitted_text:
                text = appendix
            else:
                text = appendix.lstrip()
        if text:
            self._emitted_text = True
        return text

    def _drain(self, *, final: bool) -> str:
        output: list[str] = []
        while self._buffer:
            marker_start = self._buffer.find(_SOURCE_MARKER_START)
            if marker_start < 0:
                if final:
                    output.append(self._buffer)
                    self._buffer = ""
                    break

                keep = min(len(self._buffer), len(_SOURCE_MARKER_START) - 1)
                emit_length = len(self._buffer) - keep
                if emit_length > 0:
                    output.append(self._buffer[:emit_length])
                    self._buffer = self._buffer[emit_length:]
                break

            if marker_start > 0:
                output.append(self._buffer[:marker_start].rstrip())
                self._buffer = self._buffer[marker_start:]
                continue

            marker_end = self._buffer.find("]]", len(_SOURCE_MARKER_START))
            if marker_end < 0:
                if final:
                    self._buffer = ""
                break

            self._record_source_ids(self._buffer[: marker_end + 2])
            self._buffer = self._buffer[marker_end + 2 :]

        text = "".join(output)
        if text:
            self._emitted_text = True
        return text

    def _record_source_ids(self, marker: str) -> None:
        for source_id in _extract_source_ids(marker):
            if source_id in self._source_id_set:
                continue
            self._source_id_set.add(source_id)
            self._source_ids.append(source_id)


def _extract_source_ids(text: str) -> list[str]:
    source_ids: list[str] = []
    seen: set[str] = set()
    for match in SOURCE_MARKER_RE.finditer(text):
        for source_id in _split_source_ids(match.group(1)):
            if source_id in seen:
                continue
            seen.add(source_id)
            source_ids.append(source_id)
    return source_ids


def _split_source_ids(raw_ids: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;\s]+", raw_ids) if item.strip()]


def _format_sources_appendix(
    sources: Mapping[str, Mapping[str, Any]],
    source_ids: list[str],
) -> str:
    selected_sources = _select_sources(sources, source_ids)
    if not selected_sources:
        return ""

    lines = ["", "", "Sources:"]
    for source in selected_sources:
        url = source.get("url")
        if not isinstance(url, str) or not url:
            continue
        title = source.get("title") if isinstance(source.get("title"), str) else url
        lines.append(f"- [{_escape_markdown_link_text(title)}]({url})")
    return "\n".join(lines)


def _select_sources(
    sources: Mapping[str, Mapping[str, Any]],
    source_ids: list[str],
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    seen_urls: set[str] = set()
    ordered_ids = source_ids or list(sources)

    for source_id in ordered_ids:
        source = sources.get(source_id)
        if not isinstance(source, Mapping):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        selected.append(source)
    return selected


def _escape_markdown_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")
