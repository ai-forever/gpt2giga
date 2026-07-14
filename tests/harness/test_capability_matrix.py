from gpt2giga_harness.capability_matrix import (
    CAPABILITY_MATRIX_SOURCE,
    build_adapter_capability_matrix,
    render_adapter_capability_matrix_markdown,
)
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.types import spec_to_dict


def test_capability_matrix_is_generated_from_builtin_runtime_contracts():
    registry = HarnessRegistry.with_builtins()

    matrix = build_adapter_capability_matrix(registry)

    assert matrix["schema_version"] == 1
    assert matrix["generated_from"] == CAPABILITY_MATRIX_SOURCE
    assert matrix["built_in_only"] is True
    assert [item["id"] for item in matrix["adapters"]] == [
        "claude-code",
        "codex-cli",
        "gemini-cli",
    ]

    cells = {item["id"]: item["support"] for item in matrix["capabilities"]}
    adapter_ids = {item["id"] for item in matrix["adapters"]}
    for harness in registry.list():
        spec = spec_to_dict(harness.spec())
        claims = spec["adapter_capabilities"]
        if not claims:
            assert spec["id"] not in adapter_ids
            continue
        assert spec["protocol_capability_scope"] == "harness_surface"
        generated_claims = {
            capability_id: cells[capability_id][spec["id"]] for capability_id in claims
        }
        assert generated_claims == claims


def test_capability_matrix_markdown_contains_statuses_and_evidence():
    matrix = build_adapter_capability_matrix(HarnessRegistry.with_builtins())

    rendered = render_adapter_capability_matrix_markdown(matrix)

    assert rendered.startswith("# Harness adapter capability matrix\n")
    assert "Generated from `HarnessSpec.adapter_capabilities`" in rendered
    assert (
        "| `headless_continuity` | unsupported | supported | unsupported |" in rendered
    )
    assert "## Contract evidence" in rendered
    assert "Uses a supervised Codex app-server thread" in rendered
