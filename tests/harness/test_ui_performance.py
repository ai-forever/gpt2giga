from fastapi.testclient import TestClient

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.performance import (
    UI_PERFORMANCE_BUDGETS,
    ui_performance_budgets,
)
from gpt2giga_harness.ui.static import load_asset, load_text_asset


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
        "critical_asset_bytes": 575_000,
        "initial_page_ready_ms": 3_500,
        "large_trace_nodes": 200,
        "large_trace_render_ms": 100,
        "cursor_reconnect_ms": 1_000,
        "large_preview_chars": 100_000,
        "large_preview_render_ms": 100,
    }


def test_packaged_ui_critical_assets_stay_within_initial_load_budget():
    critical_assets = (
        "index.html",
        "app.css",
        "app.js",
        "brand/gigaloom-mark.svg",
        "brand/gigaloom.webmanifest",
    )
    total_bytes = sum(len(load_asset(name)) for name in critical_assets)

    assert total_bytes <= UI_PERFORMANCE_BUDGETS["critical_asset_bytes"]


def test_ui_enforces_trace_preview_and_cursor_reconnect_budgets():
    script = load_text_asset("app.js")
    stylesheet = load_text_asset("app.css")

    for fragment in (
        "window.__gpt2gigaPerformance = uiPerformance",
        "function recordUiPerformance",
        "document.documentElement.setAttribute(`${attribute}-ms`",
        '"initial_page_ready"',
        'document.documentElement.dataset.harnessReady = "true"',
        "const RUNS_TRACE_DOM_LIMIT = 200",
        "const fragment = document.createDocumentFragment()",
        '"large_trace_render"',
        "state.runsTraceNodes = nodes.slice(-RUNS_TRACE_DOM_LIMIT)",
        '"runs_cursor_reconnect"',
        '"native_cursor_reconnect"',
        "?after_id=${encodeURIComponent(latest.event_id)}",
        "?cursor=${encodeURIComponent(state.nativeOutputCursor)}",
        "const LARGE_PREVIEW_CHAR_LIMIT = 100000",
        "function boundedPreviewText",
        "LARGE_PREVIEW_CHAR_LIMIT - suffix.length",
        "function renderReportPreviewInto",
        'expand.textContent = "Render full report"',
        '"large_diff_preview"',
        '"large_pr_report_preview"',
        '"large_report_preview"',
    ):
        assert fragment in script

    assert ".large-preview-notice" in stylesheet
    assert "renderReportPreviewInto(content, message.content)" in script
    assert 'setText("diff-text", boundedPreviewText(diffText, "Diff"))' in script
    assert 'setText("pr-text", boundedPreviewText(reportText, "PR report"))' in script
