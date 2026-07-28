"""Machine-readable performance budgets for the packaged Harness UI."""

from __future__ import annotations

from typing import Final


UI_PERFORMANCE_BUDGETS: Final[dict[str, int]] = {
    "initial_page_ready_ms": 3_500,
    "large_trace_nodes": 200,
    "large_trace_render_ms": 100,
    "cursor_reconnect_ms": 1_000,
    "large_preview_chars": 100_000,
    "large_preview_render_ms": 100,
}


def ui_performance_budgets() -> dict[str, int]:
    """Return a copy safe for API serialization."""

    return dict(UI_PERFORMANCE_BUDGETS)
