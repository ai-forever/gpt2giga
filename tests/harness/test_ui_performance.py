from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.performance import (
    UI_PERFORMANCE_BUDGETS,
    ui_performance_budgets,
)


def test_ui_performance_budgets_are_machine_readable_and_copy_safe():
    app = create_app(
        HarnessConfig(),
        registry=create_default_registry(include_entry_points=False),
    )

    response = TestClient(app).get("/api/defaults")
    copied = ui_performance_budgets()
    copied["large_trace_nodes"] = 1

    assert response.status_code == 200
    assert response.json()["performance_budgets"] == UI_PERFORMANCE_BUDGETS
    assert UI_PERFORMANCE_BUDGETS == {
        "initial_page_ready_ms": 3_500,
        "large_trace_nodes": 200,
        "large_trace_render_ms": 100,
        "cursor_reconnect_ms": 1_000,
        "large_preview_chars": 100_000,
        "large_preview_render_ms": 100,
    }
