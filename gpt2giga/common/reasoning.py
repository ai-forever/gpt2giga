"""Helpers for extracting reasoning text embedded in model content."""

from dataclasses import dataclass
from typing import Optional


THINK_OPEN_TAG = "<think>"
THINK_CLOSE_TAG = "</think>"


def _longest_tag_prefix_suffix(text: str, tag: str) -> int:
    """Return length of text suffix that can still become tag."""
    text_lower = text.lower()
    tag_lower = tag.lower()
    max_len = min(len(text), len(tag) - 1)
    for length in range(max_len, 0, -1):
        if tag_lower.startswith(text_lower[-length:]):
            return length
    return 0


def merge_reasoning_text(
    current: Optional[str],
    extracted: Optional[str],
) -> Optional[str]:
    """Append extracted reasoning to existing reasoning text."""
    if not extracted:
        return current
    if not current:
        return extracted
    return f"{current}\n{extracted}"


@dataclass
class ReasoningContent:
    """Visible content and extracted reasoning text."""

    content: str
    reasoning_content: str


class ReasoningContentParser:
    """Incrementally extracts ``<think>...</think>`` from streamed content."""

    def __init__(self):
        self._buffer = ""
        self._in_reasoning = False

    def feed(self, text: Optional[str]) -> ReasoningContent:
        """Parse a stream fragment without flushing incomplete tag prefixes."""
        if not text:
            return ReasoningContent(content="", reasoning_content="")

        self._buffer += text
        return self._consume(final=False)

    def flush(self) -> ReasoningContent:
        """Flush any buffered text at stream end."""
        return self._consume(final=True)

    def _consume(self, *, final: bool) -> ReasoningContent:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []

        while self._buffer:
            if self._in_reasoning:
                close_index = self._buffer.lower().find(THINK_CLOSE_TAG)
                if close_index >= 0:
                    reasoning_parts.append(self._buffer[:close_index])
                    self._buffer = self._buffer[close_index + len(THINK_CLOSE_TAG) :]
                    self._in_reasoning = False
                    continue

                hold_len = (
                    0
                    if final
                    else _longest_tag_prefix_suffix(self._buffer, THINK_CLOSE_TAG)
                )
                emit_len = len(self._buffer) - hold_len
                reasoning_parts.append(self._buffer[:emit_len])
                self._buffer = self._buffer[emit_len:]
                break

            open_index = self._buffer.lower().find(THINK_OPEN_TAG)
            if open_index >= 0:
                content_parts.append(self._buffer[:open_index])
                self._buffer = self._buffer[open_index + len(THINK_OPEN_TAG) :]
                self._in_reasoning = True
                continue

            hold_len = (
                0 if final else _longest_tag_prefix_suffix(self._buffer, THINK_OPEN_TAG)
            )
            emit_len = len(self._buffer) - hold_len
            content_parts.append(self._buffer[:emit_len])
            self._buffer = self._buffer[emit_len:]
            break

        return ReasoningContent(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
        )


def extract_reasoning_from_content(text: Optional[str]) -> ReasoningContent:
    """Extract all ``<think>...</think>`` blocks from non-streaming content."""
    if not text:
        return ReasoningContent(content="", reasoning_content="")

    parser = ReasoningContentParser()
    parsed = parser.feed(text)
    flushed = parser.flush()
    return ReasoningContent(
        content=f"{parsed.content}{flushed.content}",
        reasoning_content=f"{parsed.reasoning_content}{flushed.reasoning_content}",
    )
